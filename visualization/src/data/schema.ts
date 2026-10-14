// timeline 数据契约 (对齐 VisualizationPlan §6 与引擎 VisualEvent.to_dict)。
// visual_events 是结构化事实源; events 是派生的中文串 (仅兼容/日志)。

export interface WorldMeta {
  name: string;
  coordinate_system: string;
  render_map: string;
}

export interface AgentSnapshot {
  health: number;
  loc: string;
  dead: boolean;
  reasons: string[];
  attack: number;
  role: string;
  kind: string;
}

export type VisualEventType =
  | "move"
  | "conversation"
  | "attack"
  | "help"
  | "hide"
  | "flee"
  | "wait"
  | "world_event";

export interface VisualEvent {
  type: VisualEventType;
  actor: string;
  clock: number;
  location?: string;
  target?: string;
  to?: string;
  // conversation
  utterance?: string;
  reply?: string;
  reply_speaker?: string;
  // attack
  damage?: number;
  target_dead?: boolean;
  // 通用
  success?: boolean;
  failure_reason?: string;
  // 系统效果 (独立字段, 不塞进台词)
  reason_added?: string;
  reason_count?: number;
  weapon_attack?: number;
  witnessed?: boolean;
  // world_event
  description?: string;
}

export interface TimelineStep {
  step_id?: string;
  day: number;
  moment: number;
  clock: number;
  events: string[];
  visual_events: VisualEvent[];
  activities?: unknown[];
  states: Record<string, AgentSnapshot>;
  note?: string;
  persuade: number;
  decree_ended: boolean;
  shogun_dead: boolean;
}

export interface Timeline {
  schema_version: number;
  world: WorldMeta;
  reason_needed: number;
  attack_needed: number;
  persuade_n: number;
  steps: TimelineStep[];
}
