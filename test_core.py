import asyncio
from dataclasses import replace
import random
import unittest
from unittest.mock import patch
from datetime import datetime
from PIL import Image, ImageDraw, ImageOps
from PySide6.QtCore import QCoreApplication
from imaging import (render, render_with_sidebar, RenderOptions, SidebarOptions,
                     _adjust_like_website,
                     pack_bw, pack_red, pack_planes, music_card)
from protocol import image_packets, DeviceInfo, NotificationParser
from backend import Backend


def unpack_rle(data):
    result, i = bytearray(), 0
    while i < len(data):
        tag = data[i]
        i += 1
        if tag & 128:
            result.extend(bytes([data[i]]) * ((tag & 127) + 3))
            i += 1
        else:
            result.extend(data[i:i+tag+1])
            i += tag + 1
    return bytes(result)


WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)


class ImageTests(unittest.TestCase):
    def test_adjustment_lookup_matches_original_formula(self):
        source = Image.new("RGB", (6, 1))
        source.putdata([(v, v, v) for v in (0, 17, 127, 128, 200, 255)])
        brightness, contrast = 1.25, 0.8
        def clamp(value):
            return max(0, min(255, round(value)))
        expected = []
        for value in (0, 17, 127, 128, 200, 255):
            lifted = clamp(value + (brightness - 1.0) * 128)
            adjusted = clamp((lifted - 128) * contrast + 128)
            expected.append((adjusted,) * 3)
        self.assertEqual(list(_adjust_like_website(source, brightness, contrast).getdata()), expected)

    def test_known_msb_and_row_padding(self):
        im = Image.new("L", (9, 2), 0)
        im.putpixel((0, 0), 255)
        im.putpixel((8, 0), 255)
        im.putpixel((7, 1), 255)
        self.assertEqual(pack_bw(im), b"\x80\x80\x01\x00")

    def test_screen_size_and_white_polarity(self):
        self.assertEqual(pack_bw(Image.new("1", (400, 300), 1)), b"\xff" * 15000)
        self.assertEqual(pack_bw(Image.new("1", (400, 300), 0)), b"\0" * 15000)

    def test_invert(self):
        im = Image.new("RGB", (10, 10), "black")
        opt = RenderOptions(width=10, height=10, dither=False, contrast=1)
        self.assertEqual(render(im, replace(opt, invert=True)).getextrema(), ((255, 255),) * 3)

    def test_transparency_becomes_white(self):
        im = Image.new("RGBA", (3, 3), (0, 0, 0, 0))
        out = render(im, RenderOptions(width=3, height=3))
        self.assertEqual(out.getextrema(), ((255, 255),) * 3)

    def test_rotation_and_mirror(self):
        im = Image.new("L", (2, 2), 0)
        im.putpixel((0, 0), 255)
        opt = RenderOptions(width=2, height=2, dither=False, contrast=1)
        self.assertEqual(render(im, replace(opt, rotation=90)).getpixel((1, 0)), WHITE)
        self.assertEqual(render(im, replace(opt, mirror=True)).getpixel((1, 0)), WHITE)
        self.assertEqual(render(im, replace(opt, flip=True)).getpixel((0, 1)), WHITE)

    def test_red_classification_matches_website_rule(self):
        im = Image.new("RGB", (4, 1))
        im.putpixel((0, 0), RED)
        im.putpixel((1, 0), (200, 10, 10))   # R>160 and R>G and R>B → red
        im.putpixel((2, 0), WHITE)
        im.putpixel((3, 0), BLACK)
        out = render(im, RenderOptions(width=4, height=1, red=True, dither=False, contrast=1))
        self.assertEqual(out.getpixel((0, 0)), RED)
        self.assertEqual(out.getpixel((1, 0)), RED)
        self.assertEqual(out.getpixel((2, 0)), WHITE)
        self.assertEqual(out.getpixel((3, 0)), BLACK)

    def test_red_plane_polarity_and_bw_plane(self):
        im = Image.new("RGB", (4, 1))
        im.putpixel((0, 0), RED)
        im.putpixel((1, 0), (200, 10, 10))   # R>160 and R>G and R>B → red
        im.putpixel((2, 0), WHITE)
        im.putpixel((3, 0), BLACK)
        out = render(im, RenderOptions(width=4, height=1, red=True, dither=False, contrast=1))
        bw, red = pack_planes(out, 160)
        # Website polarity is active-low: red=0, non-red=1. Padding stays zero.
        self.assertEqual(red, b"\x30")
        # BW plane: only white pixel px2 is set → 0010.
        self.assertEqual(bw, b"\x20")

    def test_empty_red_plane_clears_red(self):
        out = render(Image.new("RGB", (400, 300), WHITE),
                     RenderOptions(width=400, height=300, red=True, dither=False, contrast=1))
        self.assertEqual(pack_red(out), b"\xff" * 15000)

    def test_bwr_floyd_steinberg_matches_website_fixture(self):
        colors = [
            (250, 20, 20), (180, 120, 100), (240, 240, 240), (20, 20, 20),
            (120, 40, 40), (180, 180, 180), (80, 90, 100), (245, 80, 60),
            (30, 30, 30), (220, 170, 160), (130, 130, 130), (255, 255, 255),
        ]
        source = Image.new("RGB", (4, 3))
        source.putdata(colors)
        result = render(source, RenderOptions(width=4, height=3, red=True,
                        contrast=1, dither_algorithm="floydSteinberg", dither_strength=1))
        labels = {BLACK: "K", WHITE: "W", RED: "R"}
        self.assertEqual("".join(labels[p] for p in result.getdata()), "RRWKKWKRKWWW")

    def test_all_website_dither_modes_return_only_panel_colors(self):
        source = Image.new("RGB", (9, 7))
        source.putdata([((x * 29) % 256, (x * 71) % 256, (x * 113) % 256)
                        for x in range(63)])
        for algorithm in ("floydSteinberg", "jarvis", "stucki", "burkes",
                          "sierra", "atkinson", "bayer"):
            result = render(source, RenderOptions(width=9, height=7, red=True,
                            contrast=1, dither_algorithm=algorithm, dither_strength=1))
            self.assertLessEqual(set(result.getdata()), {BLACK, WHITE, RED})

    def test_zoom_pan_crops_and_positions(self):
        im = Image.new("RGB", (400, 300), WHITE)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 199, 299), fill=BLACK)
        base = RenderOptions(width=400, height=300, dither=False, contrast=1)
        # Zoom 2x centered on the left half → frame shows only the black half.
        left = render(im, replace(base, scale=2.0, offset_x=0.5))
        self.assertEqual(left.getpixel((0, 0)), BLACK)
        self.assertEqual(left.getpixel((399, 0)), BLACK)
        # Pan right by one frame → frame shows only the white half.
        right = render(im, replace(base, scale=2.0, offset_x=-0.5))
        self.assertEqual(right.getpixel((0, 0)), WHITE)
        self.assertEqual(right.getpixel((399, 0)), WHITE)
        # Zoom out below 1.0 → white margins around the image.
        small = render(im, replace(base, scale=0.5))
        self.assertEqual(small.size, (400, 300))
        self.assertEqual(small.getpixel((0, 0)), WHITE)

    def test_contain_pads_to_frame(self):
        im = Image.new("RGB", (200, 100), (200, 30, 30))
        out = render(im, RenderOptions(width=400, height=300, dither=False, contrast=1))
        self.assertEqual(out.size, (400, 300))
        self.assertEqual(out.getpixel((0, 0)), WHITE)

    def test_music_cover_and_missing_cover(self):
        for cover in [None, Image.new("RGB", (700, 700), "red")]:
            for layout in ["cover", "card"]:
                im = music_card(cover, "一个非常长的歌曲名称" * 4, "歌手", layout=layout)
                self.assertEqual(im.size, (400, 300))

    def test_compact_sidebar_reserves_each_selected_edge(self):
        source = Image.new("RGB", (400, 300), BLACK)
        options = RenderOptions(dither=False, contrast=1)
        samples = {
            "right": ((0, 150), (399, 299)),
            "left": ((399, 150), (0, 299)),
            "top": ((200, 299), (399, 0)),
            "bottom": ((200, 0), (399, 299)),
        }
        for position, (content_pixel, sidebar_pixel) in samples.items():
            result = render_with_sidebar(source, options, SidebarOptions(
                position=position, thickness=34, battery_mv=2940,
                temperature_c=26.4, weather_code=2, weather_text="多云"),
                now=datetime(2026, 9, 14, 12, 0))
            self.assertEqual(result.size, (400, 300))
            self.assertEqual(result.getpixel(content_pixel), BLACK)
            self.assertEqual(result.getpixel(sidebar_pixel), WHITE)
            self.assertLessEqual(set(result.getdata()), {BLACK, WHITE})

    def test_upside_down_rotation_applies_to_complete_sidebar_frame(self):
        source = Image.new("RGB", (400, 300), WHITE)
        ImageDraw.Draw(source).rectangle((20, 30, 90, 80), fill=BLACK)
        sidebar = SidebarOptions(position="right", thickness=34, battery_mv=2940,
                                 temperature_c=26.4, weather_code=2, weather_text="多云")
        upright = render_with_sidebar(source, RenderOptions(dither=False, contrast=1),
                                      sidebar, now=datetime(2026, 9, 14, 12, 0))
        upside_down = render_with_sidebar(
            source, RenderOptions(rotation=180, dither=False, contrast=1), sidebar,
            now=datetime(2026, 9, 14, 12, 0))
        expected = ImageOps.mirror(ImageOps.flip(upright))
        self.assertEqual(upside_down.tobytes(), expected.tobytes())

    def test_sidebar_caps_at_48px_and_fades_into_blank_space(self):
        result = render_with_sidebar(
            Image.new("RGB", (400, 300), BLACK),
            RenderOptions(dither=False, contrast=1),
            SidebarOptions(position="right", thickness=80, battery_mv=2940,
                           temperature_c=26.4, weather_code=0,
                           weather_text="晴", is_day=True),
            now=datetime(2026, 9, 14, 12, 0))
        self.assertEqual(result.getpixel((351, 150)), BLACK)
        self.assertEqual(result.getpixel((353, 10)), WHITE)
        upper = sum(result.getpixel((x, y)) == BLACK
                    for x in range(355, 397) for y in range(242, 260))
        lower = sum(result.getpixel((x, y)) == BLACK
                    for x in range(355, 397) for y in range(280, 296))
        self.assertGreater(upper, lower)
        self.assertGreater(upper, 0)

    def test_clear_weather_uses_distinct_sun_and_moon(self):
        source = Image.new("RGB", (400, 300), WHITE)
        options = RenderOptions(dither=False, contrast=1)
        common = dict(position="right", thickness=48, temperature_c=20,
                      weather_code=0, weather_text="晴")
        day = render_with_sidebar(source, options, SidebarOptions(**common, is_day=True),
                                  now=datetime(2026, 9, 14, 12, 0))
        night = render_with_sidebar(source, options, SidebarOptions(**common, is_day=False),
                                    now=datetime(2026, 9, 14, 12, 0))
        self.assertNotEqual(day.crop((352, 60, 400, 103)).tobytes(),
                            night.crop((352, 60, 400, 103)).tobytes())


class ProtocolTests(unittest.TestCase):
    def test_legacy_flags_and_payload(self):
        data = bytes(range(50))
        packets = image_packets(data)
        self.assertEqual(packets[0][:2], b"\x30\x0f")
        self.assertEqual(packets[1][:2], b"\x30\xff")
        self.assertEqual(b"".join(p[2:] for p in packets), data)
        red = image_packets(data, red=True)
        self.assertEqual(red[0][:2], b"\x30\x00")
        self.assertEqual(red[1][:2], b"\x30\xf0")

    def test_rle_round_trip_and_packet_boundaries(self):
        rng = random.Random(123)
        for data in [b"\0" * 15000, bytes(range(256)) * 3, bytes(rng.randrange(3) for _ in range(5000))]:
            for size in [4, 20, 64, 244]:
                for red in [False, True]:
                    packets = image_packets(data, size, True, red)
                    self.assertTrue(all(len(p) <= size for p in packets))
                    self.assertTrue(packets[0][1] & 2)
                    self.assertTrue(all(not (p[1] & 2) for p in packets[1:]))
                    self.assertEqual(packets[0][1] & 1, int(red))
                    decoded = b"".join(unpack_rle(p[2:]) if p[1] & 4 else p[2:] for p in packets)
                    self.assertEqual(decoded, data)

    def test_notifications(self):
        info = DeviceInfo()
        parser = NotificationParser(info)
        parser.feed(bytes([0, 1, 2, 3, 4, 5, 6, 0x17, 0, 0]))
        parser.feed(b"mtu=244 rle=1")
        parser.feed(b"slots=0 0 -1")
        parser.feed(b"t=123 bat=2980")
        self.assertTrue(info.supported)
        self.assertTrue(info.modern)
        self.assertEqual(info.packet_size, 244)
        self.assertEqual(info.battery_mv, 2980)
        self.assertNotIn("private_sid", parser.feed(b"sid=private_sid"))

    def test_chunked_configuration(self):
        info = DeviceInfo()
        p = NotificationParser(info)
        p.feed(b"chunk=1 len=10")
        p.feed(bytes([1, 2, 3]))
        p.feed(bytes([4, 5, 6, 7, 4, 0, 0]))
        self.assertEqual(info.driver, 4)


class FakeClient:
    is_connected = True
    def __init__(self, fail_at=None, cancel_at=None, backend=None):
        self.packets = []
        self.fail_at, self.cancel_at, self.backend = fail_at, cancel_at, backend
        self.services = self
        self.max_write_without_response_size = 244
    def get_characteristic(self, uuid):
        return self
    async def write_gatt_char(self, uuid, data, response):
        if len(self.packets) == self.fail_at:
            raise OSError("simulated BLE failure")
        self.packets.append(bytes(data))
        if len(self.packets) == self.cancel_at:
            self.backend.cancel = True


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.backend = Backend()
        self.backend.read_only = False  # Test the retained encoder/transport, not read-only UI.
        self.backend.info = DeviceInfo(driver=1, packet_size=244, modern=True)
        self.backend.authorized = True

    def tearDown(self):
        self.backend.client = None
        self.backend.close()

    def run_send(self, **kwargs):
        client = FakeClient(backend=self.backend, **kwargs)
        self.backend.client = client
        self.backend.submit(self.backend.send(b"\xff" * 15000)).result(timeout=10)
        return client.packets

    def decode_plane(self, packets, red):
        out = bytearray()
        for p in packets:
            if p[0] == 0x30 and bool(p[1] & 1) == red:
                out += unpack_rle(p[2:]) if p[1] & 4 else p[2:]
        return bytes(out)

    def test_full_frame_before_refresh(self):
        packets = self.run_send()
        self.assertEqual(packets[0], b"\x01")
        self.assertEqual(packets[-1], b"\x05")
        self.assertTrue(all(p[0] == 0x30 for p in packets[1:-1]))

    def test_failure_never_refreshes_partial_image(self):
        self.assertNotIn(b"\x05", self.run_send(fail_at=2))

    def test_cancel_never_refreshes_partial_image(self):
        self.assertNotIn(b"\x05", self.run_send(cancel_at=2))

    def test_auth_gate(self):
        self.backend.authorized = False
        self.assertEqual(self.run_send(), [])

    def test_read_only_blocks_even_authorized_transport(self):
        self.backend.read_only = True
        self.assertEqual(self.run_send(), [])

    def test_slots_gate(self):
        self.backend.info.slots = 4
        self.assertEqual(self.run_send(), [])

    def test_free_slot_preserves_existing_and_cache_avoids_rewrite(self):
        self.backend.info.slots = 64
        self.backend.info.used_mask = 1
        self.backend.info.slots_received = True
        packets = self.run_send()
        self.assertEqual(packets[0], bytes([0x31, 0, 1]))
        self.assertEqual(packets[-1], b"\x05")
        self.backend.next_send = 0
        self.assertEqual(self.run_send(), [bytes([0x31, 1, 1])])

    def test_full_slots_never_overwrite_existing(self):
        self.backend.info.slots = 4
        self.backend.info.used_mask = 15
        self.backend.info.slots_received = True
        self.assertEqual(self.run_send(), [])

    def test_wrong_driver_gate(self):
        self.backend.info.driver = 0x99
        self.assertEqual(self.run_send(), [])

    def test_bwr_sends_explicit_red_plane_and_clears_without_it(self):
        self.backend.info = DeviceInfo(driver=0x16, packet_size=244, modern=True)
        client = FakeClient(backend=self.backend)
        self.backend.client = client
        self.backend.submit(self.backend.send(b"\xff" * 15000, red=b"\x00" * 15000)).result(timeout=10)
        bw = self.decode_plane(client.packets, red=False)
        red = self.decode_plane(client.packets, red=True)
        self.assertEqual(bw, b"\xff" * 15000)
        self.assertEqual(red, b"\x00" * 15000)
        # Without an explicit red plane the active-low red plane is all ones,
        # which clears previous red pixels.
        client2 = FakeClient(backend=self.backend)
        self.backend.client = client2
        self.backend.next_send = 0
        self.backend.session_slots = {}
        self.backend.submit(self.backend.send(b"\xff" * 15000)).result(timeout=10)
        self.assertEqual(self.decode_plane(client2.packets, red=True), b"\xff" * 15000)

    def test_implicit_and_explicit_clear_red_share_slot_cache(self):
        self.backend.info = DeviceInfo(driver=0x16, packet_size=244, modern=True,
                                       slots=64, used_mask=0, slots_received=True)
        first = FakeClient(backend=self.backend)
        self.backend.client = first
        self.backend.submit(self.backend.send(b"\xff" * 15000)).result(timeout=10)
        self.backend.next_send = 0
        second = FakeClient(backend=self.backend)
        self.backend.client = second
        self.backend.submit(self.backend.send(b"\xff" * 15000,
                            red=b"\xff" * 15000)).result(timeout=10)
        self.assertEqual(second.packets, [bytes([0x31, 1, 0])])


if __name__ == "__main__":
    unittest.main()
