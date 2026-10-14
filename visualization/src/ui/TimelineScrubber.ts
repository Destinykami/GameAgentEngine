import Phaser from "phaser";
import type { PlaybackController } from "../PlaybackController";

// TimelineScrubber: 顶部时间轴, 每步一个刻度, 点击/拖动播放头跳到任意 step。
// 只读回放器里的寻址工具 (计划 §7.2-10: 快速跳步不留旧 Tween/气泡, 由场景处理)。
const X0 = 30;               // 轨道起点 x
const W = 900;              // 轨道宽
const Y = 20;               // 轨道 y
const HIT_H = 22;           // 命中区高 (便于点选)
const MARKER_H = 6;
const HEAD_W = 8;
const HEAD_H = 16;

export class TimelineScrubber {
  private scene: Phaser.Scene;
  private ctrl: PlaybackController;
  private track!: Phaser.GameObjects.Rectangle;
  private fill!: Phaser.GameObjects.Rectangle;
  private head!: Phaser.GameObjects.Rectangle;
  private markers: Phaser.GameObjects.Rectangle[] = [];
  private label!: Phaser.GameObjects.Text;
  private dragging = false;
  hit!: Phaser.GameObjects.Rectangle;   // 暴露供 E2E 诊断
  // E2E 诊断
  dbg = { pointerDowns: 0, moves: 0, seeks: 0, lastSeekIndex: -1 };

  constructor(scene: Phaser.Scene, ctrl: PlaybackController) {
    this.scene = scene;
    this.ctrl = ctrl;
    const total = ctrl.totalSteps;
    const cx = X0 + W / 2;

    this.track = scene.add.rectangle(cx, Y, W, 4, 0x33333d).setDepth(320);
    this.fill = scene.add.rectangle(X0, Y, 0, 4, 0xd9a441).setOrigin(0, 0.5).setDepth(321);
    for (let i = 0; i < total; i++) {
      const x = this.xOf(i);
      this.markers.push(scene.add.rectangle(x, Y, 2, MARKER_H, 0x666677).setDepth(321));
    }
    this.head = scene.add.rectangle(this.xOf(ctrl.currentIndex), Y, HEAD_W, HEAD_H, 0xffffff)
      .setStrokeStyle(1, 0xd9a441).setDepth(322);
    this.label = scene.add.text(cx, Y - 14, "", {
      fontFamily: "monospace", fontSize: "11px", color: "#8a8a8a",
    }).setOrigin(0.5, 1).setDepth(320);

    // 命中区: 透明 Rectangle 仅作视觉占位 (自身不处理输入)。
    // 点选/拖动由 InazumaScene 的场景级输入统一驱动 (onPointerDown/Move/Up),
    // 因为场景级 pointerdown 可靠触发, 而独立游戏对象的 input 在此环境不生效。
    this.hit = scene.add.rectangle(cx, Y, W, HIT_H, 0x000000, 0.001).setDepth(323);
    this.refresh();
  }

  // 场景级输入驱动: 按下 (开始拖拽并 seek)。
  onPointerDown(x: number): void {
    this.dragging = true;
    this.dbg.pointerDowns++;
    this.seekFromPointer(x);
  }
  // 场景级输入驱动: 拖动中。
  onPointerMove(x: number): void {
    if (this.dragging) { this.dbg.moves++; this.seekFromPointer(x); }
  }
  // 场景级输入驱动: 松开。
  onPointerUp(): void { this.dragging = false; }

  private xOf(i: number): number {
    const total = this.ctrl.totalSteps;
    if (total <= 1) return X0;
    return X0 + (i / (total - 1)) * W;
  }

  private seekFromPointer(px: number): void {
    const total = this.ctrl.totalSteps;
    const ratio = Phaser.Math.Clamp((px - X0) / W, 0, 1);
    const idx = Math.round(ratio * (total - 1));
    this.dbg.seeks++;
    this.dbg.lastSeekIndex = idx;
    this.ctrl.seek(idx);
  }

  // 直播模式: 时间线增长 (addStep) 后重建刻度 (xOf 依赖 totalSteps, 总步数变了旧刻度位置错)。
  grow(): void {
    for (const m of this.markers) m.destroy();
    this.markers = [];
    const total = this.ctrl.totalSteps;
    for (let i = 0; i < total; i++) {
      this.markers.push(this.scene.add.rectangle(this.xOf(i), Y, 2, MARKER_H, 0x666677).setDepth(321));
    }
    this.refresh();
  }

  // 步/速度变化时刷新填充与播放头位置。
  refresh(): void {
    const x = this.xOf(this.ctrl.currentIndex);
    this.fill.setSize(this.ctrl.currentIndex === 0 ? 0 : x - X0, 4).setOrigin(0, 0.5).setPosition(X0, Y);
    this.head.setPosition(x, Y);
    const s = this.ctrl.current;
    this.label.setText(`第${s.day}天 ${String(Math.floor(s.moment)).padStart(2, "0")}:${String(Math.round((s.moment % 1) * 60)).padStart(2, "0")}  ·  步 ${this.ctrl.currentIndex + 1}/${this.ctrl.totalSteps}`);
  }

  destroy(): void {
    this.track.destroy(); this.fill.destroy(); this.head.destroy();
    for (const m of this.markers) m.destroy();
    this.label.destroy();
  }
}
