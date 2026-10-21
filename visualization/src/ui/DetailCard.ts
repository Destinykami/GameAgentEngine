import Phaser from "phaser";
import { wrapText } from "../text/wrapText";
import { HUD_RECTS, overlapArea, type HudRect } from "./hudRects";
import type { AgentSnapshot } from "../data/schema";

// DetailCard: 点击实体弹出的详情卡 (只读)。
// 显示 name / role / 血量 / 攻击 / 地点 / 生死, 旅行者额外显示已收集的证据理由。
// 跟随被点 NPC 定位 (优先右侧, 放不下换左侧), 并避让状态面板/事件记录/播放条/顶部栏。
// 点空白处或右上角 × 隐藏。× 用场景级几何命中 (此环境 per-object setInteractive 不可靠)。
const W = 252;
const GAP = 20;          // 卡与 NPC 的水平间隙
const MARGIN = 8;        // 卡与屏幕边缘的最小距离
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
  private px = 0;        // 卡中心 (跟随 NPC 定位)
  private py = 0;
  private lastName = "";
  private lastSnapshot: AgentSnapshot | null = null;
  private activityLabel: string | null = null;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    // 详情卡是"查看某个实体"的临时焦点, 必须盖在 HUD 之上 (面板/日志 depth 1000,
    // 气泡 1100), 否则会被地点标签/事件记录/状态面板切掉。气泡另由场景避让。
    this.root = scene.add.container(0, 0).setDepth(1500).setVisible(false);
    this.bg = scene.add.rectangle(0, 0, W, 40, 0x14141c, 0.97).setStrokeStyle(2, 0xd9a441);
    this.nameText = scene.add.text(-W / 2 + 10, -14, "", {
      fontFamily: "monospace", fontSize: "15px", color: "#ffd9a0", fontStyle: "bold",
    });
    this.root.add([this.bg, this.nameText]);
  }

  show(name: string, s: AgentSnapshot, activityLabel: string | null, nx: number, ny: number): void {
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
    let y = -h / 2 + nameH + 12;
    for (let i = 0; i < this.rows.length; i++) { this.rows[i].setY(y); y += rowHeights[i] + ROW_GAP; }
    // 跟随 NPC 定位 (优先右侧, 放不下换左侧, 夹在屏幕内)。
    this.positionNearNPC(nx, ny, h);
    this.root.setPosition(this.px, this.py);
    this.root.setVisible(true);
    this.open = true;
  }

  // 卡定位到 NPC 旁边, 同时避让 HUD。只判断屏幕边界不够: 旅行者在主城时默认右侧
  // 正好落进状态面板, 卡片内容被面板/事件记录切掉。这里用"NPC 四方向 + 每块 HUD 的
  // 左/右/上/下"做 x/y 笛卡尔候选, 优先选与 HUD 零重叠、其次离 NPC 最近的位置。
  private positionNearNPC(nx: number, ny: number, h: number): void {
    const sw = this.scene.scale.width, sh = this.scene.scale.height;
    const clamp = (cx: number, cy: number): { x: number; y: number } => ({
      x: Math.max(MARGIN + W / 2, Math.min(sw - MARGIN - W / 2, cx)),
      y: Math.max(MARGIN + h / 2, Math.min(sh - MARGIN - h / 2, cy)),
    });
    // 注意要允许"左右避让 A + 上下避让 B"的组合, 只沿单块 HUD 平移会卡在
    // "躲开面板但压住日志"的中间态 (旅行者卡曾停在面板左缘与日志上缘的交叠处)。
    const xs: number[] = [nx + GAP + W / 2, nx - GAP - W / 2, nx];
    const ys: number[] = [ny, ny - GAP - h / 2, ny + GAP + h / 2];
    for (const r of HUD_RECTS) {
      xs.push(r.x - GAP - W / 2, r.x + r.w + GAP + W / 2);
      ys.push(r.y - GAP - h / 2, r.y + r.h + GAP + h / 2);
    }
    const boxOf = (c: { x: number; y: number }): HudRect => ({
      x: c.x - W / 2, y: c.y - h / 2, w: W, h,
    });
    let best = clamp(nx, ny);
    let bestOverlap = Infinity;
    let bestDist = Infinity;
    for (const x of xs) {
      for (const y of ys) {
        const c = clamp(x, y);
        const box = boxOf(c);
        let overlap = 0;
        for (const r of HUD_RECTS) overlap += overlapArea(box, r);
        const dist = Phaser.Math.Distance.Between(c.x, c.y, nx, ny);
        // 零重叠优先; 同为 0 时取离 NPC 近的; 实在都重叠则取重叠面积最小的。
        if (overlap < bestOverlap || (overlap === bestOverlap && dist < bestDist)) {
          best = c; bestOverlap = overlap; bestDist = dist;
        }
      }
    }
    this.px = best.x; this.py = best.y;
  }

  hide(): void { this.root.setVisible(false); this.open = false; }
  isOpen(): boolean { return this.open; }
  // E2E 断言用。
  nameShown(): string { return this.lastName; }
  snapshotShown(): AgentSnapshot | null { return this.lastSnapshot; }
  activityShown(): string | null { return this.activityLabel; }
  // 卡在屏幕上的矩形 (供场景级命中: 点卡内不关, 点空白关)。
  containsPoint(px: number, py: number): boolean {
    if (!this.open) return false;
    return Math.abs(px - this.px) <= W / 2 && Math.abs(py - this.py) <= (this.bg.height / 2);
  }
  // × 关闭区 (卡右上角) —— 场景级几何命中 (per-object setInteractive 此环境不可靠)。
  closeAreaContainsPoint(px: number, py: number): boolean {
    if (!this.open) return false;
    const top = this.py - this.bg.height / 2;
    return px >= this.px + W / 2 - 26 && px <= this.px + W / 2 - 2 &&
           py >= top + 2 && py <= top + 22;
  }
}
