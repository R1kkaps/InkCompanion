"""Exercise real Qt controls and save reviewable UI screenshots. No BLE writes."""
from pathlib import Path
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import Window, STYLE
from imaging import pack_bw

app = QApplication([])
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
w = Window(persist=False)
w.show()

def settle_preview(timeout=10000):
    waited = 0
    while (w.preview_image is None or w.preview_running or w.preview_timer.isActive()) and waited < timeout:
        QTest.qWait(25)
        waited += 25
    assert waited < timeout, "preview render timed out"

assert w.rotation.currentIndex() == 2 and w.options().rotation == 180
assert w.sidebar_thickness.value() == 48 and w.sidebar_thickness.maximum() == 48
settle_preview()
before = pack_bw(w.preview_image)
w.invert.click()
settle_preview()
after = pack_bw(w.preview_image)
assert before != after
w.rotation.setCurrentIndex(1)
settle_preview()
assert w.preview_image.size == (400, 300)
w.red.setEnabled(True)
w.red.setChecked(True)
w.dither_algorithm.setCurrentIndex(w.dither_algorithm.findData('bayer'))
w.dither_strength.setValue(1.3)
settle_preview()
assert w.options().red and w.options().dither_algorithm == 'bayer'
assert set(w.preview_image.getdata()) <= {(0, 0, 0), (255, 255, 255), (255, 0, 0)}
w.dither.setChecked(False)
settle_preview()
assert not w.red_threshold.isHidden() and w.red_threshold.isEnabled()
w.dither.setChecked(True)
settle_preview()
w.sidebar_battery_mv = 2942
w.on_weather({'city': '上海', 'temperature_c': 26.4, 'weather_code': 2,
              'weather_text': '多云'})
settle_preview()
for position in ('right', 'left', 'top', 'bottom'):
    w.sidebar_position.setCurrentIndex(w.sidebar_position.findData(position))
    settle_preview()
    assert w.preview_image.size == (400, 300)
assert '边栏' in w.preview_caption.text()
w.invert.click()
w.rotation.setCurrentIndex(0)
settle_preview()
im = Image.new('RGB', (500, 500), '#d3e1c8')
d = ImageDraw.Draw(im)
d.ellipse((50, 50, 450, 450), fill='#203f35')
d.ellipse((150, 150, 350, 350), fill='#f1f3da')
d.ellipse((230, 230, 270, 270), fill='#203f35')
path = Path('research/qa-cover.png')
im.save(path)
w.tabs.setCurrentIndex(1)
w.playlist.addItems([str(path.absolute()), str(path.absolute())])
w.playlist.setCurrentRow(0)
w.toggle_slides()
assert w.slide_running
w.next_slide = 0
w.tick()
assert w.playlist.currentRow() == 1
w.stop_all()
assert not w.slide_running and not w.pending_auto
w.tabs.setCurrentIndex(2)
w.on_media({'cover': im, 'title': '测试封面 · 本地示例', 'artist': '界面测试', 'source': 'test'})
w.music_layout.setCurrentIndex(1)
settle_preview()
w.grab().save('research/music-preview.png')
assert w.preview_image.size == (400, 300)
w.tabs.setCurrentIndex(1)
settle_preview()
w.grab().save('research/slides-preview.png')
w.close()
print('UI PASS: invert, rotate, playlist navigation, stop, music rendering, shutdown')
