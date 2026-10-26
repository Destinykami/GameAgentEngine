// 狼人杀公共时间线契约；私密身份/事件不在公共文件里。

export interface WerewolfEvent {
  id: string;
  type: string;
  channel?: string;
  content: string;
  actor?: string;
  text?: string;
  votes?: Record<string, string | null>;
  target?: string | null;
  winner?: string;
  recipients?: string[];
  participants?: string[];
  evidence_kind?: string;
}

export interface WerewolfStep {
  step: number;
  round: number;
  phase: string;
  version: number;
  alive: string[];
  events: WerewolfEvent[];
  votes: Record<string, string | null>;
  winner: string | null;
}

export interface WerewolfTimeline {
  schema_version: number;
  game: "werewolf";
  instance_id: string;
  seats: string[];
  max_rounds: number;
  persona_seed?: number;
  steps: WerewolfStep[];
}

export interface WerewolfGod {
  roles: Record<string, string>;
  personas?: Record<string, { social: number; goal_oriented: number }>;
  steps: WerewolfStep[];
}

export const PRIVATE_EVENT_TYPES = new Set([
  "role_assignment", "inspection_result", "wolf_result", "wolf_chat",
  "witch_result",
]);

export function phaseLabel(step: WerewolfStep): string {
  if (step.phase === "finished") return "对局结束";
  if (step.phase === "wolf_talk") return `第 ${step.round} 夜 · 狼人密谈`;
  if (step.phase === "wolf_vote") return `第 ${step.round} 夜 · 狼人投票`;
  if (step.phase === "seer") return "预言家查验";
  if (step.phase === "witch") return "女巫用药";
  if (step.phase === "hunter") return "猎人开枪";
  if (step.phase === "vote") return `第 ${step.round} 轮 · 投票`;
  if (step.phase === "speech") return `第 ${step.round} 轮 · 发言`;
  return step.phase;
}

export function completeLines(text: string): string[] {
  const lines = text.split("\n");
  if (!text.endsWith("\n")) {
    lines.pop(); // 最后一行尚未写完
  } else if (lines[lines.length - 1] === "") {
    lines.pop(); // split 产生的尾部空串不是记录
  }
  return lines;
}

export function votesText(votes: Record<string, string | null>): string {
  const parts = Object.entries(votes).map(([actor, target]) =>
    `${actor} → ${target ?? "弃票"}`);
  return parts.length ? parts.join("；") : "本步暂无票型";
}

export function parseTimeline(raw: unknown): WerewolfTimeline {
  if (!raw || typeof raw !== "object") throw new Error("时间线不是对象");
  const value = raw as Record<string, unknown>;
  if (value.schema_version !== 1 || value.game !== "werewolf") {
    throw new Error("不是 schema_version=1 的狼人杀时间线");
  }
  if (!Array.isArray(value.seats) || !value.seats.every((s) => typeof s === "string")) {
    throw new Error("seats 非法");
  }
  if (!Array.isArray(value.steps) || value.steps.length === 0) {
    throw new Error("steps 为空");
  }
  for (const rawStep of value.steps) {
    if (!rawStep || typeof rawStep !== "object") throw new Error("step 非法");
    const step = rawStep as Record<string, unknown>;
    if (typeof step.step !== "number" || typeof step.round !== "number" ||
        typeof step.phase !== "string" || !Array.isArray(step.alive) ||
        !Array.isArray(step.events)) {
      throw new Error("step 字段不完整");
    }
  }
  return value as unknown as WerewolfTimeline;
}

export async function loadTimeline(url: string): Promise<WerewolfTimeline> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`加载 ${url} 失败：HTTP ${response.status}`);
  return parseTimeline(await response.json());
}

export async function loadGod(url: string): Promise<WerewolfGod> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`上帝视角不可用：HTTP ${response.status}`);
  const value = await response.json() as Record<string, unknown>;
  if (!value.roles || typeof value.roles !== "object" || !Array.isArray(value.steps)) {
    throw new Error("上帝视角文件格式错误");
  }
  return value as unknown as WerewolfGod;
}

export function publicEvents(steps: WerewolfStep[], index: number): WerewolfEvent[] {
  const events: WerewolfEvent[] = [];
  for (const step of steps.slice(0, index + 1)) {
    events.push(...step.events.filter((event) => event.channel === "public" || !event.channel));
  }
  return events;
}

export function privateEvents(step: WerewolfStep): WerewolfEvent[] {
  return step.events.filter((event) => event.channel !== "public");
}
