// Kenney Roguelike/RPG (CC0) 村庄素材。
// 地面 rl-town.png 由 tools/build_rl_town.py 生成; 建筑/树木是从同 pack 的示例地图
// 中裁出的透明 Sprite (CC0), 参与 y-sort。所有文件已入库。
export const RL_TOWN_FILE = "rl-town.png";
export const RL_TOWN_KEY = "rl_town";

// 需要作为纹理加载的图 (public/assets/rl/<name>.png + 地面)
export const RL_SPRITE_FILES = [
  "house_main", "house_bureau", "house_clinic", "house_forge", "house_shrine",
  "tent", "stall", "pool", "torii", "gate",
  "tree_round", "tree_round2", "tree_pine", "tree_pine2", "tree_sakura",
] as const;

export function rlKey(name: string): string {
  return `rl_${name}`;
}

export interface RlPart {
  key: string;   // 不含 rl_ 前缀
  dx: number;
  dy: number;    // 相对地点锚点 (脚底) 的垂直偏移
  scale?: number;
}

// 每个地点 1~2 栋房子; 底边锚在锚点略后方, 角色站前方 → y-sort 遮挡。
export const RL_BUILDING_PARTS: Record<string, RlPart[]> = {
  稻妻主城: [
    { key: "house_main", dx: -20, dy: 0 },
    { key: "house_clinic", dx: 22, dy: 2, scale: 0.9 },
  ],
  治疗堂: [
    { key: "house_clinic", dx: -18, dy: 0 },
    { key: "house_bureau", dx: 22, dy: 2, scale: 0.9 },
  ],
  锻造坊: [
    { key: "house_forge", dx: -18, dy: 0 },
    { key: "house_main", dx: 22, dy: 2, scale: 0.9 },
  ],
  眼狩署: [
    { key: "house_bureau", dx: -14, dy: 0 },
    { key: "pool", dx: 34, dy: -2, scale: 0.8 },
  ],
  神樱庭: [
    { key: "house_shrine", dx: 0, dy: 0 },
    { key: "torii", dx: -42, dy: 4 },
  ],
  城外官道: [
    { key: "gate", dx: 0, dy: 0 },
  ],
};

export interface RlDecor {
  key: string;
  x: number;
  y: number;
  scale?: number;
}

// 树木/帐篷/摊位等装饰。深度 = y, 角色走到树后会被遮挡。
export const RL_DECOR: RlDecor[] = [
  // 左侧森林 (神樱庭外围)
  { key: "tree_pine", x: 40, y: 100, scale: 2 },
  { key: "tree_pine2", x: 70, y: 150, scale: 2 },
  { key: "tree_pine", x: 105, y: 80, scale: 2 },
  { key: "tree_round", x: 130, y: 180, scale: 2 },
  { key: "tree_pine2", x: 60, y: 220, scale: 2 },
  { key: "tree_round2", x: 90, y: 260, scale: 2 },
  { key: "tree_pine", x: 50, y: 330, scale: 2 },
  { key: "tree_round", x: 100, y: 380, scale: 2 },
  { key: "tree_pine2", x: 60, y: 450, scale: 2 },
  { key: "tree_pine", x: 30, y: 500, scale: 2 },
  { key: "tree_round2", x: 140, y: 230, scale: 2 },
  { key: "tree_pine", x: 160, y: 300, scale: 2 },
  { key: "tree_round", x: 130, y: 500, scale: 2 },
  { key: "tree_pine2", x: 190, y: 60, scale: 2 },
  { key: "tree_pine", x: 240, y: 70, scale: 2 },
  { key: "tree_round2", x: 280, y: 100, scale: 2 },
  // 樱花林 (神樱庭)
  { key: "tree_sakura", x: 150, y: 110, scale: 2 },
  { key: "tree_sakura", x: 250, y: 120, scale: 2 },
  { key: "tree_sakura", x: 180, y: 150, scale: 2 },
  { key: "tree_sakura", x: 255, y: 155, scale: 2 },
  { key: "tree_sakura", x: 135, y: 175, scale: 2 },
  { key: "tree_sakura", x: 285, y: 65, scale: 2 },
  // 广场/路边
  { key: "tree_round", x: 300, y: 440, scale: 2 },
  { key: "tree_pine", x: 560, y: 500, scale: 2 },
  { key: "tree_round2", x: 580, y: 400, scale: 2 },
  { key: "tree_pine2", x: 580, y: 200, scale: 2 },
  { key: "tree_round", x: 380, y: 200, scale: 2 },
  // 右侧/底部边缘 (避开状态面板)
  { key: "tree_pine", x: 600, y: 80, scale: 2 },
  { key: "tree_round", x: 680, y: 100, scale: 2 },
  { key: "tree_pine2", x: 900, y: 80, scale: 2 },
  { key: "tree_round2", x: 620, y: 180, scale: 2 },
  { key: "tree_pine", x: 700, y: 200, scale: 2 },
  { key: "tree_round", x: 920, y: 200, scale: 2 },
  { key: "tree_round2", x: 600, y: 420, scale: 2 },
  { key: "tree_pine2", x: 680, y: 430, scale: 2 },
  { key: "tree_pine", x: 740, y: 420, scale: 2 },
  { key: "tree_round", x: 900, y: 380, scale: 2 },
  { key: "tree_pine2", x: 920, y: 500, scale: 2 },
  { key: "tree_round2", x: 480, y: 500, scale: 2 },
  { key: "tree_round", x: 400, y: 500, scale: 2 },
  { key: "tree_pine", x: 320, y: 500, scale: 2 },
  { key: "tree_round2", x: 250, y: 500, scale: 2 },
  // 帐篷营地 + 市场摊位
  { key: "tent", x: 330, y: 145, scale: 2 },
  { key: "tent", x: 375, y: 155, scale: 2 },
  { key: "tent", x: 300, y: 120, scale: 2 },
  { key: "stall", x: 520, y: 300, scale: 2 },
];
