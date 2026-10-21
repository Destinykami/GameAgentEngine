import Phaser from "phaser";
import { wrapText } from "../text/wrapText";

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

// SpeechBubble: 创建/销毁气泡, 跟随角色锚点, 进入/离场淡入淡出。
// 一次对话由场景编排: 先 show 行动者气泡, 再 show 目标回复气泡, 系统效果单独提示。
export class SpeechBubble {
  private scene: Phaser.Scene;
  private root: Phaser.GameObjects.Container;
  private bg!: Phaser.GameObjects.Rectangle;
  private tail!: Phaser.GameObjects.Rectangle;
  private text!: Phaser.GameObjects.Text;
  private anchor: Phaser.GameObjects.Container | null = null;   // 跟随的 sprite
  private visible = false;
  private dx = 0;   // 相对锚点的水平偏移 (对话双方同地点时左右错开)
  private dy = 0;   // 相对锚点的垂直偏移
  private original = "";   // 原始台词 (未换行); bubbleText() 返回它供 E2E 比对内容

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
  setAnchor(sprite: Phaser.GameObjects.Container | null): void {
    this.anchor = sprite;
  }

  // 相对锚点的偏移 (对话双方同地点时左右错开气泡)。
  setOffset(dx: number, dy: number): void {
    this.dx = dx; this.dy = dy;
    if (this.anchor) this.layout();
  }

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
    this.tail.setPosition(0, th / 2 + TAIL / 2 - 1);
    this.layout();
    this.scene.tweens.killTweensOf(this.root);   // 取消旧 tween (大跳转 hide 后又 show, 旧淡出回调会关掉新气泡)
    this.root.setVisible(true);
    this.visible = true;
    this.root.alpha = 0;
    this.scene.tweens.add({ targets: this.root, alpha: 1, duration: 140, ease: "Sine.easeOut" });
  }

  // 跟随锚点布局: 气泡在 sprite 头顶上方, 尾巴指向 sprite。
  private layout(): void {
    const r = this.root;
    if (this.anchor) {
      const headY = this.anchor.y - 16;          // sprite 头顶
      const halfH = this.bg.height / 2 + TAIL;
      r.setPosition(this.anchor.x + this.dx, headY - halfH - 6 + this.dy);
      // 出界保护: 顶部翻转/右移
      if (r.y < this.bg.height / 2 + 4) r.setY(this.bg.height / 2 + 4);
      if (r.x - this.bg.width / 2 < 4) r.setX(this.bg.width / 2 + 4);
      if (r.x + this.bg.width / 2 > this.scene.scale.width - 4)
        r.setX(this.scene.scale.width - this.bg.width / 2 - 4);
    }
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
