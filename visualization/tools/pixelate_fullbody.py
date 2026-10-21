#!/usr/bin/env python3
"""把原神官方全身立绘 (本地 fullbody-src/) 像素化成 40x56 的 10 帧 Sprite 表。

帧顺序 (每帧 40x56, 横向排列):
  0 idleA  1 idleB  2 walk1  3 walk2
  4 hammerA 5 hammerB 6 healA 7 healB 8 readA 9 readB

不是生成模型: 裁透明边界 → 等比缩放到 48x64 → 32 色量化 → 1px 深色描边。
待机/走路用 1px 位移; 活动帧在右上角加像素小图标 (锤/治疗十字/书)。
输出到 public/assets/fullbody/ (已被 .gitignore 排除, 仅个人学习本地使用)。

用法:
  python3 tools/pixelate_fullbody.py
"""
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "public" / "assets" / "fullbody-src"
OUT = ROOT / "public" / "assets" / "fullbody"
W, H = 40, 56
NAMES = ["PlayerBoy", "Kokomi", "Itto", "Sayu", "Wanderer", "Shougun"]
FRAME_NAMES = ["idleA", "idleB", "walk1", "walk2",
               "hammerA", "hammerB", "healA", "healB", "readA", "readB"]


def load_source(name: str) -> Image.Image:
    for ext in ("png", "webp"):
        p = SRC / f"{name}.{ext}"
        if p.exists():
            return Image.open(p)
    raise FileNotFoundError(f"{SRC}/{name}.png|.webp")


def base_frame(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    # 只取中间 72% 宽度: 去掉两侧大面积立绘特效 (将军的袖/心海的水/一斗背后的鬼),
    # 让小尺寸 Sprite 的主体更清楚; 代价是极端外伸的武器/尾巴可能被裁掉。
    crop_w = max(1, int(w * 0.72))
    cx = (w - crop_w) // 2
    im = im.crop((cx, 0, cx + crop_w, h))
    w, h = im.size
    scale = min((W - 4) / w, (H - 4) / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((W - nw) // 2, H - nh))
    alpha = canvas.getchannel("A").point(lambda v: 255 if v > 100 else 0)
    rgb = canvas.convert("RGB").quantize(colors=32, method=Image.MEDIANCUT, dither=Image.NONE).convert("RGB")
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    mask = alpha.point(lambda v: 255 if v > 0 else 0)
    grown = mask.filter(ImageFilter.MaxFilter(3))
    ring = ImageChops.subtract(grown, mask).point(lambda v: 255 if v > 0 else 0)
    dark = Image.new("RGBA", (W, H), (20, 20, 28, 255))
    dark.putalpha(ring)
    return Image.alpha_composite(dark, out)


def shifted(im: Image.Image, dx: int, dy: int) -> Image.Image:
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(im, (dx, dy))
    return out


def activity_icon(im: Image.Image, kind: str, phase: int) -> Image.Image:
    out = im.copy()
    d = ImageDraw.Draw(out)
    x, y = W - 14, 2 + phase  # 右上角, 帧间 1px 起伏
    dark = (20, 20, 28, 255)
    if kind == "hammer":
        # 柄 + 锤头
        d.rectangle((x + 3, y + 4, x + 4, y + 11), fill=(120, 78, 45, 255))
        d.rectangle((x + 1, y + 2, x + 8, y + 5), fill=dark)
        d.rectangle((x + 2, y + 3, x + 7, y + 4), fill=(190, 190, 198, 255))
        d.point((x + 3, y + 2), fill=(235, 235, 240, 255))
    elif kind == "heal":
        # 绿色十字 + 1px 高光
        d.rectangle((x + 3, y + 1, x + 5, y + 10), fill=dark)
        d.rectangle((x + 0, y + 4, x + 9, y + 6), fill=dark)
        d.rectangle((x + 4, y + 2, x + 4, y + 9), fill=(120, 235, 150, 255))
        d.rectangle((x + 1, y + 5, x + 8, y + 5), fill=(120, 235, 150, 255))
        d.point((x + 3, y + 3), fill=(220, 255, 220, 255))
    elif kind == "read":
        # 打开的书
        d.rectangle((x + 0, y + 3, x + 9, y + 10), fill=dark)
        d.rectangle((x + 1, y + 4, x + 8, y + 9), fill=(220, 210, 170, 255))
        d.line((x + 4, y + 4, x + 4, y + 9), fill=(120, 100, 70, 255))
        d.line((x + 1, y + 6, x + 8, y + 6), fill=(150, 125, 85, 255))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    done = 0
    for name in NAMES:
        try:
            base = base_frame(load_source(name))
        except FileNotFoundError as e:
            print(f"skip {name}: {e}")
            continue
        frames = [
            base,
            shifted(base, 0, -1),
            shifted(base, -1, 0),
            shifted(base, 1, 0),
            activity_icon(base, "hammer", 0),
            activity_icon(base, "hammer", 1),
            activity_icon(base, "heal", 0),
            activity_icon(base, "heal", 1),
            activity_icon(base, "read", 0),
            activity_icon(base, "read", 1),
        ]
        sheet = Image.new("RGBA", (W * len(frames), H), (0, 0, 0, 0))
        for i, fr in enumerate(frames):
            sheet.alpha_composite(fr, (i * W, 0))
        sheet.save(OUT / f"{name}.png")
        print(f"✓ {name}.png  {W*len(frames)}x{H}  (" + "/".join(FRAME_NAMES) + ")")
        done += 1
    print(f"\n{done}/{len(NAMES)} 张 Sprite 表已输出到 {OUT}")
    print("提醒: 基于 © HoYoverse 素材的本地衍生图, 仅个人学习用, 不要分发。")


if __name__ == "__main__":
    main()
