// ArtFactory: 把 tiles/buildings/characters 的像素网格烘焙成 Phaser 纹理。
// 产出:
//   "ground"            整张地面 (960x544)
//   "bldg_<name>"       建筑
//   "prop_<name>"       道具 (铁砧/病床/书桌/鸟居/樱树/灯笼)
//   "char_<name>_<f>"   角色帧 (idleA/idleB/walk1/walk2)
// 角色帧里的 "§" 占位替换为角色身体色。全部原创像素, 无第三方素材。
import Phaser from "phaser";
import { PALETTE } from "./palette";
import { TILE_VARIANTS, type TileKind } from "./tiles";
import { buildGroundGrid, MAP_COLS, MAP_ROWS, TILE_PX } from "./groundMap";
import { BUILDINGS, PROPS } from "./buildings";
import { framesFor, bodyColorOf, CHAR_BODY_COLOR, BODY_PLACEHOLDER } from "./characters";
import { ACTIVITY_FRAMES } from "./activityFrames";

function colorOf(ch: string, bodyColor?: string): string {
  if (ch === BODY_PLACEHOLDER && bodyColor) return bodyColor;
  return PALETTE[ch] ?? null;   // 透明/未知 → null (不画)
}

// 活动帧用 '#' 表身体色, 渲染前替换成占位 § (再由 drawGrid 换成角色色)。
const sub = (grid: string[]) => grid.map((row) => row.split("#").join(BODY_PLACEHOLDER));

// 把像素网格画到 ctx 的 (ox,oy), 每格 1px。bodyColor 用于角色身体色替换。
function drawGrid(ctx: CanvasRenderingContext2D, grid: string[], ox: number, oy: number, bodyColor?: string): void {
  for (let r = 0; r < grid.length; r++) {
    const row = grid[r];
    for (let c = 0; c < row.length; c++) {
      const col = colorOf(row[c], bodyColor);
      if (!col) continue;
      ctx.fillStyle = col;
      ctx.fillRect(ox + c, oy + r, 1, 1);
    }
  }
}

function makeTexture(scene: Phaser.Scene, key: string, w: number, h: number, paint: (ctx: CanvasRenderingContext2D) => void): void {
  if (scene.textures.exists(key)) scene.textures.remove(key);
  const cv = scene.textures.createCanvas(key, w, h);
  if (!cv) throw new Error(`createCanvas 失败: ${key}`);
  paint(cv.context);
  cv.refresh();
}

export function buildArt(scene: Phaser.Scene): void {
  // 1. 地面
  const grid = buildGroundGrid();
  makeTexture(scene, "ground", MAP_COLS * TILE_PX, MAP_ROWS * TILE_PX, (ctx) => {
    for (let r = 0; r < MAP_ROWS; r++) {
      for (let c = 0; c < MAP_COLS; c++) {
        const kind: TileKind = grid[r][c];
        const [va, vb] = TILE_VARIANTS[kind];
        const g = (c + r) % 2 === 0 ? va : vb;   // 确定性 A/B 抖动
        drawGrid(ctx, g, c * TILE_PX, r * TILE_PX);
      }
    }
  });
  // 2. 建筑
  for (const [name, b] of Object.entries(BUILDINGS)) {
    const w = Math.max(...b.grid.map((r) => r.length));
    const h = b.grid.length;
    makeTexture(scene, `bldg_${name}`, w, h, (ctx) => drawGrid(ctx, b.grid, 0, 0));
  }
  // 3. 道具
  for (const [name, g] of Object.entries(PROPS)) {
    const w = Math.max(...g.map((r) => r.length));
    const h = g.length;
    makeTexture(scene, `prop_${name}`, w, h, (ctx) => drawGrid(ctx, g, 0, 0));
  }
  // 4. 角色帧 + 5. 动画定义 (idle 循环, walk 循环)
  for (const cn of Object.keys(CHAR_BODY_COLOR)) {
    const frames = framesFor(cn);
    const bc = bodyColorOf(cn);
    for (const f of ["idleA", "idleB", "walk1", "walk2"] as const) {
      makeTexture(scene, `char_${cn}_${f}`, 16, 16, (ctx) => drawGrid(ctx, frames[f], 0, 0, bc));
    }
    if (!scene.anims.exists(`idle_${cn}`)) {
      scene.anims.create({ key: `idle_${cn}`, frames: [{ key: `char_${cn}_idleA` }, { key: `char_${cn}_idleB` }], frameRate: 2, repeat: -1 });
    }
    if (!scene.anims.exists(`walk_${cn}`)) {
      scene.anims.create({ key: `walk_${cn}`, frames: [{ key: `char_${cn}_walk1` }, { key: `char_${cn}_walk2` }], frameRate: 8, repeat: -1 });
    }
    // 6. Phase 3 活动帧 + 活动动画 (hammer/heal/read 循环, 驻道具活动)
    for (const [ak, [fa, fb]] of Object.entries(ACTIVITY_FRAMES)) {
      makeTexture(scene, `act_${cn}_${ak}A`, 16, 16, (ctx) => drawGrid(ctx, sub(fa), 0, 0, bc));
      makeTexture(scene, `act_${cn}_${ak}B`, 16, 16, (ctx) => drawGrid(ctx, sub(fb), 0, 0, bc));
      const key = `${ak}_${cn}`;
      if (!scene.anims.exists(key)) {
        const rate = ak === "hammer" ? 6 : ak === "heal" ? 3 : 2;   // 锤击快/治疗中/阅读慢
        scene.anims.create({ key, frames: [{ key: `act_${cn}_${ak}A` }, { key: `act_${cn}_${ak}B` }], frameRate: rate, repeat: -1 });
      }
    }
  }
}
