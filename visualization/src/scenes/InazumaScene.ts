import Phaser from "phaser";
import { loadTimeline } from "../data/timelineLoader";
import { PlaybackController } from "../PlaybackController";
import { AgentRegistry } from "../entities/AgentRegistry";
import { LOCATION_ANCHORS, anchorOf } from "../data/locationAnchors";
import { StatusPanel } from "../ui/StatusPanel";
import { EventLog } from "../ui/EventLog";
import { PlaybackControls } from "../ui/PlaybackControls";
import type { Timeline, TimelineStep } from "../data/schema";

// InazumaScene — M1 单场景回放器 (地图 + 实体 + HUD + 播放控制全在一个场景)。
// 单场景避免多场景时钟不进更新相位的问题 (timer/tween 可靠 tick)。
// create() 异步加载 timeline, 成功后建地图/实体/HUD/controller 并开始显示第 0 步。
// 消费 visual_events (结构化事实源), 地点变化 Tween 移动, 死亡/结局有视觉提示。
export class InazumaScene extends Phaser.Scene {
  private reg!: AgentRegistry;
  private panel!: StatusPanel;
  private log!: EventLog;
  private controller!: PlaybackController;
  private prevLoc: Map<string, string> = new Map();
  private lastAppliedIndex = -1;
  private loadingText!: Phaser.GameObjects.Text;

  constructor() { super("Inazuma"); }

  create(): void {
    this.loadingText = this.add.text(480, 270, "加载稻妻城时间线…", {
      fontFamily: "monospace", fontSize: "16px", color: "#b08d57",
      align: "center", wordWrap: { width: 760 },
    }).setOrigin(0.5);
    loadTimeline("stub_timeline.json")
      .then((tl) => this.setup(tl))
      .catch((e: unknown) => {
        this.loadingText.setText("时间线加载失败:\n" + String(e) +
          "\n\n请确认 public/stub_timeline.json 存在。\n" +
          "可运行: .venv/bin/python visualization/tools/gen_stub_timeline.py");
      });
  }

  private setup(tl: Timeline): void {
    this.loadingText.destroy();
    const day0 = tl.steps[0].states;

    // 占位地图: 每个地点一个色块 + 标签 (M1 用色块代替真实 Tiled 地图)
    for (const a of Object.values(LOCATION_ANCHORS)) {
      this.add.rectangle(a.x, a.y, a.w, a.h, a.color).setStrokeStyle(2, 0x666677).setAlpha(0.85);
      this.add.text(a.x, a.y - a.h / 2 - 8, a.label, {
        fontFamily: "monospace", fontSize: "13px", color: "#cfc6b8",
      }).setOrigin(0.5, 1);
    }

    // 实体注册表 (day-0 为初始注册表 + 满血参考), 记录初始地点
    this.reg = new AgentRegistry(this, day0);
    for (const [name, s] of Object.entries(day0)) this.prevLoc.set(name, s.loc);
    this.lastAppliedIndex = -1;

    // HUD: 状态面板 (右上) / 事件日志 (左下) / 播放控制 (底部)
    this.panel = new StatusPanel(this, 840, 150, 230, 270);
    this.log = new EventLog(this, 270, 430, 480, 100);
    this.controller = new PlaybackController(this, tl);
    new PlaybackControls(this, this.controller, 270, 512);

    // 订阅: 步变化 → 应用状态 + 重绘 HUD; 运输态变化 → 冻结/解冻 Tween
    this.controller.subscribe(
      (step) => { this.applyStep(step); this.panel.update(step, tl); this.log.update(step.visual_events); },
      () => { if (this.controller.isPlaying) this.reg.unfreezeAll(); else this.reg.freezeAll(); },
    );
    // 应用初始步 (day 0, 落位不移动)
    this.applyStep(tl.steps[0]);
    this.panel.update(tl.steps[0], tl);
    this.log.update(tl.steps[0].visual_events);

    // E2E 调试钩子
    (window as unknown as Record<string, unknown>).__REPLAY__ = {
      controller: this.controller, timeline: tl, sprites: this.reg,
    };
  }

  private applyStep(step: TimelineStep): void {
    const reg = this.reg;
    const idx = this.controller.currentIndex;
    // 大跨度跳步 (seek): 停所有移动 Tween 并直接落位, 不残留旧动画 (计划 §7.2-10)
    const bigJump = this.lastAppliedIndex >= 0 && Math.abs(idx - this.lastAppliedIndex) > 1;
    this.lastAppliedIndex = idx;

    for (const [name, s] of Object.entries(step.states)) {
      const spr = reg.ensure(name, s);
      const prev = this.prevLoc.get(name) ?? null;
      if (bigJump) {
        spr.stopMove();
        const a = anchorOf(s.loc);
        spr.setPosition(a.x, a.y);
      } else {
        reg.applySnapshot(spr, s, prev);   // 地点变 → Tween; 否则落位 + 血量 + 死亡
      }
      this.prevLoc.set(name, s.loc);
    }
  }
}
