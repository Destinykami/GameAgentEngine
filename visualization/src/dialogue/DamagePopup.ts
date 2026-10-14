import Phaser from "phaser";

// DamagePopup: 受击时目标头顶弹出伤害数字 (上飘+淡出), 致死时红色强化。
// 只读表现层, 不修改世界状态 (计划 §2.1/§2.4: 事件成功才表现副作用)。
export class DamagePopup {
  private scene: Phaser.Scene;
  private queue: { x: number; y: number; text: string; dead: boolean }[] = [];
  private active = false;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
  }

  // 在 (x,y) 弹出伤害数字; dead=true 时红色更大字号。
  push(x: number, y: number, damage: number, dead: boolean): void {
    this.queue.push({ x, y, text: dead ? `-${damage} ✝` : `-${damage}`, dead });
    if (!this.active) { this.active = true; this.next(); }
  }

  private next(): void {
    const item = this.queue.shift();
    if (!item) { this.active = false; return; }
    const t = this.scene.add.text(item.x, item.y - 20, item.text, {
      fontFamily: "monospace",
      fontSize: item.dead ? "22px" : "17px",
      color: item.dead ? "#ff5544" : "#ffcc44",
      stroke: "#000000",
      strokeThickness: 3,
    }).setOrigin(0.5).setDepth(210).setScale(0.6);
    this.scene.tweens.add({
      targets: t,
      y: t.y - 28,
      scale: 1,
      alpha: 0,
      duration: 900,
      ease: "Cubic.easeOut",
      onComplete: () => t.destroy(),
    });
    // 依次弹出队列里的下一个 (间隔 180ms)
    if (this.queue.length) this.scene.time.delayedCall(180, () => this.next());
  }

  clear(): void { this.queue.length = 0; }
}
