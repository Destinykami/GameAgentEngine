#!/usr/bin/env python3
"""用 Ninja Adventure 日式素材生成 60x34 村庄底图 (960x544)。

- 草地: tileset_floor.png (11,12)
- 土路: tileset_floor.png (12,15)
- 石板: tileset_interior_floor.png (12,7)
- 木台/神社前庭: tileset_interior_floor.png (12,1)
布局沿用 6 个地点锚点: 神樱庭/眼狩署/稻妻主城/治疗堂/锻造坊/城外官道。
输出 public/assets/ninja-town.png; 建筑/树/门/栅栏另作为 Sprite 参与 y-sort。
"""
from PIL import Image, ImageDraw
import random

FLOOR = Image.open("public/assets/ninja/tileset_floor.png").convert("RGBA")
INT = Image.open("public/assets/ninja/tileset_interior_floor.png").convert("RGBA")
T = 16
W, H = 60, 34
RNG = random.Random(21)


def ftile(x: int, y: int) -> Image.Image:
    return FLOOR.crop((x * T, y * T, x * T + T, y * T + T))


def itile(x: int, y: int) -> Image.Image:
    return INT.crop((x * T, y * T, x * T + T, y * T + T))


GRASS = ftile(11, 12)
DIRT = ftile(12, 15)
STONE = itile(12, 7)
WOOD = itile(12, 1)
TUFTS = [ftile(12, 12), ftile(13, 12), ftile(14, 12)]


def fill(base: Image.Image, mask: Image.Image, tile: Image.Image) -> None:
    for y in range(0, H * T, T):
        for x in range(0, W * T, T):
            if mask.getpixel((x + T // 2, y + T // 2)):
                base.alpha_composite(tile, (x, y))


def main() -> None:
    base = Image.new("RGBA", (W * T, H * T), (0, 0, 0, 0))
    fill(base, Image.new("L", base.size, 255), GRASS)

    # 土路 / 营地 / 官道口
    path = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(path)
    d.line([(200, 160), (300, 300), (440, 330), (640, 330), (700, 360), (850, 480)],
           fill=255, width=30, joint="curve")
    d.line([(440, 330), (440, 190)], fill=255, width=30)
    d.ellipse((250, 85, 410, 205), fill=255)
    d.ellipse((805, 430, 930, 530), fill=255)
    d.rounded_rectangle((292, 222, 578, 418), radius=34, fill=255)
    d.rounded_rectangle((388, 152, 500, 238), radius=18, fill=255)
    d.rounded_rectangle((596, 288, 690, 368), radius=16, fill=255)
    d.rounded_rectangle((650, 318, 750, 398), radius=16, fill=255)
    fill(base, path, DIRT)

    # 石板广场 / 建筑前庭
    stone = Image.new("L", base.size, 0)
    d2 = ImageDraw.Draw(stone)
    d2.rounded_rectangle((300, 230, 570, 410), radius=30, fill=255)
    d2.rounded_rectangle((394, 158, 494, 232), radius=14, fill=255)
    d2.rounded_rectangle((604, 294, 682, 362), radius=12, fill=255)
    d2.rounded_rectangle((658, 324, 742, 392), radius=12, fill=255)
    fill(base, stone, STONE)

    # 神社前庭: 石板
    deck = Image.new("L", base.size, 0)
    d3 = ImageDraw.Draw(deck)
    d3.ellipse((145, 115, 265, 225), fill=255)
    fill(base, deck, STONE)

    # 草叶斑块
    for _ in range(700):
        x = RNG.randrange(0, W) * T
        y = RNG.randrange(0, H) * T
        if base.getpixel((x + 8, y + 8))[:3] == GRASS.getpixel((8, 8))[:3]:
            base.alpha_composite(RNG.choice(TUFTS), (x, y))

    # 神樱庭落樱
    px = base.load()
    for _ in range(180):
        x = RNG.randint(145, 270)
        y = RNG.randint(120, 235)
        r, g, b, a = base.getpixel((x, y))
        if a:
            px[x, y] = (238, 150, 180, 255) if RNG.random() < 0.7 else (255, 230, 240, 255)

    base.convert("RGB").save("public/assets/ninja-town.png")
    print("saved public/assets/ninja-town.png", base.size)


if __name__ == "__main__":
    main()
