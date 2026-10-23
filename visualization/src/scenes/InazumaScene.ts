import Phaser from "phaser";
import { loadTimeline } from "../data/timelineLoader";
import { PlaybackController } from "../PlaybackController";
import { AgentRegistry } from "../entities/AgentRegistry";
import { SakuraPetals } from "../art/petals";
import { TILEMAP_KEY } from "../art/townTiles";
import { StatusPanel } from "../ui/StatusPanel";
import { EventLog } from "../ui/EventLog";
import { PlaybackControls } from "../ui/PlaybackControls";
import { DetailCard } from "../ui/DetailCard";
import { TimelineScrubber } from "../ui/TimelineScrubber";
import type { Timeline } from "../data/schema";
import { drawWorld, loadResources, type NinjaAssets } from "./assets";
import { SnapshotProjection } from "../replay/SnapshotProjection";
import { EventPresentation } from "../replay/EventPresentation";
import { LivePlayback } from "../replay/LivePlayback";
import { addLiveHint, bindReplayInput, type LiveHint } from "../replay/input";

export class InazumaScene extends Phaser.Scene {
  private reg!: AgentRegistry;
  private panel!: StatusPanel;
  private log!: EventLog;
  private controller!: PlaybackController;
  private loadingText!: Phaser.GameObjects.Text;
  private detailCard!: DetailCard;
  private scrubber!: TimelineScrubber;
  private controls!: PlaybackControls;
  private petals: SakuraPetals | null = null;
  private projection!: SnapshotProjection;
  private presentation!: EventPresentation;
  private livePlayback: LivePlayback | null = null;
  private liveHint: LiveHint | null = null;

  constructor() { super("Inazuma"); }

  preload(): void {
    this.load.image(TILEMAP_KEY, "assets/tiny-town-tilemap.png");
  }

  create(): void {
    this.loadingText = this.add.text(480, 270, "加载稻妻城时间线…", {
      fontFamily: "monospace", fontSize: "16px", color: "#b08d57",
      align: "center", wordWrap: { width: 760 },
    }).setOrigin(0.5);
    const params = new URLSearchParams(window.location.search);
    const isLive = params.has("live");
    const resources = loadResources();
    if (isLive) {
      // 直播模式 (?live): 轮询 live.jsonl 实时跟随运行中的模拟 (见 M5 扩展)。
      this.loadingText.setText("等待模拟开始… (直播模式, 轮询 live.jsonl)");
      this.livePlayback = new LivePlayback(this, resources, {
        setup: (tl, ttImg, portraits, fullbody, ninja) => this.setup(tl, ttImg, portraits, fullbody, ninja),
        controller: () => this.controller, scrubber: () => this.scrubber, loadingText: this.loadingText,
      });
      return;
    }
    // 默认回放 stub 时间线; ?timeline=<file> 可回放其它样本 (如 real_timeline.json 旧格式真实样本, M5)。
    const tlFile = params.get("timeline") ?? "stub_timeline.json";
    this.liveHint = addLiveHint(this);   // 普通回放页常驻提示: 点它进直播模式 (?live), 实时看运行中的模拟
    Promise.all([loadTimeline(tlFile), ...resources])
      .then(([tl, ttImg, portraits, fullbody, ninja]) => this.setup(tl, ttImg, portraits, fullbody, ninja))
      .catch((e: unknown) => {
        this.loadingText.setText("加载失败:\n" + String(e) +
          "\n\n请确认 public/stub_timeline.json 与 public/assets/tiny-town-tilemap.png 存在。");
      });
  }

  private setup(tl: Timeline, ttImg: HTMLImageElement, portraits: Map<string, HTMLImageElement>, fullbody: Map<string, HTMLImageElement>, ninja: NinjaAssets | null): void {
    this.loadingText.destroy();
    const day0 = tl.steps[0].states;

    drawWorld(this, ttImg, portraits, fullbody, ninja);

    // 实体注册表 (day-0 为初始注册表 + 满血参考), 记录初始地点
    this.reg = new AgentRegistry(this, day0);
    this.projection = new SnapshotProjection(this, this.reg, day0);

    // HUD: 状态面板 (右上) / 事件日志 (左下) / 播放控制 (底部)。
    // 面板中心 y=175 (顶边 40), 在时间轴 (y 6-36) 之下 —— 标题栏可点击折叠, 不被时间轴命中区拦截。
    this.panel = new StatusPanel(this, 840, 175, 230, 270);
    this.log = new EventLog(this, 270, 430, 480, 100);
    this.controller = new PlaybackController(this, tl);
    this.controls = new PlaybackControls(this, this.controller, 270, 512);

    // M2 交互组件
    // 气泡深度 1100: 高于面板/事件框/控制条 (1001), 低于直播标记 (1200)。
    // 近右侧的对话气泡 (如神樱庭将军) 会落在世界情况面板下, 若深度低于面板会被盖住;
    // 提到面板之上 → 气泡永远画在面板上, 可读。
    this.presentation = new EventPresentation(this, this.reg);
    this.detailCard = new DetailCard(this);
    this.scrubber = new TimelineScrubber(this, this.controller);
    this.presentation.mountBanner();

    // 点击实体 → 详情卡 (sprite 的 onClick); 点空白 → 收起。
    // 用几何判定 (指针是否落在某 sprite 命中区内) 而非事件顺序标记, 因为 Phaser 场景级
    // 点选/详情卡: 全在场景级 pointerdown 用几何判定处理 (spriteAt 识别被点 sprite)。
    // 不用每个 sprite 的 onClick 闭包 —— 闭包捕获名字不可靠 (曾出现点谁都开旅行者卡)。
    bindReplayInput(this, {
      reg: this.reg, controller: this.controller, controls: this.controls,
      scrubber: this.scrubber, panel: this.panel, detailCard: this.detailCard,
      liveHint: () => this.liveHint
    });

    // 订阅: 步变化 → 应用状态 + 渲染视觉事件 + 重绘 HUD + 刷新时间轴;
    //        运输态变化 → 冻结/解冻 Tween + 刷新时间轴
    this.controller.subscribe(
      (step) => {
        const bigJump = this.projection.apply(step, this.controller.currentIndex);
        this.presentation.render(step, bigJump);
        this.panel.update(step, tl);
        this.log.update(step.visual_events);
        this.scrubber.refresh();
      },
      () => {
        if (this.controller.isPlaying) this.reg.unfreezeAll(); else this.reg.freezeAll();
        this.scrubber.refresh();
      },
    );
    // 应用初始步 (day 0)
    const initialJump = this.projection.apply(tl.steps[0], this.controller.currentIndex);
    this.presentation.render(tl.steps[0], initialJump);
    this.panel.update(tl.steps[0], tl);
    this.log.update(tl.steps[0].visual_events);
    this.scrubber.refresh();

    this.petals = new SakuraPetals(this);

    // E2E 调试钩子 (sprites=AgentRegistry, 可 posOf/animKeyOf/depthOf)
    (window as unknown as Record<string, unknown>).__REPLAY__ = {
      controller: this.controller, timeline: tl, sprites: this.reg,
      detailCard: this.detailCard, scrubber: this.scrubber, controls: this.controls,
      bubbles: { actor: this.presentation.actorBubble, reply: this.presentation.replyBubble },
      panel: this.panel, live: this.livePlayback, projection: this.projection,
    };
  }

  update(): void {
    if (!this.presentation) return;
    this.presentation.update();
    this.projection.updatePatrol();
    this.petals?.update(this.controller.isPlaying);
    this.projection.syncAura();
  }
}
