import type Phaser from "phaser";
import type { AgentRegistry } from "../entities/AgentRegistry";
import type { AgentSprite } from "../entities/AgentSprite";
import type { PlaybackController } from "../PlaybackController";
import type { StatusPanel } from "../ui/StatusPanel";
import type { DetailCard } from "../ui/DetailCard";
import type { TimelineScrubber } from "../ui/TimelineScrubber";
import type { PlaybackControls } from "../ui/PlaybackControls";
import { defaultActivity, isInterrupted } from "../data/activityProjection";

export interface LiveHint { x: number; y: number; w: number; h: number; }
interface InputParts {
  reg: AgentRegistry; controller: PlaybackController; panel: StatusPanel;
  detailCard: DetailCard; scrubber: TimelineScrubber; controls: PlaybackControls;
  liveHint: () => LiveHint | null;
}

export function bindReplayInput(scene: Phaser.Scene, parts: InputParts): void {
  scene.input.on("pointerdown", (p: Phaser.Input.Pointer) => {
    const liveHint = parts.liveHint();
    if (liveHint && Math.abs(p.x - (liveHint.x + liveHint.w / 2)) <= liveHint.w / 2 &&
      Math.abs(p.y - (liveHint.y + liveHint.h / 2)) <= liveHint.h / 2) {
      window.location.href = window.location.pathname + "?live";   // 点「直播模式」提示 → 进 ?live
      return;
    }
    if (parts.controls.handleClick(p.x, p.y)) return;   // 播放控制按钮 (场景级几何命中, 可靠)
    if (inScrubber(p.x, p.y)) { parts.scrubber.onPointerDown(p.x); return; }   // 时间轴点选/拖拽
    if (parts.panel.headerContainsPoint(p.x, p.y)) { parts.panel.toggle(); return; }   // 点面板标题栏 → 折叠/展开
    // 点卡右上角 × → 收起 (场景级几何命中, per-object setInteractive 此环境点不动)。
    if (parts.detailCard.closeAreaContainsPoint(p.x, p.y)) { parts.detailCard.hide(); return; }
    // 卡内滚动: 在正文视口内按下开始拖动 (松手/移动由场景级 pointermove/up 驱动)。
    if (parts.detailCard.startDrag(p.x, p.y)) return;
    if (parts.detailCard.isOpen() && parts.detailCard.containsPoint(p.x, p.y)) return;   // 点在卡内, 不关
    const spr = spriteAt(parts.reg, p.x, p.y);
    if (spr) {
      const name = spr.name;
      const s = parts.controller.current.states[name];
      if (!s) return;
      // Phase 3 活动标签 (视觉投影): 死/被中断 → 无活动; 否则默认活动标签
      let actLabel: string | null = null;
      if (!s.dead && !isInterrupted(name, parts.controller.current.visual_events)) {
        actLabel = defaultActivity(name, s.loc)?.label ?? null;
      }
      parts.detailCard.show(name, s, actLabel, spr.x, spr.y);   // 卡跟随 NPC 定位
      return;
    }
    parts.detailCard.hide();   // 点空白 → 收起
  });
  // 时间轴拖拽: 场景级 pointermove/up 驱动 (独立游戏对象 input 在此环境不生效)。
  // 详情卡内滚动: pointermove 拖动正文, pointerup 结束拖动; wheel 滚动卡内正文。
  scene.input.on("pointermove", (p: Phaser.Input.Pointer) => {
    parts.scrubber.onPointerMove(p.x);
    parts.detailCard.dragTo(p.x, p.y);
  });
  scene.input.on("pointerup", () => {
    parts.scrubber.onPointerUp();
    parts.detailCard.endDrag();
  });
  scene.input.on("wheel", (p: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number) => {
    parts.detailCard.handleWheel(p.x, p.y, dy);
  });

}

function inScrubber(x: number, y: number): boolean {
  return x >= 30 && x <= 930 && y >= 4 && y <= 38;
}

function spriteAt(reg: AgentRegistry, x: number, y: number): AgentSprite | null {
  let best: AgentSprite | null = null;
  let bestDepth = -Infinity;
  for (const spr of reg.all()) {
    const dy = y - spr.y;
    if (Math.abs(x - spr.x) <= 10 && dy >= -22 && dy <= 8 && spr.depth >= bestDepth) {
      bestDepth = spr.depth;
      best = spr;
    }
  }
  return best;
}

export function addLiveHint(scene: Phaser.Scene): LiveHint {
  // y=44: 在时间轴命中区 (y≈8-32) 之下、sprite 锚点 (y≥180) 之上, 避免与时间轴拖拽/点选冲突
  const x = 10, y = 44, w = 150, h = 22;
  const hint = { x, y, w, h };
  scene.add.rectangle(x + w / 2, y + h / 2, w, h, 0x1c2b22).setStrokeStyle(1, 0x4a7a5a).setDepth(1200);
  scene.add.text(x + w / 2, y + h / 2, "● 直播模式 /?live", {
    fontFamily: "monospace", fontSize: "11px", color: "#7ec67e",
  }).setOrigin(0.5).setDepth(1201);
  return hint;
}
