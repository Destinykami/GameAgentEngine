import type Phaser from "phaser";
import type { PlaybackController } from "../PlaybackController";
import type { TimelineScrubber } from "../ui/TimelineScrubber";
import { LiveSource, type LiveMeta, type LiveIssue } from "../data/liveSource";
import type { Timeline } from "../data/schema";
import type { NinjaAssets, SceneResources } from "../scenes/assets";

interface LiveHost {
  setup: (timeline: Timeline, tilemap: HTMLImageElement, portraits: Map<string, HTMLImageElement>,
    fullbody: Map<string, HTMLImageElement>, ninja: NinjaAssets | null) => void;
  controller: () => PlaybackController;
  scrubber: () => TimelineScrubber;
  loadingText: Phaser.GameObjects.Text;
}

export class LivePlayback {
  private live: LiveSource | null = new LiveSource("live.jsonl");
  private liveBadge: Phaser.GameObjects.Text | null = null;
  private liveTimer: Phaser.Time.TimerEvent | null = null;
  private liveSetupDone = false;
  private liveDone = false;
  private liveStepCount = 0;
  private polling = false;
  private disposed = false;
  private issue: LiveIssue | null = null;
  private issueText: Phaser.GameObjects.Text | null = null;

  constructor(private scene: Phaser.Scene, private resources: SceneResources, private host: LiveHost) {
    this.showLiveBadge();
    this.startLivePolling();
    this.scene.events.once("shutdown", () => this.dispose());
  }

  status(): { done: boolean; steps: number; badgeVisible: boolean; error: LiveIssue | null; } {
    return { done: this.liveDone, steps: this.liveStepCount, badgeVisible: this.liveBadge?.visible ?? false, error: this.issue ? { ...this.issue } : null };
  }

  private startLivePolling(): void {
    this.liveTimer = this.scene.time.addEvent({
      delay: 1000, loop: true,
      callback: () => { void this.pollOnce(); },
    });
  }

  async pollOnce(): Promise<void> {
    if (!this.live || this.liveDone || this.polling || this.disposed || this.issue?.kind === "replaced") return;
    this.polling = true;
    try {
      const { meta, newSteps, done, error } = await this.live.poll();
      if (this.disposed) return;
      this.showIssue(error);
      this.liveStepCount = this.live.stepCount;
      let setupThisPoll = false;
      // 1) 首次收到 meta + ≥1 步 → 建场景。时间线用 buildLiveTimeline 拷贝 allSteps
      //    (已含本 poll 的 newSteps), 故本轮不再 addStep (setupThisPoll 防重复)。
      if (!this.liveSetupDone && meta && this.liveStepCount >= 1) {
        const [ttImg, portraits, fullbody, ninja] = await Promise.all(this.resources);
        if (this.disposed) return;
        this.host.setup(this.buildLiveTimeline(meta), ttImg, portraits, fullbody, ninja);
        this.liveSetupDone = true;
        setupThisPoll = true;
        this.host.controller().seek(this.host.controller().totalSteps - 1);   // 跳到最新步跟随
      }
      // 2) 后续 poll 的新步: addStep + 时间轴增刻度 + 跟随最新。
      if (this.liveSetupDone && !setupThisPoll && newSteps.length > 0) {
        for (const s of newSteps) this.host.controller().addStep(s);
        this.host.scrubber().grow();
        this.host.controller().seek(this.host.controller().totalSteps - 1);   // 跟随最新步
      }
      // 3) 还没收到足够数据且未结束: 更新加载提示。
      if (!this.liveSetupDone && !done) {
        this.host.loadingText.setText(`等待模拟开始… (已收 ${this.liveStepCount} 步)`);
      }
      // 4) 收到 done: 停轮询、隐藏 LIVE 标记 (时间线完整, 切回普通回放可往回拖)。
      if (done) {
        this.liveDone = true;
        this.hideLiveBadge();
        this.liveTimer?.remove(false);
        if (!this.liveSetupDone) this.host.loadingText.setText("模拟已结束（没有步骤）。");
      }
      if (error?.kind === "replaced") {
        this.liveTimer?.remove(false);
        this.hideLiveBadge();
      }
    } catch (error) {
      if (!this.disposed) this.showIssue({ kind: "parse", message: "直播显示失败：" + String(error) });
    } finally {
      this.polling = false;
    }
  }

  private showIssue(issue: LiveIssue | null): void {
    this.issue = issue;
    if (!issue) {
      this.issueText?.destroy();
      this.issueText = null;
      return;
    }
    if (!this.issueText) {
      this.issueText = this.scene.add.text(480, 42, issue.message, {
        fontFamily: "monospace", fontSize: "14px", color: "#ffcc88",
        backgroundColor: "#241c20", wordWrap: { width: 700 }, padding: { x: 8, y: 4 },
      }).setOrigin(0.5, 0).setDepth(1300);
    } else this.issueText.setText(issue.message);
  }

  dispose(): void {
    this.disposed = true;
    this.liveTimer?.remove(false);
    this.hideLiveBadge();
    this.issueText?.destroy();
    this.issueText = null;
  }

  private buildLiveTimeline(meta: LiveMeta): Timeline {
    return {
      schema_version: meta.schema_version ?? 1,
      world: meta.world ?? { name: "稻妻城", coordinate_system: "location-name", render_map: "inazuma-v1" },
      // 缺键 (旧 meta) → 默认门槛; 键为 null (B+ 涌现) → 保留 null。
      reason_needed: meta.reason_needed === undefined ? 3 : meta.reason_needed,
      attack_needed: meta.attack_needed === undefined ? 20 : meta.attack_needed,
      persuade_n: meta.persuade_n === undefined ? 3 : meta.persuade_n,
      steps: [...this.live!.allSteps],
    };
  }

  private showLiveBadge(): void {
    this.liveBadge = this.scene.add.text(940, 12, "● LIVE 直播中", {
      fontFamily: "monospace", fontSize: "13px", color: "#ff5a4a", fontStyle: "bold",
      stroke: "#000000", strokeThickness: 3,
    }).setOrigin(1, 0).setDepth(1200);
    this.scene.tweens.add({ targets: this.liveBadge, alpha: 0.3, duration: 600, yoyo: true, repeat: -1 });
  }

  private hideLiveBadge(): void {
    if (!this.liveBadge) return;
    this.scene.tweens.killTweensOf(this.liveBadge);
    this.liveBadge.destroy();
    this.liveBadge = null;
  }

}
