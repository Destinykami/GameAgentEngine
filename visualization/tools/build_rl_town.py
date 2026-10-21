#!/usr/bin/env python3
"""生成 Kenney Roguelike/RPG (CC0) 的 60x34 村庄底图 (960x544)。

布局保留现有 6 个地点锚点:
  神樱庭(200,100) / 眼狩署(440,170) / 稻妻主城(440,330)
  治疗堂(640,330) / 锻造坊(820,330) / 城外官道(850,470)
中间是石板广场 + 花圃, 不挖湖 (避免角色直线移动穿水)。
输出 public/assets/rl-town.png; 建筑/树木另作为 Sprite 参与 y-sort。
"""
from PIL import Image, ImageDraw
import random

SHEET = Image.open("public/assets/kenney-roguelike.png").convert("RGBA")
T, M, COLS = 16, 1, 57
W, H = 60, 34

GRASS = [63]
DIRT = [579]
STONE = [919]
FLOWERS = [514, 515, 516, 517, 518, 685, 686, 687, 688, 689, 801, 802, 803]
RNG = random.Random(11)


def tile(gid: int) -> Image.Image:
    idx = gid - 1
    sx = (idx % COLS) * (T + M)
    sy = (idx // COLS) * (T + M)
    return SHEET.crop((sx, sy, sx + T, sy + T))


def fill_mask(base: Image.Image, mask: Image.Image, choices: list[int]) -> None:
    for y in range(0, H * T, T):
        for x in range(0, W * T, T):
            if mask.getpixel((x + T // 2, y + T // 2)):
                base.alpha_composite(tile(RNG.choice(choices)), (x, y))


def main() -> None:
    base = Image.new("RGBA", (W * T, H * T), (0, 0, 0, 0))
    fill_mask(base, Image.new("L", base.size, 255), GRASS)

    # 土路: 连接 6 个锚点 + 中央广场
    path = Image.new("L", base.size, 0)
    d = ImageDraw.Draw(path)
    d.line([(200, 130), (300, 300), (440, 330), (640, 330), (700, 360), (850, 480)],
           fill=255, width=30, joint="curve")
    d.line([(440, 330), (440, 170)], fill=255, width=30)
    # 帐篷营地 / 官道口的土坪
    d.ellipse((250, 85, 410, 205), fill=255)
    d.ellipse((805, 430, 930, 530), fill=255)
    d.rounded_rectangle((292, 222, 578, 418), radius=34, fill=255)
    d.rounded_rectangle((388, 132, 500, 218), radius=18, fill=255)
    d.rounded_rectangle((596, 288, 690, 368), radius=16, fill=255)
    d.rounded_rectangle((650, 318, 750, 398), radius=16, fill=255)
    d.ellipse((145, 85, 265, 195), fill=255)
    fill_mask(base, path, DIRT)

    # 石板广场 / 建筑前庭
    stone = Image.new("L", base.size, 0)
    d2 = ImageDraw.Draw(stone)
    d2.rounded_rectangle((300, 230, 570, 410), radius=30, fill=255)
    d2.rounded_rectangle((394, 138, 494, 212), radius=14, fill=255)
    d2.rounded_rectangle((604, 294, 682, 362), radius=12, fill=255)
    d2.rounded_rectangle((658, 324, 742, 392), radius=12, fill=255)
    fill_mask(base, stone, STONE)

    # 广场中心花坛 (土 + 花)
    med = Image.new("L", base.size, 0)
    d3 = ImageDraw.Draw(med)
    d3.ellipse((400, 270, 480, 350), fill=255)
    fill_mask(base, med, DIRT)
    med2 = Image.new("L", base.size, 0)
    d4 = ImageDraw.Draw(med2)
    d4.ellipse((414, 284, 466, 336), fill=255)
    fill_mask(base, med2, FLOWERS)

    # 花圃/路边花丛
    spots = [(296, 208), (560, 220), (580, 400), (360, 416), (250, 176),
             (300, 120), (160, 176), (690, 372), (740, 250), (900, 400),
             (80, 340), (120, 420), (440, 470), (520, 470), (600, 240),
             (680, 160), (880, 300), (900, 520), (340, 300), (390, 380)]
    for sx, sy in spots:
        base.alpha_composite(tile(RNG.choice(FLOWERS)), (sx, sy))

    # 神樱庭粉色落花
    px = base.load()
    for _ in range(220):
        x = RNG.randint(150, 275)
        y = RNG.randint(95, 215)
        if base.getpixel((x, y))[3] > 0:
            px[x, y] = (238, 150, 180, 255) if RNG.random() < 0.7 else (255, 230, 240, 255)

    # 草叶/小野花: 只画在绿色草面上, 打散大片纯色
    px = base.load()
    for _ in range(1800):
        x = RNG.randint(0, W * T - 1)
        y = RNG.randint(0, H * T - 1)
        r, g, b, a = base.getpixel((x, y))
        if a == 0 or g < r + 18 or g < b + 18:
            continue
        if RNG.random() < 0.7:
            px[x, y] = (86, 145, 44, 255)
        else:
            px[x, y] = (247, 240, 170, 255)

    base.convert("RGB").save("public/assets/rl-town.png")
    print(f"saved public/assets/rl-town.png {base.size}")


if __name__ == "__main__":
    main()
