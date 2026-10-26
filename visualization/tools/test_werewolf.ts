import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  PRIVATE_EVENT_TYPES, completeLines, parseTimeline, phaseLabel, votesText,
} from "../src/werewolf/data";

const timeline = parseTimeline(JSON.parse(readFileSync(
  new URL("../public/werewolf_timeline.json", import.meta.url), "utf8",
)));
const god = JSON.parse(readFileSync(
  new URL("../public/werewolf_god.json", import.meta.url), "utf8",
));

test("狼人杀公共时间线可加载且不含私密身份", () => {
  assert.equal(timeline.game, "werewolf");
  assert.equal(timeline.seats.length, 10);
  assert.ok(timeline.steps.length > 0);
  assert.equal("roles" in timeline, false);
  for (const step of timeline.steps) {
    for (const event of step.events) {
      assert.equal(PRIVATE_EVENT_TYPES.has(event.type), false);
      assert.equal("recipients" in event, false);
    }
  }
});

test("阶段、票型与结局可读", () => {
  const night = timeline.steps.find((step) => step.phase === "wolf_talk");
  const vote = timeline.steps.find((step) => Object.keys(step.votes).length > 0);
  const last = timeline.steps[timeline.steps.length - 1];
  assert.ok(night);
  assert.ok(vote);
  assert.match(phaseLabel(night), /第 \d+ 夜 · 狼人密谈/);
  assert.equal(phaseLabel({ ...night, phase: "hunter" }), "猎人开枪");
  assert.match(votesText(vote.votes), /→/);
  assert.equal(last.phase, "finished");
  assert.notEqual(last.winner, null);
});

test("上帝文件单独保存身份与私密事件", () => {
  assert.equal(god.roles["1号"], "wolf");
  assert.deepEqual(new Set(Object.values(god.roles)), new Set(["wolf", "seer", "witch", "hunter", "villager"]));
  assert.ok(god.personas);
  assert.equal(Object.keys(god.personas).length, 10);
  const types = new Set<string>();
  for (const step of god.steps) {
    for (const event of step.events) types.add(event.type);
  }
  assert.ok([...types].some((type) => PRIVATE_EVENT_TYPES.has(type)));
  assert.ok(types.has("wolf_chat"));
});

test("直播只消费完整行，尾部空串不推进游标", () => {
  assert.deepEqual(completeLines('{"a":1}\n{"b":2}\n'), ['{"a":1}', '{"b":2}']);
  assert.deepEqual(completeLines('{"a":1}\n{"partial"'), ['{"a":1}']);
  assert.deepEqual(completeLines(""), []);
  assert.deepEqual(completeLines("a\n\nb\n"), ["a", "", "b"]);
});
