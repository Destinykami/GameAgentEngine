import Phaser from "phaser";

// AgentSprite: M1 占位角色 —— 彩色矩形 + 名字标签 + 血条。
// 用包装类持有 Container (不继承 Container, 避开基类 setPosition/setVisible/body 签名冲突)。
// 职责 (计划 §5.2): 更新可见性/死亡状态/名称标签, 移动 Tween, 朝向。不做世界规则判断。
// 像素约束: 整数坐标, 不做非整数缩放。

export const SPRITE_COLORS: Record<string, number> = {
  旅行者:   0x4fc3f7,
  桃音:     0xf48fb1,
  刚郎:     0xffb74d,
  小梅:     0x81c784,
  执行官:   0xe57373,
  雷电将军: 0xba68c8,
};
const FALLBACK_COLOR = 0x90a4ae;

const BODY_W = 18;
const BODY_H = 22;

export class AgentSprite {
  private scene: Phaser.Scene;
  private container: Phaser.GameObjects.Container;
  private body: Phaser.GameObjects.Rectangle;
  private hpFill: Phaser.GameObjects.Rectangle;
  private label: Phaser.GameObjects.Text;
  private deadOverlay: Phaser.GameObjects.Text;
  private maxHealth: number;
  private activeTween: Phaser.Tweens.Tween | null = null;

  constructor(scene: Phaser.Scene, name: string, x: number, y: number, maxHealth: number) {
    this.scene = scene;
    this.maxHealth = maxHealth;
    const color = SPRITE_COLORS[name] ?? FALLBACK_COLOR;

    this.body = scene.add.rectangle(0, 0, BODY_W, BODY_H, color).setStrokeStyle(2, 0xffffff);
    const hpBar = scene.add.rectangle(0, -BODY_H / 2 - 6, BODY_W + 6, 4, 0x222228);
    this.hpFill = scene.add.rectangle(-(BODY_W + 6) / 2, -BODY_H / 2 - 6, BODY_W + 6, 4, 0x66bb6a)
      .setOrigin(0, 0.5);
    this.label = scene.add.text(0, BODY_H / 2 + 6, name, {
      fontFamily: "monospace", fontSize: "12px", color: "#e8e6e3", align: "center",
    }).setOrigin(0.5, 0);
    this.deadOverlay = scene.add.text(0, 0, "✝", {
      fontFamily: "monospace", fontSize: "16px", color: "#ff5252",
    }).setOrigin(0.5, 0.5).setVisible(false);

    this.container = scene.add.container(Math.round(x), Math.round(y),
      [this.body, hpBar, this.hpFill, this.label, this.deadOverlay]);
    this.container.setDepth(Math.round(y));   // y 越大越靠前 (前景遮挡)
    this.setHealth(maxHealth);
  }

  get x(): number { return this.container.x; }
  get y(): number { return this.container.y; }
  // 暴露容器供气泡锚定 / 伤害弹出定位 / 点击交互。
  get gameObject(): Phaser.GameObjects.Container { return this.container; }

  // 点击回调 (M2 详情卡)。用 Rectangle hitArea + hitAreaCallback (Container 必须显式给,
  // 否则 Phaser 每帧命中测试抛 hitAreaCallback is not a function, 拖垮整个输入)。
  onClick(cb: () => void): void {
    const hit = new Phaser.Geom.Rectangle(-BODY_W / 2 - 5, -BODY_H / 2 - 8, BODY_W + 10, BODY_H + 18);
    this.container.setInteractive({
      hitArea: hit,
      hitAreaCallback: (p: { x: number; y: number }) => hit.contains(p.x, p.y),
      useHandCursor: true,
    });
    this.container.on("pointerdown", cb);
  }

  // 立即设位 (跳步/初始化用, 取消进行中的 Tween, 不留旧动画 —— 计划 §7.2-10)。
  setPosition(x: number, y: number): void {
    this.killMove();
    this.container.setPosition(Math.round(x), Math.round(y));
  }

  // 地点变化时 Tween 走过去 (连续行走, 不瞬移 —— 计划 Phase 0)。
  moveTo(x: number, y: number, duration: number): void {
    this.killMove();
    this.activeTween = this.scene.tweens.add({
      targets: this.container,
      x: Math.round(x),
      y: Math.round(y),
      duration,
      ease: "Sine.easeInOut",
      onComplete: () => { this.activeTween = null; },
    });
  }

  // 停止进行中的移动 Tween (跳步时用, 不残留旧 Tween —— 计划 §7.2-10)。
  stopMove(): void { this.killMove(); }

  // 暂停/恢复时冻结或解冻 Tween (计划 §7.2-9: 暂停时动画和气泡都暂停)。
  freeze(): void { this.activeTween?.pause(); }
  unfreeze(): void { this.activeTween?.resume(); }

  private killMove(): void {
    if (this.activeTween) { this.activeTween.stop(); this.activeTween = null; }
  }

  setHealth(hp: number): void {
    const frac = this.maxHealth > 0 ? Math.max(0, Math.min(1, hp / this.maxHealth)) : 0;
    const w = Math.round((BODY_W + 6) * frac);
    this.hpFill.setSize(Math.max(0, w), 4);
    this.hpFill.setPosition(-(BODY_W + 6) / 2, -BODY_H / 2 - 6);
  }

  setDead(dead: boolean): void {
    this.deadOverlay.setVisible(dead);
    this.body.setAlpha(dead ? 0.45 : 1);
    this.label.setColor(dead ? "#8a8a92" : "#e8e6e3");
    if (dead) this.killMove();   // 死亡角色不再播放普通移动/活动 (计划 §7.2-4)
  }

  setVisible(v: boolean): void { this.container.setVisible(v); }
}
