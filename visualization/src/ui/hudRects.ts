// HUD 占位矩形 (屏幕坐标, 左上角原点)。详情卡/气泡做定位时避让这些区域,
// 避免"跟着 NPC 摆"却压到状态面板/事件记录/播放条/顶部时间轴。
// 这是当前 960×540 布局的集中记录; Round 2 做布局 token 时从这里扩展。
export interface HudRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const HUD_RECTS: HudRect[] = [
  { x: 0, y: 0, w: 960, h: 40 },       // 顶部时间轴栏
  { x: 725, y: 40, w: 230, h: 270 },   // 状态面板 (折叠时仍按整块避让, 保守)
  { x: 30, y: 380, w: 480, h: 100 },   // 事件记录
  { x: 90, y: 495, w: 460, h: 45 },    // 播放控制条 + 进度
  { x: 10, y: 44, w: 150, h: 22 },     // 直播模式入口
];

export function overlapArea(a: HudRect, b: HudRect): number {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  return w > 0 && h > 0 ? w * h : 0;
}
