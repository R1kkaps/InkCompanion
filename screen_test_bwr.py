"""Authorized BWR test: reuse the app-owned slot 1 from the earlier screen test."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from PIL import Image, ImageDraw
from PySide6.QtCore import QCoreApplication, Qt

from backend import Backend
from imaging import RenderOptions, font, pack_bw, pack_red, render


def make_test_image():
    source = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 399, 299), outline="black", width=3)
    draw.rectangle((12, 12, 128, 98), fill="red")
    draw.text((36, 39), "RED", font=font(22), fill="black")
    draw.rectangle((141, 12, 257, 98), fill="black")
    draw.text((157, 39), "BLACK", font=font(19), fill="white")
    draw.rectangle((270, 12, 387, 98), fill="white", outline="black", width=2)
    draw.text((286, 39), "WHITE", font=font(18), fill="black")
    for x in range(12, 388):
        t = (x - 12) / 375
        draw.line((x, 120, x, 205), fill=(255, round(255 * t), round(255 * t)))
        level = round(255 * t)
        draw.line((x, 220, x, 273), fill=(level, level, level))
    draw.text((18, 125), "RED → WHITE", font=font(14), fill="black")
    draw.text((18, 225), "BLACK → WHITE", font=font(14), fill="red")
    draw.text((8, 278), "TL", font=font(12), fill="red")
    draw.text((368, 278), "BR", font=font(12), fill="black")
    options = RenderOptions(red=True, contrast=1.0, dither=True,
                            dither_algorithm="floydSteinberg", dither_strength=1.0)
    return source, render(source, options)


def main():
    app = QCoreApplication([])
    backend = Backend()
    result = {"started_utc": datetime.now(timezone.utc).isoformat(), "sent": False,
              "target_slot": 1, "algorithm": "floydSteinberg", "strength": 1.0}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = Path(f"research/bwr-screen-test-{stamp}.log")

    def log(message):
        line = time.strftime("%H:%M:%S ") + message
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def on_sent(success, message):
        result["sent"], result["message"] = success, message
        log(message)

    backend.log.connect(log, Qt.ConnectionType.DirectConnection)
    backend.sent.connect(on_sent, Qt.ConnectionType.DirectConnection)
    backend.progress.connect(lambda value: log(f"传输 {value}%") if value % 10 == 0 else None,
                             Qt.ConnectionType.DirectConnection)

    async def run():
        await backend.scan()
        if not backend.client or not backend.client.is_connected:
            raise RuntimeError("GATT 未连接")
        await backend.prepare_display()
        result["device"] = {key: value for key, value in asdict(backend.info).items()
                            if key != "sid"}
        if backend.read_only or not backend.authorized:
            raise RuntimeError("屏幕初始化或校验未完成")
        if backend.info.slots < 2 or not backend.info.used_mask & (1 << 1):
            raise RuntimeError("先前由墨伴创建的测试槽位 1 不存在，未覆盖其他槽位")
        source, preview = make_test_image()
        source.save("research/bwr-test-source.png")
        preview.save("research/bwr-test-preview.png")
        bw, red = pack_bw(preview), pack_red(preview)
        result["bw_sha256"] = hashlib.sha256(bw).hexdigest()
        result["red_sha256"] = hashlib.sha256(red).hexdigest()
        result["red_pixels"] = sum(1 for pixel in preview.getdata() if pixel == (255, 0, 0))
        # Slot 1 was created by this project in the prior authorized test. Mark all
        # other slots unavailable locally so Backend reuses it instead of consuming slot 2.
        backend.session_slots = {1: "previous-authorized-test-frame"}
        backend.info.used_mask = (1 << backend.info.slots) - 1
        backend.cancel = False
        await backend.send(bw, cooldown=15, red=red)
        await asyncio.sleep(15 if result["sent"] else 1)

    try:
        backend.submit(run()).result(timeout=650)
    except Exception as exc:
        result["error"] = str(exc)
        log(f"测试停止：{exc}")
    finally:
        backend.close()
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        log_path.with_suffix(".json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["sent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
