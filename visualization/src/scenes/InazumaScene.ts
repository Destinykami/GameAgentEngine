import Phaser from "phaser";
import { loadTimeline } from "../data/timelineLoader";
import { PlaybackController } from "../PlaybackController";
import { AgentRegistry } from "../entities/AgentRegistry";
import type { AgentSprite } from "../entities/AgentSprite";
import { LOCATION_ANCHORS, anchorOf } from "../data/locationAnchors";
import { buildArt } from "../art/ArtFactory";
import { BUILDINGS } from "../art/buildings";
import { TILEMAP_KEY } from "../art/townTiles";

// 自行 fetch tilemap 为 HTMLImageElement (无头 WebGL 下 Phaser 纹理 source.data 可能为 null,
// 直接 2D canvas drawImage 更可靠)。
function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => rej(new Error("tilemap 加载失败: " + url));
    img.src = url;
  });
}

// 可选本地原神像素头像。Vite 构建期 __OFFICIAL_PORTRAITS__ 为 false 时完全不请求,
// 避免目录缺失时的 404/console 错误; 素材仅本地个人学习用 (见 OFFICIAL_PORTRAITS.md)。
async function loadPortraits(): Promise<Map<string, HTMLImageElement>> {
  const out = new Map<string, HTMLImageElement>();
  if (!__OFFICIAL_PORTRAITS__) return out;
  await Promise.all(Object.entries(PORTRAIT_FILES).map(async ([name, file]) => {
    try { out.set(name, await loadImage(portraitUrl(file))); } catch { /* 单张缺失则跳过 */ }
  }));
  return out;
}
import { defaultActivity, isInterrupted } from "../data/activityProjection";
import { PORTRAIT_FILES, portraitTextureKey, portraitUrl } from "../data/avatarAssets";
import { LiveSource, type LiveMeta } from "../data/liveSource";
import { wrapText } from "../text/wrapText";
import { StatusPanel } from "../ui/StatusPanel";
import { EventLog } from "../ui/EventLog";
import { PlaybackControls } from "../ui/PlaybackControls";
import { SpeechBubble } from "../dialogue/SpeechBubble";
import { DamagePopup } from "../dialogue/DamagePopup";
import { DetailCard } from "../ui/DetailCard";
import { TimelineScrubber } from "../ui/TimelineScrubber";
import { HUD_RECTS } from "../ui/hudRects";
import type { AgentSnapshot, Timeline, TimelineStep } from "../data/schema";

// InazumaScene — 单场景回放器: 地图+实体+HUD+播放+M2 交互 (气泡/详情卡/时间轴/伤害)。
// 单场景避免多场景时钟不进更新相位 (timer/tween 可靠 tick)。
// create() 异步加载 timeline, 成功后建地图/实体/HUD/controller/M2 组件并显示第 0 步。
// 消费 visual_events (结构化事实源): 地点变化 Tween 移动, 成功对话气泡, 成功攻击伤害,
// 系统效果浮动提示, 世界事件横幅。只读, 不修改世界状态。
// 同地点错开间距: 多个 NPC 在同一地点时左右站开 (16px 角色 + 余量), 避免人物重合。
const AGENT_SPACING = 30;
export class InazumaScene extends Phaser.Scene {
  private reg!: AgentRegistry;
  private panel!: StatusPanel;
  private log!: EventLog;
  private controller!: PlaybackController;
  private prevLoc: Map<string, string> = new Map();
  private lastAppliedIndex = -1;
  private loadingText!: Phaser.GameObjects.Text;

  // M2 交互组件
  private actorBubble!: SpeechBubble;   // 行动者台词
  private replyBubble!: SpeechBubble;   // 目标回复
  // 对话队列: 同一步多段对话按序播放 (不再互相覆盖), 每段停留后切下一段。
  private convQueue: { actor: string; target?: string; utterance: string; reply?: string }[] = [];
  private convTimer: Phaser.Time.TimerEvent | null = null;
  private damagePopup!: DamagePopup;    // 受击伤害数字
  private detailCard!: DetailCard;      // 点击实体详情卡
  private scrubber!: TimelineScrubber;  // 时间轴拖拽
  private controls!: PlaybackControls;  // 播放控制 (进度文本 E2E 可读)
  private worldBanner!: Phaser.GameObjects.Text;   // 世界事件横幅

  // Phase 3 视觉活动投影状态: 巡逻 (执行官往返两点) + 坐镇特效 (将军光环)
  private patrol: { name: string; loc: string; a: { x: number; y: number }; b: { x: number; y: number }; atA: boolean } | null = null;
  private stationAura: Phaser.GameObjects.Arc | null = null;

  // 直播模式 (?live): 轮询 live.jsonl 实时跟随运行中的模拟, 跑完切回放。
  private live: LiveSource | null = null;
  private liveBadge: Phaser.GameObjects.Text | null = null;
  private liveTimer: Phaser.Time.TimerEvent | null = null;
  private liveSetupDone = false;   // setup() 是否已用直播数据建好场景
  private liveDone = false;        // 收到 __done__ 行 (模拟结束)
  private liveStepCount = 0;       // 已摄入的 step 数 (不含 meta 行)
  private liveHint: { x: number; y: number; w: number; h: number } | null = null;   // 普通页「直播模式」提示命中区

  constructor() { super("Inazuma"); }

  // 预加载 Kenney "Tiny Town" (CC0) tilemap, 供 buildArt 烘焙真实 tile。
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
    const ttImgPromise = loadImage("assets/tiny-town-tilemap.png");   // tilemap 立即开始加载 (两种模式共用)
    const portraitPromise = loadPortraits();                          // 本地原神像素头像 (可选)
    if (isLive) {
      // 直播模式 (?live): 轮询 live.jsonl 实时跟随运行中的模拟 (见 M5 扩展)。
      this.loadingText.setText("等待模拟开始… (直播模式, 轮询 live.jsonl)");
      this.live = new LiveSource("live.jsonl");
      this.showLiveBadge();
      this.startLivePolling(ttImgPromise, portraitPromise);
      return;
    }
    // 默认回放 stub 时间线; ?timeline=<file> 可回放其它样本 (如 real_timeline.json 旧格式真实样本, M5)。
    const tlFile = params.get("timeline") ?? "stub_timeline.json";
    this.addLiveHint();   // 普通回放页常驻提示: 点它进直播模式 (?live), 实时看运行中的模拟
    Promise.all([loadTimeline(tlFile), ttImgPromise, portraitPromise])
      .then(([tl, ttImg, portraits]) => this.setup(tl, ttImg, portraits))
      .catch((e: unknown) => {
        this.loadingText.setText("加载失败:\n" + String(e) +
          "\n\n请确认 public/stub_timeline.json 与 public/assets/tiny-town-tilemap.png 存在。");
      });
  }

  // 普通回放页 (非 ?live) 左上角常驻「● 直播模式」提示。场景级 pointerdown 命中它 →
  // 跳转 ?live (实时跟随运行中的模拟)。不靠 per-object input (此环境不可靠)。
  private addLiveHint(): void {
    // y=44: 在时间轴命中区 (y≈8-32) 之下、sprite 锚点 (y≥180) 之上, 避免与时间轴拖拽/点选冲突
    const x = 10, y = 44, w = 150, h = 22;
    this.liveHint = { x, y, w, h };
    this.add.rectangle(x + w / 2, y + h / 2, w, h, 0x1c2b22).setStrokeStyle(1, 0x4a7a5a).setDepth(1200);
    this.add.text(x + w / 2, y + h / 2, "● 直播模式 /?live", {
      fontFamily: "monospace", fontSize: "11px", color: "#7ec67e",
    }).setOrigin(0.5).setDepth(1201);
  }

  // 直播模式: 每 1s 轮询 live.jsonl。收到 meta + ≥1 步 → 建场景并跳到最新步跟随;
  // 之后每来新步 → addStep + 时间轴增刻度 + 跳到最新 (跟随); 收到 done → 停止轮询、
  // 隐藏 LIVE 标记, 时间线完整可往回拖 (切回普通回放)。
  private startLivePolling(ttImgPromise: Promise<HTMLImageElement>, portraitPromise: Promise<Map<string, HTMLImageElement>>): void {
    this.liveTimer = this.time.addEvent({
      delay: 1000, loop: true,
      callback: async () => {
        if (!this.live || this.liveDone) return;
        const { meta, newSteps, done } = await this.live.poll();
        this.liveStepCount = this.live.stepCount;
        let setupThisPoll = false;
        // 1) 首次收到 meta + ≥1 步 → 建场景。时间线用 buildLiveTimeline 拷贝 allSteps
        //    (已含本 poll 的 newSteps), 故本轮不再 addStep (setupThisPoll 防重复)。
        if (!this.liveSetupDone && meta && this.liveStepCount >= 1) {
          const [ttImg, portraits] = await Promise.all([ttImgPromise, portraitPromise]);
          this.setup(this.buildLiveTimeline(meta), ttImg, portraits);
          this.liveSetupDone = true;
          setupThisPoll = true;
          this.controller.seek(this.controller.totalSteps - 1);   // 跳到最新步跟随
        }
        // 2) 后续 poll 的新步: addStep + 时间轴增刻度 + 跟随最新。
        if (this.liveSetupDone && !setupThisPoll && newSteps.length > 0) {
          for (const s of newSteps) this.controller.addStep(s);
          this.scrubber.grow();
          this.controller.seek(this.controller.totalSteps - 1);   // 跟随最新步
        }
        // 3) 还没收到足够数据且未结束: 更新加载提示。
        if (!this.liveSetupDone && !done) {
          this.loadingText.setText(`等待模拟开始… (已收 ${this.liveStepCount} 步)`);
        }
        // 4) 收到 done: 停轮询、隐藏 LIVE 标记 (时间线完整, 切回普通回放可往回拖)。
        if (done) {
          this.liveDone = true;
          this.hideLiveBadge();
          this.liveTimer?.remove(false);
        }
      },
    });
  }

  // 由直播 meta 行构造 Timeline。steps 拷贝 LiveSource 已摄入的步 (setup 用它建 controller,
  // 后续新步由轮询回调 controller.addStep 增长)。
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

  // LIVE 标记 (右上, 红色脉冲)。
  private showLiveBadge(): void {
    this.liveBadge = this.add.text(940, 12, "● LIVE 直播中", {
      fontFamily: "monospace", fontSize: "13px", color: "#ff5a4a", fontStyle: "bold",
      stroke: "#000000", strokeThickness: 3,
    }).setOrigin(1, 0).setDepth(1200);
    this.tweens.add({ targets: this.liveBadge, alpha: 0.3, duration: 600, yoyo: true, repeat: -1 });
  }
  private hideLiveBadge(): void {
    if (!this.liveBadge) return;
    this.tweens.killTweensOf(this.liveBadge);
    this.liveBadge.destroy();
    this.liveBadge = null;
  }

  private setup(tl: Timeline, ttImg: HTMLImageElement, portraits: Map<string, HTMLImageElement>): void {
    this.loadingText.destroy();
    const day0 = tl.steps[0].states;

    // 本地原神像素头像 → Phaser 纹理 (64x64; UI 里缩到 20/28 显示)。
    for (const [name, img] of portraits) {
      const key = portraitTextureKey(name);
      if (this.textures.exists(key)) continue;
      const tex = this.textures.createCanvas(key, img.width, img.height);
      if (tex) { tex.context.drawImage(img, 0, 0); tex.refresh(); }
    }

    // M3 真实像素地图: 地面 (Ground) + 建筑 (Buildings) + 活动点/前景道具, 全部参与 y-sort。
    // 角色与建筑/道具同处一个深度空间, 按 y 排序 → 角色从屋顶/树后走过时正确遮挡 (计划 §M3)。
    buildArt(this, ttImg);
    this.add.image(480, 270, "ground").setOrigin(0.5, 0.5).setDepth(0);

    // 建筑: 每地点一栋, 底边锚在地点锚点略后方, 角色站在建筑前。
    const BLDG_AT: Record<string, string> = {
      稻妻主城: "inazumaMain", 治疗堂: "clinic", 锻造坊: "forge",
      眼狩署: "bureau", 神樱庭: "shrine", 城外官道: "road",
    };
    for (const [loc, bkey] of Object.entries(BLDG_AT)) {
      const a = LOCATION_ANCHORS[loc];
      const def = BUILDINGS[bkey];
      const img = this.add.image(a.x + def.anchorDx, a.y - 8 + def.anchorDy, `bldg_${bkey}`)
        .setOrigin(0.5, 1).setDepth(Math.round(a.y - 8));
      img.alpha = 0.96;
      // 地点标签 (保留, 缩小放上方)
      this.add.text(a.x, a.y - a.h / 2 - 14, a.label, {
        fontFamily: "monospace", fontSize: "11px", color: "#cfc6b8", stroke: "#000000", strokeThickness: 2,
      }).setOrigin(0.5, 1).setDepth(500);
    }
    // 活动点道具 (NPC 日常活动的锚点, 计划 Phase 3 活动投影的基础) + 前景遮挡物。
    this.prop("anvil", LOCATION_ANCHORS.锻造坊.x + 14, LOCATION_ANCHORS.锻造坊.y + 4);
    this.prop("bed", LOCATION_ANCHORS.治疗堂.x - 10, LOCATION_ANCHORS.治疗堂.y + 4);
    this.prop("desk", LOCATION_ANCHORS.稻妻主城.x - 22, LOCATION_ANCHORS.稻妻主城.y + 4);
    this.prop("torii", LOCATION_ANCHORS.神樱庭.x, LOCATION_ANCHORS.神樱庭.y + 8);
    // 樱树 (前景遮挡, 2x): 神樱庭成林 + 沿路点缀, 角色走过会被花冠遮挡
    const sx = LOCATION_ANCHORS.神樱庭.x, sy = LOCATION_ANCHORS.神樱庭.y;
    this.prop("tree", sx - 48, sy + 16, 2);
    this.prop("tree", sx - 12, sy - 6, 2);
    this.prop("tree", sx + 34, sy + 12, 2);
    this.prop("tree", sx + 62, sy - 2, 2);
    this.prop("tree", 300, 240, 2);
    this.prop("tree", 560, 420, 2);
    this.prop("tree", 760, 200, 2);
    // 松树 (点缀)
    this.prop("pine", 120, 300, 2);
    this.prop("pine", 900, 240, 2);
    // 灯笼 (路边)
    this.prop("lantern", 440, 250);
    this.prop("lantern", 700, 300);
    // 水井/木箱 (城外官道与主城点缀)
    this.prop("well", 40, 500);
    this.prop("crate", 470, 350);

    // 实体注册表 (day-0 为初始注册表 + 满血参考), 记录初始地点
    this.reg = new AgentRegistry(this, day0);
    for (const [name, s] of Object.entries(day0)) this.prevLoc.set(name, s.loc);
    this.lastAppliedIndex = -1;

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
    this.actorBubble = new SpeechBubble(this, 1100);
    this.actorBubble.setOffset(-100, -10);      // 台词在左
    this.replyBubble = new SpeechBubble(this, 1100);
    this.replyBubble.setOffset(100, 10);        // 回复在右, 同地点不重叠
    // 气泡避让 HUD (顶部栏/状态面板/事件记录/播放条/直播入口), 并互相避让:
    // 后显示的一方把对方已占矩形当避让区, 长台词也不会再叠在一起。
    this.actorBubble.setAvoidRects(HUD_RECTS);
    this.replyBubble.setAvoidRects(HUD_RECTS);
    this.actorBubble.setPeer(this.replyBubble);
    this.replyBubble.setPeer(this.actorBubble);
    this.damagePopup = new DamagePopup(this);
    this.detailCard = new DetailCard(this);
    this.scrubber = new TimelineScrubber(this, this.controller);
    this.worldBanner = this.add.text(400, 64, "", {
      fontFamily: "monospace", fontSize: "15px", color: "#ffd27a",
      stroke: "#000000", strokeThickness: 3, align: "center",
    }).setOrigin(0.5).setDepth(250).setAlpha(0);

    // 点击实体 → 详情卡 (sprite 的 onClick); 点空白 → 收起。
    // 用几何判定 (指针是否落在某 sprite 命中区内) 而非事件顺序标记, 因为 Phaser 场景级
    // 点选/详情卡: 全在场景级 pointerdown 用几何判定处理 (spriteAt 识别被点 sprite)。
    // 不用每个 sprite 的 onClick 闭包 —— 闭包捕获名字不可靠 (曾出现点谁都开旅行者卡)。
    this.input.on("pointerdown", (p: Phaser.Input.Pointer) => {
      if (this.liveHint && Math.abs(p.x - (this.liveHint.x + this.liveHint.w / 2)) <= this.liveHint.w / 2 &&
          Math.abs(p.y - (this.liveHint.y + this.liveHint.h / 2)) <= this.liveHint.h / 2) {
        window.location.href = window.location.pathname + "?live";   // 点「直播模式」提示 → 进 ?live
        return;
      }
      if (this.controls.handleClick(p.x, p.y)) return;   // 播放控制按钮 (场景级几何命中, 可靠)
      if (this.inScrubber(p.x, p.y)) { this.scrubber.onPointerDown(p.x); return; }   // 时间轴点选/拖拽
      if (this.panel.headerContainsPoint(p.x, p.y)) { this.panel.toggle(); return; }   // 点面板标题栏 → 折叠/展开
      // 点卡右上角 × → 收起 (场景级几何命中, per-object setInteractive 此环境点不动)。
      if (this.detailCard.closeAreaContainsPoint(p.x, p.y)) { this.detailCard.hide(); return; }
      // 卡内滚动: 在正文视口内按下开始拖动 (松手/移动由场景级 pointermove/up 驱动)。
      if (this.detailCard.startDrag(p.x, p.y)) return;
      if (this.detailCard.isOpen() && this.detailCard.containsPoint(p.x, p.y)) return;   // 点在卡内, 不关
      const spr = this.spriteAt(p.x, p.y);
      if (spr) {
        const name = spr.name;
        const s = this.controller.current.states[name];
        if (!s) return;
        // Phase 3 活动标签 (视觉投影): 死/被中断 → 无活动; 否则默认活动标签
        let actLabel: string | null = null;
        if (!s.dead && !isInterrupted(name, this.controller.current.visual_events)) {
          actLabel = defaultActivity(name, s.loc)?.label ?? null;
        }
        this.detailCard.show(name, s, actLabel, spr.x, spr.y);   // 卡跟随 NPC 定位
        return;
      }
      this.detailCard.hide();   // 点空白 → 收起
    });
    // 时间轴拖拽: 场景级 pointermove/up 驱动 (独立游戏对象 input 在此环境不生效)。
    // 详情卡内滚动: pointermove 拖动正文, pointerup 结束拖动; wheel 滚动卡内正文。
    this.input.on("pointermove", (p: Phaser.Input.Pointer) => {
      this.scrubber.onPointerMove(p.x);
      this.detailCard.dragTo(p.x, p.y);
    });
    this.input.on("pointerup", () => {
      this.scrubber.onPointerUp();
      this.detailCard.endDrag();
    });
    this.input.on("wheel", (p: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number) => {
      this.detailCard.handleWheel(p.x, p.y, dy);
    });

    // 订阅: 步变化 → 应用状态 + 渲染视觉事件 + 重绘 HUD + 刷新时间轴;
    //        运输态变化 → 冻结/解冻 Tween + 刷新时间轴
    this.controller.subscribe(
      (step) => {
        const bigJump = this.applyStep(step);
        this.renderVisualEvents(step, bigJump);
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
    const initialJump = this.applyStep(tl.steps[0]);
    this.renderVisualEvents(tl.steps[0], initialJump);
    this.panel.update(tl.steps[0], tl);
    this.log.update(tl.steps[0].visual_events);
    this.scrubber.refresh();

    // E2E 调试钩子 (sprites=AgentRegistry, 可 posOf/animKeyOf/depthOf)
    (window as unknown as Record<string, unknown>).__REPLAY__ = {
      controller: this.controller, timeline: tl, sprites: this.reg,
      detailCard: this.detailCard, scrubber: this.scrubber, controls: this.controls,
      bubbles: { actor: this.actorBubble, reply: this.replyBubble },
    };
  }

  // 每帧: 气泡跟随 sprite (移动 Tween 时同步)。
  // 加载 timeline 期间 (setup 未完成) 组件尚未创建, 需空值守卫, 否则每帧抛错。
  update(): void {
    if (!this.actorBubble) return;
    this.actorBubble.update();
    this.replyBubble.update();
    this.updatePatrol();                                  // Phase 3 执行官往返巡逻
    if (this.stationAura?.visible) {                       // 坐镇光环跟随将军
      const g = this.reg.get("雷电将军");
      if (g) this.stationAura.setPosition(g.x, g.y + 4);
    }
  }

  // 返回本步是否大跳转 (scrub/拖时间轴)。连续推进 (自动播放/直播/手动 next) 返回 false。
  // 场景据此决定清不清气泡/横幅: 连续推进保留气泡 (有时间读完), 大跳转清掉防残留。
  private applyStep(step: TimelineStep): boolean {
    const reg = this.reg;
    const idx = this.controller.currentIndex;
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

  // Phase 3 视觉活动投影 (计划 §Phase 3): 按角色+地点推断日常活动, 不冒充后端逐分钟模拟。
  // 死/被中断 (attack/flee/help/hide) → 停止日常活动; 否则播默认活动 (驻道具/巡逻/坐镇)。
  // talk/move/wait/conversation 不打断日计划。
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

  // 执行官巡逻: update 里检测停下瞬间切下一个巡逻点, 形成往返巡逻 (moveTo 自动播 walk)。
  private updatePatrol(): void {
    if (!this.patrol) return;
    const spr = this.reg.get(this.patrol.name);
    if (spr && !spr.isMoving) {
      const next = this.patrol.atA ? this.patrol.b : this.patrol.a;
      spr.moveTo(next.x, next.y, 1600);
      this.patrol.atA = !this.patrol.atA;
    }
  }

  // 坐镇环境特效: 将军脚下紫色脉冲光环 (坐镇观望的氛围, 非战斗)。
  private showStationAura(name: string | null): void {
    if (!name) { if (this.stationAura) { this.stationAura.setVisible(false); } return; }
    const spr = this.reg.get(name);
    if (!spr) return;
    if (!this.stationAura) {
      this.stationAura = this.add.circle(0, 0, 16, 0xba68c8, 0.28).setOrigin(0.5).setDepth(1);
      this.tweens.add({ targets: this.stationAura, scale: 1.6, alpha: 0, duration: 1400, repeat: -1, ease: "Cubic.easeOut" });
    }
    this.stationAura.setPosition(spr.x, spr.y + 4).setVisible(true).setScale(1).setAlpha(0.28);
  }

  // 渲染当前步的 visual_events (气泡/伤害/系统效果/世界事件)。
  // 事件成功后才表现副作用: success===false 的动作不显示完成态 (计划 §2.4)。
  // 同一步多段对话进队列按序播放 (不再互相覆盖, 每段停留后切下一段); 横幅/伤害每步清。
  // 连续推进 (自动播放/直播/手动 next) 无新对话时冻结最后一段对话气泡 (不推进旧队列),
  // 防直播每秒一步时气泡一闪而过。
  private renderVisualEvents(step: TimelineStep, bigJump = false): void {
    if (bigJump) { this.cancelConvTimer(); this.actorBubble.hide(); this.replyBubble.hide(); }
    this.worldBanner.setAlpha(0);        // 世界事件横幅每步都清 (一次性法令提示, 非对话)
    this.damagePopup.clear();            // 伤害数字每步都清 (飘字, 无阅读需求)

    // 收集本步对话 → 队列, 按序播放 (前面几段不再被最后一段在绘制前覆盖)。
    const convs = step.visual_events.filter(
      (ve): ve is typeof ve & { utterance: string } =>
        ve.type === "conversation" && ve.success !== false && !!ve.utterance);
    if (convs.length > 0) {
      this.convQueue = convs.map(ve => ({
        actor: ve.actor, target: ve.target, utterance: ve.utterance, reply: ve.reply,
      }));
      this.playConv(0);
    } else {
      this.cancelConvTimer();   // 无新对话: 冻结最后一段 (不推进旧队列), 保留显示防一闪而过
    }

    // 非对话事件 (系统效果浮字 / 伤害 / 世界横幅) 立即处理。
    for (const ve of step.visual_events) {
      if (ve.type === "attack" && ve.success !== false && ve.damage !== undefined) {
        const target = ve.target ? this.reg.get(ve.target) : undefined;
        if (target) this.damagePopup.push(target.x, target.y, ve.damage, !!ve.target_dead);
      } else if (ve.type === "world_event" && ve.description) {
        this.worldBanner.setText(wrapText(ve.description, 700, "15px monospace"));
        this.tweens.add({ targets: this.worldBanner, alpha: 1, duration: 200 });
      } else if (ve.type === "conversation" && ve.success !== false && ve.utterance) {
        // 系统效果浮字立即显示 (不排队, 它是事件副作用不是台词)。
        const actor = this.reg.get(ve.actor);
        if (actor) {
          if (ve.reason_added) this.floatSystem(actor, `理由 +1 (现${ve.reason_count ?? 0}条)`);
          else if (ve.weapon_attack) this.floatSystem(actor, `攻击力 → ${ve.weapon_attack}`);
          else if (ve.witnessed) this.floatSystem(actor, `目击搜捕 (理由现${ve.reason_count ?? 0}条)`);
        }
      }
    }
  }

  // 播放第 i 段对话: 显示台词 + 回复 (无回复清旧回复防错配), 停留后切下一段。
  // 最后一段停留显示 (不自动隐藏), 直到新步/大跳转替换 —— 直播每秒一步时最新对话优先。
  private playConv(i: number): void {
    this.cancelConvTimer();
    if (i >= this.convQueue.length) return;
    const conv = this.convQueue[i];
    const actor = this.reg.get(conv.actor);
    const target = conv.target ? this.reg.get(conv.target) : undefined;
    if (actor) {
      this.actorBubble.setAnchor(actor.gameObject);
      this.actorBubble.show(conv.utterance, conv.actor === "旅行者" ? "player" : "npc");
    }
    if (target && conv.reply) {
      this.replyBubble.setAnchor(target.gameObject);
      this.replyBubble.show(conv.reply, "npc");
    } else {
      this.replyBubble.hide();   // 无回复 → 清掉上一段旧回复, 防错配
    }
    if (i < this.convQueue.length - 1) {
      // 停留时长随台词长度 (每字 ~250ms, 夹 2~6s), 长台词读得完。
      const dwell = Math.min(6000, Math.max(2000, conv.utterance.length * 250));
      this.convTimer = this.time.delayedCall(dwell, () => this.playConv(i + 1));
    }
  }

  private cancelConvTimer(): void {
    if (this.convTimer) { this.convTimer.destroy(); this.convTimer = null; }
  }

  // 系统效果浮动文字 (金色, 上飘淡出), 锚在 sprite 头顶上方。
  private floatSystem(spr: { x: number; y: number }, text: string): void {
    const t = this.add.text(spr.x, spr.y - 34, text, {
      fontFamily: "monospace", fontSize: "12px", color: "#ffd27a",
      stroke: "#000000", strokeThickness: 2,
    }).setOrigin(0.5).setDepth(208);
    this.tweens.add({
      targets: t, y: t.y - 18, alpha: 0, duration: 1400, ease: "Cubic.easeOut",
      onComplete: () => t.destroy(),
    });
  }

  // 前景道具 (活动点/樱树/灯笼): 原点在脚底, 参与 y-sort (角色从其前/后走过)。
  private prop(key: string, x: number, y: number, scale = 1): void {
    this.add.image(x, y, `prop_${key}`).setOrigin(0.5, 1).setScale(scale).setDepth(Math.round(y));
  }

  // 时间轴命中区 (避免点时间轴时误收起详情卡)。顶部栏高 40, 轨道 y=27。
  private inScrubber(x: number, y: number): boolean {
    return x >= 30 && x <= 930 && y >= 4 && y <= 38;
  }

  // 几何识别被点 sprite: 命中区 (x半宽10, y -22~+8) 含指针者, 取 y-sort 最上层 (depth 最大)。
  // 不依赖 Phaser 的 per-sprite input 闭包 (曾出现命中异常/闭包捕获错名字)。
  private spriteAt(x: number, y: number): AgentSprite | null {
    let best: AgentSprite | null = null;
    let bestDepth = -Infinity;
    for (const spr of this.reg.all()) {
      const dy = y - spr.y;
      if (Math.abs(x - spr.x) <= 10 && dy >= -22 && dy <= 8 && spr.depth >= bestDepth) {
        bestDepth = spr.depth;
        best = spr;
      }
    }
    return best;
  }
}
