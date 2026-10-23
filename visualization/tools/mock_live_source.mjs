// mock_live_source.mjs — 模拟"运行中的模拟"逐步产出, 供 E2E 验证 ?live 直播跟随。
// 读 public/stub_timeline.json, 先写 meta 行, 再每隔 LIVE_DELAY_MS 毫秒 append 一个 step 行,
// 最后写 done 行 —— 与真实引擎 world_auto_sim.py 的 live.jsonl 增量写同形。
// 用法: LIVE_DELAY_MS=700 node tools/mock_live_source.mjs  (写 public/live.jsonl)
import { readFileSync, writeFileSync, appendFileSync, unlinkSync, existsSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(here, "..");
// E2E 用 vite preview (serve dist/), 所以 mock 写 dist/live.jsonl。
// 真实使用: 引擎写 public/live.jsonl + npm run dev (vite dev 直接 serve public/, 实时)。
const LIVE = resolve(ROOT, "dist", "live.jsonl");
const tl = JSON.parse(readFileSync(process.env.STUB_FIXTURE_PATH ?? resolve(ROOT, "public", "stub_timeline.json"), "utf-8"));
const delay = Number(process.env.LIVE_DELAY_MS ?? 700);

if (existsSync(LIVE)) unlinkSync(LIVE);   // 清掉上次的直播文件 (不存在则跳过)
writeFileSync(LIVE, JSON.stringify({
  __meta__: true, schema_version: 1, world: tl.world,
  reason_needed: tl.reason_needed, attack_needed: tl.attack_needed, persuade_n: tl.persuade_n,
}) + "\n");
for (const step of tl.steps) {
  appendFileSync(LIVE, JSON.stringify(step) + "\n");
  if (step === tl.steps[0] && process.env.LIVE_READY_PATH) {
    // E2E 可等页面完成首次 setup 后再推进；默认独立运行仍按原节奏直接追加。
    while (!existsSync(process.env.LIVE_READY_PATH)) await sleep(50);
  }
  await sleep(delay);
}
const last = tl.steps[tl.steps.length - 1];
appendFileSync(LIVE, JSON.stringify({ __done__: true, decree_ended: last.decree_ended, shogun_dead: last.shogun_dead }) + "\n");
console.log("mock live source: done (" + tl.steps.length + " steps @ " + delay + "ms)");
process.exit(0);
