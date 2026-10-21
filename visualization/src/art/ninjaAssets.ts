// Ninja Adventure (日式) 村庄素材。
// 地面 ninja-town.png 由 tools/build_ninja_town.py 生成; 建筑/树/门/栅栏从
// tileset_village_abandoned.png 裁成透明 Sprite, 参与 y-sort。
export const NINJA_TOWN_FILE = "ninja-town.png";
export const NINJA_TOWN_KEY = "ninja_town";

export const NINJA_SPRITE_FILES = [
  "house_main", "house_clinic", "house_shrine", "house_forge",
  "house_white", "house_ruin", "gate", "fence", "rock", "log",
  "tree_round", "tree_round2", "tree_sakura",
] as const;

export function ninjaKey(name: string): string {
  return `ninja_${name}`;
}

export interface NinjaPart {
  key: string;
  dx: number;
  dy: number;
  scale?: number;
}

// 每个地点 1~2 个建筑部件; 底边锚在锚点略后方, 角色站前方 → y-sort。
export const NINJA_BUILDING_PARTS: Record<string, NinjaPart[]> = {
  稻妻主城: [{ key: "house_clinic", dx: 0, dy: 0 }],
  治疗堂: [{ key: "house_main", dx: 0, dy: 0 }],
  锻造坊: [{ key: "house_forge", dx: 0, dy: 0, scale: 2 }],
  眼狩署: [{ key: "house_white", dx: 0, dy: 0 }],
  神樱庭: [
    { key: "house_shrine", dx: 0, dy: 0 },
    { key: "gate", dx: -55, dy: 4 },
  ],
  城外官道: [{ key: "gate", dx: 0, dy: 0 }],
};

export interface NinjaDecor {
  key: string;
  x: number;
  y: number;
  scale?: number;
}

// 日式村庄装饰: 苔藓树/樱花/岩石/倒木/栅栏/废弃小屋。
export const NINJA_DECOR: NinjaDecor[] = [
  // 左侧森林
  { key: "tree_round", x: 40, y: 100, scale: 2 },
  { key: "tree_round2", x: 75, y: 155, scale: 1 },
  { key: "tree_round", x: 110, y: 80, scale: 2 },
  { key: "tree_round2", x: 135, y: 190, scale: 1 },
  { key: "tree_round", x: 60, y: 225, scale: 1 },
  { key: "tree_round2", x: 95, y: 270, scale: 1 },
  { key: "tree_round", x: 50, y: 340, scale: 1 },
  { key: "tree_round2", x: 105, y: 395, scale: 1 },
  { key: "tree_round", x: 60, y: 455, scale: 1 },
  { key: "tree_round2", x: 30, y: 505, scale: 2 },
  { key: "rock", x: 150, y: 250, scale: 1 },
  { key: "log", x: 150, y: 330, scale: 1 },
  { key: "rock", x: 80, y: 410, scale: 1 },
  // 樱花林 (神樱庭)
  { key: "tree_sakura", x: 155, y: 115, scale: 1 },
  { key: "tree_sakura", x: 250, y: 125, scale: 1 },
  { key: "tree_sakura", x: 185, y: 155, scale: 1 },
  { key: "tree_sakura", x: 260, y: 160, scale: 1 },
  { key: "tree_sakura", x: 140, y: 180, scale: 1 },
  { key: "tree_sakura", x: 290, y: 70, scale: 1 },
  { key: "rock", x: 160, y: 200, scale: 1 },
  // 广场/路边
  { key: "rock", x: 530, y: 380, scale: 1 },
  // 右侧/底部边缘 (避开状态面板与事件框)
  { key: "tree_round", x: 610, y: 85, scale: 2 },
  { key: "tree_round2", x: 690, y: 105, scale: 1 },
  { key: "tree_round", x: 905, y: 85, scale: 2 },
  { key: "tree_round2", x: 630, y: 190, scale: 1 },
  { key: "tree_round", x: 710, y: 210, scale: 1 },
  { key: "tree_round2", x: 920, y: 210, scale: 1 },
  { key: "tree_round", x: 610, y: 430, scale: 1 },
  { key: "tree_round2", x: 690, y: 440, scale: 1 },
  { key: "tree_round", x: 900, y: 390, scale: 1 },
  { key: "tree_round2", x: 920, y: 505, scale: 2 },
  { key: "tree_round", x: 490, y: 505, scale: 1 },
  { key: "tree_round2", x: 410, y: 505, scale: 1 },
  { key: "tree_round", x: 330, y: 505, scale: 1 },
  { key: "tree_round2", x: 260, y: 505, scale: 1 },
  // 废弃小屋/栅栏/岩石点缀
  { key: "rock", x: 470, y: 470, scale: 1 },
  { key: "house_ruin", x: 330, y: 155, scale: 1 },
  { key: "fence", x: 382, y: 165, scale: 1 },
  { key: "log", x: 292, y: 170, scale: 1 },
  { key: "rock", x: 360, y: 120, scale: 1 },
];
