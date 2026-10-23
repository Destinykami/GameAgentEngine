import assert from "node:assert/strict";
import test from "node:test";
import { LiveSource } from "../src/data/liveSource";
import { normalizeTimeline, validateTimeline } from "../src/data/timelineLoader";
import { PlaybackController } from "../src/PlaybackController";
import type { Timeline, TimelineStep } from "../src/data/schema";

function step(clock: number): TimelineStep {
  return { day: 1, moment: clock, clock, states: {}, visual_events: [], events: [],
    decree_ended: false, shogun_dead: false, persuade: null };
}

function timeline(): Timeline {
  return { schema_version: 1, world: { name: "世界", coordinate_system: "location-name", render_map: "inazuma-v1" },
    reason_needed: null, attack_needed: null, persuade_n: null, steps: [step(1), step(2), step(3)] };
}

test("legacy normalization preserves null thresholds and current structured input", () => {
  const legacy = normalizeTimeline({ reason_needed: null, attack_needed: null, persuade_n: null,
    steps: [{ clock: 1, states: {}, events: [] }] });
  validateTimeline(legacy);
  assert.equal(legacy.reason_needed, null);
  assert.deepEqual(legacy.steps[0].visual_events, []);
  const current = timeline();
  assert.equal(normalizeTimeline(current), current);
  current.steps[2].clock = 0;
  assert.throws(() => validateTimeline(current), /clock 回退/);
});

test("live source consumes complete lines once and waits for a partial last line", async () => {
  const initial = JSON.stringify({ __meta__: true, reason_needed: null }) + "\n" + JSON.stringify(step(1)) + "\n";
  const replies = [initial + '{"clock":', initial + JSON.stringify(step(2)) + '\n{"__done__":true}\n'];
  const saved = globalThis.fetch;
  globalThis.fetch = async () => new Response(replies.shift() ?? initial);
  try {
    const live = new LiveSource();
    const first = await live.poll();
    assert.equal(first.newSteps.length, 1);
    assert.equal(first.meta?.reason_needed, null);
    assert.equal(first.done, false);
    const next = await live.poll();
    assert.deepEqual(next.newSteps.map(s => s.clock), [2]);
    assert.equal(next.done, true);
    assert.equal(live.stepCount, 2);
  } finally { globalThis.fetch = saved; }
});

test("live source preserves the existing malformed-complete-line progress boundary", async () => {
  const saved = globalThis.fetch;
  const text = JSON.stringify(step(1)) + "\nbad-json\n" + JSON.stringify(step(2)) + "\n";
  globalThis.fetch = async () => new Response(text);
  try {
    const live = new LiveSource();
    assert.equal((await live.poll()).newSteps.length, 1);
    assert.equal((await live.poll()).newSteps.length, 0);
    assert.equal(live.stepCount, 1);
  } finally { globalThis.fetch = saved; }
});

test("playback notifies all listeners and replay immediately emits the opening step", () => {
  const timers: { callback: () => void; delay: number }[] = [];
  const scene = { time: { addEvent: (event: { callback: () => void; delay: number }) => {
    timers.push(event);
    return { remove: () => {} };
  } } } as unknown as Phaser.Scene;
  const controller = new PlaybackController(scene, timeline());
  const first: number[] = [], second: number[] = [], transport: boolean[] = [];
  controller.subscribe(s => first.push(s.clock), () => transport.push(controller.isPlaying));
  controller.subscribe(s => second.push(s.clock), () => {});
  controller.seek(2);
  controller.play();
  assert.deepEqual(first, [3, 1]);
  assert.deepEqual(second, first);
  assert.deepEqual(transport, [true]);
  timers[0].callback();
  assert.equal(controller.currentIndex, 1);
  controller.next();
  assert.equal(controller.currentIndex, 2);
  assert.deepEqual(transport, [true, false]);
  controller.setSpeed(99);
  assert.equal(controller.currentSpeed, 4);
});

test("snapshot projection keeps stable offsets and applies death after jump positioning", async () => {
  (globalThis as unknown as Record<string, unknown>).__OFFICIAL_FULLBODY__ = false;
  const { SnapshotProjection } = await import("../src/replay/SnapshotProjection");
  const calls: unknown[][] = [];
  const sprites = new Map<string, object>();
  const registry = {
    ensure: (name: string) => {
      if (!sprites.has(name)) sprites.set(name, {
        setPosition: (...args: unknown[]) => calls.push([name, "position", ...args]),
        setHealth: (value: unknown) => calls.push([name, "health", value]),
        setDead: (value: unknown) => calls.push([name, "dead", value]),
      });
      return sprites.get(name);
    },
    applySnapshot: (_sprite: object, _state: object, _prev: unknown, offset: number) => calls.push(["offset", offset]),
    applyActivity: () => {},
  };
  const state = { health: 10, loc: "稻妻主城", dead: false, reasons: [], attack: 1, role: "", kind: "npc" as const };
  const states = { B: { ...state }, A: { ...state } };
  const projection = new SnapshotProjection({} as Phaser.Scene, registry as unknown as ConstructorParameters<typeof SnapshotProjection>[1], states);
  assert.equal(projection.apply({ ...step(1), states }, 0), false);
  assert.deepEqual(calls, [["offset", 15], ["offset", -15]]);
  calls.length = 0;
  assert.equal(projection.apply({ ...step(2), states: { A: { ...state, dead: true } } }, 3), true);
  assert.deepEqual(calls.map(call => call[1]), ["position", "health", "dead"]);
  assert.equal(calls[2][2], true);
});
