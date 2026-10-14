// Phase 3 视觉活动投影 (计划 §Phase 3)。
// 重要边界: 后端日计划/重规划未完整写入 timeline, 因此活动是"视觉活动投影"——
// 按 (角色, 地点, 动作) 推断/配置, 不冒充后端已模拟每一分钟的连续行为。
// 数据结构对齐计划建议: activity/label/location/animation/anchor (+facing 朝向道具)。
// talk/move/wait 不打断日计划; attack/flee/help/hide 中断 (见 INTERRUPT_TYPES)。

export interface ActivityDef {
  activity: string;        // 机读活动 (smithing/healing/reading/patrol/station)
  label: string;           // 展示标签 (锻造武器/治疗伤者/…)
  animation: string;       // 动画 key 前缀 (hammer/heal/read/patrol/station)
  anchor: string;          // 活动点道具 key (anvil/bed/desk, 空=无道具)
  facing?: "left" | "right"; // 朝向道具 (sprite 水平翻转)
}

// (角色 → 地点 → 活动)。旅行者无默认活动 (由实际事件驱动)。
export const ACTIVITY_MAP: Record<string, Record<string, ActivityDef>> = {
  桃音:   { 治疗堂: { activity: "healing", label: "治疗伤者", animation: "heal", anchor: "bed", facing: "left" } },
  刚郎:   { 锻造坊: { activity: "smithing", label: "锻造武器", animation: "hammer", anchor: "anvil", facing: "right" } },
  小梅:   { 稻妻主城: { activity: "reading", label: "阅读典籍", animation: "read", anchor: "desk", facing: "left" } },
  执行官: { 眼狩署: { activity: "patrol", label: "巡逻搜捕", animation: "patrol", anchor: "" },
            城外官道: { activity: "patrol", label: "巡逻搜捕", animation: "patrol", anchor: "" } },
  雷电将军: { 神樱庭: { activity: "station", label: "坐镇观望", animation: "station", anchor: "" } },
  // 旅行者: 无默认活动 —— 行走/对话/战斗由实际 visual_events 驱动
};

// 中断日计划的后端动作 (计划 §Phase 3 活动中断)。attack 对行动者和目标都中断。
export const INTERRUPT_TYPES = new Set(["attack", "flee", "help", "hide", "counterattack"]);

// 某角色在本步是否被中断 (执行了中断动作, 或被攻击)。talk/move/wait/conversation 不打断。
export function isInterrupted(name: string, events: { type: string; actor?: string; target?: string }[]): boolean {
  for (const ve of events) {
    if (!INTERRUPT_TYPES.has(ve.type)) continue;
    if (ve.type === "attack") {
      // 攻击: 行动者(进入战斗)与目标(被攻击)都中断
      if (ve.actor === name || ve.target === name) return true;
    } else if (ve.actor === name) {
      return true;   // flee/help/hide/counterattack: 执行者中断
    }
  }
  return false;
}

// 某角色在某地点的默认活动 (无则 null → 站桩 idle)。
export function defaultActivity(name: string, loc: string): ActivityDef | null {
  return ACTIVITY_MAP[name]?.[loc] ?? null;
}
