import Phaser from "phaser";
import { wrapText } from "../text/wrapText";
import { truncateLines } from "../text/truncate";
import { HUD_RECTS, overlapArea, type HudRect } from "./hudRects";
import type { AgentSnapshot } from "../data/schema";

// DetailCard: 点击实体弹出的详情卡 (只读)。
// 显示 name / role / 血量 / 攻击 / 地点 / 生死, 旅行者额外显示已收集的证据理由。
// 跟随被点 NPC 定位 (优先右侧, 放不下换左侧), 并避让状态面板/事件记录/播放条/顶部栏。
// 点空白处或右上角 × 隐藏。× 是独立文本对象 + 场景级几何命中 (此环境 per-object input 不可靠)。
// 长内容 (证据多/理由长) 卡高封顶, 正文放进可滚动容器 + 遮罩, 右侧滚动条; 标题/× 固定。
const W = 252;
const GAP = 20;          // 卡与 NPC/水平 HUD 的间隙
const V_GAP = 8;         // 卡与 NPC/垂直 HUD 的间隙 (比水平小, 长卡才放得进世界安全区)
const MARGIN = 8;        // 卡与屏幕边缘的最小距离
const MAX_REASONS = 12;  // 理由超过这个数才折叠, 其余靠卡内滚动查看
const REASON_WRAP = 214; // 给右侧滚动条留出 4px + 边距
// 标题区固定高度: 此环境 t.height 低估实际渲染行高, 用固定标题带而不是 nameH 叠行。
const TITLE_H = 24;
const TITLE_GAP = 6;     // 标题带与第一行之间
const BOTTOM_PAD = 10;
const CLOSE_W = 24;
const CLOSE_H = 24;
const CLOSE_MARGIN = 6;  // 关闭区距卡右缘
const TITLE_MAX_W = W - 20 - (CLOSE_W + CLOSE_MARGIN);   // 给 × 留出位置, 长名字省略号
// 布局行高/行距: 此环境 t.height 低估实际渲染行高 (~19px), 用 21px 固定行高 + 5px 行距,
// 保证折行后的多行理由不重叠 (12-13px 字号都够)。
const LINE_H = 21;
const ROW_GAP = 5;
// 卡高上限: 世界安全区约 324px (顶栏 40 + 8 到事件记录 380 - 8)。定 320 让 3 条理由
// 的卡 (约 311px) 完整显示, 第 4 条起进入卡内滚动而不是压住事件记录。
const MAX_CARD_H = 320;
const SCROLL_W = 4;
const SCROLL_MIN_THUMB = 16;

export class DetailCard {
  private scene: Phaser.Scene;
  private root: Phaser.GameObjects.Container;
  private bg!: Phaser.GameObjects.Rectangle;
  private content!: Phaser.GameObjects.Container;   // 正文 (可滚动, 被遮罩裁切)
  private maskGfx!: Phaser.GameObjects.Graphics;    // 正文视口遮罩 (世界坐标)
  private scrollTrack!: Phaser.GameObjects.Rectangle;
  private scrollThumb!: Phaser.GameObjects.Rectangle;
  private rows: Phaser.GameObjects.Text[] = [];
  private nameText!: Phaser.GameObjects.Text;
  private closeBtn!: Phaser.GameObjects.Text;
  private open = false;
  private px = 0;        // 卡中心 (跟随 NPC 定位)
  private py = 0;
  private lastName = "";
  private lastSnapshot: AgentSnapshot | null = null;
  private activityLabel: string | null = null;
  // 滚动状态 (相对卡片容器)
  private contentTop = 0;
  private contentH = 0;
  private viewH = 0;
  private scrollOffset = 0;
  private scrollable = false;
  private dragging = false;
  private dragStartY = 0;
  private dragStartOffset = 0;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    // 详情卡是"查看某个实体"的临时焦点, 必须盖在 HUD 之上 (面板/日志 depth 1000,
    // 气泡 1100), 否则会被地点标签/事件记录/状态面板切掉。气泡另由场景避让。
    this.root = scene.add.container(0, 0).setDepth(1500).setVisible(false);
    this.bg = scene.add.rectangle(0, 0, W, 40, 0x14141c, 0.97).setStrokeStyle(2, 0xd9a441);
    // 正文容器: 行都加到这里, 由遮罩裁到视口高度。content.y 随滚动偏移移动。
    this.content = scene.add.container(0, 0);
    this.maskGfx = scene.make.graphics({ x: 0, y: 0 }, false);
    this.content.setMask(this.maskGfx.createGeometryMask());
    this.nameText = scene.add.text(-W / 2 + 10, 0, "", {
      fontFamily: "monospace", fontSize: "15px", color: "#ffd9a0", fontStyle: "bold",
    }).setOrigin(0, 0.5);
    // × 独立成对象, 固定在卡右上角标题带内; 不再拼在名字末尾 (名字长短会把它带到
    // 卡中间, 用户点可见的 × 命中不到固定判定区)。
    this.closeBtn = scene.add.text(W / 2 - CLOSE_MARGIN - CLOSE_W / 2, 0, "×", {
      fontFamily: "monospace", fontSize: "16px", color: "#d9a441", fontStyle: "bold",
    }).setOrigin(0.5, 0.5);
    // 滚动条固定在卡片右侧, 不参与正文遮罩; 只有内容超高时显示。
    this.scrollTrack = scene.add.rectangle(0, 0, SCROLL_W, 10, 0x2a2a34)
      .setOrigin(0.5, 0).setVisible(false);
    this.scrollThumb = scene.add.rectangle(0, 0, SCROLL_W, 10, 0xd9a441)
      .setOrigin(0.5, 0).setVisible(false);
    this.root.add([this.bg, this.content, this.nameText, this.closeBtn, this.scrollTrack, this.scrollThumb]);
  }

  show(name: string, s: AgentSnapshot, activityLabel: string | null, nx: number, ny: number): void {
    this.lastName = name;
    this.lastSnapshot = s;
    this.activityLabel = activityLabel;
    const title = `${name}  [${s.dead ? "阵亡" : "存活"}]`;
    this.nameText.setText(truncateLines(title, 1, TITLE_MAX_W, "15px monospace"));
    this.nameText.setColor(s.dead ? "#ff6655" : "#ffd9a0");
    this.closeBtn.setColor(s.dead ? "#ff6655" : "#d9a441");
    this.bg.setStrokeStyle(2, s.dead ? 0x883322 : 0xd9a441);

    for (const t of this.rows) t.destroy();
    this.rows = [];
    this.dragging = false;
    this.scrollOffset = 0;
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
      this.content.add(t);
      rowHeights.push(wrapped.split("\n").length * LINE_H);
    }
    // 正文总高 / 视口高 / 卡高。超过 MAX_CARD_H 时卡高封顶, 正文进入滚动。
    const contentH = rowHeights.reduce((a, b) => a + b, 0)
      + ROW_GAP * Math.max(0, this.rows.length - 1);
    const desiredH = TITLE_H + TITLE_GAP + contentH + BOTTOM_PAD;
    const h = Math.min(desiredH, MAX_CARD_H);
    this.contentH = contentH;
    this.viewH = Math.max(1, h - TITLE_H - TITLE_GAP - BOTTOM_PAD);
    this.scrollable = contentH > this.viewH + 0.5;
    this.contentTop = -h / 2 + TITLE_H + TITLE_GAP;
    this.bg.setSize(W, h);
    const titleY = -h / 2 + TITLE_H / 2;
    this.nameText.setY(titleY);
    this.closeBtn.setY(titleY);
    // 行从正文容器顶部 0 开始排, 容器 y=contentTop; 滚动只改容器 y。
    this.content.setPosition(0, this.contentTop);
    let y = 0;
    for (let i = 0; i < this.rows.length; i++) {
      y += rowHeights[i] / 2;
      this.rows[i].setY(y);
      y += rowHeights[i] / 2 + ROW_GAP;
    }
    // 跟随 NPC 定位 (优先右侧, 放不下换左侧, 夹在屏幕内)。
    this.positionNearNPC(nx, ny, h);
    this.root.setPosition(this.px, this.py);
    this.updateMask();
    this.applyScroll();
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
    const ys: number[] = [ny, ny - V_GAP - h / 2, ny + V_GAP + h / 2];
    for (const r of HUD_RECTS) {
      xs.push(r.x - GAP - W / 2, r.x + r.w + GAP + W / 2);
      ys.push(r.y - V_GAP - h / 2, r.y + r.h + V_GAP + h / 2);
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

  // ---- 滚动 ----

  private maxScroll(): number { return Math.max(0, this.contentH - this.viewH); }

  private applyScroll(): void {
    this.content.setY(this.contentTop - this.scrollOffset);
    this.updateScrollbar();
  }

  private updateScrollbar(): void {
    if (!this.scrollable) {
      this.scrollTrack.setVisible(false);
      this.scrollThumb.setVisible(false);
      return;
    }
    const x = W / 2 - 8;
    this.scrollTrack.setPosition(x, this.contentTop)
      .setSize(SCROLL_W, this.viewH).setVisible(true);
    const thumbH = Math.max(SCROLL_MIN_THUMB, this.viewH * (this.viewH / this.contentH));
    const max = this.maxScroll();
    const t = max > 0 ? this.scrollOffset / max : 0;
    this.scrollThumb.setPosition(x, this.contentTop + (this.viewH - thumbH) * t)
      .setSize(SCROLL_W, thumbH).setVisible(true);
  }

  // 正文视口遮罩: 世界坐标 (卡不移动, 只需 show() 时更新一次)。
  private updateMask(): void {
    this.maskGfx.clear();
    this.maskGfx.fillStyle(0xffffff, 1);
    this.maskGfx.fillRect(this.px - W / 2, this.py + this.contentTop, W, this.viewH);
  }

  // 场景级 wheel 调用: 指针在卡内且内容可滚动时滚动, 返回 true。
  handleWheel(px: number, py: number, deltaY: number): boolean {
    if (!this.open || !this.scrollable || !this.containsPoint(px, py)) return false;
    this.scrollBy(deltaY * 0.5);
    return true;
  }

  // 场景级 pointerdown 调用: 在正文视口内按下开始拖动滚动, 返回 true。
  startDrag(px: number, py: number): boolean {
    if (!this.open || !this.scrollable) return false;
    if (!this.contentAreaContains(px, py)) return false;
    this.dragging = true;
    this.dragStartY = py;
    this.dragStartOffset = this.scrollOffset;
    return true;
  }

  dragTo(_px: number, py: number): void {
    if (!this.dragging) return;
    this.setScroll(this.dragStartOffset - (py - this.dragStartY));
  }

  endDrag(): void { this.dragging = false; }

  private contentAreaContains(px: number, py: number): boolean {
    if (!this.open) return false;
    const left = this.px - W / 2;
    const top = this.py + this.contentTop;
    return px >= left && px <= left + W && py >= top && py <= top + this.viewH;
  }

  scrollBy(dy: number): void {
    if (!this.open || !this.scrollable) return;
    this.setScroll(this.scrollOffset + dy);
  }

  private setScroll(v: number): void {
    this.scrollOffset = Math.max(0, Math.min(this.maxScroll(), v));
    this.applyScroll();
  }

  hide(): void { this.root.setVisible(false); this.open = false; this.dragging = false; }
  isOpen(): boolean { return this.open; }
  isScrollable(): boolean { return this.open && this.scrollable; }
  // E2E 断言用。
  nameShown(): string { return this.lastName; }
  snapshotShown(): AgentSnapshot | null { return this.lastSnapshot; }
  activityShown(): string | null { return this.activityLabel; }
  scrollInfo(): { scrollable: boolean; offset: number; contentH: number; viewH: number; max: number } {
    return {
      scrollable: this.scrollable, offset: this.scrollOffset,
      contentH: this.contentH, viewH: this.viewH, max: this.maxScroll(),
    };
  }
  // E2E 断言用: 卡片内所有文本的右/下边界 (屏幕坐标)。行在 content 里, 要加上 content.y。
  textBounds(): { maxRight: number; maxBottom: number } {
    let maxRight = 0, maxBottom = 0;
    for (const t of [this.nameText, this.closeBtn, ...this.rows]) {
      if (!t.text) continue;
      const oy = this.rows.includes(t) ? this.content.y : 0;
      maxRight = Math.max(maxRight, this.root.x + t.x + t.width);
      maxBottom = Math.max(maxBottom, this.root.y + oy + t.y + t.height);
    }
    return { maxRight, maxBottom };
  }
  // 卡在屏幕上的矩形 (供场景级命中: 点卡内不关, 点空白关)。
  containsPoint(px: number, py: number): boolean {
    if (!this.open) return false;
    return Math.abs(px - this.px) <= W / 2 && Math.abs(py - this.py) <= (this.bg.height / 2);
  }
  // × 关闭区 (卡右上角) —— 场景级几何命中 (per-object setInteractive 此环境不可靠)。
  // 与 closeBtn 的显示位置使用同一组 TITLE_H/CLOSE_* 常量, 保证"看到的 ×"就是"能点的 ×"。
  closeAreaContainsPoint(px: number, py: number): boolean {
    if (!this.open) return false;
    const top = this.py - this.bg.height / 2;
    const right = this.px + W / 2;
    const left = right - CLOSE_MARGIN - CLOSE_W;
    const cy = top + TITLE_H / 2;
    return px >= left && px <= right - CLOSE_MARGIN &&
           py >= cy - CLOSE_H / 2 && py <= cy + CLOSE_H / 2;
  }
}
