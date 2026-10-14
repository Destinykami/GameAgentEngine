import Phaser from "phaser";
import { loadTimeline } from "../data/timelineLoader";
import { PlaybackController } from "../PlaybackController";
import { AgentRegistry } from "../entities/AgentRegistry";
import { LOCATION_ANCHORS, anchorOf } from "../data/locationAnchors";
import { buildArt } from "../art/ArtFactory";
import { BUILDINGS } from "../art/buildings";
import { StatusPanel } from "../ui/StatusPanel";
import { EventLog } from "../ui/EventLog";
import { PlaybackControls } from "../ui/PlaybackControls";
import { SpeechBubble } from "../dialogue/SpeechBubble";
import { DamagePopup } from "../dialogue/DamagePopup";
import { DetailCard } from "../ui/DetailCard";
import { TimelineScrubber } from "../ui/TimelineScrubber";
import type { Timeline, TimelineStep } from "../data/schema";

// InazumaScene — 单场景回放器: 地图+实体+HUD+播放+M2 交互 (气泡/详情卡/时间轴/伤害)。
// 单场景避免多场景时钟不进更新相位 (timer/tween 可靠 tick)。
// create() 异步加载 timeline, 成功后建地图/实体/HUD/controller/M2 组件并显示第 0 步。
// 消费 visual_events (结构化事实源): 地点变化 Tween 移动, 成功对话气泡, 成功攻击伤害,
// 系统效果浮动提示, 世界事件横幅。只读, 不修改世界状态。
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
  private damagePopup!: DamagePopup;    // 受击伤害数字
  private detailCard!: DetailCard;      // 点击实体详情卡
  private scrubber!: TimelineScrubber;  // 时间轴拖拽
  private worldBanner!: Phaser.GameObjects.Text;   // 世界事件横幅

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

    // M3 真实像素地图: 地面 (Ground) + 建筑 (Buildings) + 活动点/前景道具, 全部参与 y-sort。
    // 角色与建筑/道具同处一个深度空间, 按 y 排序 → 角色从屋顶/树后走过时正确遮挡 (计划 §M3)。
    buildArt(this);
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
    // 樱树 (前景遮挡): 神樱庭周边 + 沿路, 角色走过会被花冠遮挡
    this.prop("tree", LOCATION_ANCHORS.神樱庭.x - 40, LOCATION_ANCHORS.神樱庭.y + 14);
    this.prop("tree", LOCATION_ANCHORS.神樱庭.x + 44, LOCATION_ANCHORS.神樱庭.y + 10);
    this.prop("tree", 300, 240);
    this.prop("tree", 560, 420);
    // 灯笼 (路边)
    this.prop("lantern", 440, 250);
    this.prop("lantern", 700, 300);

    // 实体注册表 (day-0 为初始注册表 + 满血参考), 记录初始地点
    this.reg = new AgentRegistry(this, day0);
    for (const [name, s] of Object.entries(day0)) this.prevLoc.set(name, s.loc);
    this.lastAppliedIndex = -1;

    // HUD: 状态面板 (右上) / 事件日志 (左下) / 播放控制 (底部)
    this.panel = new StatusPanel(this, 840, 150, 230, 270);
    this.log = new EventLog(this, 270, 430, 480, 100);
    this.controller = new PlaybackController(this, tl);
    new PlaybackControls(this, this.controller, 270, 512);

    // M2 交互组件
    this.actorBubble = new SpeechBubble(this, 200);
    this.actorBubble.setOffset(-100, -10);      // 台词在左
    this.replyBubble = new SpeechBubble(this, 200);
    this.replyBubble.setOffset(100, 10);        // 回复在右, 同地点不重叠
    this.damagePopup = new DamagePopup(this);
    this.detailCard = new DetailCard(this);
    this.scrubber = new TimelineScrubber(this, this.controller);
    this.worldBanner = this.add.text(400, 64, "", {
      fontFamily: "monospace", fontSize: "15px", color: "#ffd27a",
      stroke: "#000000", strokeThickness: 3, align: "center",
      wordWrap: { width: 640 },
    }).setOrigin(0.5).setDepth(250).setAlpha(0);

    // 点击实体 → 详情卡 (sprite 的 onClick); 点空白 → 收起。
    // 用几何判定 (指针是否落在某 sprite 命中区内) 而非事件顺序标记, 因为 Phaser 场景级
    // pointerdown 先于 sprite onClick 触发, 标记会残留误判。
    this.reg.setClickHandler((name) => {
      const s = this.controller.current.states[name];
      if (s) this.detailCard.show(name, s);
    });
    this.input.on("pointerdown", (p: Phaser.Input.Pointer) => {
      if (this.hitAnySprite(p.x, p.y)) return;   // 点的是实体, 交给其 onClick 打开详情卡
      if (this.detailCard.isOpen() && this.detailCard.containsPoint(p.x, p.y)) return;
      if (this.inScrubber(p.x, p.y)) { this.scrubber.onPointerDown(p.x); return; }   // 时间轴点选/拖拽
      this.detailCard.hide();
    });
    // 时间轴拖拽: 场景级 pointermove/up 驱动 (独立游戏对象 input 在此环境不生效)
    this.input.on("pointermove", (p: Phaser.Input.Pointer) => this.scrubber.onPointerMove(p.x));
    this.input.on("pointerup", () => this.scrubber.onPointerUp());

    // 订阅: 步变化 → 应用状态 + 渲染视觉事件 + 重绘 HUD + 刷新时间轴;
    //        运输态变化 → 冻结/解冻 Tween + 刷新时间轴
    this.controller.subscribe(
      (step) => {
        this.applyStep(step);
        this.renderVisualEvents(step);
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
    this.applyStep(tl.steps[0]);
    this.renderVisualEvents(tl.steps[0]);
    this.panel.update(tl.steps[0], tl);
    this.log.update(tl.steps[0].visual_events);
    this.scrubber.refresh();

    // E2E 调试钩子 (sprites=AgentRegistry, 可 posOf/animKeyOf/depthOf)
    (window as unknown as Record<string, unknown>).__REPLAY__ = {
      controller: this.controller, timeline: tl, sprites: this.reg,
      detailCard: this.detailCard, scrubber: this.scrubber,
      bubbles: { actor: this.actorBubble, reply: this.replyBubble },
    };
  }

  // 每帧: 气泡跟随 sprite (移动 Tween 时同步)。
  // 加载 timeline 期间 (setup 未完成) 组件尚未创建, 需空值守卫, 否则每帧抛错。
  update(): void {
    if (!this.actorBubble) return;
    this.actorBubble.update();
    this.replyBubble.update();
  }

  private applyStep(step: TimelineStep): void {
    const reg = this.reg;
    const idx = this.controller.currentIndex;
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
        reg.applySnapshot(spr, s, prev);
      }
      this.prevLoc.set(name, s.loc);
    }
  }

  // 渲染当前步的 visual_events (气泡/伤害/系统效果/世界事件)。
  // 快速跳步先清掉上一步的气泡与横幅, 不残留 (计划 §7.2-10)。
  // 事件成功后才表现副作用: success===false 的动作不显示完成态 (计划 §2.4)。
  private renderVisualEvents(step: TimelineStep): void {
    this.actorBubble.hide();
    this.replyBubble.hide();
    this.damagePopup.clear();
    this.worldBanner.setAlpha(0);

    for (const ve of step.visual_events) {
      if (ve.type === "conversation" && ve.success !== false && ve.utterance) {
        const actor = this.reg.get(ve.actor);
        const target = ve.target ? this.reg.get(ve.target) : undefined;
        if (actor) {
          this.actorBubble.setAnchor(actor.gameObject);
          this.actorBubble.show(ve.utterance, ve.actor === "旅行者" ? "player" : "npc");
        }
        if (target && ve.reply) {
          this.replyBubble.setAnchor(target.gameObject);
          this.replyBubble.show(ve.reply, "npc");
        }
        // 系统效果 → 浮动提示 (不塞进气泡正文, 计划 §4/§9.5)
        if (actor) {
          if (ve.reason_added) this.floatSystem(actor, `理由 +1 (现${ve.reason_count ?? 0}条)`);
          else if (ve.weapon_attack) this.floatSystem(actor, `攻击力 → ${ve.weapon_attack}`);
          else if (ve.witnessed) this.floatSystem(actor, `目击搜捕 (理由现${ve.reason_count ?? 0}条)`);
        }
      } else if (ve.type === "attack" && ve.success !== false && ve.damage !== undefined) {
        const target = ve.target ? this.reg.get(ve.target) : undefined;
        if (target) this.damagePopup.push(target.x, target.y, ve.damage, !!ve.target_dead);
      } else if (ve.type === "world_event" && ve.description) {
        this.worldBanner.setText(ve.description);
        this.tweens.add({ targets: this.worldBanner, alpha: 1, duration: 200 });
      }
    }
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
  private prop(key: string, x: number, y: number): void {
    this.add.image(x, y, `prop_${key}`).setOrigin(0.5, 1).setDepth(Math.round(y));
  }

  // 时间轴命中区 (避免点时间轴时误收起详情卡)。
  private inScrubber(x: number, y: number): boolean {
    return x >= 30 && x <= 930 && y >= 6 && y <= 36;
  }

  // 指针是否落在某实体命中区内 (与 AgentSprite.onClick 的 hitArea 一致: x半宽10, y -22~+8)。
  // 用于区分"点实体"(打开详情卡)与"点空白"(收起详情卡), 不依赖事件触发顺序。
  private hitAnySprite(x: number, y: number): boolean {
    for (const spr of this.reg.all()) {
      const dy = y - spr.y;
      if (Math.abs(x - spr.x) <= 10 && dy >= -22 && dy <= 8) return true;
    }
    return false;
  }
}
