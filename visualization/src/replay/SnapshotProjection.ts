import type Phaser from "phaser";
import type { AgentRegistry } from "../entities/AgentRegistry";
import { anchorOf } from "../data/locationAnchors";
import { defaultActivity, isInterrupted } from "../data/activityProjection";
import type { AgentSnapshot, TimelineStep } from "../data/schema";

const AGENT_SPACING = __OFFICIAL_FULLBODY__ ? 48 : 30;

export class SnapshotProjection {
  private prevLoc = new Map<string, string>();
  private lastAppliedIndex = -1;
  private patrol: { name: string; loc: string; a: { x: number; y: number; }; b: { x: number; y: number; }; atA: boolean; } | null = null;
  private stationAura: Phaser.GameObjects.Arc | null = null;

  constructor(private scene: Phaser.Scene, private reg: AgentRegistry, initial: Record<string, AgentSnapshot>) {
    for (const [name, snapshot] of Object.entries(initial)) this.prevLoc.set(name, snapshot.loc);
  }

  apply(step: TimelineStep, index: number): boolean {
    const reg = this.reg;
    const idx = index;
    const bigJump = this.lastAppliedIndex >= 0 && Math.abs(idx - this.lastAppliedIndex) > 1;
    this.lastAppliedIndex = idx;

    // 本步谁"仍在巡逻" (唯一排除出布局的角色): 当前巡逻者 + 未被中断 + 地点没变 + 未死。
    // 任何退出巡逻的角色 (逃跑到新地点 / 阵亡 / 同地点被战斗中断) 都要参与目标地点的错开布局,
    // 否则退出巡逻者被排除在 byLoc 外, offsetOf 算错 (独居返回 0 与他人重叠, 多人 indexOf=-1 组外偏移)。
    const stillPatrol = (name: string, s: AgentSnapshot): boolean =>
      this.patrol?.name === name
      && !isInterrupted(name, step.visual_events)
      && (this.prevLoc.get(name) ?? s.loc) === s.loc
      && !s.dead;

    // 同地点错开: 按地点分组 (按名字排序, 偏移跨步稳定不跳), 每人按组内序号左右站开。
    const byLoc = new Map<string, string[]>();
    for (const [name, s] of Object.entries(step.states)) {
      if (stillPatrol(name, s)) continue;   // 仍在巡逻: 自己往返移动, 不参与错开
      if (!byLoc.has(s.loc)) byLoc.set(s.loc, []);
      byLoc.get(s.loc)!.push(name);
    }
    for (const names of byLoc.values()) names.sort();
    const offsetOf = (name: string, loc: string): number => {
      const names = byLoc.get(loc);
      if (!names || names.length <= 1) return 0;
      const i = names.indexOf(name);
      return (i - (names.length - 1) / 2) * AGENT_SPACING;
    };

    for (const [name, s] of Object.entries(step.states)) {
      const spr = reg.ensure(name, s);
      const prev = this.prevLoc.get(name) ?? null;
      if (this.patrol?.name === name) {
        const locChanged = prev !== null && prev !== s.loc;
        const interrupted = isInterrupted(name, step.visual_events);
        if (locChanged || s.dead || interrupted) {
          // 退出巡逻 (换地点 / 阵亡 / 同地点被战斗中断): 重定位到布局位 (setPosition 内部
          // killMove 取消巡逻 tween), 再最后同步血/死 —— 顺序关键: setPosition 会重播 idle,
          // setDead 必须在其后, 否则死者被重播待机动画 (审查回归 #2)。
          const a = anchorOf(s.loc);
          spr.setPosition(a.x + offsetOf(name, s.loc), a.y);
          spr.setHealth(s.health);
          spr.setDead(s.dead);
        } else {
          // 仍在巡逻: 只更新血/死, 不重定位 (重定位会打断往返 tween)。
          reg.updateHealthDead(spr, s);
        }
      } else if (bigJump) {
        // 大跳转: 先重定位到布局位, 再同步血/死 (setDead 在 setPosition 后, 防死者重播 idle)。
        const a = anchorOf(s.loc);
        spr.setPosition(a.x + offsetOf(name, s.loc), a.y);
        spr.setHealth(s.health);
        spr.setDead(s.dead);
      } else {
        reg.applySnapshot(spr, s, prev, offsetOf(name, s.loc));
      }
      this.prevLoc.set(name, s.loc);
    }
    // Phase 3 视觉活动投影: 按 (角色, 地点, 本步是否被中断) 决定各 NPC 日常活动
    this.applyActivities(step);
    return bigJump;
  }

  private applyActivities(step: TimelineStep): void {
    let patrolName = "";
    let patrolLoc = "";
    let stationName = "";
    for (const [name, s] of Object.entries(step.states)) {
      if (s.dead) { this.reg.applyActivity(name, null); continue; }
      if (isInterrupted(name, step.visual_events)) { this.reg.applyActivity(name, null); continue; }
      const act = defaultActivity(name, s.loc);
      if (!act) { this.reg.applyActivity(name, null); continue; }
      if (act.animation === "patrol") { patrolName = name; patrolLoc = s.loc; }
      else if (act.animation === "station") { stationName = name; }
      else this.reg.applyActivity(name, act);   // 驻道具: hammer/heal/read 活动动画
    }
    // 巡逻: 执行官在巡逻地点且未被中断 → 沿两点往返 (moveTo 播 walk + update 驱动)。
    // 已在巡逻同一地点则保持 (不打断往返), 否则重新布点。
    if (patrolName) {
      const spr = this.reg.get(patrolName);
      if (!spr) { this.patrol = null; }
      else if (this.patrol && this.patrol.name === patrolName && this.patrol.loc === patrolLoc) {
        // 保持当前巡逻 (不打断往返)
      } else {
        const a = anchorOf(patrolLoc);
        this.patrol = {
          name: patrolName, loc: patrolLoc,
          a: { x: a.x - 24, y: a.y + 6 }, b: { x: a.x + 24, y: a.y + 6 }, atA: true,
        };
        spr.clearActivity();
        spr.moveTo(this.patrol.a.x, this.patrol.a.y, 900);
      }
    } else this.patrol = null;
    // 坐镇: 将军在神樱庭 → idle + 环境光环特效
    this.showStationAura(stationName || null);
  }

  updatePatrol(): void {
    if (!this.patrol) return;
    const spr = this.reg.get(this.patrol.name);
    if (spr && !spr.isMoving) {
      const next = this.patrol.atA ? this.patrol.b : this.patrol.a;
      spr.moveTo(next.x, next.y, 1600);
      this.patrol.atA = !this.patrol.atA;
    }
  }

  private showStationAura(name: string | null): void {
    if (!name) { if (this.stationAura) { this.stationAura.setVisible(false); } return; }
    const spr = this.reg.get(name);
    if (!spr) return;
    if (!this.stationAura) {
      this.stationAura = this.scene.add.circle(0, 0, 16, 0xba68c8, 0.28).setOrigin(0.5).setDepth(1);
      this.scene.tweens.add({ targets: this.stationAura, scale: 1.6, alpha: 0, duration: 1400, repeat: -1, ease: "Cubic.easeOut" });
    }
    this.stationAura.setPosition(spr.x, spr.y + 4).setVisible(true).setScale(1).setAlpha(0.28);
  }

  syncAura(): void {
    if (this.stationAura?.visible) {
      const shogun = this.reg.get("雷电将军");
      if (shogun) this.stationAura.setPosition(shogun.x, shogun.y + 4);
    }
  }
}
