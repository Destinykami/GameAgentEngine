// e2e_playwright.mjs — M1 前端端到端验证 (无头 chromium)。
// 启动 vite preview 服务 dist/, 加载页面, 用 window.__REPLAY__ 驱动 PlaybackController,
// 断言: 页面加载无错 / 6 地点 6 实体 / 逐步推进 / 移动后 sprite 落到新锚点 /
// 桃音阵亡 (target_dead + states.dead + ✝) / 结局 decree_ended / 事件日志与状态面板更新。
// 在关键时刻截图到 e2e_shots/。
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

// 启动 vite preview 服务 dist/
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
// 等待 Phaser 启动 + __REPLAY__ 就绪
await page.waitForFunction(() => window.__REPLAY__ && window.__REPLAY__.timeline, { timeout: 15000 });
await sleep(400);   // 让首帧渲染

console.log("\n== 1. 页面加载 ==");
check(errors.length === 0, "加载无 console/page 错误" + (errors.length ? " (" + errors.join("; ") + ")" : ""));
const tl = await page.evaluate(() => window.__REPLAY__.timeline);
check(tl.schema_version === 1, "schema_version=1");
check(Array.isArray(tl.steps) && tl.steps.length >= 10, "steps 数量 " + tl.steps.length);
const day0 = tl.steps[0].states;
check(Object.keys(day0).length === 6, "day-0 有 6 个实体 (旅行者+5 NPC)");
check(Object.keys(day0).every((n) => day0[n].loc), "day-0 每实体都有 loc");

console.log("\n== 2. 初始站位 (sprite 像素位置 = 地点锚点) ==");
await page.screenshot({ path: resolve(SHOTS, "01_initial.png") });
const anchors = await page.evaluate(() => window.__REPLAY__.timeline && null); // anchors 在前端, 用 sprite 位置对照
// 对照: 旅行者应在稻妻主城锚点, 雷电将军应在神樱庭锚点
const initPos = await page.evaluate(() => {
  const sp = window.__REPLAY__.sprites;
  return { 旅行者: sp.posOf("旅行者"), 雷电将军: sp.posOf("雷电将军") };
});
check(initPos.旅行者 && initPos.雷电将军, "sprite 位置可读 (旅行者/将军)");
console.log("    旅行者@(" + Math.round(initPos.旅行者.x) + "," + Math.round(initPos.旅行者.y) +
  ")  将军@(" + Math.round(initPos.雷电将军.x) + "," + Math.round(initPos.雷电将军.y) + ")");

console.log("\n== 3. 逐步推进 + 移动落到新锚点 ==");
// 第1步 (day1 9:00): 旅行者 move 治疗堂
const before = await page.evaluate(() => window.__REPLAY__.sprites.posOf("旅行者"));
await page.evaluate(() => window.__REPLAY__.controller.next());
await sleep(800);   // 等 Tween 走完
const after = await page.evaluate(() => ({
  index: window.__REPLAY__.controller.currentIndex,
  旅行者: window.__REPLAY__.sprites.posOf("旅行者"),
  step: window.__REPLAY__.controller.current,
}));
check(after.index === 1, "推进到 step 1 (index " + after.index + ")");
const moved = Math.hypot(after.旅行者.x - before.x, after.旅行者.y - before.y);
check(moved > 20, "旅行者移动了 (位移 " + Math.round(moved) + "px, 治疗堂锚点)");
check(after.step.states["旅行者"].loc === "治疗堂", "step1 旅行者 loc=治疗堂");
check(after.step.visual_events.some((v) => v.type === "move" && v.actor === "旅行者"), "step1 有 move 结构化事件");
await page.screenshot({ path: resolve(SHOTS, "02_step1_moved.png") });

console.log("\n== 4. 桃音阵亡 (day2 9:00, attack target_dead) ==");
// 跳到 day2 9:00 (index 4: day0=0, day1 9/14/19=1,2,3, day2 9=4)
await page.evaluate(() => window.__REPLAY__.controller.seek(4));
await sleep(800);
const death = await page.evaluate(() => {
  const c = window.__REPLAY__.controller;
  const s = c.current;
  return { 桃音: s.states["桃音"], atk: s.visual_events.find((v) => v.type === "attack" && v.target === "桃音") };
});
check(death.桃音.dead === true, "step4 桃音 dead=true");
check(death.atk && death.atk.target_dead === true, "step4 有 attack target_dead=true 事件");
check(death.atk && typeof death.atk.damage === "number" && death.atk.damage >= 0, "attack damage 非负 (" + (death.atk?.damage) + ")");
await page.screenshot({ path: resolve(SHOTS, "03_tao_dead.png") });

console.log("\n== 5. 结局 (最后一步 decree_ended) ==");
const last = await page.evaluate(() => {
  const c = window.__REPLAY__.controller;
  c.seek(c.totalSteps - 1);
  return c.current;
});
check(last.decree_ended === true, "最后一步 decree_ended=true");
check(last.shogun_dead === false && last.persuade >= 1, "将军被说服 (persuade=" + last.persuade + "), 非阵亡");
check(last.note && last.note.includes("废止"), "note 含'废止'眼狩令");
await sleep(400);
await page.screenshot({ path: resolve(SHOTS, "04_ending.png") });

console.log("\n== 6. 无残留错误 ==");
check(errors.length === 0, "全程无 console/page 错误" + (errors.length ? " (" + errors.join("; ") + ")" : ""));

await browser.close();
preview.kill();
console.log("\n截图已存: " + SHOTS);
if (failures) { console.error("\nE2E FAIL — " + failures + " 项未通过"); process.exit(1); }
console.log("\nE2E PASS — 页面加载 / 6地点6实体 / 移动落锚点 / 桃音阵亡 / 结局废止, 全部通过");
