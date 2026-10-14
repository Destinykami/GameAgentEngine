// Ground 地图布局 (60 列 x 34 行 tile, 每 tile 16px = 960x544, 对齐 960x540 画布)。
// 改用 Kenney "Tiny Town" (CC0) 真实 tile: 草地/石板路/沙土路。确定性生成 (无随机),
// 保证可回放一致。地点锚点 (渲染坐标, 与 locationAnchors.ts 一致):
//   稻妻主城 (440,330)  治疗堂 (640,330)  锻造坊 (820,330)
//   眼狩署 (440,170)   神樱庭 (200,100)  城外官道 (850,470)
// 注: Tiny Town 无水面 tile, 原河流区改为草地 + 水井/栅栏道具。
import { TT } from "./townTiles";

export const MAP_COLS = 60;
export const MAP_ROWS = 34;
export const TILE_PX = 16;

type Grid = number[][];   // tile 下标 (见 townTiles.TT)

function blank(): Grid {
  return Array.from({ length: MAP_ROWS }, () => Array<number>(MAP_COLS).fill(TT.grass));
}
function rect(g: Grid, x0: number, y0: number, x1: number, y1: number, t: number): void {
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    if (x >= 0 && x < MAP_COLS && y >= 0 && y < MAP_ROWS) g[y][x] = t;
  }
}
// 直线 (Bresenham), 用于斜向道路
function line(g: Grid, x0: number, y0: number, x1: number, y1: number, t: number, w = 2): void {
  let x = x0, y = y0;
  const dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  let err = dx - dy;
  for (let i = 0; i < 200; i++) {
    rect(g, x - Math.floor((w - 1) / 2), y, x + Math.floor(w / 2), y + 1, t);
    if (x === x1 && y === y1) break;
    const e2 = 2 * err;
    if (e2 > -dy) { err -= dy; x += sx; }
    if (e2 < dx) { err += dx; y += sy; }
  }
}
// 像素坐标 → tile 坐标
const px = (v: number) => Math.floor(v / TILE_PX);

export function buildGroundGrid(): Grid {
  const g = blank();   // 基础 = 草地 (TT.grass=1)
  // 神樱庭樱区 (200,100 → tile 12,6): 草地 (樱花树用前景 sprite 表现)
  rect(g, 7, 2, 17, 10, TT.grass);
  // 眼狩署前石板 (440,170 → tile 27,10): 石板广场
  rect(g, 23, 8, 31, 13, TT.road);
  // 稻妻主城石板广场 (440,330 → tile 27,20)
  rect(g, 21, 16, 33, 24, TT.road);
  // 眼狩署 → 主城 纵向道路 (沙土)
  rect(g, 26, 13, 28, 16, TT.sand);
  // 主城 → 治疗堂 → 锻造坊 横向道路 (沙土)
  rect(g, 28, 19, 52, 21, TT.sand);
  // 神樱庭 → 主城 斜向道路
  line(g, px(240), px(110), px(400), px(150), TT.sand, 2);
  // 锻造坊 → 城外官道 斜向道路 (820,330 → 850,470)
  line(g, px(820), px(345), px(850), px(465), TT.sand, 2);
  // 城外官道石板 (850,470 → tile 53,29)
  rect(g, 50, 28, 56, 32, TT.road);
  // 确定性花/植物点缀: 稀疏地把草地换成带花草地 (2) / 带植物草地 (3), 避开道路/广场
  for (let y = 0; y < MAP_ROWS; y++) {
    for (let x = 0; x < MAP_COLS; x++) {
      if (g[y][x] !== TT.grass) continue;
      const h = (x * 73 + y * 151) % 23;
      if (h === 0) g[y][x] = TT.grassFlower;
      else if (h === 1) g[y][x] = TT.grassPlant;
      else if (h === 2) g[y][x] = TT.grassDark;
    }
  }
  return g;
}
