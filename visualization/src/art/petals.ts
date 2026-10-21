import Phaser from "phaser";

// 樱花花瓣: 轻量环境粒子 (不依赖 Phaser 粒子系统, 无头环境稳定)。
// 只在播放中漂移; 暂停/停在结局时冻结。深度 900: 在角色/建筑之上, HUD(1001) 之下。
interface Petal {
  img: Phaser.GameObjects.Image;
  vx: number;
  vy: number;
  phase: number;
  sway: number;
}

const COUNT = 48;

export class SakuraPetals {
  private petals: Petal[] = [];

  constructor(private scene: Phaser.Scene) {
    this.ensureTextures();
    let seed = 20261021;
    const rand = (): number => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 0xffffffff;
    };
    for (let i = 0; i < COUNT; i++) {
      const shrine = i < 30;
      const x = shrine ? 70 + rand() * 300 : rand() * 960;
      const y = shrine ? -20 + rand() * 260 : rand() * 540;
      const key = rand() < 0.5 ? "petal_a" : "petal_b";
      const img = scene.add.image(x, y, key).setDepth(900)
        .setAlpha(0.65 + rand() * 0.3)
        .setScale(1.2 + rand() * 0.8);
      this.petals.push({
        img,
        vx: 0.18 + rand() * 0.35,
        vy: 0.25 + rand() * 0.45,
        phase: rand() * Math.PI * 2,
        sway: 0.15 + rand() * 0.3,
      });
    }
  }

  private ensureTextures(): void {
    if (!this.scene.textures.exists("petal_a")) {
      const g = this.scene.make.graphics({ x: 0, y: 0 });
      g.fillStyle(0xffb7d2, 1).fillRect(0, 0, 4, 2).fillRect(1, 2, 2, 1);
      g.fillStyle(0xffd9e6, 1).fillRect(1, 0, 1, 1);
      g.generateTexture("petal_a", 4, 3);
      g.destroy();
    }
    if (!this.scene.textures.exists("petal_b")) {
      const g = this.scene.make.graphics({ x: 0, y: 0 });
      g.fillStyle(0xf7a8c4, 1).fillRect(0, 0, 3, 2).fillRect(1, 2, 1, 1);
      g.fillStyle(0xffffff, 0.8).fillRect(0, 0, 1, 1);
      g.generateTexture("petal_b", 3, 3);
      g.destroy();
    }
  }

  update(active: boolean): void {
    if (!active) return;
    for (const p of this.petals) {
      p.phase += 0.025;
      p.img.x += p.vx + Math.sin(p.phase) * p.sway;
      p.img.y += p.vy;
      if (p.img.y > 550 || p.img.x > 975) {
        p.img.x = -10 + Math.random() * 380;
        p.img.y = -10 - Math.random() * 80;
      }
    }
  }
}
