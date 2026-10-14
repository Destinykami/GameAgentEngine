import Phaser from "phaser";
import { wrapText } from "../text/wrapText";
import type { Timeline, TimelineStep } from "../data/schema";

// StatusPanel (计划 §5.2): 血量 / 死亡 / 位置 / 旅行者理由与攻 / 劝说进度。
// 右侧面板, 每步重绘实体行。每实体一行: 名字 + 血量条 (按血量比例变色) + 地点。
// 死亡显示 ✝。旅行者额外显示理由数与攻。稻妻风格: 深底 + 金色题头线。
// 此环境 wordWrap 失效: 标题收窄 (去冗余时钟), meta 收窄字号, 页脚手动换行 + 按高截断, 防溢出。
const MAX_HEALTH = 300;   // 满血参考 (雷电将军), 血量条按比例
const FOOT_FONT = "12px monospace";
const FOOT_LINE_H = 15;   // 页脚行高 (12px 字 + 3 lineSpacing)

interface Row {
  name: Phaser.GameObjects.Text;
  barBg: Phaser.GameObjects.Rectangle;
  barFill: Phaser.GameObjects.Rectangle;
  meta: Phaser.GameObjects.Text;
  dead: Phaser.GameObjects.Text;
}

export class StatusPanel {
  private scene: Phaser.Scene;
  private x: number; private y: number; private w: number; private h: number;
  private header!: Phaser.GameObjects.Text;
  private footer!: Phaser.GameObjects.Text;
  private footerMaxLines: number;   // 页脚容得下的行数 (超出截断, 防竖向溢出)
  private rows: Row[] = [];

  constructor(scene: Phaser.Scene, x: number, y: number, w: number, h: number) {
    this.scene = scene; this.x = x; this.y = y; this.w = w; this.h = h;
    // 面板底色 + 金色题头线 (稻妻风格)
    scene.add.rectangle(x, y, w, h, 0x1c1c24).setStrokeStyle(1, 0x3a3a48).setAlpha(0.95).setDepth(1000);
    scene.add.rectangle(x, y - h / 2 + 2, w - 2, 2, 0xd9a441).setDepth(1001);
    this.header = scene.add.text(x - w / 2 + 10, y - h / 2 + 8, "", {
      fontFamily: "monospace", fontSize: "13px", color: "#d9a441", fontStyle: "bold",
    }).setDepth(1001);
    // 页脚: 放在实体行下方, 预留多行高度 (换行后的长结局说明), 按高截断防溢出。
    const rowTop = y - h / 2 + 32;
    const rowH = 22;
    const footerY = rowTop + 8 * rowH + 8;   // 8 行之后留 8px 间隙
    this.footerMaxLines = Math.max(1, Math.floor((y + h / 2 - footerY - 4) / FOOT_LINE_H));
    this.footer = scene.add.text(x - w / 2 + 10, footerY, "", {
      fontFamily: "monospace", fontSize: "12px", color: "#cfc6b8", lineSpacing: 3,
    }).setDepth(1001);
    this.buildRows();
  }

  private buildRows(): void {
    const left = this.x - this.w / 2 + 10;
    const top = this.y - this.h / 2 + 32;
    const rowH = 22;
    // 最多 6 实体 + 余量
    for (let i = 0; i < 8; i++) {
      const ry = top + i * rowH;
      const name = this.scene.add.text(left, ry, "", {
        fontFamily: "monospace", fontSize: "12px", color: "#e8e6e3",
      }).setOrigin(0, 0.5).setDepth(1001);
      const barBg = this.scene.add.rectangle(left + 62, ry, 60, 6, 0x2a2a34).setOrigin(0, 0.5).setDepth(1001);
      const barFill = this.scene.add.rectangle(left + 62, ry, 60, 6, 0x7ec67e).setOrigin(0, 0.5).setDepth(1002);
      const dead = this.scene.add.text(left + 128, ry, "✝", {
        fontFamily: "monospace", fontSize: "12px", color: "#ff6655",
      }).setOrigin(0, 0.5).setDepth(1001).setVisible(false);
      // meta 用 10px (11px 时 "血120 @稻妻主城" 会顶出面板右内边), 名字+血+地点收在框内。
      const meta = this.scene.add.text(left + 128, ry, "", {
        fontFamily: "monospace", fontSize: "10px", color: "#9a9aa2",
      }).setOrigin(0, 0.5).setDepth(1001);
      this.rows.push({ name, barBg, barFill, meta, dead });
    }
  }

  private hpColor(ratio: number): number {
    if (ratio > 0.5) return 0x7ec67e;      // 绿
    if (ratio > 0.25) return 0xd9a441;     // 黄
    return 0xe05a4a;                       // 红
  }

  update(step: TimelineStep, tl: Timeline): void {
    const hh = String(Math.floor(step.moment)).padStart(2, "0");
    // 标题不收 (19.0h) —— 与 HH:00 重复, 去掉后收窄到面板内。
    this.header.setText(`稻妻城 · 第 ${step.day} 天 ${hh}:00`);
    const entries = Object.entries(step.states);
    for (let i = 0; i < this.rows.length; i++) {
      const row = this.rows[i];
      const [name, s] = entries[i] ?? [null, null];
      if (!name || !s) {
        row.name.setText(""); row.meta.setText(""); row.dead.setVisible(false);
        row.barFill.setSize(0, 6);
        continue;
      }
      row.name.setText(name).setColor(s.dead ? "#ff6655" : "#e8e6e3");
      if (s.dead) {
        row.barFill.setSize(0, 6);
        row.dead.setVisible(true);
        row.meta.setText("@ " + s.loc).setVisible(true);
      } else {
        const ratio = Math.max(0, Math.min(1, s.health / MAX_HEALTH));
        row.barFill.setSize(60 * ratio, 6).setFillStyle(this.hpColor(ratio));
        row.dead.setVisible(false);
        row.meta.setText(`血${s.health} @${s.loc}`).setVisible(true);
      }
    }
    // 页脚: 旅行者双关进度 (理由/攻) + 劝说进度 + 结局。手动换行 (wordWrap 失效) +
    // 按页脚高度截断, 长结局说明不再顶出框。
    const player = step.states["旅行者"];
    const lines: string[] = [];
    if (player && !player.dead) lines.push(`理由${player.reasons.length}/${tl.reason_needed} 攻${player.attack}/${tl.attack_needed} 劝说${step.persuade}/${tl.persuade_n}`);
    else lines.push(`劝说 ${step.persuade}/${tl.persuade_n}`);
    if (step.shogun_dead) lines[0] += " · 将军阵亡";
    if (step.decree_ended) lines.push("★ 眼狩令已废止");
    if (step.note) lines.push("★ " + step.note);
    const wrapped = wrapText(lines.join("\n"), this.w - 20, FOOT_FONT).split("\n");
    const shown = wrapped.length > this.footerMaxLines ? wrapped.slice(0, this.footerMaxLines) : wrapped;
    this.footer.setText(shown.join("\n"));
  }
}
