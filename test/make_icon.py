# -*- mode: python ; coding: utf-8 -*-
"""
生成纯色圆角图标：白字两行「Git / 备份」

产物（输出到本文件同目录）:
    GitBundleBackuper.ico   多尺寸(256/128/64/48/32/16)，可直接用于 PyInstaller icon=
    icon_preview.png        512x512 预览图

用法:  python test/make_icon.py
底部「可自定义参数」可直接改需求（背景色/文字/圆角/尺寸）。
"""
import os

from PIL import Image, ImageDraw, ImageFont

# ---------------- 可自定义参数 ----------------
BG_COLOR = (52, 149, 255)   # 纯色背景 #3495FF
FG_COLOR = (255, 255, 255)  # 文字颜色
LINES = [                   # 文字两行: (文本, 字号相对画布比例)
    ("Git",  0.30),
    ("备份", 0.21),
]
LINE_GAP = 0.07             # 两行文字间距（相对画布边长）
CORNER = 0.22               # 圆角半径（相对画布边长）
BASE_S = 1024               # 高分辨率底图边长，越大文字边缘越平滑
ICO_SIZES = (256, 128, 64, 48, 32, 16)
PREVIEW_S = 512

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ICO = os.path.join(_HERE, "GitBundleBackuper.ico")
OUT_PNG = os.path.join(_HERE, "icon_preview.png")

# ---------------- 字体 ----------------（Windows 优先，可自行增补路径）
_WINDIR = os.environ.get("WINDIR", "C:/Windows")
_FONT_DIR = os.path.join(_WINDIR, "Fonts")
_FONT_CANDIDATES = ("msyhbd.ttc", "msyh.ttc", "Dengb.ttf", "simhei.ttf", "arialbd.ttf")


def _load_font(px: int) -> ImageFont.FreeTypeFont:
    for name in _FONT_CANDIDATES:
        path = os.path.join(_FONT_DIR, name)
        if os.path.exists(path):
            return ImageFont.truetype(path, size=px)
    raise FileNotFoundError("未找到可用字体（微软雅黑/黑体/Arial），请检查系统字体或补充字体路径。")


def _draw_rounded(base: Image.Image, bg, fg, font_sizes) -> Image.Image:
    """在 base 画布上绘制圆角底色 + 垂直居中两行文字。"""
    size = base.size[0]
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # 1) 圆角底色（圆角外透明）
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * CORNER), fill=255)
    layer = Image.new("RGBA", (size, size), bg)
    layer.putalpha(mask)

    draw = ImageDraw.Draw(layer)

    # 2) 两行文字垂直居中排版
    fonts = [_load_font(px) for px in font_sizes]
    heights, widths, boxes = [], [], []
    for text, font in zip((ln[0] for ln in LINES), fonts):
        box = font.getbbox(text)
        widths.append(box[2] - box[0])
        heights.append(box[3] - box[1])
        boxes.append(box)

    gap = int(size * LINE_GAP)
    total_h = sum(heights) + gap
    y_cursor = (size - total_h) / 2

    for (text, _), font, w, h, box in zip(LINES, fonts, widths, heights, boxes):
        x = (size - w) / 2 - box[0]
        y = y_cursor - box[1]
        draw.text((x, y), text, font=font, fill=fg)
        y_cursor += h + gap

    return Image.alpha_composite(canvas, layer)


def build_icon() -> Image.Image:
    """返回 ico 主图（256x256，圆角图标）。"""
    base = Image.new("RGBA", (BASE_S, BASE_S), (0, 0, 0, 0))
    font_sizes = [int(BASE_S * ratio) for _, ratio in LINES]
    img = _draw_rounded(base, BG_COLOR, FG_COLOR, font_sizes)
    return img.resize((ICO_SIZES[0], ICO_SIZES[0]), Image.LANCZOS)


def main():
    icon = build_icon()
    # 多尺寸 ICO（Pillow 会以 256 主图为基准生成其余小尺寸帧）
    icon.save(OUT_ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print("[OK] 已生成:", OUT_ICO)
    for s in ICO_SIZES:
        print("      %-5d x %-5d" % (s, s))

    # 预览 PNG
    prev = Image.new("RGBA", (BASE_S, BASE_S), (0, 0, 0, 0))
    font_sizes = [int(BASE_S * ratio) for _, ratio in LINES]
    full = _draw_rounded(prev, BG_COLOR, FG_COLOR, font_sizes)
    full.resize((PREVIEW_S, PREVIEW_S), Image.LANCZOS).save(OUT_PNG)
    print("[OK] 已生成:", OUT_PNG)


if __name__ == "__main__":
    main()
