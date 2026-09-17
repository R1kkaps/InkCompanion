"""Exercise the desktop's real background worker and GATT UI; never write to EPD."""
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app import Window, STYLE

application = QApplication([])
application.setStyle('Fusion')
application.setStyleSheet(STYLE)
window = Window(persist=False)
window.show()
success = False


def finish(result):
    global success
    success = True
    Path('research/desktop-gatt.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('DESKTOP GATT SUCCESS:', result['firmware'], flush=True)
    QTimer.singleShot(500, capture)


def capture():
    window.grab().save('research/desktop-gatt.png')
    window.close()


window.backend.gatt.connect(finish)
window.backend.log.connect(lambda message: print(message, flush=True))
# This diagnostic must stay read-only even when normal UI connections prepare the EPD.
QTimer.singleShot(200, lambda: window.backend.submit(window.backend.scan(prepare=False)))
QTimer.singleShot(190000, window.close)
application.exec()
raise SystemExit(0 if success else 1)
