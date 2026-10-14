// Phase 3 活动帧 (16x16, '#'→§→角色色, 默认朝右, 工具在右侧; 朝左时 sprite 水平翻转)。
// 三种"驻道具"活动: hammer (刚郎锤击循环) / heal (桃音治疗+绿光) / read (小梅阅读点头)。
// 巡逻 (执行官) 复用 walk 帧 + 路径移动; 坐镇 (将军) 复用 idle + 环境特效。原创像素。

// hammer_a: 锤举起 (锤头在上方)
export const HAMMER_A: string[] = [
  "                ",
  "      HHHH      ",
  "     HHHHHH  aa ",
  "     HFFFFH   a ",
  "     HFFFFH   M ",
  "      FFFFF    M ",
  "      ####     M ",
  "     ######   M ",
  "     #####    M ",
  "     #######    ",
  "     #######    ",
  "      ####      ",
  "      ####      ",
  "      ####      ",
  "     HHHHHH     ",
  "                ",
];
// hammer_b: 锤挥下 (锤头在下方, 落向铁砧)
export const HAMMER_B: string[] = [
  "                ",
  "      HHHH      ",
  "     HHHHHH     ",
  "     HFFFFH   M ",
  "     HFFFFH   M ",
  "      FFFFF    M ",
  "      ####     M ",
  "     ######   M ",
  "     #####    M ",
  "     #######  a ",
  "     ####### aa ",
  "      ####      ",
  "      ####      ",
  "      ####      ",
  "     HHHHHH     ",
  "                ",
];

// heal_a: 面向病床伸手, 绿光小
export const HEAL_A: string[] = [
  "                ",
  "      HHHH      ",
  "     HHHHHH     ",
  "     HFFFFH  G  ",
  "     HFFFFH GGG ",
  "      FFFFF G G ",
  "      ####  G  ",
  "     #######    ",
  "     ######     ",
  "     #######    ",
  "     #######    ",
  "      ####      ",
  "      ####      ",
  "      ####      ",
  "     HHHHHH     ",
  "                ",
];
// heal_b: 绿光大 (治疗脉冲)
export const HEAL_B: string[] = [
  "                ",
  "      HHHH      ",
  "     HHHHHH  G  ",
  "     HFFFFH GGGG",
  "     HFFFFH GGGG",
  "      FFFFF  GG ",
  "      ####  G  ",
  "     #######    ",
  "     ######     ",
  "     #######    ",
  "     #######    ",
  "      ####      ",
  "      ####      ",
  "      ####      ",
  "     HHHHHH     ",
  "                ",
];

// read_a: 头稍抬 (阅读)
export const READ_A: string[] = [
  "                ",
  "      HHHH      ",
  "     HHHHHH     ",
  "     HFFFFH     ",
  "     HFFFFH     ",
  "      FFFFF     ",
  "      ####      ",
  "     #######    ",
  "     #######    ",
  "     #######    ",
  "     #######    ",
  "      ####      ",
  "      ####      ",
  "      ####      ",
  "     HHHHHH     ",
  "                ",
];
// read_b: 低头看书 (整体下移 1px)
export const READ_B: string[] = [
  "                ",
  "                ",
  "      HHHH      ",
  "     HHHHHH     ",
  "     HFFFFH     ",
  "      FFFFF     ",
  "     ######     ",
  "     #######    ",
  "     #######    ",
  "     #######    ",
  "     #######    ",
  "      ####      ",
  "      ####      ",
  "      ####      ",
  "     HHHHHH     ",
  "                ",
];

export type ActivityFrameKey = "hammer" | "heal" | "read";
export const ACTIVITY_FRAMES: Record<ActivityFrameKey, [string[], string[]]> = {
  hammer: [HAMMER_A, HAMMER_B],
  heal: [HEAL_A, HEAL_B],
  read: [READ_A, READ_B],
};
