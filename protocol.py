"""Minimal interoperable EPD protocol; no driver, pin or firmware changes."""
import re
from dataclasses import dataclass

SERVICE = "62750001-d828-918d-fb46-b6c11c675aec"
CHARACTERISTIC = "62750002-d828-918d-fb46-b6c11c675aec"
VERSION = "62750003-d828-918d-fb46-b6c11c675aec"
TARGET = "NRF_EPD_71E9"
BW_DRIVERS = {0x01: "UC8176 黑白", 0x04: "SSD1619 黑白", 0x17: "SSD1683 黑白"}
BWR_DRIVERS = {0x02: "SSD1619 三色", 0x03: "UC8176 三色", 0x16: "SSD1683 三色"}


def rle_chunks(data: bytes, limit: int):
    if limit < 2:
        raise ValueError("Payload too small")
    tokens, i = [], 0
    while i < len(data):
        run = 1
        while i + run < len(data) and run < 130 and data[i + run] == data[i]:
            run += 1
        if run >= 3:
            tokens.append(bytes([0x80 | (run - 3), data[i]]))
            i += run
        else:
            start = i
            while i < len(data) and i - start < min(128, limit - 1):
                if i + 2 < len(data) and data[i] == data[i+1] == data[i+2]:
                    break
                i += 1
            tokens.append(bytes([i - start - 1]) + data[start:i])
    chunks, current = [], b""
    for token in tokens:
        if len(current) + len(token) > limit:
            chunks.append(current)
            current = b""
        current += token
    if current:
        chunks.append(current)
    return chunks


def image_packets(data: bytes, packet_size=20, modern=False, red=False):
    if not data or not 4 <= packet_size <= 512:
        raise ValueError("Invalid image or packet size")
    limit = packet_size - 2
    plain = [data[i:i+limit] for i in range(0, len(data), limit)]
    compressed = rle_chunks(data, limit) if modern else []
    use_rle = modern and sum(map(len, compressed)) < len(data)
    chunks = compressed if use_rle else plain
    result = []
    for index, chunk in enumerate(chunks):
        flag = (int(red) | (2 if index == 0 else 0) | (4 if use_rle else 0)) if modern else ((0 if red else 15) | (0 if index == 0 else 240))
        result.append(bytes([0x30, flag]) + chunk)
    return result


@dataclass
class DeviceInfo:
    driver: int | None = None
    packet_size: int = 20
    modern: bool = False
    slots: int = 0
    used_mask: int = 0
    current_slot: int = -1
    slots_received: bool = False
    battery_mv: int | None = None
    configuration_received: bool = False
    mtu_received: bool = False
    firmware: str = "未知"
    sid: str | None = None
    error: str | None = None

    @property
    def supported(self):
        return self.driver in BW_DRIVERS or self.driver in BWR_DRIVERS

    @property
    def color(self):
        return "BWR" if self.driver in BWR_DRIVERS else "BW"


class NotificationParser:
    def __init__(self, info):
        self.info = info
        self.first = True
        self.remaining = 0
        self.buffer = bytearray()
        self.chunk_config = False

    def feed(self, data: bytes):
        if self.remaining:
            if len(data) > self.remaining:
                raise ValueError("Notification chunk exceeds announced size")
            self.buffer.extend(data)
            self.remaining -= len(data)
            if self.remaining:
                return None
            return self._process(bytes(self.buffer), self.chunk_config)
        text = data.decode("utf-8", errors="replace")
        chunk = re.match(r"^chunk=(\d+) len=(\d+)(?: rle=(\d+))?", text)
        if chunk:
            length = int(chunk[2])
            if not 0 < length <= 65536 or chunk[3] == "1":
                raise ValueError("Unsupported compressed/oversized configuration")
            self.chunk_config, self.first = self.first, False
            self.remaining, self.buffer = length, bytearray()
            return None
        config, self.first = self.first, False
        if re.match(r"^[a-z0-9_]+=", text):
            self.first = config
        return self._process(data, config)

    def _process(self, data, config):
        text = data.decode("utf-8", errors="replace").rstrip("\0")
        # Text may arrive before config on some firmware revisions.
        if re.match(r"^[a-z0-9_]+=", text):
            if text.startswith("mtu="):
                self.info.packet_size = max(4, min(512, int(text.split()[0][4:])))
                self.info.modern = "rle=1" in text
                self.info.mtu_received = True
            elif text.startswith("slots="):
                fields = text[6:].split()
                self.info.slots = int(fields[0])
                self.info.used_mask = int(fields[1], 0)
                self.info.current_slot = int(fields[2])
                self.info.slots_received = True
                if not 0 <= self.info.slots <= 256 or self.info.used_mask < 0:
                    raise ValueError("Invalid slot configuration")
            elif text.startswith("sid="):
                self.info.sid = text[4:]
                return "设备兼容性校验标识已收到"
            elif text.startswith("err="):
                self.info.error = text[4:]
            if match := re.search(r"bat=(\d+)", text):
                self.info.battery_mv = int(match[1])
            return text
        if config and len(data) >= 8:
            self.info.driver = data[7]
            self.info.configuration_received = True
            return f"当前驱动 0x{data[7]:02x}（保持设备现有配置）"
        return f"收到 {len(data)} 字节通知"
