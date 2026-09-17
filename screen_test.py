"""One explicitly requested test frame using the application's production backend."""
import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
from PySide6.QtCore import QCoreApplication, Qt
from backend import Backend
from imaging import pack_bw
from make_test_image import make


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-refresh', action='store_true', help='Owner authorized replacing the display with the test pattern')
    args = parser.parse_args()
    if not args.allow_refresh:
        parser.error('This test replaces the display; --allow-refresh is required')
    app = QCoreApplication([])
    backend = Backend()
    result = {'started_utc': datetime.now(timezone.utc).isoformat(), 'sent': False}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    log_path = Path(f'research/screen-test-{stamp}.log')

    def log(message):
        line = time.strftime('%H:%M:%S ') + message
        print(line, flush=True)
        with log_path.open('a', encoding='utf-8') as f:
            f.write(line + '\n')

    def on_sent(success, message):
        result['sent'] = success
        result['message'] = message
        log(message)

    backend.log.connect(log, Qt.ConnectionType.DirectConnection)
    backend.sent.connect(on_sent, Qt.ConnectionType.DirectConnection)
    backend.progress.connect(lambda p: log(f'传输 {p}%') if p % 10 == 0 else None, Qt.ConnectionType.DirectConnection)

    async def run():
        debug = logging.getLogger('bleak.backends.winrt.client')
        original_level = debug.level
        handler = logging.FileHandler(log_path.with_suffix('.connect.log'), encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        debug.addHandler(handler)
        debug.setLevel(logging.DEBUG)
        try:
            await backend.scan()
        finally:
            # Notification payloads can contain SID. Never debug-log the protocol phase.
            debug.removeHandler(handler)
            debug.setLevel(original_level)
            handler.close()
        if not backend.client or not backend.client.is_connected:
            raise RuntimeError('GATT 未连接')
        await backend.prepare_display()
        result['device'] = {k: v for k, v in asdict(backend.info).items() if k != 'sid'}
        if backend.read_only or not backend.authorized:
            raise RuntimeError('屏幕初始化或校验未完成，未发送图像')
        image = make()
        image.save('research/screen-test.png')
        payload = pack_bw(image)
        result['image_sha256'] = hashlib.sha256(payload).hexdigest()
        backend.cancel = False
        await backend.send(payload, cooldown=15)
        await asyncio.sleep(15 if result['sent'] else 1)

    try:
        backend.submit(run()).result(timeout=650)
    except Exception as exc:
        result['error'] = str(exc)
        log(f'测试停止：{exc}')
    finally:
        backend.close()
        result['finished_utc'] = datetime.now(timezone.utc).isoformat()
        log_path.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['sent'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
