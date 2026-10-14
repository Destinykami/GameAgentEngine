import type { VisualEvent } from "./schema";

// 旧回放兼容层 (计划 M5「验证旧回放不回归」)。
// 引擎早期产出的 timeline 只有中文 `events` 串 (无结构化 visual_events / 无 schema_version)。
// 本模块把中文串解析成 VisualEvent[], 供加载器归一化后填进 step.visual_events,
// 使前端 (气泡/伤害/死亡/移动/世界事件/活动中断) 无改动地回放旧样本。
// 注意: 这是**兼容回退**, 不是主路径——新 timeline 直接用结构化 visual_events (计划 M3 已替换)。
//
// 覆盖的中文串格式 (对齐引擎 VisualEvent.describe()):
//   世界事件: <desc>                          → world_event
//   <actor> 移动到 <loc>                      → move
//   <actor> 帮助 <target> [效果]              → help
//   <actor> 观望                              → wait
//   <actor> 攻击 <target>, 造成 N 伤害        → attack (→ <target> 阵亡! 时 target_dead)
//   <actor> 逃离威胁, 逃到 <loc>              → flee
//   <actor> 替 <target> 藏匿                  → hide
//   <actor> 对 <target> 说: <utterance>       → conversation
//     (… ← <speaker>: <reply> [效果])         → + reply / reply_speaker / 系统效果
// 系统效果 (方括号, 独立字段不进气泡): [现N条]/[攻升至N]/[目击…现N条]

export function parseLegacyEvents(step: { events?: string[]; clock: number }): VisualEvent[] {
  const out: VisualEvent[] = [];
  for (const raw of step.events ?? []) {
    const ve = parseOne(raw, step.clock);
    if (ve) out.push(ve);
  }
  return out;
}

function parseOne(raw: string, clock: number): VisualEvent | null {
  let s = raw.trim();

  // 先抽取尾部方括号系统效果 (可多个), 与事件类型无关
  let reason_added: string | undefined;
  let reason_count: number | undefined;
  let weapon_attack: number | undefined;
  let witnessed: boolean | undefined;
  let m: RegExpMatchArray | null;
  while ((m = s.match(/\s*\[([^\]]+)\]\s*$/))) {
    const inner = m[1];
    s = s.slice(0, m.index).trim();
    if (inner.includes("积累理由")) {
      reason_added = inner;
      const c = inner.match(/现(\d+)条/);
      if (c) reason_count = Number(c[1]);
    } else if (inner.includes("锻好武器")) {
      const c = inner.match(/攻升至(\d+)/);
      if (c) weapon_attack = Number(c[1]);
    } else if (inner.includes("目击")) {
      witnessed = true;
      const c = inner.match(/现(\d+)条/);
      if (c) reason_count = Number(c[1]);
    }
  }
  s = s.trim();
  const effect = (): Partial<VisualEvent> => {
    const e: Partial<VisualEvent> = {};
    if (reason_added) e.reason_added = reason_added;
    if (reason_count != null) e.reason_count = reason_count;
    if (weapon_attack != null) e.weapon_attack = weapon_attack;
    if (witnessed) e.witnessed = witnessed;
    return e;
  };

  // 世界事件
  if (s.startsWith("世界事件")) {
    const desc = s.replace(/^世界事件[:：]\s*/, "");
    return { type: "world_event", actor: "世界", clock, description: desc };
  }

  // actor = 首个空格前的 token
  const sp = s.indexOf(" ");
  if (sp < 0) return null;
  const actor = s.slice(0, sp).trim();
  const rest = s.slice(sp).trim();

  if (rest.startsWith("移动到")) {
    const to = rest.slice("移动到".length).trim();
    return { type: "move", actor, clock, to };
  }
  if (rest.startsWith("帮助")) {
    const target = rest.slice("帮助".length).trim();
    return { type: "help", actor, clock, target, ...effect() };
  }
  if (rest.startsWith("观望")) {
    return { type: "wait", actor, clock };
  }
  if (rest.startsWith("逃离威胁")) {
    const c = rest.match(/逃到\s*(\S+)/);
    return { type: "flee", actor, clock, to: c ? c[1] : undefined };
  }
  if (rest.startsWith("替")) {
    const c = rest.match(/^替\s*(\S+?)\s*藏匿/);
    return { type: "hide", actor, clock, target: c ? c[1] : undefined };
  }
  if (rest.startsWith("攻击")) {
    const c = rest.match(/^攻击\s*(\S+?),\s*造成\s*(\d+)\s*伤害/);
    if (!c) return null;
    const target_dead = /阵亡/.test(rest);
    return {
      type: "attack", actor, clock, target: c[1], damage: Number(c[2]),
      target_dead: target_dead || undefined,
    };
  }
  if (rest.startsWith("对")) {
    const m2 = rest.match(/^对\s*(\S+?)\s*说[:：]\s*([\s\S]*)$/);
    if (!m2) return null;
    const target = m2[1];
    let body = m2[2].trim();
    let utterance = body;
    let reply: string | undefined;
    let reply_speaker: string | undefined;
    const arrow = body.lastIndexOf("←");
    if (arrow >= 0) {
      utterance = body.slice(0, arrow).trim();
      const after = body.slice(arrow + 1).trim();
      const rc = after.match(/^(\S+?)[:：]\s*([\s\S]*)$/);
      if (rc) { reply_speaker = rc[1]; reply = rc[2].trim(); }
      else { reply = after; }
    }
    const ve: VisualEvent = { type: "conversation", actor, clock, target, utterance };
    if (reply != null) ve.reply = reply;
    if (reply_speaker) ve.reply_speaker = reply_speaker;
    Object.assign(ve, effect());
    return ve;
  }
  // 兜底: 无法识别的动作按观望处理 (不丢事件)
  return { type: "wait", actor, clock };
}
