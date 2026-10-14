import Phaser from "phaser";
import { wrapText } from "../text/wrapText";
import type { VisualEvent } from "../data/schema";

// EventLog (计划 §5.2): 显示当前步的事件。M1 从结构化 visual_events 渲染成可读行,
// 不再解析中文 events 串 (计划 §9.2: 不从中文字符串长期解析语义)。
// 系统效果 (理由/锻刀/目击) 作为独立提示行, 不混进对话正文。
// 此环境 wordWrap 失效: 手动换行 (超宽插 \n) + 按框高截断 (放不下只显示前 N 行), 防溢出。

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

const FONT = "12px monospace";
const LINE_H = 15;   // 行高 (12px 字 + 3 lineSpacing)

export class EventLog {
  private text: Phaser.GameObjects.Text;
  private maxW: number;      // 内容区可换行宽度
  private maxLines: number;  // 框高容得下的行数 (超出截断)

  constructor(scene: Phaser.Scene, x: number, y: number, w: number, h: number) {
    scene.add.rectangle(x, y, w, h, 0x1c1c24).setStrokeStyle(1, 0x3a3a48).setAlpha(0.95).setDepth(1000);
    scene.add.rectangle(x, y - h / 2 + 2, w - 2, 2, 0xd9a441).setDepth(1001);
    scene.add.text(x - w / 2 + 10, y - h / 2 + 7, "事件记录", {
      fontFamily: "monospace", fontSize: "12px", color: "#d9a441", fontStyle: "bold",
    }).setDepth(1001);
    this.maxW = w - 20;
    this.maxLines = Math.max(1, Math.floor((h - 32) / LINE_H));   // 去掉标题/上下留白后能放几行
    this.text = scene.add.text(x - w / 2 + 10, y - h / 2 + 26, "", {
      fontFamily: "monospace", fontSize: "12px", color: "#d8d4cc",
      lineSpacing: 3,
    }).setDepth(1001);
  }

  update(visualEvents: VisualEvent[]): void {
    const lines: string[] = [];
    for (const ve of visualEvents) {
      lines.push(describeVisualEvent(ve));
      for (const eff of systemEffects(ve)) lines.push(eff);
    }
    const content = lines.length ? lines.join("\n") : "(本步无动作)";
    // 手动换行 (此环境 wordWrap 失效) → 按框高截断 (放不下只显示前 maxLines 行, 防竖向溢出)。
    const wrapped = wrapText(content, this.maxW, FONT).split("\n");
    const shown = wrapped.length > this.maxLines ? wrapped.slice(0, this.maxLines) : wrapped;
    this.text.setText(shown.join("\n"));
  }
}
