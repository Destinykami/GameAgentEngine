import Phaser from "phaser";
import { wrapText } from "../text/wrapText";
import type { AgentSnapshot } from "../data/schema";

// DetailCard: 点击实体弹出的详情卡 (只读)。
// 显示 name / role / 血量 / 攻击 / 地点 / 生死, 旅行者额外显示已收集的证据理由。
// 锚定固定屏幕位置 (避开右上状态面板与左下事件日志), 点空白处或关闭按钮隐藏。
const W = 252;
const X = 300;
const Y = 235;
const MAX_REASONS = 4;
const REASON_WRAP = 224;
// 布局行高/行距: 此环境 t.height 低估实际渲染行高 (~19px), 用 21px 固定行高 + 6px 行距,
// 保证折行后的多行理由不重叠 (12-13px 字号都够)。
const LINE_H = 21;
const ROW_GAP = 6;

export class DetailCard {
  private scene: Phaser.Scene;
  private root: Phaser.GameObjects.Container;
  private bg!: Phaser.GameObjects.Rectangle;
  private rows: Phaser.GameObjects.Text[] = [];
  private nameText!: Phaser.GameObjects.Text;
  private open = false;
  private closeHit: Phaser.GameObjects.Zone;
  private lastName = "";
  private lastSnapshot: AgentSnapshot | null = null;
  private activityLabel: string | null = null;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    this.root = scene.add.container(0, 0).setDepth(300).setVisible(false);
    this.bg = scene.add.rectangle(0, 0, W, 40, 0x14141c, 0.97).setStrokeStyle(2, 0xd9a441);
    this.nameText = scene.add.text(-W / 2 + 10, -14, "", {
      fontFamily: "monospace", fontSize: "15px", color: "#ffd9a0", fontStyle: "bold",
    });
    this.root.add([this.bg, this.nameText]);
    this.closeHit = scene.add.zone(W / 2 - 12, -12, 16, 16).setInteractive({ useHandCursor: true });
    this.closeHit.on("pointerdown", () => this.hide());
    this.root.add(this.closeHit);
    this.rebuild();
  }

  // 重建行文本并整体测量高度, 调整背景。
  private rebuild(): void {
    for (const t of this.rows) t.destroy();
    this.rows = [];
    // 背景垫底: 只 sendToBack 重排, 不要 remove (remove 会把 bg 从容器孤立 → 不渲染,
    // 只剩文字浮在地图上)。bg 构造时已先于 nameText/rows 加入容器, sendToBack 沉底即可。
    this.root.sendToBack(this.bg);
    const h = this.measure();
    this.bg.setSize(W, h).setOrigin(0.5);
    this.root.setPosition(X, Y);
  }

  // 返回内容总高度 (标题 + 行)。
  private measure(): number {
    let y = -18;                          // 标题下方起点
    for (const t of this.rows) {
      y += t.height + 4;
    }
    return y + 26;
  }

  show(name: string, s: AgentSnapshot, activityLabel: string | null = null): void {
    this.lastName = name;
    this.lastSnapshot = s;
    this.activityLabel = activityLabel;
    this.nameText.setText(`${name}  [${s.dead ? "阵亡" : "存活"}]  ×`);
    this.nameText.setColor(s.dead ? "#ff6655" : "#ffd9a0");
    this.bg.setStrokeStyle(2, s.dead ? 0x883322 : 0xd9a441);

    for (const t of this.rows) t.destroy();
    this.rows = [];
    const lines: { text: string; color: string; size: number; bold?: boolean }[] = [
      { text: `地点    ${s.loc}`, color: "#cfc6b8", size: 13 },
      { text: `血量    ${s.health}`, color: s.dead ? "#ff6655" : "#7ec67e", size: 13 },
      { text: `攻击    ${s.attack}`, color: "#d9a441", size: 13 },
      { text: `身份    ${s.role || "—"}`, color: "#8fb8e8", size: 13 },
      { text: `类型    ${s.kind}`, color: "#8fb8e8", size: 13 },
    ];
    // Phase 3 视觉活动投影 (按角色+地点推断, 不冒充后端逐分钟模拟)
    if (activityLabel && !s.dead) {
      lines.push({ text: `活动    ${activityLabel} (视觉投影)`, color: "#c8a0e8", size: 13 });
    }
    if (s.reasons.length > 0) {
      lines.push({ text: `证据理由 (${s.reasons.length} 条):`, color: "#d9a441", size: 13, bold: true });
      for (const r of s.reasons.slice(0, MAX_REASONS)) {
        lines.push({ text: `· ${r}`, color: "#e8e0d0", size: 12 });
      }
      if (s.reasons.length > MAX_REASONS) {
        lines.push({ text: `  … 另有 ${s.reasons.length - MAX_REASONS} 条`, color: "#8a8a8a", size: 11 });
      }
    }
    // 行高: 此环境 Phaser t.height 低估实际渲染行高 (12px 字 1 行报 15px, 实际 ~19px),
    // 用 t.height 布局会让行与行重叠。改按 行数 × 固定行高 (LINE_H) 算, 保证不叠。
    const rowHeights: number[] = [];
    for (const ln of lines) {
      // 手动换行 (此环境 wordWrap 失效): 长理由行折行不顶出卡宽; 卡高随行数自动长。
      const wrapped = wrapText(ln.text, REASON_WRAP, `${ln.size}px monospace`);
      const t = this.scene.add.text(-W / 2 + 10, 0, wrapped, {
        fontFamily: "monospace", fontSize: `${ln.size}px`, color: ln.color,
        fontStyle: ln.bold ? "bold" : "normal",
        lineSpacing: 2,
      }).setOrigin(0, 0.5);
      this.rows.push(t);
      this.root.add(t);
      rowHeights.push(wrapped.split("\n").length * LINE_H);
    }
    // 垂直布局: 背景居中 (origin 0.5), 名字置顶, 行从名字下方往下排 —— 保证所有行
    // (含折行后的多行理由) 都落在背景内, 且行间距用真实行高 (不低估)。
    const linesH = rowHeights.reduce((a, b) => a + b + ROW_GAP, 0);
    const nameH = this.nameText.height;
    const h = nameH + 10 + linesH + 12;   // 名字 + 间隙 + 行 + 底部留白
    this.bg.setSize(W, h);
    this.nameText.setY(-h / 2 + nameH / 2 + 6);
    this.closeHit.setY(-h / 2 + 10);
    let y = -h / 2 + nameH + 12;
    for (let i = 0; i < this.rows.length; i++) { this.rows[i].setY(y); y += rowHeights[i] + ROW_GAP; }
    this.root.setVisible(true);
    this.open = true;
  }

  hide(): void { this.root.setVisible(false); this.open = false; }
  isOpen(): boolean { return this.open; }
  // E2E 断言用。
  nameShown(): string { return this.lastName; }
  snapshotShown(): AgentSnapshot | null { return this.lastSnapshot; }
  activityShown(): string | null { return this.activityLabel; }
  // 点在卡片外时由场景调用 hide。
  containsPoint(px: number, py: number): boolean {
    if (!this.open) return false;
    return Math.abs(px - X) <= W / 2 && Math.abs(py - Y) <= (this.bg.height / 2);
  }
}
