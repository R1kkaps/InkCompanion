from PIL import Image, ImageDraw
from imaging import font, pack_bw
from pathlib import Path


def make():
    image = Image.new('1', (400, 300), 1)
    d = ImageDraw.Draw(image)
    d.rectangle((0, 0, 399, 299), outline=0, width=2)
    for x, y, text in [(9, 6, 'TL 左上'), (302, 6, 'TR 右上'), (9, 268, 'BL 左下'), (302, 268, 'BR 右下')]:
        d.text((x, y), text, font=font(15), fill=0)
    d.text((103, 52), '墨伴 · 测试画面', font=font(25), fill=0)
    d.text((121, 95), '400 × 300 / TOP ↑', font=font(16), fill=0)
    d.rectangle((35, 141, 175, 218), fill=0)
    d.text((58, 165), 'BLACK 黑', font=font(20), fill=1)
    d.rectangle((224, 141, 364, 218), outline=0, width=2)
    d.text((241, 165), 'WHITE 白', font=font(20), fill=0)
    d.text((85, 234), 'v1.10-om6626 · BLE 传图测试', font=font(15), fill=0)
    return image


if __name__ == '__main__':
    image = make()
    image.save('research/screen-test.png')
    Path('research/screen-test.bin').write_bytes(pack_bw(image))
