import type { VisualEvent } from "../data/schema";

// EventLog (计划 §5.2): 显示当前步的事件。M1 从结构化 visual_events 渲染成可读行,
// 不再解析中文 events 串 (计划 §9.2: 不从中文字符串长期解析语义)。
// 系统效果 (理由/锻刀/目击) 作为独立提示行, 不混进对话正文。

export function describeVisualEvent(ve: VisualEvent): string {
  const a = ve.actor;
  switch (ve.type) {
    case "move":
      return ve.success === false ? `${a} 想移动到 ${ve.to}, 未动` : `${a} → ${ve.to}`;
    case "flee":
      return ve.success === false ? `${a} 想逃但无威胁` : `${a} 逃离威胁 → ${ve.to}`;
    case "conversation": {
      if (ve.success === false) return `${a} 想对 ${ve.target} 说话 (中止: ${ve.failure_reason})`;
      let line = `${a} 对 ${ve.target}: “${ve.utterance ?? ""}”`;
      if (ve.reply) line += `\n  ${ve.reply_speaker ?? ve.target}: “${ve.reply}”`;
      return line;
    }
    case "attack": {
      if (ve.success === false) return `${a} 想攻击 ${ve.target} (中止: ${ve.failure_reason})`;
      let line = `${a} 攻击 ${ve.target}, 造成 ${ve.damage} 伤害`;
      if (ve.target_dead) line += ` → ${ve.target} 阵亡!`;
      return line;
    }
    case "help":
      return `${a} 帮助 ${ve.target}`;
    case "hide":
      return `${a} 替 ${ve.target} 藏匿`;
    case "world_event":
      return `★ 世界事件: ${ve.description ?? ""}`;
    case "wait":
    default:
      return `${a} 观望`;
  }
}

// 系统效果行 (理由/锻刀/目击) —— 独立渲染, 不进气泡正文 (计划 §9.5)。
export function systemEffects(ve: VisualEvent): string[] {
  const out: string[] = [];
  if (ve.reason_added) out.push(`  · 旅行者积累理由 (现 ${ve.reason_count} 条)`);
  if (ve.weapon_attack) out.push(`  · 刚郎锻好武器, 攻升至 ${ve.weapon_attack}`);
  if (ve.witnessed) out.push(`  · 旅行者目击搜捕, 积累理由 (现 ${ve.reason_count} 条)`);
  return out;
}

export class EventLog {
  private text: Phaser.GameObjects.Text;

  constructor(scene: Phaser.Scene, x: number, y: number, w: number, h: number) {
    scene.add.rectangle(x, y, w, h, 0x1c1c24).setStrokeStyle(1, 0x3a3a48).setAlpha(0.95).setDepth(1000);
    scene.add.rectangle(x, y - h / 2 + 2, w - 2, 2, 0xd9a441).setDepth(1001);
    scene.add.text(x - w / 2 + 10, y - h / 2 + 7, "事件记录", {
      fontFamily: "monospace", fontSize: "12px", color: "#d9a441", fontStyle: "bold",
    }).setDepth(1001);
    this.text = scene.add.text(x - w / 2 + 10, y - h / 2 + 26, "", {
      fontFamily: "monospace", fontSize: "12px", color: "#d8d4cc",
      lineSpacing: 3, wordWrap: { width: w - 20 },
    }).setDepth(1001);
  }

  update(visualEvents: VisualEvent[]): void {
    const lines: string[] = [];
    for (const ve of visualEvents) {
      lines.push(describeVisualEvent(ve));
      for (const eff of systemEffects(ve)) lines.push(eff);
    }
    this.text.setText(lines.length ? lines.join("\n") : "(本步无动作)");
  }
}
