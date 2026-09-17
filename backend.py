import asyncio
import hashlib
import io
import os
from pathlib import Path
import threading
import time
import urllib.parse
import urllib.request
from PIL import Image
from PySide6.QtCore import QObject, Signal
from protocol import (SERVICE, CHARACTERISTIC, VERSION, TARGET, DeviceInfo,
                      NotificationParser, image_packets)
from ble_connection import GattConnector, Transcript
from prepare_screen import prepare_screen
from weather import fetch_weather


def verify_device(sid):
    request = urllib.request.Request("https://epdiy.cn/ecc/check",
        data=urllib.parse.urlencode({"hash": sid}).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=8) as response:
        return response.read(128).decode().strip() == "OK"


class Backend(QObject):
    log = Signal(str)
    devices = Signal(object)
    connection = Signal(bool, object)
    progress = Signal(int)
    sent = Signal(bool, str)
    media = Signal(object)
    media_status = Signal(str)
    media_sources = Signal(object)
    weather = Signal(object)
    weather_status = Signal(str)
    scan_done = Signal()
    gatt = Signal(object)
    screen_ready = Signal(bool, object)

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.client = None
        self.connector = None
        self.connection_task = None
        self.read_only = True
        self.preparing = False
        self.info = DeviceInfo()
        self.parser = NotificationParser(self.info)
        self.cancel = False
        self.authorized = False
        self.sending = False
        self.media_task = None
        self.media_preference = "netease"
        self.next_send = 0.0
        self.session_slots = {}
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        self.loop.close()

    def submit(self, coroutine):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        def done(f):
            try:
                f.result()
            except Exception as e:
                self.log.emit(f"操作失败：{type(e).__name__}: {e}")
        future.add_done_callback(done)
        return future

    async def scan(self, prepare=False):
        if self.connection_task and not self.connection_task.done():
            return
        self.connection_task = asyncio.current_task()
        self.authorized = False
        self.read_only = True
        directory = Path(os.environ.get("LOCALAPPDATA", str(Path(__file__).parent))) / "InkCompanion" / "ble"
        transcript = Transcript(directory, self.connection_event)
        self.log.emit(f"GATT 只读诊断日志：{transcript.path}")
        self.connector = GattConnector(transcript, on_disconnect=self.disconnected, connect_timeout=45)
        try:
            result = await self.connector.run(180)
            self.client = self.connector.client
            self.info = DeviceInfo(firmware=result["firmware"] or "未读取")
            self.gatt.emit(result)
            self.connection.emit(True, self.info)
            if prepare:
                self.log.emit('GATT 已连接，正在读取屏幕配置并校验…')
                await self.prepare_display()
            else:
                self.log.emit('GATT 已连接并完成枚举；尚未初始化屏幕')
        except asyncio.CancelledError:
            self.log.emit("已停止等待连接")
            self.connection.emit(False, self.info)
        except Exception:
            self.connection.emit(False, self.info)
            raise
        finally:
            self.connection_task = None
            self.scan_done.emit()

    def connection_event(self, event):
        kind = event["event"]
        if kind == "characteristic":
            self.log.emit(f"GATT {event['uuid']} | {', '.join(event['properties'])} | writable={event['writable']}")
        elif kind in ("connect_error", "read_error", "disconnect_error"):
            self.log.emit(f"{kind} 地址={event.get('address')} 尝试={event.get('attempt')}\n{event['traceback']}")
        elif kind == "connect_attempt":
            self.log.emit(f"连接尝试 {event['attempt']}/{event['max_attempts']}：{event['address']} ({event['address_type']})")
        elif kind == "waiting":
            self.log.emit(f"等待 UUID 广播：累计 {event['advertisements']} 条，目标匹配 {event['matches']}")
        elif kind == "matched":
            self.log.emit(f"捕获 UUID：{event['address']}，RSSI {event['rssi']}，设备名 {event['name'] or '未提供'}")

    def notify(self, _, data):
        try:
            message = self.parser.feed(bytes(data))
            if message:
                self.log.emit(message)
        except Exception as e:
            self.info.error = f"通知解析失败：{e}"
            self.log.emit(self.info.error)

    def disconnected(self, client):
        self.cancel = True
        self.authorized = False
        self.read_only = True
        self.connection.emit(False, self.info)
        self.log.emit("蓝牙已断开；自动发送已停止")

    async def connect(self, device):
        # Do not connect from a stale UI entry; capture a new advertisement.
        await self.scan()

    async def prepare_display(self):
        if self.preparing or self.sending:
            return
        if not self.client or not self.client.is_connected:
            self.log.emit('请先完成 GATT 连接')
            self.screen_ready.emit(False, self.info)
            return
        if not self.read_only and self.authorized:
            self.screen_ready.emit(True, self.info)
            return
        self.preparing = True
        client = self.client
        try:
            info, parser = await prepare_screen(client, self.info.firmware, self.log.emit, verify_device)
            if self.client is not client or not client.is_connected:
                raise RuntimeError('初始化过程中连接已断开')
            self.info, self.parser = info, parser
            self.session_slots = {}
            self.authorized = True
            self.read_only = False
            self.screen_ready.emit(True, info)
        except Exception as exc:
            self.authorized = False
            self.read_only = True
            self.log.emit(f'准备屏幕失败：{exc}')
            self.screen_ready.emit(False, self.info)
        finally:
            self.preparing = False

    async def write(self, packet, response=True):
        if self.read_only:
            raise RuntimeError("屏幕尚未准备完成，禁止写入")
        if not self.client or not self.client.is_connected:
            raise RuntimeError("蓝牙未连接")
        await asyncio.wait_for(self.client.write_gatt_char(CHARACTERISTIC, packet, response=response), 10)

    async def disconnect(self):
        self.cancel = True
        self.authorized = False
        self.read_only = True
        try:
            task = self.connection_task
            if task and task is not asyncio.current_task() and not task.done():
                task.cancel()
                await task
            if self.connector:
                await self.connector.disconnect()
            elif self.client and self.client.is_connected:
                await self.client.disconnect()
        finally:
            self.client = None
            self.connection.emit(False, self.info)

    async def send(self, data, cooldown=15, red=None):
        if self.sending:
            self.sent.emit(False, "已有传输进行中")
            return
        self.sending = True
        try:
            if self.read_only:
                raise RuntimeError("屏幕尚未初始化或校验完成")
            if not self.authorized or not self.info.supported:
                raise RuntimeError("请先连接并完成设备校验")
            if len(data) != 15000 or (red is not None and len(red) != 15000):
                raise ValueError("ZKC42VM 当前配置需要 400×300 的 15000 字节平面")
            delay = self.next_send - time.monotonic()
            while delay > 0:
                if self.cancel:
                    raise RuntimeError("已取消")
                await asyncio.sleep(min(delay, .2))
                delay = self.next_send - time.monotonic()
            self.info.error = None
            if self.cancel:
                raise RuntimeError("已取消")
            red_plane = None
            if self.info.color == "BWR":
                # epdiy BWR plane is active-low: 0=red, 1=not red.
                # All 0xff therefore clears stale red when three-color output is off.
                red_plane = bytes([255]) * len(data) if red is None else red
            digest = hashlib.sha256(data + (red_plane or b"")).hexdigest()
            slot = None
            if self.info.slots:
                if not self.info.slots_received:
                    raise RuntimeError("未收到完整槽位信息")
                slot = next((i for i, value in self.session_slots.items() if value == digest), None)
                if slot is not None:
                    await self.write(bytes([0x31, 1, slot]))
                    self.next_send = time.monotonic() + max(5, cooldown)
                    self.progress.emit(100)
                    self.sent.emit(True, "已提交已缓存槽位的显示请求")
                    return
                slot = next((i for i in range(self.info.slots) if not self.info.used_mask & (1 << i)), None)
                if slot is None:
                    slot = next(iter(self.session_slots), None)
                if slot is None:
                    raise RuntimeError("没有空槽位；为保留原有图片，未写入")
                self.session_slots.pop(slot, None)
                # Reserve even if transfer fails; never treat a partial frame as cached.
                self.info.used_mask |= 1 << slot
                self.log.emit(f"写入空闲/本次会话槽位 {slot}（从 0 计数），保留连接前已有图片")
                await self.write(bytes([0x31, 0, slot]))
            await self.write(b"\x01")
            await asyncio.sleep(.2)
            characteristic = self.client.services.get_characteristic(CHARACTERISTIC)
            packet_size = min(self.info.packet_size, characteristic.max_write_without_response_size, 244)
            packets = image_packets(data, packet_size, self.info.modern)
            if red_plane is not None:
                packets += image_packets(red_plane, packet_size, self.info.modern, red=True)
            for index, packet in enumerate(packets):
                if self.cancel:
                    raise RuntimeError("已取消，未提交剩余图像")
                if self.info.error:
                    raise RuntimeError(f"设备返回错误：{self.info.error}")
                # Website interleaves response writes; final block always acknowledged here.
                response = (index % 11 == 10) or index == len(packets) - 1
                await self.write(packet, response=response)
                if not response:
                    await asyncio.sleep(.006)
                self.progress.emit(int((index + 1) * 95 / len(packets)))
            await asyncio.sleep(.1)
            if self.cancel or self.info.error:
                raise RuntimeError(self.info.error or "已取消")
            await self.write(b"\x05")
            self.next_send = time.monotonic() + max(5, cooldown)
            await asyncio.sleep(.4)
            if self.info.error:
                raise RuntimeError(f"刷新返回错误：{self.info.error}")
            if slot is not None:
                self.session_slots[slot] = digest
                self.info.used_mask |= 1 << slot
            self.progress.emit(100)
            self.sent.emit(True, f"图像已传输并提交刷新；等待至少 {cooldown} 秒（固件未提供物理刷新完成确认）")
        except Exception as e:
            # Never resume a partly accepted image: next attempt starts a new INIT/frame.
            self.sent.emit(False, str(e))
        finally:
            self.sending = False

    async def watch_media(self, enabled):
        if self.media_task:
            self.media_task.cancel()
            try:
                await self.media_task
            except asyncio.CancelledError:
                pass
            self.media_task = None
        if enabled:
            self.media_task = asyncio.create_task(self._media_loop())

    async def _media_loop(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        from winrt.windows.storage.streams import Buffer, InputStreamOptions
        previous = None
        status = None
        try:
            manager = await Manager.request_async()
            sources_before = None
            while True:
                try:
                    sessions = list(manager.get_sessions())
                    sources = [s.source_app_user_model_id for s in sessions]
                    if sources != sources_before:
                        self.media_sources.emit(sources)
                        sources_before = sources
                    if self.media_preference == "netease":
                        session = next((s for s in sessions if any(key in s.source_app_user_model_id.lower()
                            for key in ("cloudmusic", "netease", "163music", "music.163"))), None)
                    elif self.media_preference == "current":
                        session = manager.get_current_session()
                    else:
                        session = next((s for s in sessions if s.source_app_user_model_id == self.media_preference), None)
                    if not session:
                        new_status = "未发现所选播放器的媒体会话。请播放歌曲；网易云需启用系统媒体控件（SMTC）。"
                        previous = None
                    else:
                        properties = await session.try_get_media_properties_async()
                        cover_data, cover = b"", None
                        if properties.thumbnail:
                            stream = await properties.thumbnail.open_read_async()
                            try:
                                if 0 < stream.size <= 16 * 1024 * 1024:
                                    buffer = await stream.read_async(Buffer(stream.size), stream.size, InputStreamOptions.NONE)
                                    cover_data = bytes(memoryview(buffer))
                                    with Image.open(io.BytesIO(cover_data)) as im:
                                        cover = im.convert("RGB")
                            finally:
                                stream.close()
                        key = (session.source_app_user_model_id, properties.title, properties.artist,
                               hashlib.sha256(cover_data).hexdigest())
                        new_status = f"{properties.title or '未命名媒体'} · {properties.artist or '未知歌手'}" + ("" if cover else "（播放器未提供封面）")
                        if key != previous:
                            self.media.emit({"title": properties.title, "artist": properties.artist,
                                             "cover": cover, "source": session.source_app_user_model_id})
                            previous = key
                    if new_status != status:
                        self.media_status.emit(new_status)
                        status = new_status
                except Exception as e:
                    new_status = f"媒体读取失败：{e}"
                    if new_status != status:
                        self.media_status.emit(new_status)
                        status = new_status
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.media_status.emit(f"媒体接口不可用：{e}")

    async def refresh_weather(self, city):
        city = city.strip()
        if not city:
            self.weather_status.emit("请输入天气城市")
            return
        self.weather_status.emit(f"正在获取 {city} 天气…")
        try:
            data = await asyncio.to_thread(fetch_weather, city)
            self.weather.emit(data)
            self.weather_status.emit(
                f"{data['city']} · {data['weather_text']} · {data['temperature_c']:.1f} °C")
        except Exception as exc:
            self.weather_status.emit(f"天气更新失败：{exc}")

    async def shutdown(self):
        await self.watch_media(False)
        await self.disconnect()
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def close(self):
        future = asyncio.run_coroutine_threadsafe(self.shutdown(), self.loop)
        try:
            future.result(timeout=6)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=1)
