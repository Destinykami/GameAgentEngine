// 稻妻地图改用公开素材: Kenney "Tiny Town" (CC0 公共领域, 无需署名, 许可证见
// public/assets/TinyTown-LICENSE.txt)。tilemap 16x16, 12 列 x 11 行, tile 间距 1px。
// 本模块定义各用途的 tile 下标 (0-based, 行优先) 与取源矩形, 供 ArtFactory 烘焙。
// 下标已对照完整带索引 tile 表逐一确认。
export const TOWN_COLS = 12;
export const TOWN_TILE = 16;
export const TOWN_SPACING = 1;
export const TILEMAP_KEY = "tt";   // Phaser 纹理键 (public/assets/tiny-town-tilemap.png)

// tile 下标 → 用途
export const TT = {
  // 草地
  grass: 1,          // 基础草地
  grassDark: 0,      // 深草
  grassFlower: 2,    // 带橙色花的草
  grassPlant: 3,     // 带小植物的草
  // 沙土 (路/空地)
  sand: 13,
  sand2: 12,
  sand3: 14,
  sand4: 21,
  sand5: 24,
  sand6: 25,
  sand7: 26,
  sand8: 36,
  sand9: 37,
  sand10: 39,
  // 石板路 (主路/广场)
  road: 109,         // 纯石板
  road2: 108,
  road3: 110,
  roadCorner: 112,
  road4: 120,
  road5: 121,
  roadCorner2: 122,
  road6: 125,
  // 树
  pineGreen: 4,      // 绿树
  pineGreen2: 28,
  pineOrange: 27,    // 橙树
  pineOrange2: 9,
  treeRoundGreen: 16,
  treeRoundOrange: 15,
  bushRound: 5,      // 圆灌木 (染粉 = 樱花树)
  hedge: 17,
  plant: 7,
  plant2: 8,
  bushGreen: 31,
  bushOrange: 33,
  bushOrange2: 34,
  mossStone: 42,     // 苔藓石
  mossStone2: 43,
  // 道具
  mushroom: 29,
  fence: 45,
  fenceCorner: 44,
  fencePost: 46,
  fencePost2: 47,
  beam: 80,
  beam2: 81,
  sign: 83,
  sign2: 119,
  lanternBrown: 93,
  lanternOrange: 94,
  lanternRed: 95,
  lanternRed2: 129,
  well: 104,
  well2: 124,
  crate: 106,
  crate2: 130,
  bench: 107,
  stone: 105,
  stonePillar: 117,
  // 建筑 (屋顶/墙/门)
  roofGray: 48,
  roofGray2: 49,
  roofGray3: 50,
  roofOrange: 52,
  roofOrange2: 53,
  roofOrange3: 54,
  wallOrange: 64,
  wallOrange2: 65,
  wallOrange3: 66,
  houseOrangeDoor: 67,   // 完整橙房 (拱门)
  houseOrangeRoof: 63,   // 完整橙房 (屋顶带门)
  hutBrown: 57,          // 完整棕色小屋
  wallOrangeBrown: 72,
  wallOrangeBrown2: 73,
  archOrange: 74,
  wallOrangeBrown3: 75,
  wallGray: 76,
  wallGray2: 77,
  archGray: 78,
  wallGray3: 79,
  houseGrayDoor: 51,     // 完整灰房 (门窗)
  houseGray2: 55,        // 完整灰房
  houseGrayWindow: 103,  // 完整灰房 (带窗)
  wallBrown: 84,         // 棕墙 (双门)
  wallBrownWin: 85,
  wallBrownDoor: 86,
  wallBrownDoor2: 87,
  wallBrownDoor3: 88,
  wallBrownWin2: 89,
  wallBrownWin3: 90,
  wallBrownDoor4: 91,
  wallBrownDoor5: 92,
  roofStone: 96,
  roofStone2: 97,
  roofStoneDoor: 98,
  wallStone: 99,
  wallStone2: 100,
  wallStone3: 101,
  wallStone4: 102,
  archStone: 115,
  archStone2: 116,
  stoneBlock: 126,
  stoneBlock2: 127,
} as const;

export type TownTile = (typeof TT)[keyof typeof TT];

// tile 下标 → tilemap 内的源左上角 (drawImage 用)
export function tileSrc(i: number): { sx: number; sy: number } {
  const col = i % TOWN_COLS;
  const row = Math.floor(i / TOWN_COLS);
  return { sx: col * (TOWN_TILE + TOWN_SPACING), sy: row * (TOWN_TILE + TOWN_SPACING) };
}
