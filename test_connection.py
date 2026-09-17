import asyncio
from types import SimpleNamespace as NS
import unittest
from bleak.backends.device import BLEDevice
from ble_connection import GattConnector, error_details
from protocol import SERVICE, VERSION, CHARACTERISTIC


def observation(address, uuid=SERVICE, kind=1, name=None):
    raw = NS(adv=NS(bluetooth_address_type=kind, is_connectable=True), scan=None)
    device = BLEDevice(address, name, raw)
    adv = NS(local_name=name, rssi=-53, service_uuids=[uuid], platform_data=())
    return device, adv


class Services(list):
    def get_characteristic(self, uuid):
        return next((c for s in self for c in s.characteristics if c.uuid == uuid), None)


class Client:
    def __init__(self, device, *, fail=False, hang=False, **kwargs):
        assert isinstance(device, BLEDevice), "String MAC lookup is forbidden"
        self.device, self.kwargs = device, kwargs
        self.address = device.address
        self.fail, self.hang = fail, hang
        self.is_connected = False
        self.disposed = False
        self.reads = []
        self.services = Services([
            NS(uuid="other-service", handle=1, characteristics=[NS(uuid="other", handle=2, properties=["read"])]),
            NS(uuid=SERVICE, handle=3, characteristics=[
                NS(uuid=CHARACTERISTIC, handle=4, properties=["write", "write-without-response", "notify"]),
                NS(uuid=VERSION, handle=5, properties=["read"])])])

    async def connect(self):
        if self.hang:
            await asyncio.Event().wait()
        if self.fail:
            exc = OSError("GATT unavailable")
            exc.winerror = -2147023673
            raise exc
        self.is_connected = True

    async def disconnect(self):
        self.disposed = True
        self.is_connected = False

    async def read_gatt_char(self, c):
        self.reads.append(c.uuid)
        assert c.uuid == VERSION
        return b"v1.10-om6626"

    async def write_gatt_char(self, *args, **kwargs):
        raise AssertionError("Must not write")

    async def start_notify(self, *args, **kwargs):
        raise AssertionError("Must not write CCCD")


class Harness:
    def __init__(self, observations, fail_first=False, hang=False):
        self.observations = observations
        self.fail_first, self.hang = fail_first, hang
        self.scanners, self.clients, self.events = [], [], []

    def report(self, event, **data):
        self.events.append({"event": event, **data})

    def scanner(self, detection_callback, scanning_mode, **kwargs):
        assert scanning_mode == "active"
        assert "service_uuids" not in kwargs
        index = len(self.scanners)
        parent = self
        class Scanner:
            stopped = False
            async def start(self):
                if index < len(parent.observations):
                    asyncio.get_running_loop().call_soon(detection_callback, *parent.observations[index])
            async def stop(self):
                self.stopped = True
        s = Scanner()
        self.scanners.append(s)
        return s

    def client(self, device, **kwargs):
        c = Client(device, fail=self.fail_first and not self.clients, hang=self.hang, **kwargs)
        self.clients.append(c)
        return c

    def connector(self):
        return GattConnector(self.report, scanner_factory=self.scanner,
            client_factory=self.client, backoff=.001, connect_timeout=.03)


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_unnamed_random_device_reads_without_writes(self):
        obs = observation("FA:00:00:00:00:01")
        h = Harness([obs])
        c = h.connector()
        result = await c.run(1)
        self.assertIs(h.clients[0].device, obs[0])
        self.assertEqual(h.clients[0].kwargs['winrt']['address_type'], 'random')
        self.assertFalse(h.clients[0].kwargs['pair'])
        self.assertEqual(result['firmware'], 'v1.10-om6626')
        self.assertEqual(len(result['services']), 2)
        self.assertEqual(h.clients[0].reads, [VERSION])
        self.assertTrue(h.scanners[0].stopped)
        await c.disconnect()
        self.assertTrue(h.clients[0].disposed)

    async def test_retry_uses_new_advertisement_and_new_address(self):
        old, fresh = observation('FA:00:00:00:00:01'), observation('F1:00:00:00:00:02')
        h = Harness([old, fresh], fail_first=True)
        c = h.connector()
        result = await c.run(1)
        self.assertEqual(result['attempts'], 2)
        self.assertIs(h.clients[1].device, fresh[0])
        self.assertTrue(h.clients[0].disposed)
        error = next(e for e in h.events if e['event'] == 'connect_error')
        self.assertIn('winerror', error['exceptions'][0]['codes'])
        self.assertIn('OSError', error['traceback'])
        await c.disconnect()

    async def test_name_and_old_mac_cannot_override_wrong_service(self):
        h = Harness([observation('CE:14:7F:FD:71:E9', uuid='wrong', name='NRF_EPD_71E9')])
        c = h.connector()
        with self.assertRaises(TimeoutError):
            await c.run(.05)
        self.assertEqual(h.clients, [])
        self.assertTrue(h.scanners[0].stopped)

    async def test_cancel_during_listening_cleans_up(self):
        h = Harness([])
        c = h.connector()
        task = asyncio.create_task(c.run(10))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(h.scanners[0].stopped)

    async def test_cancel_during_connection_disposes_client(self):
        h = Harness([observation('FA:00:00:00:00:01')], hang=True)
        c = h.connector()
        task = asyncio.create_task(c.run(10))
        await asyncio.sleep(.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(h.clients[0].disposed)

    async def test_queue_keeps_latest_object(self):
        h = Harness([])
        c = h.connector()
        c.accepting = True
        first, second = observation('FA:00:00:00:00:01'), observation('FA:00:00:00:00:02')
        c._enqueue(*first)
        c._enqueue(*second)
        self.assertEqual(c.queue.qsize(), 1)
        self.assertIs(c.queue.get_nowait().device, second[0])

    async def test_public_address_is_not_forced_random(self):
        h = Harness([observation('10:00:00:00:00:01', kind=0)])
        c = h.connector()
        await c.run(1)
        self.assertEqual(h.clients[0].kwargs['winrt']['address_type'], 'public')
        await c.disconnect()

    async def test_connection_can_finish_after_scan_budget(self):
        h = Harness([observation('FA:00:00:00:00:01')])
        original_factory = h.client
        def factory(device, **kwargs):
            client = original_factory(device, **kwargs)
            original_connect = client.connect
            async def connect():
                await asyncio.sleep(.08)
                await original_connect()
            client.connect = connect
            return client
        c = GattConnector(h.report, scanner_factory=h.scanner, client_factory=factory, connect_timeout=.2)
        result = await c.run(.02)
        self.assertEqual(result['firmware'], 'v1.10-om6626')
        await c.disconnect()


if __name__ == '__main__':
    unittest.main()
