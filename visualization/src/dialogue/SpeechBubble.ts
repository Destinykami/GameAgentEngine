import Phaser from "phaser";
import { wrapText } from "../text/wrapText";
import { overlapArea, type HudRect } from "../ui/hudRects";

// 气泡风格: player=旅行者 (蓝边), npc=NPC (灰白边), system=系统提示 (金边)。
// 对应计划 §4 气泡模型: 锚点跟随 Sprite, 进入/停留/离场动画, 自动换行。
export type BubbleStyle = "player" | "npc" | "system";

const STYLE_COLOR: Record<BubbleStyle, number> = {
  player: 0x4a90d9,
  npc: 0xcfc6b8,
  system: 0xd9a441,
};
const BG = 0x14141a;
const WRAP_WIDTH = 168;      // 气泡文字换行宽度 (像素)
const PAD = 8;               // 内边距
const FONTSIZE = 14;
const FONT = `${FONTSIZE}px monospace`;
// Phaser 在此环境回报的 text.height 会低估实际渲染行高 (14px 字约少报 4px/行),
// 长台词按 text.height 建背景会直接溢出。与 DetailCard 一样按行数 × 固定行高计算。
const LINE_H = FONTSIZE + 7; // 21px
const TAIL = 8;              // 尾巴高

// SpeechBubble: 创建/销毁气泡, 跟随角色锚点, 入场直接显示、离场淡出。
// 一次对话由场景编排: 先 show 行动者气泡, 再 show 目标回复气泡, 系统效果单独提示。
export class SpeechBubble {
  private scene: Phaser.Scene;
  private root: Phaser.GameObjects.Container;
  private bg!: Phaser.GameObjects.Rectangle;
  private tail!: Phaser.GameObjects.Rectangle;
  private text!: Phaser.GameObjects.Text;
  private anchor: Phaser.GameObjects.Container | null = null;   // 跟随的 sprite
  private headOffset = 16;   // 锚点(脚底)到头顶距离
  private visible = false;
  private dx = 0;   // 相对锚点的水平偏移 (对话双方同地点时左右错开)
  private dy = 0;   // 相对锚点的垂直偏移
  private original = "";   // 原始台词 (未换行); bubbleText() 返回它供 E2E 比对内容
  private avoid: HudRect[] = [];      // 需要避让的 HUD 区 (面板/日志/播放条/顶部栏)
  private peer: SpeechBubble | null = null;   // 同屏的另一侧气泡 (避免互相重叠)
  // show() 时锁定一次的相对位置。之后跟随锚点移动, 不再每帧重新做碰撞求解 (防抖动)。
  private placed: { dx: number; dy: number; tailUp: boolean } | null = null;

  constructor(scene: Phaser.Scene, depth = 200) {
    this.scene = scene;
    this.root = scene.add.container(0, 0).setDepth(depth);
    // 不配 wordWrap (此环境不生效), 靠 show() 手动换行插 \n。
    this.text = scene.add.text(0, 0, "", {
      fontFamily: "monospace",
      fontSize: `${FONTSIZE}px`,
      color: "#f0ece4",
      align: "left",
      lineSpacing: 2,
    });
    this.bg = scene.add.rectangle(0, 0, 10, 10, BG, 1).setStrokeStyle(2, 0xffffff);
    this.tail = scene.add.rectangle(0, 0, 6, TAIL, BG, 1);
    this.root.add([this.bg, this.text, this.tail]);
    this.root.setVisible(false).setAlpha(0);
  }

  // 锚定到某个 sprite (气泡随其移动), null 表示固定世界坐标。
  setAnchor(sprite: Phaser.GameObjects.Container | null, headOffset = 16): void {
    this.anchor = sprite;
    this.headOffset = headOffset;
  }

  // 相对锚点的偏移 (对话双方同地点时左右错开气泡)。
  setOffset(dx: number, dy: number): void {
    this.dx = dx; this.dy = dy;
    if (this.anchor) { if (this.visible) this.place(); this.layout(); }
  }

  // 需要避让的屏幕区域 (场景传入共享的 HUD_RECTS)。
  setAvoidRects(rects: HudRect[]): void { this.avoid = rects; }

  // 同屏另一侧气泡: 后显示的一方把对方已占的矩形也当作避让区。
  setPeer(peer: SpeechBubble | null): void { this.peer = peer; }

  // 显示气泡: 手动换行 + 按换行后行数定背景高度, 重建背景/尾巴。
  show(text: string, style: BubbleStyle): void {
    this.original = text;                          // 存原始台词 (bubbleText 比对用)
    const wrapped = wrapText(text, WRAP_WIDTH, FONT);   // 手动换行 (此环境 wordWrap 失效)
    this.text.setText(wrapped);
    const color = STYLE_COLOR[style];
    this.bg.setStrokeStyle(2, color);
    this.tail.setFillStyle(color).setStrokeStyle(2, color);

    // 换行后: 宽=最宽行 (≤WRAP_WIDTH), 高=行数×真实行高。背景 = 文本尺寸 + 内边距。
    // 不用 this.text.height: 此环境它按 15-17px/行回报, 实际约 21px/行, 长台词会溢出黑框。
    const lines = wrapped.split("\n").length;
    const tw = this.text.width + PAD * 2;
    const th = Math.max(this.text.height, lines * LINE_H) + PAD * 2;
    this.bg.setSize(tw, th);
    this.text.setOrigin(0.5).setPosition(0, 0);
    this.bg.setPosition(0, 0);
    // 位置求解: 优先头顶上方; 上方会压住顶部栏/面板时翻到角色下方, 并在水平方向
    // 避让 HUD 与另一侧气泡。求解结果锁定为相对锚点的偏移。
    this.place();
    this.layout();
    this.scene.tweens.killTweensOf(this.root);   // 取消旧 tween (大跳转 hide 后又 show, 旧淡出回调会关掉新气泡)
    this.root.setVisible(true);
    this.root.alpha = 1;
    this.visible = true;
    // 不做淡入: 无头/低帧率环境下 Phaser 的 tween 可能长时间不走, 气泡会保持 alpha=0
    // (文字在但背景半透明/看不见)。气泡出现直接置 1, 离场仍可淡出。
  }

  // 选择气泡位置: 上方/下方 × (默认 x + 各 HUD 左边/右边/中心)。零重叠优先,
  // 其次离默认位置近; 上方优先于下方。避免此前"头顶放不下就被 clamp 到左上角,
  // 压住直播入口/时间轴, 两个同地点气泡还互相重叠"。
  private place(): void {
    if (!this.anchor) { this.placed = null; return; }
    const sw = this.scene.scale.width, sh = this.scene.scale.height;
    const hw = this.bg.width / 2, hh = this.bg.height / 2;
    const MARGIN = 6;
    const TOP_SAFE = 44;                       // 顶部时间轴栏高 40 + 4
    const xMin = MARGIN + hw, xMax = sw - MARGIN - hw;
    const yMin = TOP_SAFE + hh, yMax = sh - MARGIN - hh;
    const clampX = (v: number): number => Math.max(xMin, Math.min(xMax, v));
    const clampY = (v: number): number => Math.max(yMin, Math.min(yMax, v));
    const headY = this.anchor.y - this.headOffset;
    const aboveY = headY - hh - 6 + this.dy;
    const belowY = this.anchor.y + 26 + hh + this.dy;   // 26px 让开脚下的名字牌
    // 上方/下方都得真的放在角色之外: 若上方被顶部栏压到 yMin (等于贴在角色身上),
    // 不应因为"零 HUD 重叠"就选中它。上方放不下就翻到下方, 反之亦然。
    const ys: { y: number; tailUp: boolean }[] = [];
    if (aboveY >= yMin) ys.push({ y: clampY(aboveY), tailUp: false });
    if (belowY <= yMax) ys.push({ y: clampY(belowY), tailUp: true });
    if (ys.length === 0) {
      ys.push({ y: clampY(aboveY), tailUp: false }, { y: clampY(belowY), tailUp: true });
    }
    const xs: number[] = [this.anchor.x + this.dx, sw / 2, xMin, xMax];
    for (const r of this.avoid) {
      xs.push(r.x - 6 - hw, r.x + r.w + 6 + hw, r.x + r.w / 2);
    }
    const pr = this.peer && this.peer.isVisible() ? this.peer.screenRect() : null;
    const peerBox: HudRect | null = pr
      ? { x: pr.x - pr.w / 2, y: pr.y - pr.h / 2, w: pr.w, h: pr.h }
      : null;
    let best = { x: clampX(this.anchor.x + this.dx), y: clampY(aboveY), tailUp: false };
    let bestScore = Infinity;
    for (const { y, tailUp } of ys) {
      for (const rawX of xs) {
        const x = clampX(rawX);
        const box: HudRect = { x: x - hw, y: y - hh, w: hw * 2, h: hh * 2 };
        let overlap = 0;
        for (const r of this.avoid) overlap += overlapArea(box, r);
        if (peerBox) overlap += overlapArea(box, peerBox);
        // 面积加权远大于距离; 同为 0 时取离默认位置近的; 下方加固定惩罚 → 能上方就上方。
        const score = overlap * 1000 + Math.abs(x - (this.anchor.x + this.dx)) + (tailUp ? 240 : 0);
        if (score < bestScore) { bestScore = score; best = { x, y, tailUp }; }
      }
    }
    this.placed = { dx: best.x - this.anchor.x, dy: best.y - this.anchor.y, tailUp: best.tailUp };
  }

  // 每帧跟随锚点 (sprite 移动 Tween 时气泡同步)。位置用 place() 锁定的相对偏移;
  // 仅做基本的屏幕夹取, 不在移动中重新求解 (避免气泡在 HUD 边缘来回跳)。
  private layout(): void {
    const r = this.root;
    if (!this.anchor) return;
    const hw = this.bg.width / 2, hh = this.bg.height / 2;
    let x: number, y: number;
    if (this.placed) {
      x = this.anchor.x + this.placed.dx;
      y = this.anchor.y + this.placed.dy;
    } else {
      const halfH = hh + TAIL;
      x = this.anchor.x + this.dx;
      y = this.anchor.y - this.headOffset - halfH - 6 + this.dy;
    }
    x = Math.max(hw + 4, Math.min(this.scene.scale.width - hw - 4, x));
    y = Math.max(hh + 4, Math.min(this.scene.scale.height - hh - 4, y));
    r.setPosition(x, y);
    const tailUp = this.placed?.tailUp ?? false;
    // 尾巴水平指向锚点 (气泡被 HUD 推离角色左右时, 尾巴仍指向角色而不是框中心)。
    const tailX = Phaser.Math.Clamp(this.anchor.x - x, -hw + 10, hw - 10);
    this.tail.setPosition(tailX, tailUp ? -hh - TAIL / 2 + 1 : hh + TAIL / 2 - 1);
  }

  // 每帧跟随锚点 (sprite 移动 Tween 时气泡同步)。
  update(): void {
    if (!this.visible || !this.anchor) return;
    this.layout();
  }

  hide(): void {
    if (!this.visible) return;
    this.visible = false;
    this.scene.tweens.killTweensOf(this.root);   // 取消旧 tween (如正在淡入的 show), 再淡出
    this.scene.tweens.add({
      targets: this.root, alpha: 0, duration: 140, ease: "Sine.easeIn",
      onComplete: () => this.root.setVisible(false),
    });
  }

  // E2E 断言用。
  isVisible(): boolean { return this.visible; }
  bubbleText(): string { return this.original; }   // 原始台词 (不含换行), E2E 比对内容用
  // 当前气泡在屏幕上的矩形 (中心 + 尺寸), 供另一侧气泡避让。
  screenRect(): { x: number; y: number; w: number; h: number } | null {
    if (!this.visible) return null;
    return { x: this.root.x, y: this.root.y, w: this.bg.width, h: this.bg.height };
  }
  // E2E 断言用: 背景是否容得下文字 (bg 尺寸 >= 文本尺寸, 即无溢出)。
  // textH 用行数 × LINE_H (真实行高), 避免再拿低估的 text.height 做"自证不溢出"。
  fitInfo(): { bgW: number; bgH: number; textW: number; textH: number; lines: number } {
    const lines = this.text.text.split("\n").length;
    return {
      bgW: this.bg.width, bgH: this.bg.height,
      textW: this.text.width,
      textH: Math.max(this.text.height, lines * LINE_H),
      lines,
    };
  }

  destroy(): void {
    this.bg.destroy(); this.text.destroy(); this.tail.destroy(); this.root.destroy();
  }
}
