// e2e_playwright.mjs — 回放器端到端验证 (无头 chromium), 覆盖 M1 + M2 交互 + M3 像素地图。
// 启动 vite preview 服务 dist/, 加载页面, 用 window.__REPLAY__ 驱动 PlaybackController,
// 断言:
//   M1: 加载无错 / 6地点6实体 / 移动落锚点 / 桃音阵亡 / 结局废止
//   M2: 对话气泡 (行动者台词 + 目标回复, 锚定/文本正确) / 点击实体详情卡 / 时间轴拖拽寻址
//   M3: 像素角色播 idle/walk 动画 / y-sort 深度层级 (前景遮挡排序基础)
//   Phase3: 视觉活动投影 (刚郎锻造/桃音治疗/小梅阅读/将军坐镇, 被攻击中断, 详情卡活动标签)
//   M5: 真实 9/10 天旧格式样本回放 (中文 events 串回退解析, 31 步/day10 结局/全事件类型覆盖/不回归)
// 游戏坐标→页面坐标: Phaser FIT 缩放, 用 canvas 的 getBoundingClientRect 映射。
// 关键时刻截图到 e2e_shots/。
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = process.env.STUB_FIXTURE_PATH ?? resolve(here, "..", "public", "stub_timeline.json");
const fixture = JSON.parse(readFileSync(fixturePath, "utf-8"));
const expectedSteps = fixture.steps.length;
const expectedEnding = fixture.steps[fixture.steps.length - 1];
const SHOTS = resolve(here, "..", "e2e_shots");
mkdirSync(SHOTS, { recursive: true });

const PORT = 4173;
const errors = [];
let failures = 0;
function check(cond, msg) {
  if (cond) console.log("  ✓ " + msg);
  else { failures++; console.error("  ✗ " + msg); }
}
// 游戏逻辑坐标 (960x540) → 页面 CSS 坐标 (Phaser FIT + CENTER_BOTH)
async function gameToPage(page, gx, gy) {
  return page.evaluate(([x, y]) => {
    const canvas = window.__PHASER_GAME__.canvas;
    const r = canvas.getBoundingClientRect();
    return { px: r.left + (x / 960) * r.width, py: r.top + (y / 540) * r.height };
  }, [gx, gy]);
}

// 无头环境截图/切页会有 >500ms 停顿。Phaser TweenManager 默认的 lag smoothing 会把
// startTime 推到未来, 导致之后数秒 tween progress 恒为 0 (移动停在 walk、气泡 alpha 停在 0)。
// E2E 里关掉 smoothing (setLagSmooth() 无参 = 关闭), 让长停顿后的 delta 直接补上。
// 只影响测试页, 不改应用默认行为。
async function disableTweenLagSmooth(page) {
  await page.evaluate(() => {
    // 场景 Clock 也使用游戏循环的 delta；无头低帧率时不让平滑把墙钟等待截短。
    window.__PHASER_GAME__.loop.smoothStep = false;
    const t = window.__PHASER_GAME__.scene.getScene("Inazuma").tweens;
    if (!t) return;
    // 关闭 lag smoothing: 之后 >500ms 的停顿不再把 manager.startTime 推到未来。
    t.setLagSmooth();
    // 页面加载阶段可能已经发生过一次 lag skip, 这里把 manager 自己的计时器重置到
    // 当前时刻, 顺便清掉被推前的 nextTime; 已有 tween 会用一次较大 delta 追上。
    t.startTime = Date.now();
    t.prevTime = t.startTime;
    t.time = 0;
    t.nextTime = t.gap;
  });
}

const preview = spawn("npx", ["vite", "preview", "--port", String(PORT), "--strictPort"], {
  cwd: resolve(here, ".."), stdio: "ignore",
});
async function waitServer(url, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(url); if (r.ok) return true; } catch { /* retry */ }
    await sleep(300);
  }
  return false;
}
const up = await waitServer(`http://localhost:${PORT}/`);
if (!up) { console.error("vite preview 未就绪"); preview.kill(); process.exit(1); }
console.log("vite preview 已就绪 → http://localhost:" + PORT + "/");

// 无头 Chromium 在多标签/无窗口环境会把非前台页的 rAF 降频甚至暂停,
// 导致 Phaser 的 Tween/动画不走 (移动停在 walk、气泡 alpha 停在 0.57 等)。
// 关掉后台节流/窗口遮挡暂停, 并在每个新页显式提到前台。
const browser = await chromium.launch({
  args: [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion",
  ],
});
const page = await browser.newPage({ viewport: { width: 980, height: 560 } });
await page.bringToFront();
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + String(e)));

await page.goto(`http://localhost:${PORT}/`, { waitUntil: "load" });
await page.waitForFunction(() => window.__REPLAY__ && window.__REPLAY__.timeline, { timeout: 15000 });
await disableTweenLagSmooth(page);
await sleep(400);

console.log("\n== 1. 页面加载 (M1) ==");
check(errors.length === 0, "加载无 console/page 错误" + (errors.length ? " (" + errors.join("; ") + ")" : ""));
const tl = await page.evaluate(() => window.__REPLAY__.timeline);
check(tl.schema_version === 1, "schema_version=1");
check(Array.isArray(tl.steps) && tl.steps.length === expectedSteps, "steps 数量 " + tl.steps.length + " = 样本步数 " + expectedSteps);
const day0 = tl.steps[0].states;
check(Object.keys(day0).length === 6, "day-0 有 6 个实体");
check(Object.keys(day0).every((n) => day0[n].loc), "day-0 每实体都有 loc");

console.log("\n== 2. 初始站位 (M1) ==");
await page.screenshot({ path: resolve(SHOTS, "01_initial.png") });
// 可选本地原神像素头像: 有素材时状态面板显示, 缺失时自动隐藏 (不产生 404)。
const portraitInfo = await page.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  const count = Object.keys(s.textures.list).filter((k) => k.startsWith("portrait_")).length;
  const row = window.__REPLAY__.panel.rows.find((r) => r.name.text === "旅行者");
  return { count, visible: !!row && row.avatar.visible, key: row && row.avatar.texture.key };
});
if (portraitInfo.count > 0) {
  check(portraitInfo.visible && portraitInfo.key === "portrait_旅行者",
    "本地原神像素头像已显示 (旅行者)");
} else {
  check(true, "未安装本地原神像素头像 → 自动隐藏 (可选项)");
}
// 可选本地原神全身 Sprite: 有素材时角色高 56px, 缺失时回退 16px 原创。
const bodyInfo = await page.evaluate(() => {
  const spr = window.__REPLAY__.sprites.get("旅行者");
  return { h: spr.charHeight, anim: spr.animKey };
});
if (bodyInfo.h > 16) {
  check(bodyInfo.h === 56 && bodyInfo.anim === "idle_旅行者",
    "本地原神全身 Sprite 已启用 (高 " + bodyInfo.h + "px)");
} else {
  check(true, "未安装本地原神全身 Sprite → 回退 16px 原创角色");
}
// 环境: Ninja Adventure 日式村庄底图/建筑; 缺失则回退 Tiny Town。
const rlMap = await page.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  return { town: s.textures.exists("ninja_town"), house: s.textures.exists("ninja_house_main"), torii: s.textures.exists("ninja_torii_red"), lantern: s.textures.exists("ninja_lantern_stone"), banner: s.textures.exists("ninja_banner_red"), steps: s.textures.exists("ninja_stone_steps"), petal: s.textures.exists("petal_a") };
});
if (rlMap.town) {
  check(rlMap.house && rlMap.torii && rlMap.lantern && rlMap.banner && rlMap.steps && rlMap.petal, "Ninja 日式地图 + 建筑/鸟居/石灯笼/幟旗/石阶/樱花纹理已加载");
} else {
  check(true, "Ninja 地图缺失 → 回退 Tiny Town");
}
const initPos = await page.evaluate(() => ({
  旅行者: window.__REPLAY__.sprites.posOf("旅行者"), 雷电将军: window.__REPLAY__.sprites.posOf("雷电将军"),
}));
check(initPos.旅行者 && initPos.雷电将军, "sprite 位置可读");
console.log("    旅行者@(" + Math.round(initPos.旅行者.x) + "," + Math.round(initPos.旅行者.y) +
  ")  将军@(" + Math.round(initPos.雷电将军.x) + "," + Math.round(initPos.雷电将军.y) + ")");
// 同地点错开: day0 小梅和旅行者同在稻妻主城, 应水平错开站 (不重合)。
const overlap = await page.evaluate(() => {
  const s = window.__REPLAY__.sprites;
  const a = s.posOf("小梅"), b = s.posOf("旅行者");
  return { dx: Math.abs(a.x - b.x), dy: Math.abs(a.y - b.y) };
});
check(overlap.dx >= 20 && overlap.dy < 10,
  "同地点两人错开站 (小梅/旅行者 dx=" + overlap.dx + " dy=" + overlap.dy + ", 不重合)");

console.log("\n== 2b. M3 像素角色动画 + y-sort 遮挡 ==");
// 角色换成带 idle 动画的像素 Sprite: animKey 应为 idle_<name>; 深度应 = round(y) (y-sort 层级)。
const m3 = await page.evaluate(() => {
  const r = window.__REPLAY__.sprites;
  const p = r.posOf("旅行者");
  return { anim: r.animKeyOf("旅行者"), depth: r.depthOf("旅行者"), y: p?.y, 将军anim: r.animKeyOf("雷电将军") };
});
check(m3.anim === "idle_旅行者", "旅行者播 idle 动画 (实际 " + m3.anim + ")");
check(m3.将军anim === "idle_雷电将军", "将军播 idle 动画 (实际 " + m3.将军anim + ")");
check(m3.depth === Math.round(m3.y), "旅行者深度=round(y) y-sort 层级 (depth " + m3.depth + " = y " + Math.round(m3.y) + ")");
// 遮挡不变量: y 更大者深度更大 → 角色与建筑/樱树按 y 排序, 走过屋顶/树后正确遮挡。
check(typeof m3.depth === "number" && m3.depth > 0, "深度为正且随 y 递增 (遮挡排序基础)");

console.log("\n== 2c. Phase 3 视觉活动投影 ==");
// day0 各 NPC 按 (角色+地点) 推断日常活动: 刚郎锻造/桃音治疗/小梅阅读/将军坐镇, 被攻击则中断。
await sleep(300);   // 等活动动画起播
const act0 = await page.evaluate(() => {
  const r = window.__REPLAY__.sprites;
  return { 刚郎: r.animKeyOf("刚郎"), 桃音: r.animKeyOf("桃音"), 小梅: r.animKeyOf("小梅"), 将军: r.animKeyOf("雷电将军") };
});
check(act0.刚郎 === "hammer_刚郎", "刚郎@锻造坊 播锻造锤击 (实际 " + act0.刚郎 + ")");
check(act0.桃音 === "heal_桃音", "桃音@治疗堂 播治疗 (实际 " + act0.桃音 + ")");
check(act0.小梅 === "read_小梅", "小梅@稻妻主城 播阅读 (实际 " + act0.小梅 + ")");
check(act0.将军 === "idle_雷电将军", "将军@神樱庭 坐镇待机 (实际 " + act0.将军 + ")");
// 详情卡显示活动 (视觉投影): 点刚郎 → 活动=锻造武器 (视觉投影)
const gl = await page.evaluate(() => window.__REPLAY__.sprites.posOf("刚郎"));
const glPage = await gameToPage(page, gl.x, gl.y);
await page.mouse.click(glPage.px, glPage.py);
await sleep(150);
const glCard = await page.evaluate(() => ({ name: window.__REPLAY__.detailCard.nameShown(), act: window.__REPLAY__.detailCard.activityShown() }));
check(glCard.name === "刚郎", "点刚郎 → 详情卡名字=刚郎 (实际 " + glCard.name + ")");
check(glCard.act === "锻造武器", "详情卡活动=锻造武器 (视觉投影) (实际 " + glCard.act + ")");
await page.screenshot({ path: resolve(SHOTS, "08_activity.png") });
// 收起并回 day0 (不污染后续依赖 day0 坐标的段落)
await page.evaluate(() => { window.__REPLAY__.detailCard.hide(); window.__REPLAY__.controller.seek(0); });
await sleep(200);

console.log("\n== 3. 点击实体详情卡 (M2) ==");
// 点击旅行者 (day0 在稻妻主城), 断言详情卡打开且内容正确
const tv = initPos.旅行者;
const tvPage = await gameToPage(page, tv.x, tv.y);
await page.mouse.click(tvPage.px, tvPage.py);
await sleep(150);
const card = await page.evaluate(() => {
  const c = window.__REPLAY__.detailCard;
  return { open: c.isOpen(), name: c.nameShown(), snap: c.snapshotShown() };
});
check(card.open === true, "点击旅行者 → 详情卡打开");
check(card.name === "旅行者", "详情卡显示名字=旅行者");
check(card.snap && card.snap.loc === "稻妻主城", "详情卡地点=稻妻主城 (实际 " + (card.snap?.loc) + ")");
check(card.snap && card.snap.health === 300, "详情卡血量=300 (实际 " + (card.snap?.health) + ")");
check(card.snap && card.snap.kind === "player", "详情卡类型=player");
await page.screenshot({ path: resolve(SHOTS, "05_detail_card.png") });
// 点空白处收起 (卡跟随旅行者 ~601,330, (700,300) 落卡内 → 改点卡外安全位 (50,120))
const emptyPage = await gameToPage(page, 50, 120);
await page.mouse.click(emptyPage.px, emptyPage.py);
await sleep(100);
check(await page.evaluate(() => window.__REPLAY__.detailCard.isOpen() === false), "点空白 → 详情卡收起");
// 点卡右上角 × → 收起 (场景级几何命中, per-object setInteractive 此环境点不动)
const tv2 = await page.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  const tv = window.__REPLAY__.sprites.get("旅行者");
  window.__REPLAY__.detailCard.show("旅行者", window.__REPLAY__.controller.current.states["旅行者"], null, tv.x, tv.y);
  return { cx: window.__REPLAY__.detailCard.root.x, top: window.__REPLAY__.detailCard.root.y - window.__REPLAY__.detailCard.bg.height / 2 };
});
const xPage = await gameToPage(page, tv2.cx + 126 - 14, tv2.top + 12);   // × 区 (卡右上角), 转页面坐标
await page.mouse.click(xPage.px, xPage.py);
await sleep(100);
check(await page.evaluate(() => window.__REPLAY__.detailCard.isOpen() === false), "点 × → 详情卡收起");
// 详情卡长理由不溢出: 手动换行 + 布局修正 (背景居中, 行从名字下方排), 所有行落在背景内。
// 防回归: 长理由曾折行后顶出背景底边 (掉到卡外/压事件日志), 横向也顶出 252 卡宽。
const cardFit = await page.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  const LONG_REASON = "目击执行官在稻妻主城当众收缴持眼者的神之眼, 持眼者被拖走时苦苦哀求却无人敢拦, 眼狩令的暴行昭然若揭。";
  window.__REPLAY__.detailCard.show("旅行者", { name: "旅行者", health: 300, attack: 20, loc: "稻妻主城", dead: false,
    role: "traveler", kind: "player", reasons: [LONG_REASON, "帮助桃音藏好雷神之眼"] }, "游历", 300, 300);
  // 行现在在 content 容器里; textBounds 会加上 content.y, 比只遍历 root.list 完整。
  const b = window.__REPLAY__.detailCard.textBounds();
  const bg = window.__REPLAY__.detailCard.bg;
  return {
    maxRight: Math.round(b.maxRight), maxBottom: Math.round(b.maxBottom),
    bgRight: Math.round(window.__REPLAY__.detailCard.root.x + bg.width / 2),
    bgBottom: Math.round(window.__REPLAY__.detailCard.root.y + bg.height / 2),
  };
});
check(cardFit.maxRight <= cardFit.bgRight, "详情卡长理由不横向溢出 (最右 " + cardFit.maxRight + " ≤ " + cardFit.bgRight + ")");
check(cardFit.maxBottom <= cardFit.bgBottom, "详情卡长理由不竖向溢出 (最底 " + cardFit.maxBottom + " ≤ " + cardFit.bgBottom + ")");

console.log("\n== 3b. 详情卡内滚动 ==");
const scrollSetup = await page.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  const LONG = "目击执行官在稻妻主城当众收缴持眼者的神之眼, 持眼者被拖走时苦苦哀求却无人敢拦, 眼狩令的暴行昭然若揭。";
  window.__REPLAY__.detailCard.show("旅行者", { name: "旅行者", health: 300, attack: 20, loc: "稻妻主城", dead: false,
    role: "traveler", kind: "player", reasons: [LONG, LONG, LONG, LONG, LONG] }, "游历", 625, 330);
  return {
    scrollable: window.__REPLAY__.detailCard.isScrollable(), info: window.__REPLAY__.detailCard.scrollInfo(),
    cx: window.__REPLAY__.detailCard.root.x, cy: window.__REPLAY__.detailCard.root.y, bgH: window.__REPLAY__.detailCard.bg.height,
    track: window.__REPLAY__.detailCard.scrollTrack.visible, thumb: window.__REPLAY__.detailCard.scrollThumb.visible,
  };
});
check(scrollSetup.scrollable === true, "长理由卡进入滚动模式 (scrollable=true)");
check(scrollSetup.bgH <= 320, "卡高封顶 320, 不压事件记录 (实际 " + scrollSetup.bgH + ")");
check(scrollSetup.info.contentH > scrollSetup.info.viewH,
  "内容高超过视口 (" + scrollSetup.info.contentH + " > " + scrollSetup.info.viewH + ")");
check(scrollSetup.track === true && scrollSetup.thumb === true, "滚动条可见");
const cardCenter = await gameToPage(page, scrollSetup.cx, scrollSetup.cy);
await page.mouse.move(cardCenter.px, cardCenter.py);
await page.mouse.wheel(0, 300);
await sleep(150);
const wheeled = await page.evaluate(() => window.__REPLAY__.detailCard.scrollInfo());
check(wheeled.offset > 0, "滚轮滚动卡内正文 (offset " + Math.round(wheeled.offset) + ")");
check(wheeled.offset <= wheeled.max + 0.01, "滚动偏移被 clamp 到 max (" + Math.round(wheeled.offset) + " ≤ " + Math.round(wheeled.max) + ")");
await page.screenshot({ path: resolve(SHOTS, "15_detail_scroll.png") });
// 拖动正文向上滚 (先回到顶部)
await page.evaluate(() => window.__REPLAY__.detailCard.scrollBy(-10000));
await page.mouse.move(cardCenter.px, cardCenter.py);
await page.mouse.down();
await page.mouse.move(cardCenter.px, cardCenter.py - 100, { steps: 6 });
await page.mouse.up();
await sleep(120);
const dragged = await page.evaluate(() => window.__REPLAY__.detailCard.scrollInfo());
check(dragged.offset > 0, "拖动卡内正文滚动 (offset " + Math.round(dragged.offset) + ")");
// 滚动后点 × 仍关闭
const closeAt = await page.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  return { x: window.__REPLAY__.detailCard.root.x + window.__REPLAY__.detailCard.closeBtn.x, y: window.__REPLAY__.detailCard.root.y + window.__REPLAY__.detailCard.closeBtn.y };
});
const closePage = await gameToPage(page, closeAt.x, closeAt.y);
await page.mouse.click(closePage.px, closePage.py);
await sleep(100);
check(await page.evaluate(() => window.__REPLAY__.detailCard.isOpen() === false), "滚动后点 × 仍可关闭");
await page.evaluate(() => window.__REPLAY__.detailCard.hide());

console.log("\n== 4. 逐步推进 + 移动落锚点 (M1) + walk 动画 (M3) ==");
const before = await page.evaluate(() => window.__REPLAY__.sprites.posOf("旅行者"));
// next() 同步应用本步 → moveTo() 同步切 walk; 立即读取, 避免固定 sleep 在重负载下
// 偶发错过 600ms Tween (读成 idle)。
const walkAnim = await page.evaluate(() => {
  window.__REPLAY__.controller.next();
  return window.__REPLAY__.sprites.animKeyOf("旅行者");
});
check(walkAnim === "walk_旅行者", "移动途中播 walk 动画 (实际 " + walkAnim + ")");
// 等移动 Tween 完成回 idle (轮询, 不固定 sleep; 无头环境下固定 800ms 偶发不够)
await page.waitForFunction(
  () => window.__REPLAY__.sprites.animKeyOf("旅行者") === "idle_旅行者",
  { timeout: 3000 },
).catch(() => {});
const after = await page.evaluate(() => ({
  index: window.__REPLAY__.controller.currentIndex,
  旅行者: window.__REPLAY__.sprites.posOf("旅行者"),
  step: window.__REPLAY__.controller.current,
  anim: window.__REPLAY__.sprites.animKeyOf("旅行者"),
}));
check(after.index === 1, "推进到 step 1");
check(Math.hypot(after.旅行者.x - before.x, after.旅行者.y - before.y) > 20, "旅行者移动落到治疗堂锚点");
check(after.step.states["旅行者"].loc === "治疗堂", "step1 旅行者 loc=治疗堂");
check(after.anim === "idle_旅行者", "移动到位回 idle 动画 (实际 " + after.anim + ")");
await page.screenshot({ path: resolve(SHOTS, "02_step1_moved.png") });

console.log("\n== 5. 对话气泡 (M2) ==");
// step2: 旅行者→桃音 @治疗堂, utterance + reply
await page.evaluate(() => window.__REPLAY__.controller.seek(2));
await sleep(400);   // 等气泡显示/定位
const bubbles = await page.evaluate(() => {
  const b = window.__REPLAY__.bubbles;
  const ve = window.__REPLAY__.controller.current.visual_events.find((v) => v.type === "conversation");
  return {
    actorVisible: b.actor.isVisible(), actorText: b.actor.bubbleText(),
    replyVisible: b.reply.isVisible(), replyText: b.reply.bubbleText(),
    utterance: ve?.utterance, reply: ve?.reply,
  };
});
check(bubbles.actorVisible === true, "行动者气泡可见");
check(bubbles.actorText === bubbles.utterance, "行动者气泡文本=台词 (实际 \"" + bubbles.actorText + "\")");
check(bubbles.replyVisible === true, "目标回复气泡可见");
check(bubbles.replyText === bubbles.reply, "回复气泡文本=NPC回复 (实际 \"" + bubbles.replyText + "\")");
// 长台词换行不溢出: 手动换行后背景须容得下文字 (此环境 Phaser wordWrap 失效, 靠手动 \n)。
// 防回归: 真实 LLM 长 utterance 曾因气泡按 1 行高建而溢出到框外。
const longFit = await page.evaluate(() => {
  const b = window.__REPLAY__.bubbles.actor;
  b.setAnchor(window.__REPLAY__.sprites.get("旅行者"));
  b.show("你知道眼狩令造成了什么吗？持眼者被搜捕、被收缴，我见过太多人因此家破人亡，稻妻的秩序压碎的是活生生的人。", "player");
  return b.fitInfo();
});
check(longFit.lines >= 2, "长台词手动换行成多行 (" + longFit.lines + " 行)");
check(longFit.textW <= longFit.bgW && longFit.textH <= longFit.bgH,
  "长台词气泡不溢出 (bg " + longFit.bgW + "x" + longFit.bgH + " 容 text " + longFit.textW + "x" + longFit.textH + ")");
// 气泡深度须高于世界情况面板 (1001), 近右侧对话气泡 (如神樱庭) 落在面板上不被盖住。
const bubbleDepth = await page.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  return { actor: window.__REPLAY__.bubbles.actor.root.depth, reply: window.__REPLAY__.bubbles.reply.root.depth };
});
check(bubbleDepth.actor > 1001 && bubbleDepth.reply > 1001,
  "气泡深度盖过面板 (" + bubbleDepth.actor + "/" + bubbleDepth.reply + " > 1001, 不被世界情况遮挡)");
// 事件框同样 wordWrap 失效: 手动换行 + 按框高截断, 防长对话/多事件溢出框外。
const logFit = await page.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  s.log.update([
    { type: "conversation", actor: "旅行者", target: "桃音", success: true,
      utterance: "你知道眼狩令造成了什么吗？持眼者被搜捕、被收缴，我见过太多人因此家破人亡，稻妻的秩序压碎的是活生生的人。",
      reply: "我懂你的苦，但眼狩令是将军的意志。", reply_speaker: "桃音" },
    { type: "attack", actor: "执行官", target: "小梅", success: true, damage: 30, target_dead: false },
    { type: "move", actor: "刚郎", to: "锻造坊", success: true },
  ]);
  const t = s.log.text;
  return { w: Math.round(t.width), lines: t.text.split("\n").length };
});
check(logFit.w <= 460, "事件框换行不横向溢出 (宽 " + logFit.w + " ≤ 460)");
check(logFit.lines <= 4, "事件框按框高截断 (" + logFit.lines + " 行 ≤ 4, 防竖向溢出)");
await page.screenshot({ path: resolve(SHOTS, "06_bubbles.png") });
// 跳到无对话的步, 气泡应消失 (快速跳步不留旧气泡, 计划 §7.2-10)
await page.evaluate(() => window.__REPLAY__.controller.seek(0));
await sleep(300);
const bubblesGone = await page.evaluate(() => ({
  a: window.__REPLAY__.bubbles.actor.isVisible(), r: window.__REPLAY__.bubbles.reply.isVisible(),
}));
check(bubblesGone.a === false && bubblesGone.r === false, "跳回 day0 → 对话气泡消失");
// 气泡跨连续步保留: 直播每秒推进一步, 若每步都清气泡会一闪而过来不及读。
// 连续推进 (自动播放/直播/手动 next) 保留上一条对话气泡; 只有大跳转 (scrub) 才清。
const persist = await page.evaluate(async () => {
  const rep = window.__REPLAY__;
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  const sleep2 = (ms) => new Promise((r) => setTimeout(r, ms));
  let convIdx = -1;
  for (let i = 0; i < rep.timeline.steps.length; i++) {
    if (rep.timeline.steps[i].visual_events.some((v) => v.type === "conversation" && v.utterance)) { convIdx = i; break; }
  }
  rep.controller.seek(convIdx); await sleep2(300);
  const afterConv = window.__REPLAY__.bubbles.actor.isVisible();
  rep.controller.seek(convIdx + 1); await sleep2(300);   // 连续下一步 (非对话)
  const afterNext = window.__REPLAY__.bubbles.actor.isVisible();
  return { convIdx, afterConv, afterNext };
});
check(persist.afterConv === true && persist.afterNext === true,
  "连续推进气泡保留 (对话步后可见 → 下一步仍可见, 直播不再一闪而过)");

console.log("\n== 6. 时间轴拖拽寻址 (M2) ==");
const idxBefore = await page.evaluate(() => window.__REPLAY__.controller.currentIndex);
const midPage = await gameToPage(page, 480, 20);   // 时间轴中点
await page.mouse.click(midPage.px, midPage.py);
await sleep(200);
const idxAfter = await page.evaluate(() => window.__REPLAY__.controller.currentIndex);
check(idxAfter > idxBefore, "点击时间轴中点 → 步前进 (" + idxBefore + "→" + idxAfter + ")");
check(Math.abs(idxAfter - 7) <= 1, "跳转到约中间步 (index " + idxAfter + ", 期望~7)");
// 拖拽: 按下→移动→松开
const startPage = await gameToPage(page, 60, 20);
const endPage = await gameToPage(page, 900, 20);
await page.mouse.move(startPage.px, startPage.py);
await page.mouse.down();
await page.mouse.move(endPage.px, endPage.py, { steps: 8 });
await page.mouse.up();
await sleep(200);
const idxDrag = await page.evaluate(() => window.__REPLAY__.controller.currentIndex);
check(idxDrag >= expectedSteps - 2, "拖拽到右端 → 跳到末尾附近 (index " + idxDrag + ")");
await page.screenshot({ path: resolve(SHOTS, "07_scrubber.png") });

console.log("\n== 7. 桃音阵亡 (M1) ==");
await page.evaluate(() => window.__REPLAY__.controller.seek(4));
await sleep(400);
const death = await page.evaluate(() => {
  const s = window.__REPLAY__.controller.current;
  return { 桃音: s.states["桃音"], atk: s.visual_events.find((v) => v.type === "attack" && v.target === "桃音") };
});
check(death.桃音.dead === true, "step4 桃音 dead=true");
check(death.atk && death.atk.target_dead === true, "step4 有 attack target_dead=true");
check(death.atk && typeof death.atk.damage === "number" && death.atk.damage >= 0, "attack damage 非负 (" + (death.atk?.damage) + ")");
await page.screenshot({ path: resolve(SHOTS, "03_tao_dead.png") });

console.log("\n== 8. 结局 (M1) ==");
const last = await page.evaluate(() => {
  const c = window.__REPLAY__.controller;
  c.seek(c.totalSteps - 1);
  return c.current;
});
check(last.decree_ended === expectedEnding.decree_ended, "最后一步废止状态与样本一致 (" + last.decree_ended + ")");
check(last.shogun_dead === expectedEnding.shogun_dead && last.persuade === expectedEnding.persuade,
  "将军存活与劝说进度和样本一致 (persuade=" + last.persuade + ")");
check((last.note ?? "") === (expectedEnding.note ?? ""), "末帧结局文本与样本一致");
await sleep(400);
await page.screenshot({ path: resolve(SHOTS, "04_ending.png") });

console.log("\n== 9. 活动中断 (Phase 3) ==");
// step2 桃音被执行官攻击 (非致死) → 治疗活动中断 (attack 中断日计划); 刚郎未被攻击 → 继续锻造。
await page.evaluate(() => window.__REPLAY__.controller.seek(2));
await sleep(300);
const actInt = await page.evaluate(() => ({ 桃音: window.__REPLAY__.sprites.animKeyOf("桃音"), 刚郎: window.__REPLAY__.sprites.animKeyOf("刚郎") }));
check(actInt.桃音 !== "heal_桃音", "step2 桃音被攻击 → 治疗中断 (实际 " + actInt.桃音 + ")");
check(actInt.刚郎 === "hammer_刚郎", "step2 刚郎未被攻击 → 继续锻造 (实际 " + actInt.刚郎 + ")");
await page.evaluate(() => window.__REPLAY__.controller.seek(0));

console.log("\n== 9b. 播放自动推进 + 进度条刷新 (play → 步 X/N 随步进更新) ==");
// 真实点播放 (不是手动 next/seek): timer 自动推进 step, 进度文本 "步 X/N" 必须跟着变。
// 回归防护: 此前 subscribe() 覆盖式, 场景订阅盖掉 PlaybackControls 的 refresh,
// 世界在走 (index 推进) 但底部 "步 1/14" 卡住不刷新。
const prog0 = await page.evaluate(() => window.__REPLAY__.controls.progressText());
check(/^步 1\/\d+$/.test(prog0), "播放前进度=步 1/N (实际 \"" + prog0 + "\")");
await page.evaluate(() => window.__REPLAY__.controller.play());
await sleep(150);
const playingNow = await page.evaluate(() => window.__REPLAY__.controller.isPlaying);
check(playingNow === true, "play() 后 isPlaying=true");
await sleep(6000);   // 约 2-3 步 (每步 2.2s)
const prog1 = await page.evaluate(() => ({
  text: window.__REPLAY__.controls.progressText(),
  index: window.__REPLAY__.controller.currentIndex,
}));
check(prog1.index > 0, "播放自动推进 index 前进 (0→" + prog1.index + ")");
const progNum = parseInt((prog1.text.match(/^步 (\d+)\//) || [])[1] ?? "0", 10);
check(progNum === prog1.index + 1, "进度文本随步进刷新 (实际 \"" + prog1.text + "\", index=" + prog1.index + ")");
await page.screenshot({ path: resolve(SHOTS, "09b_playback_progress.png") });
// 清理: 暂停并回 step0, 不污染后续段
await page.evaluate(() => { window.__REPLAY__.controller.pause(); window.__REPLAY__.controller.seek(0); });
await sleep(200);

console.log("\n== 10. M5 真实样本回放 (旧格式: 中文 events 串 → 回退解析) ==");
// 真实 9/10 天样本 (data/auto_sim/timeline.json → public/real_timeline.json) 无 visual_events/
// schema_version。加载器归一化 (回退解析中文串填 visual_events) 后应完整可回放, 不回归。
const page2 = await browser.newPage({ viewport: { width: 980, height: 560 } });
await page2.bringToFront();
const errors2 = [];
page2.on("console", (m) => { if (m.type() === "error") errors2.push("console: " + m.text()); });
page2.on("pageerror", (e) => errors2.push("pageerror: " + String(e)));
await page2.goto(`http://localhost:${PORT}/?timeline=real_timeline.json`, { waitUntil: "load" });
await page2.waitForFunction(() => window.__REPLAY__ && window.__REPLAY__.timeline, { timeout: 15000 });
await disableTweenLagSmooth(page2);
await sleep(400);
const real = await page2.evaluate(() => window.__REPLAY__.timeline);
check(Array.isArray(real.steps) && real.steps.length === 31, "真实样本 31 步 (实际 " + real.steps.length + ")");
const realLast = real.steps[real.steps.length - 1];
check(realLast.day === 10, "真实样本到最后 day=10 (实际 " + realLast.day + ")");
check(realLast.decree_ended === true, "真实样本结局 decree_ended=true");
check(realLast.persuade === 5, "真实样本结局 persuade=5 (实际 " + realLast.persuade + ")");
check(realLast.note && realLast.note.includes("废止"), "真实样本 note 含'废止'眼狩令");
// 事件类型覆盖: 回退解析后的 visual_events 应含 move/conversation/help/attack/flee + 死亡 + 结局
const coverage = await page2.evaluate(() => {
  const tl = window.__REPLAY__.timeline;
  const types = new Set(); let death = false, deadState = false;
  for (const s of tl.steps) {
    for (const ve of s.visual_events) {
      types.add(ve.type);
      if (ve.type === "attack" && ve.target_dead) death = true;
    }
    for (const st of Object.values(s.states)) if (st.dead) deadState = true;
  }
  return { types: [...types], death, deadState };
});
for (const t of ["move", "conversation", "help", "attack", "flee"]) {
  check(coverage.types.includes(t), "覆盖 " + t + " (实际类型: " + coverage.types.join("/") + ")");
}
check(coverage.death === true, "覆盖死亡 (有 attack target_dead=true)");
check(coverage.deadState === true, "覆盖死亡 (有实体 dead=true, 桃音)");
// UI 回放: seek 到对话步 → 气泡可见; seek 到桃音阵亡步 (step20) → dead=true
const convStep = await page2.evaluate(() => {
  const tl = window.__REPLAY__.timeline;
  return tl.steps.findIndex((s) => s.visual_events.some((v) => v.type === "conversation"));
});
await page2.evaluate((i) => window.__REPLAY__.controller.seek(i), convStep);
await sleep(400);
const realBubble = await page2.evaluate(() => ({
  a: window.__REPLAY__.bubbles.actor.isVisible(),
  text: window.__REPLAY__.bubbles.actor.bubbleText(),
}));
check(realBubble.a === true && realBubble.text.length > 0, "真实样本对话气泡可见 (文本 " + realBubble.text.length + " 字)");
await page2.screenshot({ path: resolve(SHOTS, "10_real_conv.png") });
await page2.evaluate(() => window.__REPLAY__.controller.seek(20));
await sleep(400);
const realDeath = await page2.evaluate(() => ({
  桃音: window.__REPLAY__.controller.current.states["桃音"],
  atk: window.__REPLAY__.controller.current.visual_events.find((v) => v.type === "attack" && v.target === "桃音"),
}));
check(realDeath.桃音 && realDeath.桃音.dead === true, "真实样本 step20 桃音 dead=true");
check(realDeath.atk && realDeath.atk.target_dead === true, "真实样本 step20 致死 attack target_dead=true");
await page2.screenshot({ path: resolve(SHOTS, "11_real_death.png") });
await page2.evaluate(() => window.__REPLAY__.controller.seek(window.__REPLAY__.controller.totalSteps - 1));
await sleep(400);
// 世界情况面板不溢出: 标题/页脚(长结局说明换行)/meta(血@地点) 右缘 ≤ 面板右内边 945。
// 防回归: 真实样本长 note + 4 字地点名曾把标题/页脚/meta 顶出框外。
const panelFit = await page2.evaluate(() => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  const rightInner = 945;   // 面板 (840,150,230,270) 右内边
  const texts = s.children.list.filter((o) => o.type === "Text" && o.depth === 1001
    && o.x >= 725 && o.x <= 955 && o.text.length > 0);
  let maxRight = 0; let worst = "";
  for (const t of texts) {
    const r = Math.round(t.x + t.width);
    if (r > maxRight) { maxRight = r; worst = t.text.slice(0, 12); }
  }
  return { maxRight, rightInner, worst };
});
check(panelFit.maxRight <= panelFit.rightInner,
  "世界情况面板不溢出 (最右 " + panelFit.maxRight + " ≤ " + panelFit.rightInner + ", 最宽 \"" + panelFit.worst + "…\")");
// 面板可折叠: 点标题栏 (840,52) → 收起 (只剩标题条, 让位地图/气泡); 再点 → 展开。
const panelToggle = await page2.evaluate(async () => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  const sleep2 = (ms) => new Promise((r) => setTimeout(r, ms));
  const h0 = window.__REPLAY__.panel.bg.height;
  window.__REPLAY__.panel.toggle(); await sleep2(50);
  const collapsed = window.__REPLAY__.panel.isCollapsed();
  const hCollapsed = window.__REPLAY__.panel.bg.height;
  window.__REPLAY__.panel.toggle(); await sleep2(50);
  return { h0, collapsed, hCollapsed, h1: window.__REPLAY__.panel.bg.height };
});
check(panelToggle.collapsed === true && panelToggle.hCollapsed < panelToggle.h0,
  "面板点标题栏可折叠 (收起后高度 " + Math.round(panelToggle.hCollapsed) + " < " + Math.round(panelToggle.h0) + ", 让位地图)");
check(panelToggle.h1 === panelToggle.h0, "面板再点展开 (高度恢复 " + Math.round(panelToggle.h1) + ")");
// 审查防回归 — 回放正确性: 跨步跳转同步死活 / 大跳转气泡不被旧淡出关 / 重播立即显示第0步。
const auditFix = await page2.evaluate(async () => {
  const s = window.__PHASER_GAME__.scene.getScene("Inazuma");
  const rep = window.__REPLAY__;
  const sleep2 = (ms) => new Promise((r) => setTimeout(r, ms));
  const readSprite = (name) => {
    const spr = window.__REPLAY__.sprites.get(name); if (!spr) return null;
    const list = spr.gameObject.list;
    const char = list.find((c) => c.type === "Sprite");
    const marker = list.find((c) => c.type === "Text" && c.text === "✝");
    return { alpha: char?.alpha, marker: marker?.visible };
  };
  const out = {};
  // #1 大跳转同步死活: 桃音 step20 阵亡。seek 活步 → 大跳转死步, sprite 须同步死亡
  // 且死者不重播 idle (setPosition 会 play idle, setDead 须在其后停动画)。
  rep.controller.seek(5); await sleep2(60);
  rep.controller.seek(25); await sleep2(60);
  const p25 = readSprite("桃音");
  const p25char = window.__REPLAY__.sprites.get("桃音").char;
  out.f1 = { dead: rep.controller.current.states["桃音"].dead, ...p25,
             idle: p25char.anims.isPlaying,
             ok: rep.controller.current.states["桃音"].dead === true && p25.alpha === 0.45 && p25.marker === true
                 && p25char.anims.isPlaying === false };
  // #2 大跳转气泡不被旧淡出关: 两段不同对话, 跳后新气泡须保留。查实际 Container
  // 可见性 + alpha (入场直接置 1), 不只看 isVisible() 逻辑标记 (旧淡出回调可能把 root.visible
  // 设回 false 而标记仍 true)。
  const convIdx = [];
  for (let i = 0; i < rep.timeline.steps.length; i++)
    if (rep.timeline.steps[i].visual_events.find((v) => v.type === "conversation" && v.utterance)) convIdx.push(i);
  const A = convIdx[0], B = convIdx[convIdx.length - 1];
  rep.controller.seek(A); await sleep2(160);
  const txtA = window.__REPLAY__.bubbles.actor.bubbleText();
  rep.controller.seek(B);
  const root = window.__REPLAY__.bubbles.actor.root;
  // 等 alpha 就绪 (轮询, 入场直接置 1), 再等 200ms 确认新气泡没有被旧淡出回调关掉。
  for (let i = 0; i < 40; i++) {
    if (root.visible && root.alpha > 0.9) break;
    await sleep2(50);
  }
  await sleep2(200);
  out.f2 = { txtB: window.__REPLAY__.bubbles.actor.bubbleText(), rootVisible: root.visible, rootAlpha: root.alpha,
             ok: txtA !== window.__REPLAY__.bubbles.actor.bubbleText() && root.visible === true && root.alpha > 0.9 };
  // #5 重播立即显示第 0 步: 末步 → play(), 面板须立即显示第 0 天。
  rep.controller.seek(rep.controller.totalSteps - 1); await sleep2(60);
  rep.controller.play(); await sleep2(50);
  out.f5 = { ok: window.__REPLAY__.panel.header.text.includes("第 0 天") };
  rep.controller.pause();
  // #1 同一步多段对话按序播放 (不再互相覆盖): seek 到多对话步, 先显第一段,
  // 停留 (台词长度*250ms) 后切到第二段 —— 前面几段不再被最后一段在绘制前覆盖。
  const steps = rep.timeline.steps;
  let multiIdx = -1;
  for (let i = 0; i < steps.length; i++) {
    const c = (steps[i].visual_events || []).filter((v) => v.type === "conversation" && v.success !== false && v.utterance);
    if (c.length >= 2) { multiIdx = i; break; }
  }
  rep.controller.seek(multiIdx); await sleep2(150);
  const firstLine = window.__REPLAY__.bubbles.actor.bubbleText();
  const dwell = Math.min(6000, Math.max(2000, steps[multiIdx].visual_events.find(v => v.type === "conversation" && v.success !== false && v.utterance).utterance.length * 250)) + 150;
  await sleep2(dwell);
  const secondLine = window.__REPLAY__.bubbles.actor.bubbleText();
  out.f3 = { first: firstLine.slice(0, 8), second: secondLine.slice(0, 8),
             ok: firstLine !== secondLine };
  return out;
});
check(auditFix.f1.ok, "跨步大跳转同步死活 (桃音死→半透明+死亡标记, 且死者不重播 idle)");
check(auditFix.f2.ok, "大跳转到另一段对话 → 新气泡保留 (visible=" + auditFix.f2.rootVisible +
  ", alpha=" + auditFix.f2.rootAlpha + ")");
check(auditFix.f5.ok, "结局后重播 → 立即显示第 0 步 (不再跳过第 0 步)");
check(auditFix.f3.ok, "同一步多段对话按序播放 (\"" + auditFix.f3.first + "…\" → 停留后 \"" + auditFix.f3.second + "…\", 不再被覆盖)");
await page2.screenshot({ path: resolve(SHOTS, "12_real_ending.png") });
await page2.close();

console.log("\n== 11. M5 直播跟随 (?live 运行中实时可视化) ==");
// 模拟"运行中的模拟": mock 源逐步 (700ms/步) append 到 public/live.jsonl, 前端 ?live
// 每秒轮询逐步接入并自动跟随最新步, LIVE 标记脉冲; 收到 done 行停止轮询、隐藏标记、
// 时间线完整可往回拖 (切回普通回放)。验证"运行中可视化" (不只是跑完回放)。
const liveGateDir = mkdtempSync(resolve(tmpdir(), "gameagent-live-"));
const liveReady = resolve(liveGateDir, "ready");
const mock = spawn("node", ["tools/mock_live_source.mjs"], {
  cwd: resolve(here, ".."), env: { ...process.env, LIVE_DELAY_MS: "700", LIVE_READY_PATH: liveReady }, stdio: "ignore",
});
await sleep(300);   // 等 mock 写好 meta + 首步
const page3 = await browser.newPage({ viewport: { width: 980, height: 560 } });
await page3.bringToFront();
const errors3 = [];
page3.on("console", (m) => { if (m.type() === "error") errors3.push("console: " + m.text()); });
page3.on("pageerror", (e) => errors3.push("pageerror: " + String(e)));
await page3.goto(`http://localhost:${PORT}/?live`, { waitUntil: "load" });
// 等直播场景建好 (轮询收到 meta + ≥1 步后 setup, __REPLAY__ 出现且 timeline 非空)
await page3.waitForFunction(() => window.__REPLAY__ && window.__REPLAY__.timeline
  && window.__REPLAY__.timeline.steps.length >= 1, { timeout: 20000 });
await disableTweenLagSmooth(page3);
await sleep(300);
// LIVE 标记可见 (场景里 liveBadge 文本含 "LIVE")
const liveBadgeVisible = await page3.evaluate(() => {
  const g = window.__PHASER_GAME__;
  return window.__REPLAY__.live?.status().badgeVisible ?? false;
});
check(liveBadgeVisible === true, "LIVE 直播标记可见");
writeFileSync(liveReady, "ready");   // 页面接到首步并完成素材组装后，才开始追加其余步。
// 步数随轮询增长 (mock 每 700ms 写一步, 前端 1s 轮询逐步接入)
const stepsA = await page3.evaluate(() => window.__REPLAY__.controller.totalSteps);
await sleep(2500);
const stepsB = await page3.evaluate(() => window.__REPLAY__.controller.totalSteps);
check(stepsB > stepsA, "直播逐步接入, 步数增长 (" + stepsA + " → " + stepsB + ")");
// 自动跟随最新步 (currentIndex === totalSteps - 1)
const follow = await page3.evaluate(() => {
  const c = window.__REPLAY__.controller;
  return { cur: c.currentIndex, total: c.totalSteps };
});
check(follow.cur === follow.total - 1, "自动跟随最新步 (index " + follow.cur + " = total-1)");
await page3.screenshot({ path: resolve(SHOTS, "13_live_follow.png") });
// 等实际 done 状态，允许仓库 14 步样本或重新生成的确定性样本有不同长度。
await page3.waitForFunction(() => window.__REPLAY__.live?.status().done, { timeout: 30000 });
const liveEnd = await page3.evaluate(() => ({
  total: window.__REPLAY__.controller.totalSteps,
  badge: (() => { const s = window.__PHASER_GAME__.scene.getScene("Inazuma"); return window.__REPLAY__.live?.status().badgeVisible ?? false; })(),
}));
check(liveEnd.total === expectedSteps, "直播结束时间线完整 (" + expectedSteps + " 步, 实际 " + liveEnd.total + ")");
check(liveEnd.badge === false, "收到 done → LIVE 标记隐藏 (切回普通回放)");
await page3.screenshot({ path: resolve(SHOTS, "14_live_done.png") });
await page3.close();
mock.kill();
rmSync(liveGateDir, { recursive: true, force: true });

console.log("\n== 12. 直播坏行恢复与运行替换 ==");
const page4 = await browser.newPage({ viewport: { width: 980, height: 560 } });
const errors4 = [];
page4.on("pageerror", e => errors4.push(String(e)));
const livePrefix = JSON.stringify({ __meta__: true, schema_version: 1, run_id: "fault-test-1" }) + "\n";
let liveData = livePrefix + JSON.stringify(fixture.steps[0]) + "\nbad-json\n";
await page4.route("**/live.jsonl?*", route => route.fulfill({ status: 200, body: liveData }));
await page4.goto(`http://localhost:${PORT}/?live`, { waitUntil: "load" });
await page4.waitForFunction(() => window.__REPLAY__?.live?.status().error?.kind === "parse");
check(await page4.evaluate(() => window.__REPLAY__.controller.totalSteps === 1), "坏行阻塞，保留已成功摄入的首步");
await page4.screenshot({ path: resolve(SHOTS, "15_live_parse_error.png") });
liveData = livePrefix + JSON.stringify(fixture.steps[0]) + "\n" + JSON.stringify(fixture.steps[1]) + "\n";
await page4.waitForFunction(() => window.__REPLAY__.controller.totalSteps === 2 && !window.__REPLAY__.live.status().error);
check(true, "坏行修复后继续摄入且清除提示");
liveData = JSON.stringify({ __meta__: true, schema_version: 1, run_id: "fault-test-2" }) + "\n" + JSON.stringify(fixture.steps[0]) + "\n";
await page4.waitForFunction(() => window.__REPLAY__.live.status().error?.kind === "replaced");
check(await page4.evaluate(() => window.__REPLAY__.controller.totalSteps === 2), "新运行不混入原时间线，提示重新加载");
check(errors4.length === 0, "直播异常页无 page 错误");
await page4.screenshot({ path: resolve(SHOTS, "16_live_replaced.png") });
await page4.close();

console.log("\n== 12. 无残留错误 (stub + 真实样本 + 直播三页) ==");
check(errors.length === 0, "stub 页全程无 console/page 错误" + (errors.length ? " (" + errors.join("; ") + ")" : ""));
check(errors2.length === 0, "真实样本页全程无 console/page 错误" + (errors2.length ? " (" + errors2.join("; ") + ")" : ""));
check(errors3.length === 0, "直播页全程无 console/page 错误" + (errors3.length ? " (" + errors3.join("; ") + ")" : ""));

await browser.close();
preview.kill();
console.log("\n截图已存: " + SHOTS);
if (failures) { console.error("\nE2E FAIL — " + failures + " 项未通过"); process.exit(1); }
console.log("\nE2E PASS — M1(移动/阵亡/结局) + M2(气泡/详情卡/时间轴拖拽) + M3(像素角色动画/y-sort遮挡) + Phase3(视觉活动投影/中断) + M5(真实样本旧格式回放/全事件覆盖/不回归) + 直播(运行中实时跟随/live.jsonl) 全部通过");
