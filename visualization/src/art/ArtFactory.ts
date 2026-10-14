// ArtFactory: 把地图/建筑/角色像素烘焙成 Phaser 纹理。
// 地图与建筑改用 Kenney "Tiny Town" (CC0) 真实 tile (public/assets/tiny-town-tilemap.png),
// 活动点道具 (铁砧/病床/书桌) 与鸟居保留手绘像素 (辨识度高, Phase 3 活动锚点),
// 樱树用圆灌木 tile 染粉, 灯笼/井/栅栏/蘑菇/松树用真实 tile。
// 产出:
//   "ground"            整张地面 (960x544, 真实 tile)
//   "bldg_<name>"       建筑 (真实 tile 拼)
//   "prop_<name>"       道具 (手绘 or 真实 tile)
//   "char_<name>_<f>"   角色帧 (idleA/idleB/walk1/walk2, 手绘原创)
import Phaser from "phaser";
import { PALETTE } from "./palette";
import { TILE_PX, buildGroundGrid, MAP_COLS, MAP_ROWS } from "./groundMap";
import { BUILDINGS, TILE_PROPS, DRAW_PROPS, CHERRY_TILE } from "./buildings";
import { tileSrc, TOWN_TILE } from "./townTiles";
import { framesFor, bodyColorOf, CHAR_BODY_COLOR, BODY_PLACEHOLDER } from "./characters";
import { ACTIVITY_FRAMES } from "./activityFrames";

function colorOf(ch: string, bodyColor?: string): string {
  if (ch === BODY_PLACEHOLDER && bodyColor) return bodyColor;
  return PALETTE[ch] ?? null;   // 透明/未知 → null (不画)
}
const sub = (grid: string[]) => grid.map((row) => row.split("#").join(BODY_PLACEHOLDER));

// 手绘像素网格画到 ctx (每格 1px)
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

// 从 tilemap 画一个 tile 到 (dx,dy)
function drawTile(ctx: CanvasRenderingContext2D, img: CanvasImageSource, tileIdx: number, dx: number, dy: number, size = TOWN_TILE): void {
  const { sx, sy } = tileSrc(tileIdx);
  ctx.drawImage(img, sx, sy, TOWN_TILE, TOWN_TILE, dx, dy, size, size);
}

// 画一个染色的 tile (先画 tile, 再 source-atop 叠色) → 用于樱树染粉
function drawTiledTile(ctx: CanvasRenderingContext2D, img: CanvasImageSource, tileIdx: number, dx: number, dy: number, tint: string, size = TOWN_TILE): void {
  const { sx, sy } = tileSrc(tileIdx);
  ctx.save();
  ctx.drawImage(img, sx, sy, TOWN_TILE, TOWN_TILE, dx, dy, size, size);
  ctx.globalCompositeOperation = "source-atop";
  ctx.fillStyle = tint;
  ctx.fillRect(dx, dy, size, size);
  ctx.restore();
}

// ttImg: Kenney Tiny Town tilemap 的 HTMLImageElement (场景自行 fetch, 不依赖 Phaser 纹理解码——
// 无头 WebGL 下纹理 source.data 可能为 null)。
export function buildArt(scene: Phaser.Scene, ttImg: HTMLImageElement): void {
  // 1. 地面 (真实 tile)
  const grid = buildGroundGrid();
  makeTexture(scene, "ground", MAP_COLS * TILE_PX, MAP_ROWS * TILE_PX, (ctx) => {
    for (let r = 0; r < MAP_ROWS; r++) {
      for (let c = 0; c < MAP_COLS; c++) {
        drawTile(ctx, ttImg, grid[r][c], c * TILE_PX, r * TILE_PX);
      }
    }
  });

  // 2. 建筑 (真实 tile 拼, 每 tile 16px)
  for (const [name, b] of Object.entries(BUILDINGS)) {
    const w = Math.max(...b.grid.map((r) => r.length)) * TOWN_TILE;
    const h = b.grid.length * TOWN_TILE;
    makeTexture(scene, `bldg_${name}`, w, h, (ctx) => {
      for (let r = 0; r < b.grid.length; r++) {
        for (let c = 0; c < b.grid[r].length; c++) {
          drawTile(ctx, ttImg, b.grid[r][c], c * TOWN_TILE, r * TOWN_TILE);
        }
      }
    });
  }

  // 3. 真实 tile 道具 (单 tile 16px)
  for (const [name, idx] of Object.entries(TILE_PROPS)) {
    makeTexture(scene, `prop_${name}`, TOWN_TILE, TOWN_TILE, (ctx) => drawTile(ctx, ttImg, idx, 0, 0));
  }
  // 樱树: 圆树染粉 (16px, 场景里 2x 放大显示)
  makeTexture(scene, "prop_tree", TOWN_TILE, TOWN_TILE, (ctx) => drawTiledTile(ctx, ttImg, CHERRY_TILE, 0, 0, "rgba(255,120,175,0.72)"));

  // 4. 手绘道具 (铁砧/病床/书桌/鸟居)
  for (const [name, g] of Object.entries(DRAW_PROPS)) {
    const w = Math.max(...g.map((r) => r.length));
    const h = g.length;
    makeTexture(scene, `prop_${name}`, w, h, (ctx) => drawGrid(ctx, g, 0, 0));
  }

  // 5. 角色帧 + 6. 动画 (idle/walk/活动循环) — 手绘原创, 不变
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
    for (const [ak, [fa, fb]] of Object.entries(ACTIVITY_FRAMES)) {
      makeTexture(scene, `act_${cn}_${ak}A`, 16, 16, (ctx) => drawGrid(ctx, sub(fa), 0, 0, bc));
      makeTexture(scene, `act_${cn}_${ak}B`, 16, 16, (ctx) => drawGrid(ctx, sub(fb), 0, 0, bc));
      const key = `${ak}_${cn}`;
      if (!scene.anims.exists(key)) {
        const rate = ak === "hammer" ? 6 : ak === "heal" ? 3 : 2;
        scene.anims.create({ key, frames: [{ key: `act_${cn}_${ak}A` }, { key: `act_${cn}_${ak}B` }], frameRate: rate, repeat: -1 });
      }
    }
  }
}
