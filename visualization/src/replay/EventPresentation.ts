import type Phaser from "phaser";
import type { AgentRegistry } from "../entities/AgentRegistry";
import type { TimelineStep } from "../data/schema";
import { SpeechBubble } from "../dialogue/SpeechBubble";
import { DamagePopup } from "../dialogue/DamagePopup";
import { HUD_RECTS } from "../ui/hudRects";
import { wrapText } from "../text/wrapText";

export class EventPresentation {
  readonly actorBubble: SpeechBubble;
  readonly replyBubble: SpeechBubble;
  private damagePopup: DamagePopup;
  private worldBanner!: Phaser.GameObjects.Text;
  private convQueue: { actor: string; target?: string; utterance: string; reply?: string; }[] = [];
  private convTimer: Phaser.Time.TimerEvent | null = null;

  constructor(private scene: Phaser.Scene, private reg: AgentRegistry) {
    this.actorBubble = new SpeechBubble(this.scene, 1100);
    this.actorBubble.setOffset(-100, -10);      // 台词在左
    this.replyBubble = new SpeechBubble(this.scene, 1100);
    this.replyBubble.setOffset(100, 10);        // 回复在右, 同地点不重叠
    // 气泡避让 HUD (顶部栏/状态面板/事件记录/播放条/直播入口), 并互相避让:
    // 后显示的一方把对方已占矩形当避让区, 长台词也不会再叠在一起。
    this.actorBubble.setAvoidRects(HUD_RECTS);
    this.replyBubble.setAvoidRects(HUD_RECTS);
    this.actorBubble.setPeer(this.replyBubble);
    this.replyBubble.setPeer(this.actorBubble);
    this.damagePopup = new DamagePopup(this.scene);
  }

  mountBanner(): void {
    this.worldBanner = this.scene.add.text(400, 64, "", {
      fontFamily: "monospace", fontSize: "15px", color: "#ffd27a",
      stroke: "#000000", strokeThickness: 3, align: "center",
    }).setOrigin(0.5).setDepth(250).setAlpha(0);
  }

  update(): void {
    this.actorBubble.update();
    this.replyBubble.update();
  }

  render(step: TimelineStep, bigJump = false): void {
    if (bigJump) { this.cancelConvTimer(); this.actorBubble.hide(); this.replyBubble.hide(); }
    this.worldBanner.setAlpha(0);        // 世界事件横幅每步都清 (一次性法令提示, 非对话)
    this.damagePopup.clear();            // 伤害数字每步都清 (飘字, 无阅读需求)

    // 收集本步对话 → 队列, 按序播放 (前面几段不再被最后一段在绘制前覆盖)。
    const convs = step.visual_events.filter(
      (ve): ve is typeof ve & { utterance: string; } =>
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
        this.scene.tweens.add({ targets: this.worldBanner, alpha: 1, duration: 200 });
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

  private playConv(i: number): void {
    this.cancelConvTimer();
    if (i >= this.convQueue.length) return;
    const conv = this.convQueue[i];
    const actor = this.reg.get(conv.actor);
    const target = conv.target ? this.reg.get(conv.target) : undefined;
    if (actor) {
      this.actorBubble.setAnchor(actor.gameObject, actor.charHeight);
      this.actorBubble.show(conv.utterance, conv.actor === "旅行者" ? "player" : "npc");
    }
    if (target && conv.reply) {
      this.replyBubble.setAnchor(target.gameObject, target.charHeight);
      this.replyBubble.show(conv.reply, "npc");
    } else {
      this.replyBubble.hide();   // 无回复 → 清掉上一段旧回复, 防错配
    }
    if (i < this.convQueue.length - 1) {
      // 停留时长随台词长度 (每字 ~250ms, 夹 2~6s), 长台词读得完。
      const dwell = Math.min(6000, Math.max(2000, conv.utterance.length * 250));
      this.convTimer = this.scene.time.delayedCall(dwell, () => this.playConv(i + 1));
    }
  }

  private cancelConvTimer(): void {
    if (this.convTimer) { this.convTimer.destroy(); this.convTimer = null; }
  }

  private floatSystem(spr: { x: number; y: number; }, text: string): void {
    const t = this.scene.add.text(spr.x, spr.y - 34, text, {
      fontFamily: "monospace", fontSize: "12px", color: "#ffd27a",
      stroke: "#000000", strokeThickness: 2,
    }).setOrigin(0.5).setDepth(208);
    this.scene.tweens.add({
      targets: t, y: t.y - 18, alpha: 0, duration: 1400, ease: "Cubic.easeOut",
      onComplete: () => t.destroy(),
    });
  }

}
