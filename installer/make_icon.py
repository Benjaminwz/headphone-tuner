"""畫耳機調音台的圖示（暖橘圓角方塊＋白色耳機＋三條等化器）：輸出 tuner.ico（程式、捷徑用）和 tuner.png（安裝精靈用）。
只需要 numpy。用法：python installer/make_icon.py"""
import os
import struct
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOP, BOTTOM = np.array([0xF2, 0x8C, 0x4C]), np.array([0xCF, 0x5A, 0x1E])  # 跟調音台介面一樣的陶土橘（上亮下深）


def render(size, ss=8, full=False):
    """在 256×256 的座標裡畫，超取樣 ss 倍再平均 → 邊緣平滑。回傳 size×size×4 的 RGBA。
    full＝底色鋪滿整個正方形（iPhone 主畫面圖示：透明的角會變黑，系統會自己裁圓角）"""
    n = size * ss
    y, x = (np.mgrid[0:n, 0:n] + 0.5) * (256 / n)

    def rrect(x0, y0, x1, y1, r):
        dx = np.maximum(np.maximum(x0 + r - x, x - (x1 - r)), 0)
        dy = np.maximum(np.maximum(y0 + r - y, y - (y1 - r)), 0)
        return (dx ** 2 + dy ** 2 <= r * r) & (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)

    bg = np.ones_like(x, dtype=bool) if full else rrect(8, 8, 248, 248, 56)
    d = np.hypot(x - 128, y - 142)
    band = (np.abs(d - 80) <= 10) & (y <= 142)  # 頭帶：上半圓
    cups = rrect(34, 128, 76, 206, 16) | rrect(180, 128, 222, 206, 16)  # 左右耳罩
    bars = rrect(99, 150, 115, 200, 7) | rrect(120, 118, 136, 200, 7) | rrect(141, 164, 157, 200, 7)  # 等化器
    fg = (band | cups | bars) & bg
    t = (y / 256)[..., None]
    rgb = (TOP * (1 - t) + BOTTOM * t) * (~fg)[..., None] + 255 * fg[..., None]
    rgba = np.concatenate([rgb * bg[..., None], bg[..., None] * 255.0], axis=2)
    rgba = rgba.reshape(size, ss, size, ss, 4).mean(axis=(1, 3))
    a = rgba[..., 3:4]
    rgba[..., :3] = np.where(a > 0, rgba[..., :3] * 255 / np.maximum(a, 1e-6), 0)  # 還原成未預乘的顏色
    return np.clip(np.round(rgba), 0, 255).astype(np.uint8)


def png_bytes(img):
    h, w = img.shape[:2]
    raw = b"".join(b"\0" + img[r].tobytes() for r in range(h))
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def write_ico(path, sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256)):
    pngs = [png_bytes(render(s)) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for s, data in zip(sizes, pngs):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as f:
        f.write(out + b"".join(pngs))


if __name__ == "__main__":
    write_ico(os.path.join(ROOT, "tuner.ico"))
    with open(os.path.join(HERE, "tuner.png"), "wb") as f:
        f.write(png_bytes(render(256)))
    print("ok")
