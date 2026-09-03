# -*- mode: python ; coding: utf-8 -*-
"""
生成纯色圆角图标：白字两行「Git / 备份」

产物（同时输出到本文件同目录 和 项目根目录）:
    test/GitBundleBackuper.ico   多尺寸(256/128/64/48/32/16)，test 目录副本
    test/icon_preview.png        512x512 预览图
    ../icon.png                  1024x1024 高清 PNG（项目根目录，运行时动态图标用）
    ../GitBundleBackuper.ico     同步更新根目录 ICO（PyInstaller 打包用）

用法:  python test/make_icon.py
底部「可自定义参数」可直接改需求（背景色/文字/圆角/尺寸）。
"""
import os
import shutil

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
ICO_SIZES = (256,)
PREVIEW_S = 512

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)   # 项目根目录

# 输出路径
OUT_ICO_TEST = os.path.join(_HERE, "GitBundleBackuper.ico")   # test/ 目录
OUT_PNG_TEST = os.path.join(_HERE, "icon_preview.png")        # test/ 目录 512px 预览
OUT_PNG_ROOT = os.path.join(_ROOT, "icon.png")                # 根目录 1024px 高清 PNG（运行时用）
OUT_ICO_ROOT = os.path.join(_ROOT, "GitBundleBackuper.ico")   # 根目录 ICO（打包用）

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


def _draw_rounded(size: int) -> Image.Image:
    """在指定边长的画布上绘制圆角底色 + 垂直居中两行文字，返回 RGBA 图像。"""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # 1) 圆角遮罩
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * CORNER), fill=255)
    layer = Image.new("RGBA", (size, size), BG_COLOR)
    layer.putalpha(mask)

    draw = ImageDraw.Draw(layer)

    # 2) 字号按画布大小等比缩放
    font_sizes = [int(size * ratio) for _, ratio in LINES]
    fonts = [_load_font(px) for px in font_sizes]

    heights, widths, boxes = [], [], []
    for (text, _), font in zip(LINES, fonts):
        box = font.getbbox(text)
        widths.append(box[2] - box[0])
        heights.append(box[3] - box[1])
        boxes.append(box)

    # 3) 垂直居中排版
    gap = int(size * LINE_GAP)
    total_h = sum(heights) + gap
    y_cursor = (size - total_h) / 2

    for (text, _), font, w, h, box in zip(LINES, fonts, widths, heights, boxes):
        x = (size - w) / 2 - box[0]
        y = y_cursor - box[1]
        draw.text((x, y), text, font=font, fill=FG_COLOR)
        y_cursor += h + gap

    return Image.alpha_composite(canvas, layer)


def main():
    # ---- 生成 1024px 高清主图
    print("正在渲染 %dx%d 底图..." % (BASE_S, BASE_S))
    full_img = _draw_rounded(BASE_S)

    # ---- 根目录高清 PNG（1024px，运行时 wm_iconphoto 用）
    full_img.save(OUT_PNG_ROOT, format="PNG")
    print("[OK] 根目录高清 PNG : %s" % OUT_PNG_ROOT)

    # ---- 多尺寸 ICO（每帧独立从高清底图缩放，256px 为第一帧保证 Windows 优先取最清晰帧）
    ico_frames = [full_img.resize((s, s), Image.LANCZOS).convert("RGBA")
                  for s in ICO_SIZES]   # ICO_SIZES = (256, 128, 64, 48, 32, 16)
    # Pillow ICO：第一个参数是第一帧（256px），append_images 是后续帧
    ico_frames[0].save(
        OUT_ICO_TEST,
        format="ICO",
        append_images=ico_frames[1:],
        sizes=[(s, s) for s in ICO_SIZES],
    )
    print("[OK] test/ ICO       : %s" % OUT_ICO_TEST)
    for s in ICO_SIZES:
        print("      %d x %d" % (s, s))

    # 同步到根目录（覆盖旧文件）
    shutil.copy2(OUT_ICO_TEST, OUT_ICO_ROOT)
    print("[OK] 根目录 ICO 已更新: %s" % OUT_ICO_ROOT)

    # ---- test/ 预览 PNG（512px）
    full_img.resize((PREVIEW_S, PREVIEW_S), Image.LANCZOS).save(OUT_PNG_TEST, format="PNG")
    print("[OK] test/ 预览 PNG  : %s  (%dx%d)" % (OUT_PNG_TEST, PREVIEW_S, PREVIEW_S))


if __name__ == "__main__":
    main()
