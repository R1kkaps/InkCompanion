"""Image pipeline matching epdiy.cn's BW/BWR quantizer and wire format."""
from dataclasses import dataclass, replace
from datetime import datetime
import math
from PIL import Image, ImageOps, ImageDraw, ImageFont


BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
FLOYD_STEINBERG = ((1, 0, 7 / 16), (-1, 1, 3 / 16),
                   (0, 1, 5 / 16), (1, 1, 1 / 16))
DITHER_KERNELS = {
    "floydSteinberg": (FLOYD_STEINBERG, False),
    "atkinson": (((1, 0, 1 / 8), (2, 0, 1 / 8), (-1, 1, 1 / 8),
                   (0, 1, 1 / 8), (1, 1, 1 / 8), (0, 2, 1 / 8)), True),
    "stucki": (((1, 0, 8 / 42), (2, 0, 4 / 42), (-2, 1, 2 / 42),
                (-1, 1, 4 / 42), (0, 1, 8 / 42), (1, 1, 4 / 42),
                (2, 1, 2 / 42), (-2, 2, 1 / 42), (-1, 2, 2 / 42),
                (0, 2, 4 / 42), (1, 2, 2 / 42), (2, 2, 1 / 42)), False),
    "jarvis": (((1, 0, 7 / 48), (2, 0, 5 / 48), (-2, 1, 3 / 48),
                (-1, 1, 5 / 48), (0, 1, 7 / 48), (1, 1, 5 / 48),
                (2, 1, 3 / 48), (-2, 2, 1 / 48), (-1, 2, 3 / 48),
                (0, 2, 5 / 48), (1, 2, 3 / 48), (2, 2, 1 / 48)), True),
    "burkes": (((1, 0, 1 / 4), (2, 0, 1 / 8), (-2, 1, 1 / 16),
                (-1, 1, 1 / 8), (0, 1, 1 / 4), (1, 1, 1 / 8),
                (2, 1, 1 / 16)), False),
    "sierra": (((1, 0, 5 / 32), (2, 0, 3 / 32), (-2, 1, 2 / 32),
                (-1, 1, 4 / 32), (0, 1, 5 / 32), (1, 1, 4 / 32),
                (2, 1, 2 / 32), (-1, 2, 2 / 32), (0, 2, 3 / 32),
                (1, 2, 2 / 32)), False),
}
BAYER_8X8 = (
    (0, 32, 8, 40, 2, 34, 10, 42), (48, 16, 56, 24, 50, 18, 58, 26),
    (12, 44, 4, 36, 14, 46, 6, 38), (60, 28, 52, 20, 62, 30, 54, 22),
    (3, 35, 11, 43, 1, 33, 9, 41), (51, 19, 59, 27, 49, 17, 57, 25),
    (15, 47, 7, 39, 13, 45, 5, 37), (63, 31, 55, 23, 61, 29, 53, 21),
)


@dataclass(frozen=True)
class RenderOptions:
    width: int = 400
    height: int = 300
    rotation: int = 0
    invert: bool = False
    mirror: bool = False
    flip: bool = False
    fit: str = "contain"
    dither: bool = True
    dither_algorithm: str = "floydSteinberg"
    dither_strength: float = 1.0
    threshold: int = 140
    brightness: float = 1.0
    contrast: float = 1.2
    red: bool = False
    red_threshold: int = 160
    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass(frozen=True)
class SidebarOptions:
    enabled: bool = True
    position: str = "right"
    thickness: int = 48
    battery_mv: int | None = None
    city: str = "上海"
    temperature_c: float | None = None
    weather_code: int | None = None
    weather_text: str = "--"
    is_day: bool | None = None


def _zoom_pan(image: Image.Image, size, options: RenderOptions) -> Image.Image:
    """Zoom (multiplier on the fitted size) and pan (frame units) inside the frame."""
    sw = image.width if options.scale == 1.0 else max(1, round(image.width * options.scale))
    sh = image.height if options.scale == 1.0 else max(1, round(image.height * options.scale))
    scaled = image if (sw, sh) == image.size else image.resize((sw, sh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "white")
    left = size[0] // 2 - sw // 2 + round(options.offset_x * size[0])
    top = size[1] // 2 - sh // 2 + round(options.offset_y * size[1])
    canvas.paste(scaled, (left, top))
    return canvas


def _clamp8(value):
    # JavaScript Uint8ClampedArray uses round-to-nearest, ties-to-even.
    return max(0, min(255, round(value)))


def _adjust_like_website(image, brightness, contrast):
    lift = (brightness - 1.0) * 128
    # Each channel uses the same independent transform. A 256-entry lookup
    # table is byte-for-byte equivalent to the website formula and avoids
    # running three Python loops for every preview pixel.
    table = []
    for source in range(256):
        value = _clamp8(source + lift)
        table.append(_clamp8((value - 128) * contrast + 128))
    return image.convert("RGB").point(table * 3)


def _nearest(r, g, b, bwr):
    if not bwr:
        return BLACK if .299 * r + .587 * g + .114 * b < 128 else WHITE
    # The website deliberately uses ordinary RGB Euclidean distance for BWR.
    best, distance = BLACK, float("inf")
    for color in (BLACK, WHITE, RED):
        candidate = ((r - color[0]) ** 2 + (g - color[1]) ** 2 +
                     (b - color[2]) ** 2)
        if candidate < distance:
            best, distance = color, candidate
    return best


def _palette_dither(image, algorithm, strength, bwr):
    width, height = image.size
    work = bytearray(image.convert("RGB").tobytes())
    output = bytearray(work)
    if algorithm == "bayer":
        for y in range(height):
            for x in range(width):
                i = (y * width + x) * 3
                delta = (BAYER_8X8[y % 8][x % 8] / 64 * 255 - 127.5) * strength
                color = _nearest(*(_clamp8(work[i + c] + delta) for c in range(3)), bwr)
                output[i:i + 3] = bytes(color)
        return Image.frombytes("RGB", image.size, bytes(output))
    kernel, immediate = DITHER_KERNELS.get(algorithm, DITHER_KERNELS["floydSteinberg"])
    for y in range(height):
        for x in range(width):
            i = (y * width + x) * 3
            source = tuple(work[i:i + 3])
            color = _nearest(*source, bwr)
            if immediate:
                output[i:i + 3] = bytes(color)
            error = tuple((source[c] - color[c]) * strength for c in range(3))
            for dx, dy, weight in kernel:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    ni = (ny * width + nx) * 3
                    for channel in range(3):
                        work[ni + channel] = _clamp8(work[ni + channel] + error[channel] * weight)
    if not immediate:
        for i in range(0, len(work), 3):
            output[i:i + 3] = bytes(_nearest(*work[i:i + 3], bwr))
    return Image.frombytes("RGB", image.size, bytes(output))


def _threshold_quantize(image, threshold, red_threshold=None):
    data = image.convert("RGB").tobytes()
    output = bytearray(len(data))
    for i in range(0, len(data), 3):
        r, g, b = data[i:i + 3]
        if red_threshold is not None and r > red_threshold and r > g and r > b:
            color = RED
        else:
            color = WHITE if round(.299 * r + .587 * g + .114 * b) >= threshold else BLACK
        output[i:i + 3] = bytes(color)
    return Image.frombytes("RGB", image.size, bytes(output))


def _invert_bw_palette(image):
    data = bytearray(image.convert("RGB").tobytes())
    for i in range(0, len(data), 3):
        color = tuple(data[i:i + 3])
        if color == BLACK:
            data[i:i + 3] = bytes(WHITE)
        elif color == WHITE:
            data[i:i + 3] = bytes(BLACK)
    return Image.frombytes("RGB", image.size, bytes(data))


def render(source: Image.Image, options: RenderOptions) -> Image.Image:
    """Render to an RGB image matching what the EPD will display."""
    if not (1 <= options.width <= 2000 and 1 <= options.height <= 2000):
        raise ValueError("Invalid dimensions")
    image = ImageOps.exif_transpose(source).convert("RGBA")
    white = Image.new("RGBA", image.size, "white")
    white.alpha_composite(image)
    image = white.convert("RGB").rotate(-options.rotation, expand=True)
    if options.mirror:
        image = ImageOps.mirror(image)
    if options.flip:
        image = ImageOps.flip(image)
    size = (options.width, options.height)
    if options.fit == "cover":
        image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
    elif options.fit == "stretch":
        image = image.resize(size, Image.Resampling.LANCZOS)
    else:
        image = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
    image = _zoom_pan(image, size, options)
    image = _adjust_like_website(image, options.brightness, options.contrast)
    algorithm = options.dither_algorithm if options.dither else "none"
    if algorithm != "none" and options.dither_strength > 0:
        image = _palette_dither(image, algorithm, options.dither_strength, options.red)
    else:
        image = _threshold_quantize(image, options.threshold,
                                    options.red_threshold if options.red else None)
    if options.invert:
        image = _invert_bw_palette(image)
    return image


def pack_bw(image: Image.Image) -> bytes:
    # Row-major, MSB first, white=1. Zero padding matches the website.
    width, height = image.size
    pixels = image.convert("L").load()
    stride = (width + 7) // 8
    data = bytearray(stride * height)
    for y in range(height):
        for x in range(width):
            if pixels[x, y] >= 140:
                data[y * stride + x // 8] |= 1 << (7 - x % 8)
    return bytes(data)


def pack_red(image: Image.Image, threshold: int = 160) -> bytes:
    # Website BWR polarity: 0 means red, 1 means non-red. Padding remains zero.
    width, height = image.size
    pixels = image.convert("RGB").load()
    stride = (width + 7) // 8
    data = bytearray(stride * height)
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            is_red = r > threshold and r > g and r > b
            if not is_red:
                data[y * stride + x // 8] |= 1 << (7 - x % 8)
    return bytes(data)


def pack_planes(image: Image.Image, threshold: int = 160):
    return pack_bw(image), pack_red(image, threshold)


def font(size: int):
    for path in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _center_text(draw, box, text, text_font, fill=BLACK):
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=text_font)
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    draw.text(((left + right - width) / 2 - bounds[0],
               (top + bottom - height) / 2 - bounds[1]), text, font=text_font, fill=fill)


def _weather_kind(code):
    if code is None:
        return "unknown"
    code = int(code)
    if code == 0:
        return "sun"
    if code in (1, 2):
        return "partly"
    if code in (3,):
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    if 50 <= code <= 82:
        return "rain"
    return "unknown"


def _draw_weather_icon(draw, box, code, is_day=True, fill=BLACK):
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    cx, cy = (left + right) // 2, (top + bottom) // 2
    kind = _weather_kind(code)

    def sun(x, y, radius=6):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     outline=fill, width=2)
        for degrees in range(0, 360, 45):
            angle = math.radians(degrees)
            x1 = round(x + math.cos(angle) * (radius + 3))
            y1 = round(y + math.sin(angle) * (radius + 3))
            x2 = round(x + math.cos(angle) * (radius + 6))
            y2 = round(y + math.sin(angle) * (radius + 6))
            draw.line((x1, y1, x2, y2), fill=fill, width=2)

    def moon(x, y, radius=8):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
        # White overlap creates a bold crescent that survives 1-bit conversion.
        draw.ellipse((x - 2, y - radius - 2, x + radius + 3, y + radius - 2),
                     fill=WHITE)
        draw.ellipse((x + radius - 1, y - radius + 1,
                      x + radius + 1, y - radius + 3), fill=fill)

    def cloud(x, y):
        # A filled silhouette is clearer than a fine outline on this 4.2-inch panel.
        draw.ellipse((x - 13, y - 5, x + 1, y + 8), fill=fill)
        draw.ellipse((x - 7, y - 11, x + 10, y + 8), fill=fill)
        draw.rounded_rectangle((x - 13, y, x + 13, y + 9), radius=4, fill=fill)

    day = True if is_day is None else bool(is_day)
    if kind == "sun":
        (sun if day else moon)(cx, cy)
        return
    if kind == "partly":
        (sun if day else moon)(cx - 7, cy - 7, 5 if day else 7)
        cloud(cx + 3, cy + 3)
        return
    if kind in ("cloud", "rain", "snow", "storm"):
        cloud(cx, cy - 4)
        if kind == "rain":
            for dx in (-7, 0, 7):
                draw.line((cx + dx + 1, cy + 7, cx + dx - 2, cy + 13),
                          fill=fill, width=2)
        elif kind == "snow":
            for dx in (-6, 6):
                draw.line((cx + dx - 3, cy + 10, cx + dx + 3, cy + 10), fill=fill)
                draw.line((cx + dx, cy + 7, cx + dx, cy + 13), fill=fill)
        elif kind == "storm":
            draw.line((cx + 3, cy + 5, cx - 2, cy + 11,
                       cx + 3, cy + 10, cx - 1, cy + 16), fill=fill, width=3)
        return
    if kind == "fog":
        for offset, inset in ((-7, 2), (0, 7), (7, 3)):
            draw.line((left + inset, cy + offset, right - inset, cy + offset),
                      fill=fill, width=2)
        return
    _center_text(draw, box, "?", font(max(12, min(width, height) - 8)), fill)


def _draw_stipple_fade(draw, box, horizontal=False):
    """Draw a deterministic 1-bit ordered-dot fade into otherwise empty space."""
    left, top, right, bottom = (int(v) for v in box)
    if right <= left or bottom <= top:
        return
    matrix = ((0, 8, 2, 10), (12, 4, 14, 6),
              (3, 11, 1, 9), (15, 7, 13, 5))
    span = max(1, (right - left - 1) if horizontal else (bottom - top - 1))
    for y in range(top, bottom):
        for x in range(left, right):
            progress = ((x - left) if horizontal else (y - top)) / span
            level = round(6 * (1 - progress) ** 1.55)
            if matrix[y % 4][x % 4] < level:
                draw.point((x, y), fill=BLACK)


def _draw_battery(draw, box, battery_mv):
    left, top, right, bottom = box
    cy = (top + bottom) // 2
    body_right = right - 3
    draw.rectangle((left, cy - 4, body_right, cy + 4), outline=BLACK)
    draw.rectangle((body_right + 1, cy - 2, right, cy + 2), fill=BLACK)
    if battery_mv is not None:
        # The device only reports voltage; do not invent an uncalibrated percentage.
        fraction = max(0.0, min(1.0, (battery_mv - 2400) / 650))
        fill_right = left + 2 + round(max(0, body_right - left - 3) * fraction)
        if fill_right > left + 1:
            draw.rectangle((left + 2, cy - 2, fill_right, cy + 2), fill=BLACK)


def render_with_sidebar(source, options: RenderOptions, sidebar: SidebarOptions, now=None):
    """Reserve a compact edge strip and compose date, weather and EPD voltage."""
    if not sidebar.enabled:
        return render(source, options)
    if sidebar.position not in {"top", "bottom", "left", "right"}:
        raise ValueError("Invalid sidebar position")
    rotation = options.rotation % 360
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("Invalid rotation")
    output_size = (options.width, options.height)
    # Compose in installed-screen coordinates, then rotate the complete frame.
    # This keeps the sidebar upright and on the requested physical edge after
    # the panel itself is mounted upside down or sideways.
    width, height = (output_size if rotation in {0, 180}
                     else (output_size[1], output_size[0]))
    thickness = max(34, min(48, int(sidebar.thickness)))
    vertical = sidebar.position in {"left", "right"}
    content_size = (width - thickness, height) if vertical else (width, height - thickness)
    if min(content_size) < 32:
        raise ValueError("Sidebar leaves too little room for content")
    content = render(source, replace(options, width=content_size[0], height=content_size[1],
                                     rotation=0))
    canvas = Image.new("RGB", (width, height), WHITE)
    if sidebar.position == "left":
        box, content_xy = (0, 0, thickness, height), (thickness, 0)
    elif sidebar.position == "right":
        box, content_xy = (width - thickness, 0, width, height), (0, 0)
    elif sidebar.position == "top":
        box, content_xy = (0, 0, width, thickness), (0, thickness)
    else:
        box, content_xy = (0, height - thickness, width, height), (0, 0)
    canvas.paste(content, content_xy)
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = box
    if sidebar.position == "left":
        draw.line((right - 1, top, right - 1, bottom), fill=BLACK)
    elif sidebar.position == "right":
        draw.line((left, top, left, bottom), fill=BLACK)
    elif sidebar.position == "top":
        draw.line((left, bottom - 1, right, bottom - 1), fill=BLACK)
    else:
        draw.line((left, top, right, top), fill=BLACK)
    current = now or datetime.now()
    weekdays = "一二三四五六日"
    date_text = f"{current.month:02d}/{current.day:02d}"
    weekday = f"周{weekdays[current.weekday()]}"
    temperature = "--°" if sidebar.temperature_c is None else f"{round(sidebar.temperature_c):d}°"
    voltage = "--.--V" if sidebar.battery_mv is None else f"{sidebar.battery_mv / 1000:.2f}V"
    condition = (sidebar.weather_text or "--")[:4]
    if vertical:
        scale = max(0.0, min(1.0, (thickness - 34) / 14))
        text_size = lambda small, large: round(small + (large - small) * scale)
        _center_text(draw, (left + 1, top + 5, right - 1, top + 28),
                     date_text, font(text_size(10, 14)))
        _center_text(draw, (left + 1, top + 28, right - 1, top + 51),
                     weekday, font(text_size(10, 14)))
        draw.line((left + 6, top + 57, right - 6, top + 57), fill=BLACK, width=2)
        _draw_weather_icon(draw, (left + 5, top + 64, right - 5, top + 100),
                           sidebar.weather_code, sidebar.is_day)
        _center_text(draw, (left + 1, top + 103, right - 1, top + 131),
                     temperature, font(text_size(14, 19)))
        _center_text(draw, (left + 1, top + 132, right - 1, top + 154),
                     condition, font(text_size(9, 13)))
        draw.line((left + 6, top + 160, right - 6, top + 160), fill=BLACK, width=2)
        _center_text(draw, (left + 1, top + 165, right - 1, top + 184),
                     "EPD", font(text_size(8, 11)))
        _draw_battery(draw, (left + 10, top + 190, right - 10, top + 208),
                      sidebar.battery_mv)
        _center_text(draw, (left + 1, top + 211, right - 1, top + 234),
                     voltage, font(text_size(9, 12)))
        _draw_stipple_fade(draw, (left + 3, top + 240, right - 3, bottom - 4))
    else:
        middle = (top + bottom) // 2
        _center_text(draw, (left + 5, top + 2, left + 73, bottom - 2), date_text, font(14))
        _center_text(draw, (left + 72, top + 2, left + 115, bottom - 2), weekday, font(13))
        draw.line((left + 121, top + 7, left + 121, bottom - 7), fill=BLACK, width=2)
        _draw_weather_icon(draw, (left + 128, top + 6, left + 162, bottom - 6),
                           sidebar.weather_code, sidebar.is_day)
        _center_text(draw, (left + 164, top + 2, left + 217, bottom - 2), condition, font(13))
        _center_text(draw, (left + 217, top + 2, left + 262, bottom - 2), temperature, font(17))
        draw.line((left + 269, top + 7, left + 269, bottom - 7), fill=BLACK, width=2)
        _draw_battery(draw, (left + 280, middle - 9, left + 309, middle + 9),
                      sidebar.battery_mv)
        _center_text(draw, (left + 313, top + 2, left + 358, bottom - 2), voltage, font(12))
        _draw_stipple_fade(draw, (left + 363, top + 4, right - 4, bottom - 4),
                            horizontal=True)
    # Text antialiasing creates gray edge pixels. Quantize only the strip so the
    # preview remains an exact representation of the 1-bit planes sent later.
    strip = _threshold_quantize(canvas.crop(box), 140)
    canvas.paste(strip, (left, top))
    if rotation:
        canvas = canvas.rotate(-rotation, expand=True)
    if canvas.size != output_size:
        raise RuntimeError(f"Rotated sidebar frame has unexpected size {canvas.size}")
    return canvas


def short_text(draw, text, f, width):
    if draw.textlength(text, font=f) <= width:
        return text
    while text and draw.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text + "…"


def music_card(cover, title, artist, size=(400, 300), layout="card"):
    if layout == "cover" and cover is not None:
        return ImageOps.pad(cover.convert("RGB"), size, color="white")
    w, h = size
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    pad = max(8, h // 25)
    side = h - 2 * pad
    if cover is not None:
        image.paste(ImageOps.fit(cover.convert("RGB"), (side, side)), (pad, pad))
    else:
        draw.rectangle((pad, pad, pad + side, pad + side), fill="#eeeeee")
        draw.text((pad + side // 4, h // 2 - 20), "♪", font=font(40), fill="black")
    x = side + 2 * pad
    room = w - x - pad
    if room < 60:
        return ImageOps.pad(cover.convert("RGB"), size, color="white") if cover else image
    draw.text((x, pad + 12), "正在播放", font=font(12), fill="black")
    draw.line((x, pad + 38, w - pad, pad + 38), fill="black")
    f = font(17)
    # Character wrapping handles CJK titles and long unspaced words.
    lines, line = [], ""
    for char in title or "未知曲目":
        if line and draw.textlength(line + char, font=f) > room:
            lines.append(line)
            line = ""
        line += char
    lines.append(line)
    for i, line in enumerate(lines[:5]):
        if i == 4 and len(lines) > 5:
            line = short_text(draw, line + "…", f, room)
        draw.text((x, pad + 54 + i * 25), line, font=f, fill="black")
    draw.text((x, h - 45), short_text(draw, artist or "", font(12), room), font=font(12), fill="black")
    return image


def welcome(size=(400, 300)):
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((15, 15, size[0]-16, size[1]-16), radius=12, outline="black", width=2)
    d.text((32, 42), "INK / 墨伴", font=font(34), fill="black")
    d.text((34, 107), "让画面，留在纸上。", font=font(23), fill="black")
    d.text((34, 179), "图片 · 幻灯片 · 歌曲封面", font=font(18), fill="black")
    d.text((34, 235), "ZKC42VM   /   400 × 300", font=font(14), fill="black")
    return im
