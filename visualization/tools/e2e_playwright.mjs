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

console.log("\n== 9. 活动中断 (Phase 3) ==");
// step2 桃音被执行官攻击 (非致死) → 治疗活动中断 (attack 中断日计划); 刚郎未被攻击 → 继续锻造。
await page.evaluate(() => window.__REPLAY__.controller.seek(2));
await sleep(300);
const actInt = await page.evaluate(() => ({ 桃音: window.__REPLAY__.sprites.animKeyOf("桃音"), 刚郎: window.__REPLAY__.sprites.animKeyOf("刚郎") }));
check(actInt.桃音 !== "heal_桃音", "step2 桃音被攻击 → 治疗中断 (实际 " + actInt.桃音 + ")");
check(actInt.刚郎 === "hammer_刚郎", "step2 刚郎未被攻击 → 继续锻造 (实际 " + actInt.刚郎 + ")");
await page.evaluate(() => window.__REPLAY__.controller.seek(0));

console.log("\n== 10. M5 真实样本回放 (旧格式: 中文 events 串 → 回退解析) ==");
// 真实 9/10 天样本 (data/auto_sim/timeline.json → public/real_timeline.json) 无 visual_events/
// schema_version。加载器归一化 (回退解析中文串填 visual_events) 后应完整可回放, 不回归。
const page2 = await browser.newPage({ viewport: { width: 980, height: 560 } });
const errors2 = [];
page2.on("console", (m) => { if (m.type() === "error") errors2.push("console: " + m.text()); });
page2.on("pageerror", (e) => errors2.push("pageerror: " + String(e)));
await page2.goto(`http://localhost:${PORT}/?timeline=real_timeline.json`, { waitUntil: "load" });
await page2.waitForFunction(() => window.__REPLAY__ && window.__REPLAY__.timeline, { timeout: 15000 });
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
await page2.screenshot({ path: resolve(SHOTS, "12_real_ending.png") });
await page2.close();

console.log("\n== 11. 无残留错误 (stub + 真实样本两页) ==");
check(errors.length === 0, "stub 页全程无 console/page 错误" + (errors.length ? " (" + errors.join("; ") + ")" : ""));
check(errors2.length === 0, "真实样本页全程无 console/page 错误" + (errors2.length ? " (" + errors2.join("; ") + ")" : ""));

await browser.close();
preview.kill();
console.log("\n截图已存: " + SHOTS);
if (failures) { console.error("\nE2E FAIL — " + failures + " 项未通过"); process.exit(1); }
console.log("\nE2E PASS — M1(移动/阵亡/结局) + M2(气泡/详情卡/时间轴拖拽) + M3(像素角色动画/y-sort遮挡) + Phase3(视觉活动投影/中断) + M5(真实样本旧格式回放/全事件覆盖/不回归) 全部通过");
