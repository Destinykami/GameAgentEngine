import type { TimelineStep } from "./schema";

// 直播数据源 (计划 M5 扩展: 运行中实时可视化)。
// 引擎 (world_auto_sim.py) 每跑完一步就 append 一行 JSON 到 live.jsonl:
//   首行 meta: {"__meta__":true, schema_version, world, reason_needed, attack_needed, persuade_n}
//   每步:      一个 TimelineStep 对象 (与 timeline.json 的 steps 同形)
//   末行 done: {"__done__":true, decree_ended, shogun_dead}
// 本类轮询该文件, 只返回**新增**的行 (跟踪已摄入行号), 处理"写入中途抓到半行"
// (末尾无换行 → 丢弃末行, 下轮重试)。前端 ?live 模式用它逐步接入并自动跟随。

export interface LiveMeta {
  schema_version?: number;
  world?: { name: string; coordinate_system: string; render_map: string };
  // B+ 涌现: 无门控, 这三个门槛为 null (旧时间线为数字)。
  reason_needed?: number | null;
  attack_needed?: number | null;
  persuade_n?: number | null;
}

export interface LivePollResult {
  meta: LiveMeta | null;      // 首次见到 meta 行时返回 (之后一直持有)
  newSteps: TimelineStep[];   // 本轮新增的 step (已按行顺序)
  done: boolean;              // 见到 __done__ 行
}

export class LiveSource {
  private url: string;
  private ingested = 0;       // 已摄入的行数 (只处理其后的新行)
  private meta: LiveMeta | null = null;
  private doneSeen = false;
  private steps: TimelineStep[] = [];      // 累计摄入的所有 step (供首次 setup 建完整时间线)

  constructor(url = "live.jsonl") { this.url = url; }

  get stepCount(): number { return this.steps.length; }
  get allSteps(): readonly TimelineStep[] { return this.steps; }
  get done(): boolean { return this.doneSeen; }

  async poll(): Promise<LivePollResult> {
    const result: LivePollResult = { meta: this.meta, newSteps: [], done: this.doneSeen };
    let text = "";
    try {
      const res = await fetch(this.url + "?t=" + Date.now(), { cache: "no-store" });
      if (!res.ok) return result;   // 文件还没生成 (模拟未启动), 下轮再试
      text = await res.text();
    } catch { return result; }      // 网络/404, 下轮再试

    // 只处理完整行: 末尾无换行 → 末行是写了一半的半行, 丢弃 (下轮重试)。
    let lines = text.split("\n");
    if (!text.endsWith("\n") && lines.length > 0) lines = lines.slice(0, -1);
    lines = lines.filter((l) => l.trim().length > 0);

    for (let i = this.ingested; i < lines.length; i++) {
      let obj: Record<string, unknown>;
      try { obj = JSON.parse(lines[i]); } catch { break; }   // 半行/坏行, 停在本轮, 下轮重试
      if (obj.__meta__) {
        this.meta = obj as unknown as LiveMeta;
        result.meta = this.meta;
      } else if (obj.__done__) {
        this.doneSeen = true;
        result.done = true;
      } else {
        const st = obj as unknown as TimelineStep;
        result.newSteps.push(st);
        this.steps.push(st);
      }
    }
    this.ingested = lines.length;
    return result;
  }
}
