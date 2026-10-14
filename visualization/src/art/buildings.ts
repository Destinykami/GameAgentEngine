// 建筑与道具。地图改用 Kenney "Tiny Town" (CC0) 真实 tile:
// 建筑由 tile 网格拼成 (屋顶+墙+门), 烘焙成纹理 (每 tile 16px), 参与 y-sort 遮挡。
// 活动点道具 (铁砧/病床/书桌) 与鸟居保留手绘像素 (辨识度高, 是 Phase 3 活动锚点)。
// 樱树/灯笼/井/栅栏/蘑菇/松树用真实 tile (樱树=圆灌木染粉)。
import { TT } from "./townTiles";

export interface BuildingDef {
  // tile 下标网格 (行), 每 tile 16px
  grid: number[][];
  // 锚点 (角色站位) 相对建筑中心底部的偏移
  anchorDx: number;
  anchorDy: number;
}

// 6 地点建筑 (真实 tile 拼)
export const BUILDINGS: Record<string, BuildingDef> = {
  // 稻妻主城: 橙瓦顶 + 棕墙 (门窗)
  inazumaMain: {
    anchorDx: 0, anchorDy: 6,
    grid: [
      [TT.roofOrange, TT.roofOrange2, TT.roofOrange3, TT.roofOrange2, TT.roofOrange],
      [TT.wallBrown, TT.wallBrownWin, TT.wallBrownDoor, TT.wallBrownDoor2, TT.wallBrownDoor3],
      [TT.wallBrownWin2, TT.wallBrownWin3, TT.wallBrownDoor3, TT.wallBrownDoor4, TT.wallBrownDoor5],
    ],
  },
  // 治疗堂: 灰瓦顶 + 灰墙 (拱门)
  clinic: {
    anchorDx: 0, anchorDy: 4,
    grid: [
      [TT.roofGray, TT.roofGray2, TT.roofGray3, TT.roofGray2],
      [TT.wallGray, TT.wallGray2, TT.archGray, TT.wallGray3],
      [TT.wallGray3, TT.wallGray2, TT.archGray, TT.wallGray],
    ],
  },
  // 锻造坊: 橙瓦顶 + 橙墙 (拱门)
  forge: {
    anchorDx: 10, anchorDy: 4,
    grid: [
      [TT.roofOrange, TT.roofOrange2, TT.roofOrange3, TT.roofOrange2],
      [TT.wallOrange, TT.wallOrange2, TT.houseOrangeDoor, TT.wallOrange3],
      [TT.wallOrange3, TT.wallOrange2, TT.houseOrangeDoor, TT.wallOrange],
    ],
  },
  // 眼狩署: 石顶 + 石墙 (带窗石屋)
  bureau: {
    anchorDx: 0, anchorDy: 4,
    grid: [
      [TT.roofStone, TT.roofStone2, TT.roofStoneDoor, TT.roofStone2, TT.roofStone],
      [TT.wallStone, TT.wallStone2, TT.houseGrayWindow, TT.wallStone3, TT.wallStone4],
      [TT.wallStone4, TT.wallStone3, TT.houseGrayWindow, TT.wallStone2, TT.wallStone],
    ],
  },
  // 神樱庭: 橙瓦顶 + 灰墙拱门 (神社本殿, 前接鸟居)
  shrine: {
    anchorDx: 0, anchorDy: 8,
    grid: [
      [TT.roofOrange, TT.roofOrange2, TT.roofOrange3, TT.roofOrange2, TT.roofOrange],
      [TT.wallGray, TT.wallGray2, TT.archGray, TT.wallGray2, TT.wallGray],
      [TT.wallGray3, TT.wallGray2, TT.archGray, TT.wallGray2, TT.wallGray3],
    ],
  },
  // 城外官道: 石拱门 + 石块
  road: {
    anchorDx: 0, anchorDy: 0,
    grid: [
      [TT.archStone, TT.archStone2, TT.archStone],
      [TT.stone, TT.stone, TT.stone],
    ],
  },
};

// 真实 tile 道具 (单 tile): 下标
export const TILE_PROPS: Record<string, number> = {
  lantern: TT.lanternRed,      // 红灯笼
  lantern2: TT.lanternRed2,
  well: TT.well,               // 水井
  mushroom: TT.mushroom,       // 红蘑菇
  fence: TT.fence,             // 木栅栏
  fencePost: TT.fencePost,
  crate: TT.crate,             // 木箱
  sign: TT.sign,               // 路标
  pine: TT.pineGreen,          // 松树 (绿)
  stone: TT.stoneBlock,        // 石块
};

// 手绘道具 (字符网格, 对应 palette.ts): 铁砧/病床/书桌 (活动点) + 鸟居 (稻妻标志)
export const DRAW_PROPS: Record<string, string[]> = {
  anvil: [
    "                ",
    "                ",
    "                ",
    "     aaaa       ",
    "   aaaaaaa      ",
    "  aaaaaaaaa     ",
    "   aaaaaaa      ",
    "    bbbb        ",
    "     bb         ",
    "    bbbb        ",
    "   bbbbbbb      ",
    "  bbbbbbbbb     ",
    "                ",
    "                ",
    "                ",
    "                ",
  ],
  bed: [
    "                ",
    "                ",
    "                ",
    "   WWWWWW       ",
    "   WWGGWW       ",
    "   WWWWWW       ",
    "   WWWWWW       ",
    "   WWWWWW       ",
    "   MMMMMM       ",
    "   MMMMMM       ",
    "  MMMMMMMM      ",
    "  MMMMMMMM      ",
    "                ",
    "                ",
    "                ",
    "                ",
  ],
  desk: [
    "                ",
    "                ",
    "                ",
    "   MBBMM        ",
    "   MMMMM        ",
    "   MMMMM        ",
    "  MMMMMMM       ",
    "  MMMMMMM       ",
    "  MMMMMMM       ",
    "  MMMMMMM       ",
    "   MMM MM       ",
    "   MMM MM       ",
    "                ",
    "                ",
    "                ",
    "                ",
  ],
  torii: [
    "  RRRRRRRRRRRR  ",
    "  RRRRRRRRRRRR  ",
    "   RRRRRRRRRR   ",
    "    RR    RR    ",
    "    RR    RR    ",
    "    RR    RR    ",
    "    RR    RR    ",
    "    RR    RR    ",
    "    RR    RR    ",
    "    RR    RR    ",
    "    RR    RR    ",
    "   RRRRRRRRRR   ",
    "    RR    RR    ",
    "    RR    RR    ",
    "    RR    RR    ",
    "    RR    RR    ",
  ],
};

// 樱树: 圆树 (TT.treeRoundOrange, 16px 完整树形含树干) 染粉 (ArtFactory 专门烘焙)
export const CHERRY_TILE = TT.treeRoundOrange;
