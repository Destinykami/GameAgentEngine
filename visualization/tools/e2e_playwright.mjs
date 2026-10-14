// e2e_playwright.mjs — 回放器端到端验证 (无头 chromium), 覆盖 M1 + M2 交互 + M3 像素地图。
// 启动 vite preview 服务 dist/, 加载页面, 用 window.__REPLAY__ 驱动 PlaybackController,
// 断言:
//   M1: 加载无错 / 6地点6实体 / 移动落锚点 / 桃音阵亡 / 结局废止
//   M2: 对话气泡 (行动者台词 + 目标回复, 锚定/文本正确) / 点击实体详情卡 / 时间轴拖拽寻址
//   M3: 像素角色播 idle/walk 动画 / y-sort 深度层级 (前景遮挡排序基础)
// 游戏坐标→页面坐标: Phaser FIT 缩放, 用 canvas 的 getBoundingClientRect 映射。
// 关键时刻截图到 e2e_shots/。
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
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

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 980, height: 560 } });
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + String(e)));

await page.goto(`http://localhost:${PORT}/`, { waitUntil: "load" });
await page.waitForFunction(() => window.__REPLAY__ && window.__REPLAY__.timeline, { timeout: 15000 });
await sleep(400);

console.log("\n== 1. 页面加载 (M1) ==");
check(errors.length === 0, "加载无 console/page 错误" + (errors.length ? " (" + errors.join("; ") + ")" : ""));
const tl = await page.evaluate(() => window.__REPLAY__.timeline);
check(tl.schema_version === 1, "schema_version=1");
check(Array.isArray(tl.steps) && tl.steps.length >= 10, "steps 数量 " + tl.steps.length);
const day0 = tl.steps[0].states;
check(Object.keys(day0).length === 6, "day-0 有 6 个实体");
check(Object.keys(day0).every((n) => day0[n].loc), "day-0 每实体都有 loc");

console.log("\n== 2. 初始站位 (M1) ==");
await page.screenshot({ path: resolve(SHOTS, "01_initial.png") });
const initPos = await page.evaluate(() => ({
  旅行者: window.__REPLAY__.sprites.posOf("旅行者"), 雷电将军: window.__REPLAY__.sprites.posOf("雷电将军"),
}));
check(initPos.旅行者 && initPos.雷电将军, "sprite 位置可读");
console.log("    旅行者@(" + Math.round(initPos.旅行者.x) + "," + Math.round(initPos.旅行者.y) +
  ")  将军@(" + Math.round(initPos.雷电将军.x) + "," + Math.round(initPos.雷电将军.y) + ")");

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
// 点空白处收起
const emptyPage = await gameToPage(page, 700, 300);
await page.mouse.click(emptyPage.px, emptyPage.py);
await sleep(100);
check(await page.evaluate(() => window.__REPLAY__.detailCard.isOpen() === false), "点空白 → 详情卡收起");

console.log("\n== 4. 逐步推进 + 移动落锚点 (M1) + walk 动画 (M3) ==");
const before = await page.evaluate(() => window.__REPLAY__.sprites.posOf("旅行者"));
await page.evaluate(() => window.__REPLAY__.controller.next());
await sleep(120);   // 移动途中 (Tween 600ms), 应播 walk 动画
const walkAnim = await page.evaluate(() => window.__REPLAY__.sprites.animKeyOf("旅行者"));
check(walkAnim === "walk_旅行者", "移动途中播 walk 动画 (实际 " + walkAnim + ")");
await sleep(800);   // 等移动完成
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
await sleep(400);   // 等气泡淡入
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
await page.screenshot({ path: resolve(SHOTS, "06_bubbles.png") });
// 跳到无对话的步, 气泡应消失 (快速跳步不留旧气泡, 计划 §7.2-10)
await page.evaluate(() => window.__REPLAY__.controller.seek(0));
await sleep(300);
const bubblesGone = await page.evaluate(() => ({
  a: window.__REPLAY__.bubbles.actor.isVisible(), r: window.__REPLAY__.bubbles.reply.isVisible(),
}));
check(bubblesGone.a === false && bubblesGone.r === false, "跳回 day0 → 对话气泡消失");

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
check(idxDrag >= 12, "拖拽到右端 → 跳到末尾附近 (index " + idxDrag + ")");
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
check(last.decree_ended === true, "最后一步 decree_ended=true");
check(last.shogun_dead === false && last.persuade >= 1, "将军被说服 (persuade=" + last.persuade + ")");
check(last.note && last.note.includes("废止"), "note 含'废止'眼狩令");
await sleep(400);
await page.screenshot({ path: resolve(SHOTS, "04_ending.png") });

console.log("\n== 9. 无残留错误 ==");
check(errors.length === 0, "全程无 console/page 错误" + (errors.length ? " (" + errors.join("; ") + ")" : ""));

await browser.close();
preview.kill();
console.log("\n截图已存: " + SHOTS);
if (failures) { console.error("\nE2E FAIL — " + failures + " 项未通过"); process.exit(1); }
console.log("\nE2E PASS — M1(移动/阵亡/结局) + M2(气泡/详情卡/时间轴拖拽) + M3(像素角色动画/y-sort遮挡) 全部通过");
