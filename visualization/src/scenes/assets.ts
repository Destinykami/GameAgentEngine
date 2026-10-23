import type Phaser from "phaser";
import { LOCATION_ANCHORS } from "../data/locationAnchors";
import { buildArt } from "../art/ArtFactory";
import { BUILDINGS } from "../art/buildings";
import { FULLBODY_FILES, PORTRAIT_FILES, fullbodyUrl, portraitTextureKey, portraitUrl } from "../data/avatarAssets";
import { NINJA_BUILDING_PARTS, NINJA_DECOR, NINJA_SPRITE_FILES, NINJA_TOWN_FILE, NINJA_TOWN_KEY, ninjaKey } from "../art/ninjaAssets";

const LOCATION_LABEL_LIFT = __OFFICIAL_FULLBODY__ ? 26 : 0;

export function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => rej(new Error("tilemap 加载失败: " + url));
    img.src = url;
  });
}

// 可选本地原神像素头像。Vite 构建期 __OFFICIAL_PORTRAITS__ 为 false 时完全不请求,
// 避免目录缺失时的 404/console 错误; 素材仅本地个人学习用 (见 OFFICIAL_PORTRAITS.md)。
export async function loadPortraits(): Promise<Map<string, HTMLImageElement>> {
  const out = new Map<string, HTMLImageElement>();
  if (!__OFFICIAL_PORTRAITS__) return out;
  await Promise.all(Object.entries(PORTRAIT_FILES).map(async ([name, file]) => {
    try { out.set(name, await loadImage(portraitUrl(file))); } catch { /* 单张缺失则跳过 */ }
  }));
  return out;
}

// 可选本地原神全身 Sprite 表 (480x64, 10 帧)。缺失时回退到原 16x16 原创角色。
export async function loadFullbody(): Promise<Map<string, HTMLImageElement>> {
  const out = new Map<string, HTMLImageElement>();
  if (!__OFFICIAL_FULLBODY__) return out;
  await Promise.all(Object.entries(FULLBODY_FILES).map(async ([name, file]) => {
    try { out.set(name, await loadImage(fullbodyUrl(file))); } catch { /* 单张缺失则回退 */ }
  }));
  return out;
}

// Ninja Adventure (日式) 村庄素材: 地面 + 建筑/树/门/栅栏 Sprite。
// 资源已入库; 任一缺失则返回 null, 回退到原 Tiny Town 地图。
export interface NinjaAssets {
  town: HTMLImageElement;
  sprites: Map<string, HTMLImageElement>;
}

export async function loadNinjaAssets(): Promise<NinjaAssets | null> {
  try {
    const town = await loadImage(`assets/${NINJA_TOWN_FILE}`);
    const entries = await Promise.all(NINJA_SPRITE_FILES.map(async (n) => {
      const img = await loadImage(`assets/ninja/${n}.png`);
      return [n, img] as const;
    }));
    return { town, sprites: new Map(entries) };
  } catch {
    return null;
  }
}

// 把 HTMLImageElement 写成 Phaser canvas 纹理 (无头 WebGL 下比 load.image 稳)。
function addCanvasTexture(scene: Phaser.Scene, key: string, img: HTMLImageElement): void {
  if (scene.textures.exists(key)) return;
  const tex = scene.textures.createCanvas(key, img.width, img.height);
  if (!tex) return;
  tex.context.drawImage(img, 0, 0);
  tex.refresh();
}

export type SceneResources = [Promise<HTMLImageElement>, Promise<Map<string, HTMLImageElement>>,
  Promise<Map<string, HTMLImageElement>>, Promise<NinjaAssets | null>];

export function loadResources(): SceneResources {
  return [loadImage("assets/tiny-town-tilemap.png"), loadPortraits(), loadFullbody(), loadNinjaAssets()];
}

export function drawWorld(scene: Phaser.Scene, ttImg: HTMLImageElement,
  portraits: Map<string, HTMLImageElement>, fullbody: Map<string, HTMLImageElement>, ninja: NinjaAssets | null): void {
  // 本地原神像素头像 → Phaser 纹理 (64x64; UI 里缩到 20/28 显示)。
  for (const [name, img] of portraits) {
    const key = portraitTextureKey(name);
    if (scene.textures.exists(key)) continue;
    const tex = scene.textures.createCanvas(key, img.width, img.height);
    if (tex) { tex.context.drawImage(img, 0, 0); tex.refresh(); }
  }

  // M3 地图: 优先使用 Ninja Adventure 日式村庄; 缺失则回退原 Tiny Town。
  // 两种模式都保持: 建筑/树木/角色同一深度空间, 按 y 排序遮挡。
  buildArt(scene, ttImg, fullbody);
  if (ninja) {
    addCanvasTexture(scene, NINJA_TOWN_KEY, ninja.town);
    for (const [name, img] of ninja.sprites) addCanvasTexture(scene, ninjaKey(name), img);
    scene.add.image(480, 272, NINJA_TOWN_KEY).setOrigin(0.5, 0.5).setDepth(0);
    addNinjaWorld(scene);
  } else {
    scene.add.image(480, 270, "ground").setOrigin(0.5, 0.5).setDepth(0);
    // 建筑: 每地点一栋, 底边锚在地点锚点略后方, 角色站在建筑前。
    const BLDG_AT: Record<string, string> = {
      稻妻主城: "inazumaMain", 治疗堂: "clinic", 锻造坊: "forge",
      眼狩署: "bureau", 神樱庭: "shrine", 城外官道: "road",
    };
    for (const [loc, bkey] of Object.entries(BLDG_AT)) {
      const a = LOCATION_ANCHORS[loc];
      const def = BUILDINGS[bkey];
      const img = scene.add.image(a.x + def.anchorDx, a.y - 8 + def.anchorDy, `bldg_${bkey}`)
        .setOrigin(0.5, 1).setDepth(Math.round(a.y - 8));
      img.alpha = 0.96;
    }
  }
  // 地点标签: 统一放建筑/角色上方; 顶部过近时夹到 y=50 (避开时间轴)。
  for (const a of Object.values(LOCATION_ANCHORS)) {
    const labelY = a.labelY ?? Math.max(56, a.y - a.h / 2 - 14 - LOCATION_LABEL_LIFT);
    scene.add.text(a.x, labelY, a.label, {
      fontFamily: "monospace", fontSize: "11px", color: "#cfc6b8", stroke: "#000000", strokeThickness: 2,
    }).setOrigin(0.5, 1).setDepth(500);
  }
  // 活动点道具 (NPC 日常活动的锚点) —— 两种地图都保留。
  prop(scene, "anvil", LOCATION_ANCHORS.锻造坊.x + 14, LOCATION_ANCHORS.锻造坊.y + 4);
  prop(scene, "bed", LOCATION_ANCHORS.治疗堂.x - 10, LOCATION_ANCHORS.治疗堂.y + 4);
  prop(scene, "desk", LOCATION_ANCHORS.稻妻主城.x - 22, LOCATION_ANCHORS.稻妻主城.y + 4);
  if (ninja) {
    // 日式地图: 保留红灯笼/水井/木箱做点缀; 树/门/栅栏已由 addNinjaWorld 放置。
    prop(scene, "lantern", 470, 300, 2);
    prop(scene, "lantern", 640, 300, 2);
    prop(scene, "well", 80, 470, 2);
    prop(scene, "crate", 500, 350, 2);
  } else {
    prop(scene, "torii", LOCATION_ANCHORS.神樱庭.x, LOCATION_ANCHORS.神樱庭.y + 8);
    const sx = LOCATION_ANCHORS.神樱庭.x, sy = LOCATION_ANCHORS.神樱庭.y;
    prop(scene, "tree", sx - 48, sy + 16, 2);
    prop(scene, "tree", sx - 12, sy - 6, 2);
    prop(scene, "tree", sx + 34, sy + 12, 2);
    prop(scene, "tree", sx + 62, sy - 2, 2);
    prop(scene, "tree", 300, 240, 2);
    prop(scene, "tree", 560, 420, 2);
    prop(scene, "tree", 760, 200, 2);
    prop(scene, "pine", 120, 300, 2);
    prop(scene, "pine", 900, 240, 2);
    prop(scene, "lantern", 440, 250);
    prop(scene, "lantern", 700, 300);
    prop(scene, "well", 40, 500);
    prop(scene, "crate", 470, 350);
  }

}

function prop(scene: Phaser.Scene, key: string, x: number, y: number, scale = 1): void {
  scene.add.image(x, y, `prop_${key}`).setOrigin(0.5, 1).setScale(scale).setDepth(Math.round(y));
}

function addNinjaWorld(scene: Phaser.Scene): void {
  for (const [loc, parts] of Object.entries(NINJA_BUILDING_PARTS)) {
    const a = LOCATION_ANCHORS[loc];
    for (const p of parts) {
      const y = a.y + p.dy;
      scene.add.image(a.x + p.dx, y, ninjaKey(p.key))
        .setOrigin(0.5, 1)
        .setScale(p.scale ?? 1)
        .setDepth(Math.round(y - 2));
    }
  }
  for (const d of NINJA_DECOR) {
    const sc = d.scale ?? 1;
    if (d.key.startsWith("tree")) {
      scene.add.ellipse(d.x, d.y - 3, 18 * sc, 6, 0x000000, 0.16)
        .setDepth(Math.round(d.y) - 1);
    } else if (d.key === "lantern_stone") {
      scene.add.ellipse(d.x, d.y - 26, 26, 9, 0xf5d27a, 0.18)
        .setDepth(Math.round(d.y) - 1);
    }
    scene.add.image(d.x, d.y, ninjaKey(d.key))
      .setOrigin(0.5, 1)
      .setScale(sc)
      .setDepth(Math.round(d.y));
  }
}
