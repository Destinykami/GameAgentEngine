// validate_timeline.ts — 离线校验 timeline 数据层 (计划 §7.1)。
// 检查: schema 版本 / clock 单调不回退 / 每步有 states+visual_events / loc 是已知地点 /
// attack.damage 非负 / target_dead=true 时目标快照必须死亡 / 成功 talk 含 actor+target+文本 /
// 失败动作不得携带成功态字段 (damage/reply)。
// 运行: npx tsx tools/validate_timeline.ts [路径.json]   (缺省 public/stub_timeline.json)
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { validateTimeline } from "../src/data/timelineLoader";
import { ALL_LOCATIONS } from "../src/data/locationAnchors";
import type { Timeline } from "../src/data/schema";

const arg = process.argv[2];
const here = dirname(fileURLToPath(import.meta.url));
const file = arg
  ? resolve(arg)
  : resolve(here, "..", "public", "stub_timeline.json");

const errors: string[] = [];
const tl = JSON.parse(readFileSync(file, "utf-8")) as Timeline;

// 1. 基础 schema (版本 / world / steps / clock 单调 / states / visual_events)
try {
  validateTimeline(tl);
} catch (e) {
  errors.push("schema: " + String(e));
}

const knownLocs = new Set(ALL_LOCATIONS);

// 2. 逐步深层语义检查
for (let i = 0; i < tl.steps.length; i++) {
  const s = tl.steps[i];
  // loc 必须是已知地点
  for (const [name, snap] of Object.entries(s.states)) {
    if (!knownLocs.has(snap.loc))
      errors.push(`step[${i}] ${name}.loc="${snap.loc}" 不是已知地点`);
  }
  for (const ve of s.visual_events) {
    // attack.damage 非负
    if (ve.type === "attack" && ve.success !== false) {
      if (typeof ve.damage !== "number" || ve.damage < 0)
        errors.push(`step[${i}] attack ${ve.actor} damage 非法: ${ve.damage}`);
      // target_dead=true 时目标快照必须死亡
      if (ve.target_dead && ve.target) {
        const targetSnap = s.states[ve.target];
        if (!targetSnap || !targetSnap.dead)
          errors.push(`step[${i}] ${ve.actor}→${ve.target} target_dead 但目标快照未死`);
      }
    }
    // 成功 talk 必须含 actor / target / 文本
    if (ve.type === "conversation" && ve.success !== false) {
      if (!ve.actor || !ve.target || !ve.utterance)
        errors.push(`step[${i}] 成功 conversation 缺 actor/target/utterance: ${JSON.stringify(ve)}`);
    }
    // 失败动作不得携带成功态字段 (damage / reply / reason / weapon)
    if (ve.success === false) {
      const bad: string[] = [];
      if (typeof ve.damage === "number") bad.push("damage");
      if (ve.reply) bad.push("reply");
      if (ve.reason_added) bad.push("reason_added");
      if (ve.weapon_attack) bad.push("weapon_attack");
      if (bad.length)
        errors.push(`step[${i}] 失败动作 ${ve.actor}(${ve.type}) 携带成功态字段: ${bad.join(",")}`);
    }
  }
}

// 3. 汇总
if (errors.length) {
  console.error(`FAIL — ${file}`);
  for (const e of errors) console.error("  ✗ " + e);
  process.exit(1);
}
console.log(`PASS — ${file}`);
console.log(`  steps=${tl.steps.length}  地点=${ALL_LOCATIONS.length}  schema_version=${tl.schema_version}`);
console.log("  全部数据层校验通过: clock 单调 / loc 合法 / damage 非负 / 致死一致 / talk 完整 / 失败无成功态字段");
