// 视觉锚点: 渲染坐标层, 与模拟坐标 (Location.x/y 小整数) 严格分离 (计划 §2.3)。
// 第一版用静态映射表, 稳定后迁 Tiled 自定义属性。画布 960x540。
// 布局按计划 §4 Phase 0: 主城中央 / 治疗堂东 / 锻造坊再东 / 眼狩署北 /
// 神樱庭北方高地 / 城外官道右下出口。

export interface LocationAnchor {
  x: number;
  y: number;
  label: string;
  // 占位地图色块尺寸 (M1 用色块代替真实 tile)
  w: number;
  h: number;
  color: number;
}

export const LOCATION_ANCHORS: Record<string, LocationAnchor> = {
  稻妻主城: { x: 440, y: 330, label: "稻妻主城", w: 180, h: 140, color: 0x3a4a5a },
  治疗堂:   { x: 640, y: 330, label: "治疗堂",   w: 130, h: 140, color: 0x4a5a4a },
  锻造坊:   { x: 700, y: 360, label: "锻造坊",   w: 120, h: 140, color: 0x5a4a3a },
  眼狩署:   { x: 440, y: 170, label: "眼狩署",   w: 140, h: 100, color: 0x5a3a3a },
  神樱庭:   { x: 200, y: 130, label: "神樱庭",   w: 150, h: 110, color: 0x5a3a5a },
  城外官道: { x: 850, y: 470, label: "城外官道", w: 130, h: 70,  color: 0x4a4a3a },
};

// 某地点的视觉锚点中心 (Sprite 站位)。未知地点回退画布中心。
export function anchorOf(locName: string): { x: number; y: number } {
  const a = LOCATION_ANCHORS[locName];
  if (!a) return { x: 480, y: 270 };
  return { x: a.x, y: a.y };
}

export const ALL_LOCATIONS = Object.keys(LOCATION_ANCHORS);
