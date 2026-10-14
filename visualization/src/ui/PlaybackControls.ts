import type { PlaybackController } from "../PlaybackController";

// PlaybackControls (计划 §5.2): 播放/暂停、上一步/下一步、调速、进度。
// Phaser 文本按钮 (input 事件), 底部一排。onState 时刷新播放图标/速度/进度。
export class PlaybackControls {
  private controller: PlaybackController;
  private playBtn: Phaser.GameObjects.Text;
  private speedLabel: Phaser.GameObjects.Text;
  private progress: Phaser.GameObjects.Text;

  constructor(scene: Phaser.Scene, controller: PlaybackController, x: number, y: number) {
    this.controller = controller;
    const style = { fontFamily: "monospace", fontSize: "18px", color: "#e8e6e3" };
    const btn = (label: string, dx: number, cb: () => void) => {
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
    this.speedLabel = scene.add.text(x + 100, y, "1.0x", { ...style, fontSize: "14px" })
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
}
