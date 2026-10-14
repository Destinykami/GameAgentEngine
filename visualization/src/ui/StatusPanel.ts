import type { Timeline, TimelineStep } from "../data/schema";

// StatusPanel (计划 §5.2): 血量 / 死亡 / 位置 / 旅行者理由与攻 / 劝说进度。
// 右侧面板, 每步重绘实体行。死亡显示 ✝。旅行者额外显示理由数与攻 (双关进度)。
export class StatusPanel {
  private header: Phaser.GameObjects.Text;
  private rows: Phaser.GameObjects.Text;

  constructor(scene: Phaser.Scene, x: number, y: number, w: number, h: number) {
    // 面板底色
    scene.add.rectangle(x, y, w, h, 0x232329).setStrokeStyle(1, 0x333340).setAlpha(0.92).setDepth(1000);
    this.header = scene.add.text(x - w / 2 + 10, y - h / 2 + 8, "", {
      fontFamily: "monospace", fontSize: "13px", color: "#b08d57",
    }).setDepth(1001);
    this.rows = scene.add.text(x - w / 2 + 10, y - h / 2 + 30, "", {
      fontFamily: "monospace", fontSize: "12px", color: "#e8e6e3", lineSpacing: 4,
      wordWrap: { width: w - 20 },
    }).setDepth(1001);
  }

  update(step: TimelineStep, tl: Timeline): void {
    const day = step.day;
    const hh = String(Math.floor(step.moment)).padStart(2, "0");
    this.header.setText(`第 ${day} 天 ${hh}:00  ·  ${step.clock.toFixed(1)}h`);
    const lines: string[] = [];
    for (const [name, s] of Object.entries(step.states)) {
      if (s.dead) {
        lines.push(`${name.padEnd(6, "　")} ✝ 阵亡`);
        continue;
      }
      let line = `${name.padEnd(6, "　")} 血${String(s.health).padStart(3)} @${s.loc}`;
      if (s.kind === "player") {
        line += `  理由${s.reasons.length}/${tl.reason_needed} 攻${s.attack}/${tl.attack_needed}`;
      }
      lines.push(line);
    }
    // 劝说 / 结局进度
    lines.push("");
    lines.push(`劝说 ${step.persuade}/${tl.persuade_n}${step.shogun_dead ? "  ·  将军阵亡" : ""}`);
    if (step.decree_ended) lines.push("★ 眼狩令已废止");
    if (step.note) lines.push("★ " + step.note);
    this.rows.setText(lines.join("\n"));
  }
}
