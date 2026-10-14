// 角色像素帧 (16x16)。'#' 是身体色占位, 渲染时替换为角色专属色 (见 SPRITE_COLORS)。
// idle 两帧 (呼吸: 身体微起伏), walk 两帧 (迈腿/并腿)。原创像素。
// 帧结构: 头发(H)/脸(F)/身体(#→§)/靴(深色)。
function frame(body: string, legs: string[]): string[] {
  // body: 躯干颜色字符, legs: 4 行腿部字符串
  return [
    "                ",
    "      HHHH      ",
    "     HHHHHH     ",
    "     HFFFFH     ",
    "     HFFFFH     ",
    "      FFFFF     ",
    `      ${body}${body}${body}${body}      `,
    `     ${body}${body}${body}${body}${body}${body}${body}     `,
    `     ${body}${body}${body}${body}${body}${body}${body}     `,
    `     ${body}${body}${body}${body}${body}${body}${body}     `,
    `     ${body}${body}${body}${body}${body}${body}${body}     `,
    `      ${body}${body}${body}${body}      `,
    legs[0],
    legs[1],
    legs[2],
    legs[3],
  ];
}

// idle A: 并腿站立
const idleA = frame("#", [
  "      ####      ",
  "      ####      ",
  "      ####      ",
  "     HHHHHH     ",
]);
// idle B: 呼吸 (身体上移 1px, 腿不变) — 用整体位移表现, 这里躯干缩短 1 行
const idleB = [
  "                ",
  "     HHHHHH     ",
  "    HHHHHHHH    ",
  "    HFFFFFH     ",
  "    HFFFFFH     ",
  "     FFFFFF     ",
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
// walk 1: 迈腿 (左前右后)
const walk1 = frame("#", [
  "     ### ##     ",
  "     ### ##     ",
  "     ##   ##    ",
  "    HHH   HHH   ",
]);
// walk 2: 并腿 (过渡)
const walk2 = frame("#", [
  "      ####      ",
  "      ####      ",
  "      ##        ",
  "     HHH        ",
]);

export interface CharFrames {
  idleA: string[];
  idleB: string[];
  walk1: string[];
  walk2: string[];
}

// 角色名 → 身体色 (与 AgentSprite.SPRITE_COLORS 一致, 复用同一套配色)
export const CHAR_BODY_COLOR: Record<string, string> = {
  旅行者:   "#4fc3f7",
  桃音:     "#f48fb1",
  刚郎:     "#ffb74d",
  小梅:     "#81c784",
  执行官:   "#e57373",
  雷电将军: "#ba68c8",
};
const FALLBACK_BODY = "#90a4ae";

export function framesFor(name: string): CharFrames {
  // 把 '#' 占位替换成唯一 § (ArtFactory 渲染时再把 § 换成角色身体色)。
  void name;   // 帧形状对所有角色相同, 仅颜色不同 (由 bodyColorOf 提供)
  const sub = (grid: string[]) => grid.map((row) => row.split("#").join("§"));
  return { idleA: sub(idleA), idleB: sub(idleB), walk1: sub(walk1), walk2: sub(walk2) };
}

// ArtFactory 用: 把 § 换成角色色 (返回颜色映射后的网格, 配合 palette 渲染)
export const BODY_PLACEHOLDER = "§";
export function bodyColorOf(name: string): string {
  return CHAR_BODY_COLOR[name] ?? FALLBACK_BODY;
}
