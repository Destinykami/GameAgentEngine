import type { Timeline, TimelineStep } from "./data/schema";
import { stepAt } from "./data/timelineLoader";

// PlaybackController (计划 §5.2): 播放/暂停、上一步/下一步、跳转到指定 step、
// 调整现实播放速度, 区分游戏时间 (step.clock) 与现实时间 (auto-advance 间隔)。
// 纯逻辑, 不持有 Phaser 渲染对象。两类回调严格分离:
//   onStep      — 任意步变化 (自动推进/手动 next/prev/seek) → 应用状态/日志/进度
//   onTransport — 播放/暂停/调速 (运输态变化) → 冻结/解冻 Tween、刷新按钮
// 手动逐步只触发 onStep, 不会把刚启动的移动 Tween 冻死 (否则逐步查看时角色不动)。
export class PlaybackController {
  private tl: Timeline;
  private index = 0;
  private playing = false;
  private speed = 1.0;
  private readonly baseInterval = 2200;   // 1x 时一步的现实毫秒
  private timer: Phaser.Time.TimerEvent | null = null;
  private scene: Phaser.Scene;
  // 支持多监听器 (场景 + PlaybackControls 都订阅): 累积而非覆盖, 否则后订阅者会
  // 盖掉前者, 导致播放自动推进时进度文本/按钮不刷新 (世界在走但"步 X/N"卡住)。
  private onStepCbs: ((step: TimelineStep) => void)[] = [];
  private onTransportCbs: (() => void)[] = [];

  constructor(scene: Phaser.Scene, tl: Timeline) {
    this.scene = scene;
    this.tl = tl;
  }

  subscribe(onStep: (step: TimelineStep) => void, onTransport: () => void): void {
    this.onStepCbs.push(onStep);
    this.onTransportCbs.push(onTransport);
  }

  private emitStep(step: TimelineStep): void { for (const cb of this.onStepCbs) cb(step); }
  private emitTransport(): void { for (const cb of this.onTransportCbs) cb(); }

  get current(): TimelineStep { return stepAt(this.tl, this.index); }
  get currentIndex(): number { return this.index; }
  get totalSteps(): number { return this.tl.steps.length; }
  get isPlaying(): boolean { return this.playing; }
  get currentSpeed(): number { return this.speed; }
  get timeline(): Timeline { return this.tl; }

  play(): void {
    if (this.playing) return;
    if (this.index >= this.tl.steps.length - 1) this.index = 0;   // 播完再 play 从头
    this.playing = true;
    this.emitTransport();
    this.startTimer();
  }

  pause(): void {
    this.playing = false;
    this.stopTimer();
    this.emitTransport();
  }

  toggle(): void { this.playing ? this.pause() : this.play(); }

  // 手动下一步 (暂停自动播放, 供逐步查看; 只 onStep, 不触发 onTransport → 不冻结 Tween)
  next(): void {
    if (this.playing) this.pause();
    if (this.index < this.tl.steps.length - 1) { this.index++; this.emitStep(this.current); }
  }

  // 手动上一步 (暂停自动播放)
  prev(): void {
    if (this.playing) this.pause();
    if (this.index > 0) { this.index--; this.emitStep(this.current); }
  }

  // 跳转到指定 step (停 Tween 残影由场景处理)
  seek(i: number): void {
    if (this.playing) this.pause();
    this.index = Math.max(0, Math.min(this.tl.steps.length - 1, i));
    this.emitStep(this.current);
  }

  setSpeed(s: number): void {
    this.speed = Math.max(0.25, Math.min(4, s));
    if (this.playing) { this.stopTimer(); this.startTimer(); }   // 调速立即生效
    this.emitTransport();
  }

  private startTimer(): void {
    this.stopTimer();
    const ms = this.baseInterval / this.speed;
    this.timer = this.scene.time.addEvent({
      delay: ms,
      loop: true,
      callback: () => {
        if (this.index < this.tl.steps.length - 1) { this.index++; this.emitStep(this.current); }
        else this.pause();   // 到末尾自动停
      },
    });
  }

  private stopTimer(): void { this.timer?.remove(false); this.timer = null; }
}
