import Phaser from "phaser";
import type { PlaybackController } from "../PlaybackController";

// PlaybackControls (计划 §5.2): 播放/暂停、上一步/下一步、调速、进度。
// 底部一排像素按钮 (圆角深色底 + 金色描边), onState 时刷新图标/速度/进度。
export class PlaybackControls {
  private controller: PlaybackController;
  private playBtn: Phaser.GameObjects.Text;
  private speedLabel: Phaser.GameObjects.Text;
  private progress: Phaser.GameObjects.Text;

  constructor(scene: Phaser.Scene, controller: PlaybackController, x: number, y: number) {
    this.controller = controller;
    const style = { fontFamily: "monospace", fontSize: "16px", color: "#e8e6e3" };
    const btn = (label: string, dx: number, cb: () => void) => {
      // 按钮底 (圆角深色 + 金色描边) + 文本
      scene.add.rectangle(x + dx, y, 30, 26, 0x232329).setStrokeStyle(1, 0x4a4a5a).setDepth(1000);
      const t = scene.add.text(x + dx, y, label, { ...style }).setOrigin(0.5)
        .setInteractive({ useHandCursor: true })
        .setDepth(1001)
        .on("pointerdown", cb);
      return t;
    };
    btn("⏮", -150, () => controller.prev());
    this.playBtn = btn("▶", -75, () => controller.toggle());
    btn("⏭", 0, () => controller.next());
    btn("−", 70, () => controller.setSpeed(controller.currentSpeed - 0.25));
    this.speedLabel = scene.add.text(x + 100, y, "1.00x", { ...style, fontSize: "13px", color: "#d9a441" })
      .setOrigin(0.5).setDepth(1001);
    btn("+", 130, () => controller.setSpeed(controller.currentSpeed + 0.25));
    this.progress = scene.add.text(x + 200, y, "", { ...style, fontSize: "13px", color: "#9a9aa2" })
      .setOrigin(0, 0.5).setDepth(1001);

    // 进度随每步 (onStep) 刷新; 播放按钮/速度随运输态 (onTransport) 刷新。
    controller.subscribe(() => this.refresh(), () => this.refresh());
    this.refresh();
  }

  private refresh(): void {
    const c = this.controller;
    this.playBtn.setText(c.isPlaying ? "⏸" : "▶");
    this.speedLabel.setText(c.currentSpeed.toFixed(2) + "x");
    this.progress.setText(`步 ${c.currentIndex + 1}/${c.totalSteps}`);
  }

  // E2E 断言用: 读当前进度文本 ("步 X/N")。
  progressText(): string { return this.progress.text; }
}
