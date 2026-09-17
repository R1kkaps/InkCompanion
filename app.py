"""墨伴 — native Windows EPD companion."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QPixmap, QPainter, QFont, QPalette, QColor, QPainterPath, QLinearGradient, QPen, QBrush
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QDoubleSpinBox, QSpinBox, QFormLayout, QLineEdit,
    QGroupBox, QFileDialog, QPlainTextEdit, QProgressBar, QListWidget, QTabWidget,
    QMessageBox, QSplitter, QScrollArea)
from imaging import (RenderOptions, SidebarOptions, render_with_sidebar,
                     pack_bw, pack_red, music_card, welcome)
from backend import Backend

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
DATA = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "InkCompanion"
ASSETS = DATA / "ui-assets"
try:
    ASSETS.mkdir(parents=True, exist_ok=True)
except OSError:
    ASSETS = Path(tempfile.gettempdir()) / "InkCompanion" / "ui-assets"
    ASSETS.mkdir(parents=True, exist_ok=True)
CHECK_ICON_PATH = ASSETS / "checkbox_check.png"
CHEVRON_DOWN_PATH = ASSETS / "chevron_down.png"
CHEVRON_UP_PATH = ASSETS / "chevron_up.png"

def _ensure_assets():
    from PIL import ImageDraw
    if not CHECK_ICON_PATH.exists():
        chk = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(chk)
        d.line([(7, 16), (13, 22), (25, 9)], fill=(255, 255, 255, 255), width=4)
        chk.save(CHECK_ICON_PATH)
    if not CHEVRON_DOWN_PATH.exists():
        dn = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(dn)
        d.line([(6, 8), (10, 12), (14, 8)], fill=(120, 120, 128, 255), width=2)
        dn.save(CHEVRON_DOWN_PATH)
    if not CHEVRON_UP_PATH.exists():
        up = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(up)
        d.line([(6, 12), (10, 8), (14, 12)], fill=(120, 120, 128, 255), width=2)
        up.save(CHEVRON_UP_PATH)

try:
    _ensure_assets()
except Exception:
    pass

CHECK_ICON_URL = CHECK_ICON_PATH.resolve().as_posix()
CHEVRON_DOWN_URL = CHEVRON_DOWN_PATH.resolve().as_posix()
CHEVRON_UP_URL = CHEVRON_UP_PATH.resolve().as_posix()

DITHER_MODES = [
    ("Floyd–Steinberg", "floydSteinberg"),
    ("Jarvis–Judice–Ninke", "jarvis"),
    ("Stucki", "stucki"),
    ("Burkes", "burkes"),
    ("Sierra", "sierra"),
    ("Atkinson", "atkinson"),
    ("Bayer 8×8", "bayer"),
]
STYLE = f"""
QWidget {{
    font-family: 'Segoe UI Variable Text', 'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC', sans-serif;
    font-size: 13px;
    color: #1d1d1f;
}}
QMainWindow {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F7F8FA, stop:1 #ECEFF4);
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* Apple-style grouped surfaces */
QGroupBox {{
    background: rgba(255, 255, 255, 0.86);
    border: 1px solid rgba(60, 60, 67, 0.12);
    border-radius: 14px;
    margin-top: 24px;
    padding: 18px 14px 14px 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 2px;
    padding: 2px 4px;
    background: transparent;
    border: none;
    color: #3c3c43;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}

/* Buttons */
QPushButton {{
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid rgba(60, 60, 67, 0.14);
    border-radius: 9px;
    padding: 8px 16px;
    color: #1d1d1f;
    font-weight: 500;
    font-size: 13px;
}}
QPushButton:hover {{
    background: #ffffff;
    border-color: rgba(60, 60, 67, 0.22);
}}
QPushButton:pressed {{
    background: rgba(209, 209, 214, 0.72);
    border-color: rgba(60, 60, 67, 0.2);
}}
QPushButton:disabled {{
    background: rgba(255, 255, 255, 0.4);
    color: #a1a1a6;
    border: 1px solid rgba(0, 0, 0, 0.05);
}}
QPushButton:checked {{
    background: rgba(0, 122, 255, 0.12);
    color: #007aff;
    border: 1px solid rgba(0, 122, 255, 0.35);
    font-weight: 600;
}}
QPushButton#primary {{
    background: #007AFF;
    color: #ffffff;
    border: 1px solid #007AFF;
    border-radius: 9px;
    font-weight: 600;
    padding: 9px 18px;
    font-size: 13px;
    letter-spacing: 0.2px;
}}
QPushButton#primary:hover {{
    background: #1687FF;
    border-color: #1687FF;
}}
QPushButton#primary:pressed {{
    background: #0066D6;
    border-color: #0066D6;
}}
QPushButton#primary:disabled {{
    background: rgba(118, 118, 128, 0.10);
    color: #8e8e93;
    border: 1px solid rgba(60, 60, 67, 0.06);
}}

/* Form Controls */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: rgba(255, 255, 255, 0.94);
    border: 1px solid rgba(60, 60, 67, 0.14);
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 22px;
    color: #1d1d1f;
    font-size: 13px;
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border: 1.5px solid #007AFF;
    background: #ffffff;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border: none;
}}
QComboBox::down-arrow {{
    image: url('{CHEVRON_DOWN_URL}');
    width: 12px;
    height: 12px;
}}
QComboBox QAbstractItemView {{
    background: rgba(255, 255, 255, 0.98);
    border: 1px solid rgba(0, 0, 0, 0.1);
    border-radius: 10px;
    padding: 4px;
    selection-background-color: #007AFF;
    selection-color: #ffffff;
    color: #1d1d1f;
    outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid rgba(0, 0, 0, 0.06);
    border-bottom: 1px solid rgba(0, 0, 0, 0.06);
    border-top-right-radius: 7px;
    background: rgba(0, 0, 0, 0.02);
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
    background: rgba(0, 0, 0, 0.07);
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid rgba(0, 0, 0, 0.06);
    border-bottom-right-radius: 7px;
    background: rgba(0, 0, 0, 0.02);
}}
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: rgba(0, 0, 0, 0.07);
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url('{CHEVRON_UP_URL}');
    width: 9px;
    height: 9px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url('{CHEVRON_DOWN_URL}');
    width: 9px;
    height: 9px;
}}

/* CheckBoxes */
QCheckBox {{
    spacing: 8px;
    color: #1d1d1f;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1.5px solid #b4b9c1;
    background: rgba(255, 255, 255, 0.88);
}}
QCheckBox::indicator:hover {{
    border-color: #007AFF;
    background: #ffffff;
}}
QCheckBox::indicator:checked {{
    border: 1.5px solid #007AFF;
    background: #007AFF;
    image: url('{CHECK_ICON_URL}');
}}

/* Apple Segmented Control (Tabs) */
QTabWidget::pane {{
    border: 1px solid rgba(60, 60, 67, 0.12);
    background: rgba(255, 255, 255, 0.86);
    border-radius: 16px;
    padding: 14px;
    margin-top: 6px;
}}
QTabBar {{
    background: rgba(142, 142, 147, 0.12);
    border-radius: 10px;
    padding: 3px;
}}
QTabBar::tab {{
    background: transparent;
    color: #636366;
    font-size: 13px;
    font-weight: 500;
    padding: 7px 22px;
    border-radius: 8px;
    border: none;
    margin: 1px;
}}
QTabBar::tab:hover {{
    color: #1d1d1f;
    background: rgba(255, 255, 255, 0.45);
}}
QTabBar::tab:selected {{
    background: #ffffff;
    color: #1d1d1f;
    font-weight: 600;
    border: 0.5px solid rgba(0, 0, 0, 0.05);
}}

/* Progress Bar */
QProgressBar {{
    border: none;
    background: rgba(0, 0, 0, 0.06);
    border-radius: 5px;
    text-align: center;
    height: 10px;
    font-size: 10px;
    color: transparent;
}}
QProgressBar::chunk {{
    background: #007AFF;
    border-radius: 5px;
}}

/* Terminal / Logs */
QPlainTextEdit, QListWidget {{
    background: rgba(255, 255, 255, 0.65);
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 12px;
    padding: 8px 10px;
    font-family: -apple-system, 'SF Mono', Consolas, Menlo, 'Courier New', monospace;
    font-size: 12px;
    color: #2c2c2e;
}}
QPlainTextEdit:focus, QListWidget:focus {{
    border: 1px solid rgba(0, 122, 255, 0.5);
    background: rgba(255, 255, 255, 0.9);
}}
QListWidget::item {{
    padding: 7px 10px;
    border-radius: 7px;
    color: #1d1d1f;
}}
QListWidget::item:selected {{
    background: #007AFF;
    color: #ffffff;
}}
QListWidget::item:hover:!selected {{
    background: rgba(0, 0, 0, 0.04);
}}

/* macOS Minimalist Scrollbars */
QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 7px;
    margin: 2px 2px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: rgba(0, 0, 0, 0.16);
    min-height: 28px;
    border-radius: 3.5px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(0, 0, 0, 0.32);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    border: none;
    height: 0px;
}}
QScrollBar:horizontal {{
    border: none;
    background: transparent;
    height: 7px;
    margin: 0px 2px 2px 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(0, 0, 0, 0.16);
    min-width: 28px;
    border-radius: 3.5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(0, 0, 0, 0.32);
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
    border: none;
    width: 0px;
}}
"""


class StatusBadge(QLabel):
    """Apple-style liquid glass status badge with color-coded glow."""

    def __init__(self, text="○  尚未连接", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_style(text)

    def setText(self, text):
        super().setText(text)
        self._apply_style(text)

    def _apply_style(self, text):
        if "就绪" in text:
            # Green pill (Ready / Online) with micro glow
            self.setStyleSheet("""
                QLabel {
                    background: rgba(52, 199, 89, 0.12);
                    color: #15732f;
                    border: 1px solid rgba(52, 199, 89, 0.35);
                    border-top: 1px solid rgba(52, 199, 89, 0.55);
                    border-radius: 14px;
                    padding: 5px 16px;
                    font-size: 12px;
                    font-weight: 600;
                    letter-spacing: 0.3px;
                    min-height: 20px;
                }
            """)
        elif any(k in text for k in ("广播", "准备", "连接中", "正在")):
            # Amber / Orange pill (Connecting / Preparing / Scanning)
            self.setStyleSheet("""
                QLabel {
                    background: rgba(255, 149, 0, 0.12);
                    color: #b25800;
                    border: 1px solid rgba(255, 149, 0, 0.35);
                    border-top: 1px solid rgba(255, 149, 0, 0.55);
                    border-radius: 14px;
                    padding: 5px 16px;
                    font-size: 12px;
                    font-weight: 600;
                    letter-spacing: 0.3px;
                    min-height: 20px;
                }
            """)
        else:
            # Neutral silver glass (Disconnected / Standby)
            self.setStyleSheet("""
                QLabel {
                    background: rgba(142, 142, 147, 0.14);
                    color: #55585d;
                    border: 1px solid rgba(142, 142, 147, 0.25);
                    border-top: 1px solid rgba(255, 255, 255, 0.7);
                    border-radius: 14px;
                    padding: 5px 16px;
                    font-size: 12px;
                    font-weight: 500;
                    letter-spacing: 0.2px;
                    min-height: 20px;
                }
            """)


class PreviewCanvas(QWidget):
    """Interactive screen preview: wheel zooms, left-drag pans the image inside the frame."""

    def __init__(self, on_zoom, on_pan, on_reset, parent=None):
        super().__init__(parent)
        self._image = None
        self._on_zoom = on_zoom
        self._on_pan = on_pan
        self._on_reset = on_reset
        self._pressed = None
        self.setMinimumHeight(260)
        self.setMaximumHeight(315)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_image(self, image):
        self._image = image
        self.update()

    def frame_px(self):
        scale = min(self.width() / 400.0, self.height() / 300.0)
        return max(1, 400.0 * scale), max(1, 300.0 * scale)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w = self.width()
        h = self.height()

        # Studio Pedestal Background (frosted glass inset surface)
        pedestal_path = QPainterPath()
        pedestal_path.addRoundedRect(QRectF(0, 0, w, h), 14, 14)

        pedestal_grad = QLinearGradient(0, 0, 0, h)
        pedestal_grad.setColorAt(0.0, QColor(246, 248, 252, 220))
        pedestal_grad.setColorAt(1.0, QColor(235, 240, 248, 190))
        painter.fillPath(pedestal_path, pedestal_grad)

        painter.setPen(QPen(QColor(255, 255, 255, 240), 1))
        painter.drawPath(pedestal_path)

        if self._image is None:
            painter.setPen(QColor("#86868b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "400 × 300 墨水屏预览未就绪")
            return

        pix = QPixmap.fromImage(self._image)
        scaled = pix.scaled(max(1, w - 28), max(1, h - 48),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        sw, sh = scaled.width(), scaled.height()
        x = (w - sw) // 2
        y = (h - sh) // 2

        # One restrained shadow keeps preview repaints inexpensive.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 25, 45, 28))
        painter.drawRoundedRect(QRectF(x - 7, y - 3, sw + 14, sh + 14), 7, 7)

        # Hardware Bezel (Apple-style ultra-thin matte bezel)
        bezel_rect = QRectF(x - 3, y - 3, sw + 6, sh + 6)
        bezel_grad = QLinearGradient(0, y - 3, 0, y + sh + 3)
        bezel_grad.setColorAt(0.0, QColor("#ffffff"))
        bezel_grad.setColorAt(1.0, QColor("#e8ecf2"))
        painter.setBrush(bezel_grad)
        painter.setPen(QPen(QColor("#c5cbd6"), 1))
        painter.drawRoundedRect(bezel_rect, 4, 4)

        # E-ink Display Pixmap
        painter.drawPixmap(x, y, scaled)

        # Micro hairline border around display content
        painter.setPen(QPen(QColor(0, 0, 0, 25), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(x, y, sw, sh)

    def wheelEvent(self, event):
        factor = 1.15 ** (event.angleDelta().y() / 120)
        if factor != 1:
            self._on_zoom(factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._pressed is not None:
            pos = event.position()
            dx = pos.x() - self._pressed.x()
            dy = pos.y() - self._pressed.y()
            self._pressed = pos
            fw, fh = self.frame_px()
            self._on_pan(dx / fw, dy / fh)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_reset()


class Window(QMainWindow):
    preview_ready = Signal(int, object, object)

    def __init__(self, persist=True):
        super().__init__()
        palette = QPalette()
        for role, color in [(QPalette.ColorRole.Window, '#F4F7FC'),
                (QPalette.ColorRole.WindowText, '#1D1D1F'), (QPalette.ColorRole.Base, '#FFFFFF'),
                (QPalette.ColorRole.Text, '#1D1D1F'), (QPalette.ColorRole.Button, '#FFFFFF'),
                (QPalette.ColorRole.ButtonText, '#1D1D1F'), (QPalette.ColorRole.Highlight, '#007AFF'),
                (QPalette.ColorRole.HighlightedText, '#FFFFFF')]:
            palette.setColor(role, QColor(color))
        QApplication.instance().setPalette(palette)
        self.persist = persist
        self.setWindowTitle("墨伴 Ink Companion 1.5 · ZKC42VM")
        self.resize(1200, 870)
        self.setMinimumSize(1000, 740)
        self.backend = Backend()
        self.connected = False
        self.connecting = False
        self.busy = False
        self.source = welcome()
        self.photo_source = self.source.copy()
        self.preview_image = None
        self.preview_revision = 0
        self.preview_running = False
        self.preview_send_after = None
        self.preview_closing = False
        self.preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self.last_media = None
        self.last_hash = None
        self.flight_hash = None
        self.pending_auto = False
        self.slide_running = False
        self.next_slide = 0.0
        self.last_refresh = 0.0
        self.last_status = ""
        self.sidebar_weather = {}
        self.sidebar_battery_mv = None
        self.next_weather_refresh = 0.0
        self.weather_pending = False
        self.sidebar_date_key = datetime.now().date().isoformat()
        self._build()
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(90)
        self.preview_timer.timeout.connect(self._start_preview_render)
        self.preview_ready.connect(self._apply_preview)
        self.backend.log.connect(self.log)
        self.backend.devices.connect(self.on_devices)
        self.backend.scan_done.connect(self.scan_finished)
        self.backend.connection.connect(self.on_connection)
        self.backend.gatt.connect(self.show_gatt)
        self.backend.screen_ready.connect(self.on_screen_ready)
        self.backend.progress.connect(self.progress.setValue)
        self.backend.sent.connect(self.on_sent)
        self.backend.media.connect(self.on_media)
        self.backend.media_status.connect(self.music_status.setText)
        self.backend.media_sources.connect(self.update_media_sources)
        self.backend.weather.connect(self.on_weather)
        self.backend.weather_status.connect(self.on_weather_status)
        self._load()
        self.refresh_preview()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        if self.persist and self.sidebar_enabled.isChecked():
            QTimer.singleShot(0, self.request_weather)

    def button(self, text, slot, primary=False):
        b = QPushButton(text)
        if primary:
            b.setObjectName("primary")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _build(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title = QLabel("墨伴")
        title.setStyleSheet("font-size: 26px; font-weight: 700; color: #1d1d1f; letter-spacing: -0.4px;")
        sub = QLabel("INK COMPANION  ·  ZKC42VM  ·  4.2 英寸  ·  400 × 300")
        sub.setStyleSheet("color: #6e6e73; font-size: 12px; font-weight: 500; letter-spacing: 0.3px;")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        header.addLayout(title_box)
        header.addStretch()
        self.badge = StatusBadge("○  尚未连接")
        header.addWidget(self.badge)
        outer.addLayout(header)
        splitter = QSplitter()
        splitter.setStyleSheet("QSplitter::handle { background: transparent; width: 8px; }")
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 14, 0)
        left_layout.setSpacing(16)
        connection = QGroupBox("连接墨水屏")
        cl = QVBoxLayout(connection)
        cl.setSpacing(10)
        self.device_combo = QComboBox()
        self.device_combo.addItem("按 EPD Service UUID 捕获，无需设备名", None)
        cl.addWidget(self.device_combo)
        cr = QHBoxLayout()
        self.scan_button = self.button("连接墨水屏", self.scan, True)
        self.connect_button = self.button("停止 / 断开", self.toggle_connection)
        cr.addWidget(self.scan_button)
        cr.addWidget(self.connect_button)
        cl.addLayout(cr)
        self.device_info = QLabel("自动寻找墨水屏并读取现有配置。连接可能需要等待几十秒；兼容性校验需要网络。")
        self.device_info.setWordWrap(True)
        self.device_info.setStyleSheet("color: #86868b; font-size: 12px; line-height: 1.4;")
        cl.addWidget(self.device_info)
        self.prepare_button = self.button('重试屏幕初始化', self.prepare_again)
        self.prepare_button.setVisible(False)
        cl.addWidget(self.prepare_button)
        self.gatt_view = QPlainTextEdit()
        self.gatt_view.setReadOnly(True)
        self.gatt_view.setPlaceholderText("连接后在这里列出全部 characteristic、properties、writable")
        self.gatt_view.setMaximumHeight(130)
        self.gatt_view.setVisible(False)
        details = self.button('连接详情', lambda: None)
        details.setCheckable(True)
        details.toggled.connect(self.gatt_view.setVisible)
        cl.addWidget(details)
        cl.addWidget(self.gatt_view)
        left_layout.addWidget(connection)
        adjustments = QGroupBox("画面调整")
        form = QFormLayout(adjustments)
        form.setSpacing(8)
        form.setContentsMargins(14, 16, 14, 14)
        self.rotation = QComboBox()
        self.rotation.addItems(["0°", "90° 顺时针", "180°", "270° 顺时针"])
        self.rotation.setCurrentIndex(2)
        self.fit = QComboBox()
        self.fit.addItems(["完整显示 / 留白", "填满画面 / 居中裁剪", "拉伸至屏幕"])
        self.invert = QCheckBox("黑白反转")
        self.mirror = QCheckBox("左右镜像")
        self.flip = QCheckBox("上下翻转")
        self.dither = QCheckBox("照片抖动（保留灰度层次）")
        self.dither.setChecked(True)
        self.dither_algorithm = QComboBox()
        for label, key in DITHER_MODES:
            self.dither_algorithm.addItem(label, key)
        self.dither_strength = QDoubleSpinBox()
        self.dither_strength.setRange(0.1, 5.0)
        self.dither_strength.setSingleStep(0.1)
        self.dither_strength.setValue(1.0)
        self.red = QCheckBox("启用红色（三色屏）")
        self.red_threshold = QSpinBox()
        self.red_threshold.setRange(1, 254)
        self.red_threshold.setValue(160)
        self.zoom = QDoubleSpinBox()
        self.zoom.setRange(.1, 5)
        self.zoom.setSingleStep(.05)
        self.zoom.setDecimals(2)
        self.zoom.setValue(1)
        self.zoom.setSuffix(" 倍")
        self.offset_x = QDoubleSpinBox()
        self.offset_x.setRange(-1, 1)
        self.offset_x.setSingleStep(.01)
        self.offset_x.setDecimals(2)
        self.offset_x.setValue(0)
        self.offset_y = QDoubleSpinBox()
        self.offset_y.setRange(-1, 1)
        self.offset_y.setSingleStep(.01)
        self.offset_y.setDecimals(2)
        self.offset_y.setValue(0)
        self.brightness = QDoubleSpinBox()
        self.brightness.setRange(.2, 3)
        self.brightness.setSingleStep(.1)
        self.brightness.setValue(1)
        self.contrast = QDoubleSpinBox()
        self.contrast.setRange(.2, 3)
        self.contrast.setSingleStep(.1)
        self.contrast.setValue(1.2)
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 254)
        self.threshold.setValue(140)
        for label, widget in [("旋转", self.rotation), ("构图", self.fit), ("", self.invert),
            ("", self.mirror), ("", self.flip), ("", self.dither), ("", self.red),
            ("抖动算法", self.dither_algorithm), ("抖动强度", self.dither_strength),
            ("红色阈值", self.red_threshold), ("缩放", self.zoom), ("水平位置", self.offset_x),
            ("垂直位置", self.offset_y), ("亮度", self.brightness), ("对比度", self.contrast),
            ("黑白阈值", self.threshold)]:
            form.addRow(label, widget)
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.refresh_preview)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self.refresh_preview)
            else:
                widget.valueChanged.connect(self.refresh_preview)
        self.reset_transform = self.button("重置缩放 / 位置", lambda: self.set_transform(1, 0, 0))
        form.addRow(self.reset_transform)
        hint = QLabel("三色抖动按网页的黑/白/红调色板量化；关闭抖动后使用阈值。预览可滚轮缩放、按住左键拖动调整位置。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #86868b; font-size: 12px; line-height: 1.4;")
        form.addRow(hint)
        left_layout.addWidget(adjustments)
        schedule = QGroupBox("刷新节奏")
        sf = QFormLayout(schedule)
        sf.setSpacing(8)
        sf.setContentsMargins(14, 16, 14, 14)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(5, 600)
        self.cooldown.setValue(15)
        self.cooldown.setSuffix(" 秒")
        self.auto_edit = QCheckBox("调整画面后自动发送")
        sf.addRow("最短刷新等待", self.cooldown)
        sf.addRow(self.auto_edit)
        hint = QLabel("默认 15 秒，仅在画面变化时发送。实机刷新速度需测试；画面闪烁属于全刷过程。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #86868b; font-size: 12px; line-height: 1.4;")
        sf.addRow(hint)
        left_layout.addWidget(schedule)
        sidebar_box = QGroupBox("信息边栏")
        sidebar_form = QFormLayout(sidebar_box)
        sidebar_form.setSpacing(8)
        sidebar_form.setContentsMargins(14, 16, 14, 14)
        self.sidebar_enabled = QCheckBox("显示电量、天气和日期")
        self.sidebar_enabled.setChecked(True)
        self.sidebar_position = QComboBox()
        for label, key in (("安装后右侧", "right"), ("安装后左侧", "left"),
                           ("安装后顶部", "top"), ("安装后底部", "bottom")):
            self.sidebar_position.addItem(label, key)
        self.sidebar_thickness = QSpinBox()
        self.sidebar_thickness.setRange(34, 48)
        self.sidebar_thickness.setValue(48)
        self.sidebar_thickness.setSuffix(" px")
        self.sidebar_city = QLineEdit("上海")
        self.sidebar_city.setMaxLength(80)
        self.sidebar_city.setPlaceholderText("城市，如 上海")
        self.sidebar_auto = QCheckBox("信息变化后自动发送")
        self.sidebar_refresh = self.button("立即更新天气", self.request_weather)
        self.sidebar_status = QLabel("位置按实体安装后的方向计算。天气每 30 分钟更新；电量显示设备实测电压。")
        self.sidebar_status.setWordWrap(True)
        self.sidebar_status.setStyleSheet("color: #86868b; font-size: 12px; line-height: 1.4;")
        sidebar_form.addRow(self.sidebar_enabled)
        sidebar_form.addRow("位置", self.sidebar_position)
        sidebar_form.addRow("边栏厚度", self.sidebar_thickness)
        sidebar_form.addRow("天气城市", self.sidebar_city)
        sidebar_form.addRow(self.sidebar_refresh)
        sidebar_form.addRow(self.sidebar_auto)
        sidebar_form.addRow(self.sidebar_status)
        self.sidebar_enabled.toggled.connect(self.sidebar_changed)
        self.sidebar_position.currentIndexChanged.connect(self.refresh_preview)
        self.sidebar_thickness.valueChanged.connect(self.refresh_preview)
        self.sidebar_city.editingFinished.connect(self.request_weather)
        left_layout.addWidget(sidebar_box)
        left_layout.addStretch()
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(330)
        splitter.addWidget(scroll)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.setSpacing(14)
        self.tabs = QTabWidget()
        self.tabs.tabBar().setCursor(Qt.CursorShape.PointingHandCursor)
        photo = QWidget()
        pl = QVBoxLayout(photo)
        pl.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(self.button("导入图片", self.import_image, True))
        self.save_preview_button = self.button("保存屏幕预览", self.save_preview)
        row.addWidget(self.save_preview_button)
        pl.addLayout(row)
        photo_tip = QLabel("支持 PNG、JPG、BMP、WebP；透明背景自动铺白。")
        photo_tip.setStyleSheet("color: #86868b; font-size: 12px;")
        pl.addWidget(photo_tip)
        self.tabs.addTab(photo, "图片")
        slide = QWidget()
        sl = QVBoxLayout(slide)
        sl.setSpacing(10)
        self.playlist = QListWidget()
        self.playlist.setMaximumHeight(90)
        self.playlist.currentRowChanged.connect(self.show_slide)
        sl.addWidget(self.playlist)
        sr = QHBoxLayout()
        sr.addWidget(self.button("添加图片", self.add_slides))
        sr.addWidget(self.button("移除", self.remove_slide))
        self.slide_button = self.button("开始轮播", self.toggle_slides)
        sr.addWidget(self.slide_button)
        self.slide_interval = QSpinBox()
        self.slide_interval.setRange(15, 86400)
        self.slide_interval.setValue(60)
        self.slide_interval.setSuffix(" 秒 / 张")
        sr.addWidget(self.slide_interval)
        sl.addLayout(sr)
        self.tabs.addTab(slide, "幻灯片")
        music = QWidget()
        ml = QVBoxLayout(music)
        ml.setSpacing(10)
        mr = QHBoxLayout()
        self.watch = QCheckBox("监听 Windows 正在播放")
        self.watch.toggled.connect(lambda enabled: self.backend.submit(self.backend.watch_media(enabled)))
        self.music_auto = QCheckBox("封面变化时自动发到屏幕")
        self.music_auto.toggled.connect(lambda enabled: self.queue_auto() if enabled and self.last_media else None)
        mr.addWidget(self.watch)
        mr.addWidget(self.music_auto)
        ml.addLayout(mr)
        self.media_source = QComboBox()
        self.media_source.addItem("网易云音乐（自动识别）", "netease")
        self.media_source.addItem("Windows 当前媒体会话", "current")
        self.media_source.currentIndexChanged.connect(self.change_media_source)
        ml.addWidget(self.media_source)
        self.music_layout = QComboBox()
        self.music_layout.addItems(["只显示封面", "封面 + 歌名 / 歌手"])
        self.music_layout.currentIndexChanged.connect(self.recompose_music)
        ml.addWidget(self.music_layout)
        self.music_status = QLabel("开启监听后读取播放器提供的封面。没有封面时会显示占位画面。")
        self.music_status.setWordWrap(True)
        self.music_status.setStyleSheet("color: #86868b; font-size: 12px; line-height: 1.4;")
        ml.addWidget(self.music_status)
        self.tabs.addTab(music, "歌曲封面")
        self.tabs.currentChanged.connect(self.tab_changed)
        rl.addWidget(self.tabs)
        preview_box = QGroupBox("屏幕预览 · 与发送像素一致")
        pv = QVBoxLayout(preview_box)
        pv.setSpacing(6)
        pv.setContentsMargins(14, 16, 14, 14)
        self.preview = PreviewCanvas(self.zoom_by, self.pan_by,
                                     lambda: self.set_transform(1, 0, 0))
        self.preview_caption = QLabel("400 × 300 · 黑白 · 15,000 字节")
        self.preview_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_caption.setStyleSheet("font-size: 13px; font-weight: 600; color: #1d1d1f; margin-top: 2px;")
        pv.addWidget(self.preview_caption)
        self.preview_hint = QLabel("滚轮：缩放   左键拖动：移动位置   双击预览：重置")
        self.preview_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_hint.setStyleSheet("font-size: 11px; color: #86868b; margin-bottom: 4px;")
        pv.addWidget(self.preview_hint)
        pv.addWidget(self.preview, 1)
        rl.addWidget(preview_box, 1)
        actions = QHBoxLayout()
        self.send_button = self.button("发送到墨水屏", lambda: self.send(manual=True), True)
        self.send_button.setEnabled(False)
        actions.addWidget(self.send_button, 1)
        self.stop_button = self.button("停止自动 / 取消传输", self.stop_all)
        actions.addWidget(self.stop_button)
        rl.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        rl.addWidget(self.progress)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(250)
        self.logs.setMaximumHeight(100)
        rl.addWidget(self.logs)
        splitter.addWidget(right)
        splitter.setSizes([345, 810])
        outer.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def options(self):
        return RenderOptions(rotation=self.rotation.currentIndex() * 90, invert=self.invert.isChecked(),
            mirror=self.mirror.isChecked(), flip=self.flip.isChecked(),
            fit=["contain", "cover", "stretch"][self.fit.currentIndex()], dither=self.dither.isChecked(),
            threshold=self.threshold.value(), brightness=self.brightness.value(), contrast=self.contrast.value(),
            red=self.red.isChecked() and self.red.isEnabled(), red_threshold=self.red_threshold.value(),
            dither_algorithm=self.dither_algorithm.currentData(),
            dither_strength=self.dither_strength.value(),
            scale=self.zoom.value(), offset_x=self.offset_x.value(), offset_y=self.offset_y.value())

    def sidebar_options(self):
        weather = self.sidebar_weather
        return SidebarOptions(
            enabled=self.sidebar_enabled.isChecked(),
            position=self.sidebar_position.currentData(),
            thickness=self.sidebar_thickness.value(),
            battery_mv=self.sidebar_battery_mv,
            city=weather.get("city") or self.sidebar_city.text().strip() or "--",
            temperature_c=weather.get("temperature_c"),
            weather_code=weather.get("weather_code"),
            weather_text=weather.get("weather_text", "--"),
            is_day=weather.get("is_day"),
        )

    def refresh_preview(self, *_):
        if not hasattr(self, "preview"):
            return
        self.threshold.setEnabled(not self.dither.isChecked())
        self.red_threshold.setEnabled(self.red.isChecked() and self.red.isEnabled() and not self.dither.isChecked())
        self.dither_algorithm.setEnabled(self.dither.isChecked())
        self.dither_strength.setEnabled(self.dither.isChecked())
        opt = self.options()
        color_caption = ("三色（黑白红）· 双平面 30,000 字节" if opt.red
                         else "黑白 · 15,000 字节")
        sidebar_caption = f" · {self.sidebar_position.currentText()} {self.sidebar_thickness.value()} px 边栏" if self.sidebar_enabled.isChecked() else ""
        self.preview_caption.setText(f"400 × 300 · {color_caption}{sidebar_caption} · 生成中…")
        self.preview_revision += 1
        self.save_preview_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.preview_timer.start()

    def _start_preview_render(self):
        if self.preview_running or self.preview_closing:
            return
        revision = self.preview_revision
        source = self.source.copy()
        options = self.options()
        sidebar = self.sidebar_options()
        self.preview_running = True
        future = self.preview_executor.submit(render_with_sidebar, source, options, sidebar)

        def completed(result):
            try:
                image, error = result.result(), None
            except Exception as exc:
                image, error = None, f"{type(exc).__name__}: {exc}"
            if not self.preview_closing:
                self.preview_ready.emit(revision, image, error)

        future.add_done_callback(completed)

    def _apply_preview(self, revision, image, error):
        self.preview_running = False
        if error and revision == self.preview_revision:
            self.log(f"预览生成失败：{error}")
            self.preview_caption.setText("预览生成失败")
            self.preview_send_after = None
        elif revision == self.preview_revision:
            self.preview_image = image
            self.draw_preview()
            opt = self.options()
            color_caption = ("三色（黑白红）· 双平面 30,000 字节" if opt.red
                             else "黑白 · 15,000 字节")
            sidebar_caption = (f" · {self.sidebar_position.currentText()} {self.sidebar_thickness.value()} px 边栏"
                               if self.sidebar_enabled.isChecked() else "")
            self.preview_caption.setText(f"400 × 300 · {color_caption}{sidebar_caption}")
            self.save_preview_button.setEnabled(True)
            self.send_button.setEnabled(
                self.connected and not self.backend.read_only and not self.busy)
            if self.auto_edit.isChecked():
                self.queue_auto()
        if revision != self.preview_revision:
            self.preview_timer.start(0)
            return
        if self.preview_send_after is not None and image is not None and not error:
            manual = self.preview_send_after
            self.preview_send_after = None
            QTimer.singleShot(0, lambda: self.send(manual=manual))

    def draw_preview(self):
        if self.preview_image is not None:
            self.preview.set_image(ImageQt(self.preview_image.convert("RGB")))

    def zoom_by(self, factor):
        self.zoom.setValue(round(max(.1, min(5, self.zoom.value() * factor)), 2))

    def pan_by(self, dx, dy):
        self.offset_x.setValue(round(max(-1, min(1, self.offset_x.value() + dx)), 3))
        self.offset_y.setValue(round(max(-1, min(1, self.offset_y.value() + dy)), 3))

    def set_transform(self, scale, x, y):
        self.zoom.setValue(scale)
        self.offset_x.setValue(x)
        self.offset_y.setValue(y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview"):
            QTimer.singleShot(0, self.draw_preview)

    def log(self, message):
        self.logs.appendPlainText(time.strftime("%H:%M:%S  ") + message)
        if self.persist:
            DATA.mkdir(parents=True, exist_ok=True)
            path = DATA / "app.log"
            if path.exists() and path.stat().st_size > 2_000_000:
                path.replace(DATA / "app.previous.log")
            with path.open("a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + message + "\n")

    def scan(self):
        if self.connected or self.connecting:
            return
        self.connecting = True
        self.scan_button.setEnabled(False)
        self.badge.setText("◌  等待 UUID 广播")
        self.log("持续捕获 EPD UUID；命中后自动连接，使用当次广播的地址和地址类型")
        self.backend.submit(self.backend.scan(prepare=True))

    def scan_finished(self):
        self.connecting = False
        self.scan_button.setEnabled(not self.connected)

    def on_devices(self, devices):
        self.device_combo.clear()
        for name, device in devices:
            self.device_combo.addItem(f"{name}  ·  {device.address}", device)
        if not devices:
            self.device_combo.addItem("未发现墨水屏；请唤醒设备后重试", None)

    def toggle_connection(self):
        self.stop_all()
        self.backend.submit(self.backend.disconnect())

    def on_connection(self, connected, info):
        self.connected = connected
        self.connect_button.setEnabled(True)
        self.connect_button.setText("停止 / 断开")
        self.scan_button.setEnabled(not connected)
        self.device_combo.setEnabled(not connected)
        self.send_button.setEnabled(False)
        self.prepare_button.setVisible(False)
        self.badge.setText("◌  已连接，准备屏幕中" if connected else "○  尚未连接")
        if connected:
            self.last_hash = None
            self.device_info.setText(f"已连接 · 固件 {info.firmware}\n正在读取现有屏幕配置…")
        else:
            self.stop_all()

    def prepare_again(self):
        self.prepare_button.setEnabled(False)
        self.backend.submit(self.backend.prepare_display())

    def on_screen_ready(self, ready, info):
        self.send_button.setEnabled(ready and self.connected and not self.busy)
        self.prepare_button.setVisible(not ready and self.connected)
        self.prepare_button.setEnabled(True)
        if ready:
            self.sidebar_battery_mv = info.battery_mv
            self.badge.setText('●  屏幕已就绪')
            battery = f' · {info.battery_mv / 1000:.2f} V' if info.battery_mv else ''
            self.device_info.setText(f'固件 {info.firmware}\n400 × 300 · {info.color} · 驱动 0x{info.driver:02X}{battery}')
            self.red.setEnabled(info.color == "BWR")
            if info.color == "BWR" and self.red.isChecked():
                self.log("三色屏已就绪：红色平面已启用")
            self.refresh_preview()
        elif self.connected:
            self.badge.setText('○  屏幕初始化未完成')

    def show_gatt(self, result):
        self.gatt_view.setPlainText("\n".join(
            f"{s['uuid']}\n" + "\n".join(f"  {c['uuid']}\n  {', '.join(c['properties'])} | writable={c['writable']}"
                for c in s['characteristics']) for s in result['services']))
        self.device_combo.clear()
        self.device_combo.addItem(f"{result['address']} / {result['address_type']} / 当次捕获")

    def import_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.load_image(path)

    def load_image(self, path):
        try:
            with Image.open(path) as im:
                self.source = im.copy()
            if self.tabs.currentIndex() == 0:
                self.photo_source = self.source.copy()
            self.refresh_preview()
            self.log(f"已载入：{Path(path).name}")
        except Exception as e:
            self.log(f"图片读取失败：{e}")
            return False
        return True

    def save_preview(self):
        if self.preview_image is None or self.preview_running or self.preview_timer.isActive():
            self.log("预览仍在生成，请稍候")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出屏幕像素", "ink-preview.png", "PNG (*.png)")
        if path:
            try:
                self.preview_image.save(path)
                self.log("预览已保存")
            except Exception as e:
                self.log(f"保存失败：{e}")

    def add_slides(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加幻灯片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        for path in paths:
            self.playlist.addItem(path)
        if self.playlist.currentRow() < 0 and paths:
            self.playlist.setCurrentRow(0)

    def remove_slide(self):
        self.playlist.takeItem(self.playlist.currentRow())
        if not self.playlist.count():
            self.slide_running = False
            self.slide_button.setText("开始轮播")

    def show_slide(self, index):
        if index >= 0 and self.tabs.currentIndex() == 1:
            item = self.playlist.item(index)
            if item and not self.load_image(item.text()):
                self.slide_running = False
                self.slide_button.setText("开始轮播")

    def toggle_slides(self):
        if not self.playlist.count():
            self.add_slides()
            return
        self.slide_running = not self.slide_running
        self.slide_button.setText("暂停轮播" if self.slide_running else "开始轮播")
        if self.slide_running:
            self.music_auto.setChecked(False)
            index = max(0, self.playlist.currentRow())
            self.playlist.setCurrentRow(index)
            self.show_slide(index)
            self.next_slide = time.monotonic() + self.slide_interval.value()
            self.queue_auto()

    def on_media(self, data):
        self.last_media = data
        if self.tabs.currentIndex() == 2:
            self.recompose_music()

    def update_media_sources(self, sources):
        selected = self.media_source.currentData()
        self.media_source.blockSignals(True)
        while self.media_source.count() > 2:
            self.media_source.removeItem(2)
        for source in sources:
            self.media_source.addItem(source, source)
        index = self.media_source.findData(selected)
        self.media_source.setCurrentIndex(max(0, index))
        self.media_source.blockSignals(False)
        self.backend.media_preference = self.media_source.currentData()

    def change_media_source(self, *_):
        self.backend.media_preference = self.media_source.currentData()
        self.last_media = None
        self.pending_auto = False

    def recompose_music(self, *_):
        if self.last_media and self.tabs.currentIndex() == 2:
            data = self.last_media
            self.source = data["cover"].copy() if self.music_layout.currentIndex() == 0 and data["cover"] is not None else music_card(
                data["cover"], data["title"], data["artist"], layout="card")
            self.refresh_preview()
            if self.music_auto.isChecked():
                self.queue_auto()

    def tab_changed(self, index):
        self.pending_auto = False
        if index != 1:
            self.slide_running = False
            self.slide_button.setText("开始轮播")
        if index == 2:
            self.recompose_music()
        elif index == 1:
            self.show_slide(self.playlist.currentRow())
        elif index == 0:
            self.source = self.photo_source.copy()
            self.refresh_preview()

    def queue_auto(self):
        self.pending_auto = True
        self.edit_ready = time.monotonic() + 1

    def sidebar_changed(self, enabled):
        for widget in (self.sidebar_position, self.sidebar_thickness, self.sidebar_city,
                       self.sidebar_auto, self.sidebar_refresh):
            widget.setEnabled(enabled)
        self.refresh_preview()
        if enabled and self.persist and not self.sidebar_weather:
            self.request_weather()

    def request_weather(self):
        if not self.sidebar_enabled.isChecked() or self.weather_pending:
            return
        city = self.sidebar_city.text().strip()
        if not city:
            self.sidebar_status.setText("请输入天气城市")
            return
        self.weather_pending = True
        self.next_weather_refresh = time.monotonic() + 30 * 60
        self.backend.submit(self.backend.refresh_weather(city))

    def on_weather(self, data):
        self.weather_pending = False
        self.sidebar_weather = dict(data)
        if self.persist:
            try:
                DATA.mkdir(parents=True, exist_ok=True)
                cached = dict(data)
                cached["cached_at"] = time.time()
                (DATA / "weather.json").write_text(
                    json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as exc:
                self.log(f"天气缓存保存失败：{exc}")
        self.refresh_preview()
        if self.sidebar_auto.isChecked():
            self.queue_auto()

    def on_weather_status(self, message):
        self.sidebar_status.setText(message)
        if not message.startswith("正在获取"):
            self.weather_pending = False

    def tick(self):
        now = time.monotonic()
        date_key = datetime.now().date().isoformat()
        if self.sidebar_enabled.isChecked() and date_key != self.sidebar_date_key:
            self.sidebar_date_key = date_key
            self.refresh_preview()
            if self.sidebar_auto.isChecked():
                self.queue_auto()
        if (self.persist and self.sidebar_enabled.isChecked() and not self.weather_pending
                and now >= self.next_weather_refresh):
            self.request_weather()
        if self.slide_running and not self.busy and now >= self.next_slide and self.playlist.count():
            self.playlist.setCurrentRow((self.playlist.currentRow()+1) % self.playlist.count())
            self.next_slide = now + self.slide_interval.value()
            self.queue_auto()
        if self.pending_auto and self.connected and not self.backend.read_only and not self.busy and now >= getattr(self, "edit_ready", 0) and now - self.last_refresh >= self.cooldown.value():
            self.pending_auto = False
            self.send(manual=False)

    def send(self, manual=False):
        if self.backend.read_only or not self.connected or self.busy:
            return
        if self.preview_image is None or self.preview_running or self.preview_timer.isActive():
            self.preview_send_after = bool(manual or self.preview_send_after)
            self.preview_timer.stop()
            self._start_preview_render()
            if manual:
                self.log("画面正在生成，完成后立即发送")
            return
        opt = self.options()
        bw = pack_bw(self.preview_image)
        red = pack_red(self.preview_image, opt.red_threshold) if opt.red else None
        digest = hashlib.sha256(bw + (red or b"")).hexdigest()
        if not manual and digest == self.last_hash:
            return
        self.busy = True
        self.backend.cancel = False
        self.flight_hash = digest
        self.send_button.setEnabled(False)
        self.progress.setValue(0)
        self.backend.submit(self.backend.send(bw, self.cooldown.value(), red=red))

    def on_sent(self, success, message):
        self.busy = False
        self.send_button.setEnabled(self.connected and not self.backend.read_only)
        if success:
            self.last_hash = self.flight_hash
            self.last_refresh = time.monotonic()
        else:
            self.stop_all()
        self.log(message)

    def stop_all(self):
        self.pending_auto = False
        self.slide_running = False
        self.slide_button.setText("开始轮播")
        self.music_auto.setChecked(False)
        self.auto_edit.setChecked(False)
        self.sidebar_auto.setChecked(False)
        self.backend.cancel = True

    def _load(self):
        if not self.persist:
            return
        try:
            settings = json.loads((DATA / "settings.json").read_text(encoding="utf-8"))
            # One-time migration for this upside-down mounted screen. Once the
            # schema marker is saved, later manual direction choices persist.
            rotation = settings.get("rotation", 2) if settings.get("orientation_schema") == 1 else 2
            self.rotation.setCurrentIndex(rotation)
            self.fit.setCurrentIndex(settings.get("fit", 0))
            self.music_layout.setCurrentIndex(settings.get('music_layout', 0))
            self.sidebar_enabled.setChecked(settings.get("sidebar_enabled", True))
            self.sidebar_auto.setChecked(settings.get("sidebar_auto", False))
            sidebar_index = self.sidebar_position.findData(settings.get("sidebar_position", "right"))
            self.sidebar_position.setCurrentIndex(max(0, sidebar_index))
            thickness = (settings.get("sidebar_thickness", 48)
                         if settings.get("sidebar_schema") == 1 else 48)
            self.sidebar_thickness.setValue(thickness)
            self.sidebar_city.setText(settings.get("sidebar_city", "上海"))
            algorithm = settings.get("dither_algorithm", "floydSteinberg")
            algorithm_index = self.dither_algorithm.findData(algorithm)
            self.dither_algorithm.setCurrentIndex(max(0, algorithm_index))
            for key in ("invert", "mirror", "flip", "dither"):
                getattr(self, key).setChecked(settings.get(key, key == "dither"))
            self.red.setChecked(settings.get("red", False))
            self.red_threshold.setValue(settings.get("red_threshold", 160))
            self.zoom.setValue(settings.get("zoom", 1))
            self.offset_x.setValue(settings.get("offset_x", 0))
            self.offset_y.setValue(settings.get("offset_y", 0))
            for key in ("brightness", "contrast", "threshold", "cooldown", "slide_interval",
                        "dither_strength"):
                if key in settings:
                    getattr(self, key).setValue(settings[key])
            for path in settings.get("playlist", []):
                if Path(path).is_file():
                    self.playlist.addItem(path)
        except (OSError, ValueError, TypeError):
            pass
        try:
            cached = json.loads((DATA / "weather.json").read_text(encoding="utf-8"))
            if isinstance(cached, dict) and "temperature_c" in cached and "weather_code" in cached:
                self.sidebar_weather = cached
        except (OSError, ValueError, TypeError):
            pass

    def closeEvent(self, event):
        self.timer.stop()
        self.preview_timer.stop()
        self.preview_closing = True
        self.stop_all()
        if self.persist:
            DATA.mkdir(parents=True, exist_ok=True)
            settings = {"rotation": self.rotation.currentIndex(), "orientation_schema": 1,
                "fit": self.fit.currentIndex(),
                "music_layout": self.music_layout.currentIndex(),
                "dither_algorithm": self.dither_algorithm.currentData(),
                "sidebar_enabled": self.sidebar_enabled.isChecked(),
                "sidebar_auto": self.sidebar_auto.isChecked(),
                "sidebar_schema": 1,
                "sidebar_position": self.sidebar_position.currentData(),
                "sidebar_thickness": self.sidebar_thickness.value(),
                "sidebar_city": self.sidebar_city.text().strip(),
                "playlist": [self.playlist.item(i).text() for i in range(self.playlist.count())]}
            for key in ("invert", "mirror", "flip", "dither", "red"):
                settings[key] = getattr(self, key).isChecked()
            for key in ("brightness", "contrast", "threshold", "cooldown", "slide_interval",
                        "red_threshold", "dither_strength", "zoom", "offset_x", "offset_y"):
                settings[key] = getattr(self, key).value()
            (DATA / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self.preview_executor.shutdown(wait=False, cancel_futures=True)
        self.backend.close()
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--screenshot")
    parser.add_argument("--native-check", help="Write a read-only native API diagnostic JSON, then exit")
    args = parser.parse_args()
    if args.native_check:
        from native_check import run
        import asyncio
        asyncio.run(run(args.native_check))
        return
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(persist=not args.smoke)
    window.show()
    if args.screenshot:
        QTimer.singleShot(1400, lambda: window.grab().save(args.screenshot))
    if args.smoke:
        QTimer.singleShot(2000, window.close)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
