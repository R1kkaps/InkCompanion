"""Initialize existing EPD driver after explicit user action; never selects a driver."""
import asyncio
import time
from protocol import CHARACTERISTIC, DeviceInfo, NotificationParser


async def prepare_screen(client, firmware, log, verifier):
    info = DeviceInfo(firmware=firmware)
    parser = NotificationParser(info)
    last_notification = time.monotonic()

    def notification(_, data):
        nonlocal last_notification
        last_notification = time.monotonic()
        try:
            text = parser.feed(bytes(data))
            if text:
                log(text)  # SID is redacted by NotificationParser.
        except Exception as exc:
            info.error = f"通知解析失败：{exc}"
            log(info.error)

    await client.start_notify(CHARACTERISTIC, notification)
    try:
        await asyncio.wait_for(client.write_gatt_char(CHARACTERISTIC, b'\x01', response=True), 10)
        started = time.monotonic()
        while time.monotonic() - started < 10:
            if info.error:
                raise RuntimeError(info.error)
            if info.configuration_received and info.mtu_received and info.sid and time.monotonic() - last_notification > .6:
                break
            await asyncio.sleep(.1)
        if not info.configuration_received:
            raise RuntimeError('未收到驱动配置；保持禁止发送')
        if not info.mtu_received:
            raise RuntimeError('未收到协议分包信息；保持禁止发送')
        if not info.supported:
            raise RuntimeError(f'当前驱动 0x{info.driver:02x} 尚未适配，未改变驱动')
        if not info.sid:
            raise RuntimeError('未收到设备校验标识')
        if not await asyncio.to_thread(verifier, info.sid):
            raise RuntimeError('官网兼容性校验未通过')
        log(f'初始化完成：驱动 0x{info.driver:02x} / {info.color} / 分包 {info.packet_size} / RLE {info.modern}')
        return info, parser
    except BaseException:
        try:
            await client.stop_notify(CHARACTERISTIC)
        except Exception:
            pass
        raise
