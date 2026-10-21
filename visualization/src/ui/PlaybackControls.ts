import Phaser from "phaser";
import type { PlaybackController } from "../PlaybackController";

// PlaybackControls (计划 §5.2): 播放/暂停、上一步/下一步、调速、进度。
// 底部一排像素按钮 (深色底 + 金色描边)。点选走**场景级 pointerdown 几何命中**
// (handleClick), 不依赖 per-object setInteractive —— 与时间轴/详情卡一致的可靠路径
// (独立游戏对象 input 在某些环境不稳定, 场景级 pointerdown 总是触发)。
// onStep 时刷新进度; onTransport 时刷新播放图标/速度。
const BTN_W = 30;
const BTN_H = 26;

interface Btn { cx: number; cy: number; cb: () => void }

export class PlaybackControls {
  private controller: PlaybackController;
  private playBtn: Phaser.GameObjects.Text;
  private speedLabel: Phaser.GameObjects.Text;
  private progress: Phaser.GameObjects.Text;
  private buttons: Btn[] = [];

  constructor(scene: Phaser.Scene, controller: PlaybackController, x: number, y: number) {
    this.controller = controller;
    const style = { fontFamily: "monospace", fontSize: "16px", color: "#e8e6e3" };
    // 按钮只画视觉 (底 + 文本), 命中区存入 this.buttons 供场景级 handleClick 用。
    // 图标只用 ASCII / 常见字形: ⏮/⏭/⏸ 在回退的 monospace 字体里缺字形, 会渲染成豆腐块。
    const btn = (label: string, dx: number, cb: () => void, size = 14) => {
      scene.add.rectangle(x + dx, y, BTN_W, BTN_H, 0x232329).setStrokeStyle(1, 0x4a4a5a).setDepth(1000);
      const t = scene.add.text(x + dx, y, label, { ...style, fontSize: `${size}px` })
        .setOrigin(0.5).setDepth(1001);
      this.buttons.push({ cx: x + dx, cy: y, cb });
      return t;
    };
    btn("|<", -150, () => controller.prev(), 12);
    this.playBtn = btn("▶", -75, () => controller.toggle(), 15);
    btn(">|", 0, () => controller.next(), 12);
    btn("-", 70, () => controller.setSpeed(controller.currentSpeed - 0.25), 15);
    this.speedLabel = scene.add.text(x + 100, y, "1.00x", { ...style, fontSize: "13px", color: "#d9a441" })
      .setOrigin(0.5).setDepth(1001);
    btn("+", 130, () => controller.setSpeed(controller.currentSpeed + 0.25), 15);
    this.progress = scene.add.text(x + 200, y, "", { ...style, fontSize: "13px", color: "#9a9aa2" })
      .setOrigin(0, 0.5).setDepth(1001);

    // 进度随每步 (onStep) 刷新; 播放按钮/速度随运输态 (onTransport) 刷新。
    controller.subscribe(() => this.refresh(), () => this.refresh());
    this.refresh();
  }

  // 场景级 pointerdown 调用: 命中任一按钮则执行其回调并返回 true (场景据此不再当空白/时间轴处理)。
  handleClick(px: number, py: number): boolean {
    for (const b of this.buttons) {
      if (Math.abs(px - b.cx) <= BTN_W / 2 && Math.abs(py - b.cy) <= BTN_H / 2) {
        b.cb();
        return true;
      }
    }
    return false;
  }

  private refresh(): void {
    const c = this.controller;
    this.playBtn.setText(c.isPlaying ? "||" : "▶");
    this.speedLabel.setText(c.currentSpeed.toFixed(2) + "x");
    this.progress.setText(`步 ${c.currentIndex + 1}/${c.totalSteps}`);
  }

  // E2E 断言用: 读当前进度文本 ("步 X/N")。
  progressText(): string { return this.progress.text; }
}
