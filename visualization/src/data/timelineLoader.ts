import type { Timeline, TimelineStep } from "./schema";
import { parseLegacyEvents } from "./legacyEvents";

// 职责 (计划 §5.2): 读取 JSON / 校验版本与必需字段 / 规范化 / 提供 step 游标。
// 不负责绘制。失败抛出带原因的 Error, 由 BootScene 捕获并显示。
//
// 旧回放兼容 (计划 M5): 引擎早期 timeline 只有中文 events 串 (无 visual_events /
// schema_version / world)。loadTimeline 先归一化 (回退解析中文串填 visual_events +
// 合成 world), 再走统一校验, 使旧样本可回放且不回归。新 timeline 直接用结构化事件。

// 旧格式判定: 有 steps 且每个 step 都无 visual_events 数组。
export function isLegacyTimeline(tl: unknown): boolean {
  if (!tl || typeof tl !== "object") return false;
  const o = tl as Record<string, unknown>;
  if (!Array.isArray(o.steps) || (o.steps as unknown[]).length === 0) return false;
  return (o.steps as Record<string, unknown>[]).every((s) => !Array.isArray(s.visual_events));
}

// 归一化: 旧格式补 visual_events (回退解析中文串) + 合成 world + 设 schema_version。
// 新格式原样返回。
export function normalizeTimeline(tl: unknown): Timeline {
  if (!isLegacyTimeline(tl)) return tl as Timeline;
  const o = tl as Record<string, unknown>;
  const steps = o.steps as Record<string, unknown>[];
  return {
    schema_version: 1,
    world: { name: "稻妻城", coordinate_system: "top_down_2d", render_map: "inazuma_town" },
    reason_needed: (o.reason_needed as number) ?? 3,
    attack_needed: (o.attack_needed as number) ?? 20,
    persuade_n: (o.persuade_n as number) ?? 3,
    steps: steps.map((s) => ({
      ...s,
      visual_events: parseLegacyEvents(s as unknown as { events?: string[]; clock: number }),
    })),
  } as Timeline;
}

export function validateTimeline(tl: unknown): asserts tl is Timeline {
  if (!tl || typeof tl !== "object") throw new Error("timeline 不是对象");
  const o = tl as Record<string, unknown>;
  if (typeof o.schema_version !== "number") throw new Error("缺 schema_version");
  if (o.schema_version !== 1) throw new Error(`不支持的 schema_version: ${o.schema_version}`);
  if (!o.world || typeof o.world !== "object") throw new Error("缺 world");
  if (!Array.isArray(o.steps)) throw new Error("缺 steps 数组");
  for (let i = 0; i < (o.steps as unknown[]).length; i++) {
    const s = (o.steps as Record<string, unknown>[])[i];
    if (typeof s.clock !== "number") throw new Error(`step[${i}] 缺 clock`);
    if (!s.states || typeof s.states !== "object") throw new Error(`step[${i}] 缺 states`);
    if (!Array.isArray(s.visual_events))
      throw new Error(`step[${i}] 缺 visual_events (结构化事件, 不解析中文 events 串)`);
    if (i > 0) {
      const prev = (o.steps as Record<string, unknown>[])[i - 1];
      if (s.clock < (prev.clock as number))
        throw new Error(`step[${i}] clock 回退 (${prev.clock} → ${s.clock})`);
    }
  }
}

export async function loadTimeline(url: string): Promise<Timeline> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`加载 timeline 失败: ${res.status} ${res.statusText} (${url})`);
  const raw = await res.json();
  const tl = normalizeTimeline(raw);   // 旧格式归一化 (回退解析中文串), 新格式原样
  validateTimeline(tl);
  return tl;
}

// step 游标: 当前步 / 总步数 / 边界。供播放控制器与 UI 使用。
export function stepAt(tl: Timeline, index: number): TimelineStep {
  const i = Math.max(0, Math.min(tl.steps.length - 1, index));
  return tl.steps[i];
}
