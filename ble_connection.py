"""Advertisement -> bounded queue -> fresh BLEDevice -> read-only GATT.

No writes, notifications/CCCD writes, pairing, HTTP calls or fixed-address lookup.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
import traceback
from bleak import BleakClient, BleakScanner
from protocol import SERVICE, VERSION


def error_details(exc):
    chain, seen = [], set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        codes = {}
        for field in ("hresult", "winerror", "errno", "protocol_error", "error_code"):
            value = getattr(current, field, None)
            if value is not None:
                codes[field] = {"value": str(value), "hex": f"0x{value & 0xffffffff:08X}" if isinstance(value, int) else None}
        chain.append({"type": f"{type(current).__module__}.{type(current).__name__}",
                      "message": str(current), "repr": repr(current), "args": repr(current.args), "codes": codes})
        current = current.__cause__ or current.__context__
    return {"exceptions": chain, "traceback": "".join(traceback.format_exception(exc))}


def address_metadata(device, advertisement):
    raw = getattr(device, "details", None)
    event = getattr(raw, "adv", None) or getattr(raw, "scan", None)
    if event is None:
        platform = getattr(advertisement, "platform_data", ())
        if len(platform) > 1:
            event = getattr(platform[1], "adv", None) or getattr(platform[1], "scan", None)
    value = getattr(event, "bluetooth_address_type", None)
    try:
        kind = {0: "public", 1: "random"}.get(int(value))
    except (ValueError, TypeError):
        kind = None
    return {"address_type": kind,
            "address_type_raw": str(value) if value is not None else None,
            "connectable": getattr(event, "is_connectable", None),
            "has_scan_response": bool(getattr(raw, "scan", None))}


class Transcript:
    def __init__(self, directory, callback=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        self.path = directory / f"gatt_{stamp}.jsonl"
        self.callback = callback or (lambda record: None)

    def __call__(self, event, **data):
        record = {"time_utc": datetime.now(timezone.utc).isoformat(), "event": event, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self.callback(record)


@dataclass
class Candidate:
    device: object
    metadata: dict
    received: float


class GattConnector:
    def __init__(self, report, *, scanner_factory=BleakScanner, client_factory=BleakClient,
                 on_disconnect=None, connect_timeout=30, max_attempts=5, backoff=2):
        self.report = report
        self.scanner_factory = scanner_factory
        self.client_factory = client_factory
        self.on_disconnect = on_disconnect
        self.connect_timeout = connect_timeout
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.queue = asyncio.Queue(maxsize=1)
        self.scanner = None
        self.scanning = False
        self.accepting = False
        self.client = None
        self.attempts = 0
        self.events = 0
        self.matches = 0
        self.loop = None
        self._attempt_client = None

    def detection_callback(self, device, advertisement):
        # Bleak calls this on its asyncio loop; marshal defensively for other adapters.
        if not self.accepting:
            return
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._enqueue, device, advertisement)

    def _enqueue(self, device, advertisement):
        if not self.accepting:
            return
        self.events += 1
        if SERVICE not in {str(u).lower() for u in advertisement.service_uuids}:
            return
        metadata = address_metadata(device, advertisement)
        if metadata["connectable"] is False:
            return
        self.matches += 1
        metadata.update(address=device.address, name=advertisement.local_name or device.name,
                        rssi=advertisement.rssi, service_uuid=SERVICE)
        candidate = Candidate(device, metadata, time.monotonic())
        # Bound memory and keep the freshest observation, including address changes.
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(candidate)

    async def _start_scanner(self):
        while not self.queue.empty():
            self.queue.get_nowait()
        self.scanner = self.scanner_factory(detection_callback=self.detection_callback,
                                            scanning_mode="active")
        self.accepting = True
        try:
            await self.scanner.start()
            self.scanning = True
        except BaseException:
            self.accepting = False
            # Bleak start can fail after creating a native watcher.
            try:
                await asyncio.wait_for(self.scanner.stop(), 5)
            except Exception:
                pass
            raise
        self.report("listening", service_uuid=SERVICE, name_filter=False, fixed_mac=False,
                    attempt=self.attempts, mode="active")

    async def _stop_scanner(self):
        self.accepting = False
        if self.scanning:
            try:
                await asyncio.wait_for(self.scanner.stop(), 5)
            finally:
                self.scanning = False

    async def _dispose(self, client):
        if client is None:
            return
        try:
            await asyncio.wait_for(client.disconnect(), 10)
        except Exception as exc:
            self.report("disconnect_error", address=getattr(client, "address", None), **error_details(exc))

    async def run(self, listen_seconds=180):
        self.loop = asyncio.get_running_loop()
        remaining_listen = listen_seconds
        try:
            # A rare advertisement arriving at the end of the scan budget still
            # gets a complete connection attempt. Keep the overall job bounded.
            async with asyncio.timeout(listen_seconds + self.max_attempts * (self.connect_timeout + 20)):
                await self._start_scanner()
                while self.attempts < self.max_attempts:
                    if remaining_listen <= 0:
                        raise TimeoutError('Advertisement listening budget exhausted')
                    wait_started = time.monotonic()
                    try:
                        candidate = await asyncio.wait_for(self.queue.get(), min(15, remaining_listen))
                    except TimeoutError:
                        self.report("waiting", advertisements=self.events, matches=self.matches, attempts=self.attempts)
                        continue
                    finally:
                        remaining_listen -= time.monotonic() - wait_started
                    self.report("matched", **candidate.metadata)
                    # Release the scanner before initiating, still using the captured object.
                    await self._stop_scanner()
                    age = time.monotonic() - candidate.received
                    if age > 5:
                        self.report("stale_candidate", age_seconds=age, **candidate.metadata)
                        await self._start_scanner()
                        continue
                    self.attempts += 1
                    winrt = {"use_cached_services": False}
                    if candidate.metadata["address_type"]:
                        winrt["address_type"] = candidate.metadata["address_type"]
                    self.report("connect_attempt", attempt=self.attempts, max_attempts=self.max_attempts,
                                age_seconds=age, winrt=winrt, **candidate.metadata)
                    client = self.client_factory(candidate.device, timeout=self.connect_timeout,
                        pair=False, winrt=winrt, disconnected_callback=self._disconnected)
                    self._attempt_client = client
                    try:
                        await asyncio.wait_for(client.connect(), self.connect_timeout + 5)
                        services = []
                        for service in client.services:
                            chars = []
                            for c in service.characteristics:
                                properties = list(c.properties)
                                entry = {"uuid": c.uuid, "handle": c.handle, "properties": properties,
                                         "writable": bool(set(properties) & {"write", "write-without-response", "authenticated-signed-writes"})}
                                chars.append(entry)
                                self.report("characteristic", service_uuid=service.uuid, **entry)
                            services.append({"uuid": service.uuid, "handle": service.handle, "characteristics": chars})
                        if not any(s["uuid"].lower() == SERVICE for s in services):
                            raise RuntimeError("EPD service absent after GATT enumeration")
                        firmware = None
                        characteristic = client.services.get_characteristic(VERSION)
                        if characteristic and "read" in characteristic.properties:
                            try:
                                raw = bytes(await asyncio.wait_for(client.read_gatt_char(characteristic), 8))
                                firmware = raw.decode("utf-8", errors="replace").rstrip("\0") if len(raw) > 1 else raw.hex()
                                self.report("firmware_read", uuid=VERSION, value=firmware, hex=raw.hex())
                            except Exception as exc:
                                # Read failure is distinct from a successful GATT connection.
                                self.report("read_error", uuid=VERSION, address=candidate.device.address, **error_details(exc))
                        if not client.is_connected:
                            raise RuntimeError("Link lost before GATT inspection completed")
                        self.client = client
                        self._attempt_client = None
                        result = {"address": candidate.device.address, "address_type": candidate.metadata["address_type"],
                                  "attempts": self.attempts, "services": services, "firmware": firmware,
                                  "read_only": True}
                        self.report("gatt_ready", **result)
                        return result
                    except Exception as exc:
                        self.report("connect_error", attempt=self.attempts, **candidate.metadata, **error_details(exc))
                        await self._dispose(client)
                        self._attempt_client = None
                        if self.attempts >= self.max_attempts:
                            raise RuntimeError("GATT connection retry limit reached") from exc
                        await asyncio.sleep(self.backoff)
                        # Never retry a saved MAC or BLEDevice; wait for a fresh ADV.
                        await self._start_scanner()
        except TimeoutError as exc:
            self.report("deadline", advertisements=self.events, matches=self.matches, attempts=self.attempts,
                        seconds=listen_seconds, **error_details(exc))
            raise TimeoutError(f"累计监听 {listen_seconds} 秒后仍未完成 GATT 连接；广播 {self.events}，匹配 {self.matches}，连接尝试 {self.attempts}") from exc
        except asyncio.CancelledError:
            self.report("cancelled", attempts=self.attempts)
            raise
        finally:
            await self._stop_scanner()
            if self._attempt_client:
                await self._dispose(self._attempt_client)
                self._attempt_client = None

    def _disconnected(self, client):
        # Failed attempts must not mark a later/current connection disconnected.
        if client is self.client:
            self.report("disconnected", address=getattr(client, "address", None))
            self.client = None
            if self.on_disconnect:
                self.on_disconnect(client)

    async def disconnect(self):
        client, self.client = self.client, None
        await self._dispose(client)


async def cli(args):
    report = Transcript(args.output, lambda record: print(json.dumps(record, ensure_ascii=False), flush=True))
    handler = logging.FileHandler(report.path.with_suffix(".bleak.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("bleak.backends.winrt.client")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    connector = GattConnector(report, connect_timeout=args.timeout, max_attempts=args.attempts)
    try:
        result = await connector.run(args.seconds)
        report.path.with_suffix(".gatt.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        await asyncio.sleep(args.hold)
        return 0
    except Exception as exc:
        report("failed", **error_details(exc))
        return 1
    finally:
        await connector.disconnect()
        logger.removeHandler(handler)
        handler.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--hold", type=float, default=3)
    parser.add_argument("--output", default="research/ble")
    args = parser.parse_args()
    if min(args.seconds, args.timeout, args.attempts) <= 0 or args.hold < 0:
        parser.error("Timeouts/attempts must be positive; hold must be nonnegative")
    return asyncio.run(cli(args))


if __name__ == "__main__":
    raise SystemExit(main())
