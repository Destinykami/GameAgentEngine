import Phaser from "phaser";
import { buildArt } from "../art/ArtFactory";

// AgentSprite: M3 像素角色 —— 带 idle/walk 动画的角色 Sprite + 名字标签 + 血条。
// 用包装类持有 Container (不继承 Container, 避开基类 setPosition/setVisible/body 签名冲突)。
// 角色 Sprite 原点在脚底 (0.5,1), 站在锚点上; Container 深度=y 实现 y-sort 前景遮挡。
// 职责 (计划 §5.2): 更新可见性/死亡状态/名称标签/动画, 移动 Tween。不做世界规则判断。
// 像素约束: 整数坐标, 不做非整数缩放。

export const SPRITE_COLORS: Record<string, number> = {
  旅行者:   0x4fc3f7,
  桃音:     0xf48fb1,
  刚郎:     0xffb74d,
  小梅:     0x81c784,
  执行官:   0xe57373,
  雷电将军: 0xba68c8,
};
const BODY_W = 18;   // 血条宽 (略宽于 16px 角色)

export class AgentSprite {
  private scene: Phaser.Scene;
  private container: Phaser.GameObjects.Container;
  private char: Phaser.GameObjects.Sprite;
  private hpFill: Phaser.GameObjects.Rectangle;
  private label: Phaser.GameObjects.Text;
  private deadOverlay: Phaser.GameObjects.Text;
  private maxHealth: number;
  private activeTween: Phaser.Tweens.Tween | null = null;
  private name: string;

  constructor(scene: Phaser.Scene, name: string, x: number, y: number, maxHealth: number) {
    this.scene = scene;
    this.name = name;
    this.maxHealth = maxHealth;

    // 确保角色纹理/动画已生成 (幂等)
    if (!scene.textures.exists(`char_${name}_idleA`)) buildArt(scene);

    // 角色动画 Sprite, 原点在脚底, 站在容器原点
    this.char = scene.add.sprite(0, 0, `char_${name}_idleA`).setOrigin(0.5, 1);
    this.char.play(`idle_${name}`);

    const hpBar = scene.add.rectangle(0, -20, BODY_W + 6, 4, 0x222228);
    this.hpFill = scene.add.rectangle(-(BODY_W + 6) / 2, -20, BODY_W + 6, 4, 0x66bb6a).setOrigin(0, 0.5);
    this.label = scene.add.text(0, 8, name, {
      fontFamily: "monospace", fontSize: "12px", color: "#e8e6e3", align: "center",
    }).setOrigin(0.5, 0);
    this.deadOverlay = scene.add.text(0, -8, "✝", {
      fontFamily: "monospace", fontSize: "18px", color: "#ff5252",
    }).setOrigin(0.5, 0.5).setVisible(false);

    this.container = scene.add.container(Math.round(x), Math.round(y),
      [this.char, hpBar, this.hpFill, this.label, this.deadOverlay]);
    this.container.setDepth(Math.round(y));   // y-sort: y 越大越靠前 (前景遮挡)
    this.setHealth(maxHealth);
  }

  get x(): number { return this.container.x; }
  get y(): number { return this.container.y; }
  get gameObject(): Phaser.GameObjects.Container { return this.container; }
  // 当前播放的动画 key (idle_<name> / walk_<name>), 供 E2E 断言动画生效。
  get animKey(): string | null { return this.char.anims.currentAnim?.key ?? null; }
  get depth(): number { return this.container.depth; }

  onClick(cb: () => void): void {
    const hit = new Phaser.Geom.Rectangle(-10, -22, 20, 30);
    this.container.setInteractive({
      hitArea: hit,
      hitAreaCallback: (p: { x: number; y: number }) => hit.contains(p.x, p.y),
      useHandCursor: true,
    });
    this.container.on("pointerdown", cb);
  }

  setPosition(x: number, y: number): void {
    this.killMove();
    this.container.setPosition(Math.round(x), Math.round(y));
    this.container.setDepth(Math.round(y));
    this.char.play(`idle_${this.name}`);
  }

  // 地点变化时 Tween 走过去 (连续行走, 不瞬移), 途中播 walk, 到位回 idle。
  moveTo(x: number, y: number, duration: number): void {
    this.killMove();
    this.char.play(`walk_${this.name}`);
    this.activeTween = this.scene.tweens.add({
      targets: this.container,
      x: Math.round(x),
      y: Math.round(y),
      duration,
      ease: "Sine.easeInOut",
      onUpdate: () => this.container.setDepth(Math.round(this.container.y)),   // 移动中持续 y-sort
      onComplete: () => { this.activeTween = null; this.char.play(`idle_${this.name}`); },
    });
  }

  stopMove(): void { this.killMove(); this.char.play(`idle_${this.name}`); }

  // 暂停/恢复: 冻结 Tween + 暂停动画 (计划 §7.2-9: 暂停时动画和气泡都暂停)。
  freeze(): void {
    this.activeTween?.pause();
    this.char.anims.pause();
  }
  unfreeze(): void {
    this.activeTween?.resume();
    this.char.anims.resume();
  }

  private killMove(): void {
    if (this.activeTween) { this.activeTween.stop(); this.activeTween = null; }
  }

  setHealth(hp: number): void {
    const frac = this.maxHealth > 0 ? Math.max(0, Math.min(1, hp / this.maxHealth)) : 0;
    const w = Math.round((BODY_W + 6) * frac);
    this.hpFill.setSize(Math.max(0, w), 4);
    this.hpFill.setPosition(-(BODY_W + 6) / 2, -20);
  }

  setDead(dead: boolean): void {
    this.deadOverlay.setVisible(dead);
    this.char.setAlpha(dead ? 0.45 : 1);
    this.label.setColor(dead ? "#8a8a92" : "#e8e6e3");
    if (dead) { this.killMove(); this.char.anims.stop(); }   // 死亡停动画 (计划 §7.2-4)
  }

  setVisible(v: boolean): void { this.container.setVisible(v); }
}
