#!/usr/bin/env python3
"""把原神官方头像 (本地 portraits-src/) 程序化像素化成 2D 像素风头像。

不是生成模型: 裁透明边界 → 方形化 → LANCZOS 降采样 → 32 色量化 → 1px 深色描边。
输出到 public/assets/portraits/ (已被 .gitignore 排除, 仅个人学习本地使用)。

用法:
  python3 tools/pixelate_portraits.py [--size 64] [--colors 32]
"""
import argparse
from pathlib import Path
from PIL import Image, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "public" / "assets" / "portraits-src"
OUT = ROOT / "public" / "assets" / "portraits"
FILES = ["PlayerBoy", "Kokomi", "Itto", "Sayu", "Wanderer", "Shougun"]


def square(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    side = max(w, h) + 8
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.alpha_composite(im, ((side - w) // 2, (side - h) // 2))
    return out


def pixelate(im: Image.Image, size: int, colors: int, alpha_thr: int = 110) -> Image.Image:
    im = square(im).resize((size, size), Image.LANCZOS)
    alpha = im.getchannel("A").point(lambda v: 255 if v > alpha_thr else 0)
    rgb = im.convert("RGB").quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.NONE).convert("RGB")
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    # 1px 深色描边 (像素风轮廓)
    mask = alpha.point(lambda v: 255 if v > 0 else 0)
    grown = mask.filter(ImageFilter.MaxFilter(3))
    ring = ImageChops.subtract(grown, mask).point(lambda v: 255 if v > 0 else 0)
    dark = Image.new("RGBA", (size, size), (20, 20, 28, 255))
    dark.putalpha(ring)
    return Image.alpha_composite(dark, out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--colors", type=int, default=32)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    done = 0
    for name in FILES:
        src = SRC / f"{name}.png"
        if not src.exists():
            print(f"skip {name}: {src} 不存在")
            continue
        dst = OUT / f"{name}.png"
        pixelate(Image.open(src), args.size, args.colors).save(dst)
        print(f"✓ {src.name} → {dst.name} ({args.size}x{args.size}, {args.colors} colors)")
        done += 1
    print(f"\n{done}/{len(FILES)} 张像素头像已输出到 {OUT}")
    print("提醒: 这些是基于 © HoYoverse 素材的本地衍生图, 仅个人学习用, 不要分发。")


if __name__ == "__main__":
    main()
