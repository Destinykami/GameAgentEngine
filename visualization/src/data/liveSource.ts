import type { TimelineStep } from "./schema";
import { validateTimeline } from "./timelineLoader";

// 直播数据源 (计划 M5 扩展: 运行中实时可视化)。
// 引擎 (world_auto_sim.py) 每跑完一步就 append 一行 JSON 到 live.jsonl:
//   首行 meta: {"__meta__":true, schema_version, world, reason_needed, attack_needed, persuade_n}
//   每步:      一个 TimelineStep 对象 (与 timeline.json 的 steps 同形)
//   末行 done: {"__done__":true, decree_ended, shogun_dead}
// 本类轮询该文件, 只返回**新增**的行 (跟踪已摄入行号), 处理"写入中途抓到半行"
// (末尾无换行 → 丢弃末行, 下轮重试)。前端 ?live 模式用它逐步接入并自动跟随。

export interface LiveMeta {
  run_id?: string;
  schema_version?: number;
  world?: { name: string; coordinate_system: string; render_map: string };
  // B+ 涌现: 无门控, 这三个门槛为 null (旧时间线为数字)。
  reason_needed?: number | null;
  attack_needed?: number | null;
  persuade_n?: number | null;
}

export interface LiveIssue {
  kind: "parse" | "network" | "replaced";
  message: string;
}

export interface LivePollResult {
  meta: LiveMeta | null;
  newSteps: TimelineStep[];
  done: boolean;
  error: LiveIssue | null;
}

export class LiveSource {
  private consumed: string[] = [];
  private meta: LiveMeta | null = null;
  private doneSeen = false;
  private steps: TimelineStep[] = [];
  private polling = false;
  private replacement: LiveIssue | null = null;

  constructor(private url = "live.jsonl") {}

  get stepCount(): number { return this.steps.length; }
  get allSteps(): readonly TimelineStep[] { return this.steps; }
  get done(): boolean { return this.doneSeen; }

  async poll(): Promise<LivePollResult> {
    const result: LivePollResult = {
      meta: this.meta, newSteps: [], done: this.doneSeen, error: this.replacement,
    };
    if (this.polling || this.replacement) return result;
    this.polling = true;
    try {
      let text: string;
      try {
        const res = await fetch(this.url + "?t=" + Date.now(), { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        text = await res.text();
      } catch {
        result.error = { kind: "network", message: "直播数据暂不可用，正在重试…" };
        return result;
      }
      // 不消费尾部半行；完整坏行也留在原位置等待修复。
      let lines = text.split("\n");
      if (!text.endsWith("\n")) lines = lines.slice(0, -1);
      lines = lines.filter(line => line.trim().length > 0);
      if (lines.length < this.consumed.length || this.consumed.some((line, i) => line !== lines[i])) {
        this.replacement = { kind: "replaced", message: "直播文件已更换或重置，请重新加载页面。" };
        result.error = this.replacement;
        return result;
      }
      for (let i = this.consumed.length; i < lines.length; i++) {
        let obj: Record<string, unknown>;
        try {
          obj = JSON.parse(lines[i]);
          if (!obj || typeof obj !== "object" || Array.isArray(obj)) throw new Error("invalid record");
          if (!obj.__meta__ && !obj.__done__) {
            const previous = this.steps[this.steps.length - 1];
            validateTimeline({ schema_version: 1, world: {}, steps: previous ? [previous, obj] : [obj] });
            if (!Number.isFinite(obj.clock)) throw new Error("invalid clock");
          }
        } catch {
          result.error = { kind: "parse", message: `直播第 ${i + 1} 行损坏，等待数据修复…` };
          break;
        }
        if (obj.__meta__) {
          this.meta = obj as unknown as LiveMeta;
          result.meta = this.meta;
        } else if (obj.__done__) {
          this.doneSeen = true;
          result.done = true;
        } else {
          const step = obj as unknown as TimelineStep;
          this.steps.push(step);
          result.newSteps.push(step);
        }
        this.consumed.push(lines[i]);
      }
      return result;
    } finally {
      this.polling = false;
    }
  }
}
