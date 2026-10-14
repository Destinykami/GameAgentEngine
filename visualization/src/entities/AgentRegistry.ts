import { AgentSprite } from "./AgentSprite";
import { anchorOf } from "../data/locationAnchors";
import type { AgentSnapshot } from "../data/schema";

// AgentRegistry (计划 §5.2): 按名称维护 Sprite, 将后端角色名映射到 Sprite 资源,
// 更新可见性/死亡状态/名称标签, 不做世界规则判断。
// 用 day-0 的 states 作为初始注册表 (满血参考 + 站位); 之后出现的新实体按需创建。

export class AgentRegistry {
  private sprites: Map<string, AgentSprite> = new Map();
  private scene: Phaser.Scene;
  private maxHealth: Map<string, number> = new Map();

  constructor(scene: Phaser.Scene, initialStates: Record<string, AgentSnapshot>) {
    this.scene = scene;
    for (const [name, s] of Object.entries(initialStates)) {
      this.maxHealth.set(name, Math.max(1, s.health));   // day-0 血量当满值参考
    }
    for (const [name, s] of Object.entries(initialStates)) {
      const a = anchorOf(s.loc);
      const spr = new AgentSprite(scene, name, a.x, a.y, this.maxHealth.get(name) ?? 100);
      spr.setDead(s.dead);
      this.sprites.set(name, spr);
    }
  }

  // 确保某实体有 Sprite (新实体按当前快照创建, 满血未知则用当前血量)。
  ensure(name: string, s: AgentSnapshot): AgentSprite {
    let spr = this.sprites.get(name);
    if (!spr) {
      this.maxHealth.set(name, Math.max(1, s.health));
      const a = anchorOf(s.loc);
      spr = new AgentSprite(this.scene, name, a.x, a.y, this.maxHealth.get(name) ?? 100);
      this.sprites.set(name, spr);
    }
    return spr;
  }

  get(name: string): AgentSprite | undefined { return this.sprites.get(name); }
  all(): AgentSprite[] { return [...this.sprites.values()]; }
  has(name: string): boolean { return this.sprites.has(name); }

  // E2E 断言用: 某实体的当前像素位置。
  posOf(name: string): { x: number; y: number } | null {
    const s = this.sprites.get(name);
    return s ? { x: s.x, y: s.y } : null;
  }

  // 把某实体更新到快照: 站位 (若地点变了, 由调用方决定是否 Tween)、血量、死亡。
  applySnapshot(spr: AgentSprite, s: AgentSnapshot, prevLoc: string | null): { moved: boolean; newLoc: string } {
    const a = anchorOf(s.loc);
    const moved = prevLoc !== null && prevLoc !== s.loc;
    if (moved) spr.moveTo(a.x, a.y, 600);
    else if (prevLoc === null) spr.setPosition(a.x, a.y);
    spr.setHealth(s.health);
    spr.setDead(s.dead);
    return { moved, newLoc: s.loc };
  }

  freezeAll(): void { for (const s of this.sprites.values()) s.freeze(); }
  unfreezeAll(): void { for (const s of this.sprites.values()) s.unfreeze(); }
  stopAllMoves(): void { for (const s of this.sprites.values()) s.stopMove(); }
}
