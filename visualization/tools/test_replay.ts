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

test("live source retries a malformed line without losing following records", async () => {
  const saved = globalThis.fetch;
  const prefix = JSON.stringify(step(1)) + "\n";
  let text = prefix + "bad-json\n" + JSON.stringify(step(3)) + "\n";
  globalThis.fetch = async () => new Response(text);
  try {
    const live = new LiveSource();
    const first = await live.poll();
    assert.equal(first.newSteps.length, 1);
    assert.equal(first.error?.kind, "parse");
    assert.equal((await live.poll()).newSteps.length, 0);
    text = prefix + JSON.stringify(step(2)) + "\n" + JSON.stringify(step(3)) + '\n{"__done__":true}\n';
    const repaired = await live.poll();
    assert.deepEqual(repaired.newSteps.map(s => s.clock), [2, 3]);
    assert.equal(repaired.error, null);
    assert.equal(repaired.done, true);
    assert.equal(live.stepCount, 3);
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


test("live source rejects replacement and truncation without mixing runs", async () => {
  const saved = globalThis.fetch;
  for (const replacement of [
    JSON.stringify({ __meta__: true, run_id: "second" }) + "\n" + JSON.stringify(step(9)) + "\n",
    JSON.stringify({ __meta__: true, run_id: "first" }) + "\n",
    JSON.stringify({ __meta__: true, run_id: "first" }) + "\n" + JSON.stringify(step(9)) + "\n",
  ]) {
    let text = JSON.stringify({ __meta__: true, run_id: "first" }) + "\n" + JSON.stringify(step(1)) + "\n";
    globalThis.fetch = async () => new Response(text);
    try {
      const live = new LiveSource();
      await live.poll();
      text = replacement;
      const result = await live.poll();
      assert.equal(result.error?.kind, "replaced");
      assert.deepEqual(result.newSteps, []);
      assert.deepEqual(live.allSteps.map(s => s.clock), [1]);
      assert.equal((await live.poll()).error?.kind, "replaced");
    } finally { globalThis.fetch = saved; }
  }
});

test("live source allows only one request and retries network failures", async () => {
  const saved = globalThis.fetch;
  let resolve!: (value: Response) => void;
  let calls = 0;
  globalThis.fetch = () => { calls++; return new Promise(r => { resolve = r; }); };
  try {
    const live = new LiveSource();
    const pending = live.poll();
    assert.deepEqual((await live.poll()).newSteps, []);
    assert.equal(calls, 1);
    resolve(new Response("", { status: 404 }));
    assert.equal((await pending).error?.kind, "network");
    globalThis.fetch = async () => new Response(JSON.stringify(step(1)) + "\n");
    const recovered = await live.poll();
    assert.equal(recovered.error, null);
    assert.equal(recovered.newSteps.length, 1);
  } finally { globalThis.fetch = saved; }
});

async function liveHarness(resourceReady: Promise<HTMLImageElement>) {
  const { LivePlayback } = await import("../src/replay/LivePlayback");
  let setups = 0;
  const texts: { text: string; visible: boolean; destroy: () => void; setText: (s: string) => unknown }[] = [];
  const text = (value: string) => {
    const item = { text: value, visible: true,
      setOrigin: () => item, setDepth: () => item,
      setText: (s: string) => { item.text = s; return item; },
      destroy: () => { item.visible = false; } };
    texts.push(item);
    return item;
  };
  const scene = { add: { text: (_x: number, _y: number, value: string) => text(value) },
    tweens: { add: () => {}, killTweensOf: () => {} },
    time: { addEvent: () => ({ remove: () => {} }) }, events: { once: () => {} } } as unknown as Phaser.Scene;
  const controller = { totalSteps: 1, seek: () => {}, addStep: () => { controller.totalSteps++; } };
  const resources = [resourceReady, Promise.resolve(new Map()), Promise.resolve(new Map()), Promise.resolve(null)] as ConstructorParameters<typeof LivePlayback>[1];
  const host = { setup: () => { setups++; }, controller: () => controller,
    scrubber: () => ({ grow: () => {} }), loadingText: text("loading") } as unknown as ConstructorParameters<typeof LivePlayback>[2];
  const live = new LivePlayback(scene, resources, host);
  return { live, setups: () => setups, texts, controller };
}

test("live playback prevents duplicate setup while resources are pending", async () => {
  const saved = globalThis.fetch;
  let resolve!: (value: HTMLImageElement) => void;
  const resources = new Promise<HTMLImageElement>(r => { resolve = r; });
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response('{"__meta__":true}\n' + JSON.stringify(step(1)) + '\n');
  };
  const { live, setups } = await liveHarness(resources);
  try {
    const pending = live.pollOnce();
    await new Promise(r => setTimeout(r, 0));
    await live.pollOnce();
    assert.equal(calls, 1);
    resolve({} as HTMLImageElement);
    await pending;
    assert.equal(setups(), 1);
    assert.equal(live.status().error, null);
  } finally { live.dispose(); globalThis.fetch = saved; }
});

test("live playback cancels pending setup after scene disposal", async () => {
  const saved = globalThis.fetch;
  let resolve!: (value: HTMLImageElement) => void;
  const resources = new Promise<HTMLImageElement>(r => { resolve = r; });
  globalThis.fetch = async () => new Response('{"__meta__":true}\n' + JSON.stringify(step(1)) + '\n');
  const { live, setups } = await liveHarness(resources);
  try {
    const pending = live.pollOnce();
    await new Promise(r => setTimeout(r, 0));
    live.dispose();
    resolve({} as HTMLImageElement);
    await pending;
    assert.equal(setups(), 0);
  } finally { globalThis.fetch = saved; }
});

test("live playback shows a recoverable issue after setup and retains steps on replacement", async () => {
  const saved = globalThis.fetch;
  const prefix = '{"__meta__":true,"run_id":"first"}\n' + JSON.stringify(step(1)) + '\n';
  let data = prefix;
  globalThis.fetch = async () => new Response(data);
  const { live, texts, controller } = await liveHarness(Promise.resolve({} as HTMLImageElement));
  try {
    await live.pollOnce();
    data = prefix + 'bad\n';
    await live.pollOnce();
    assert.equal(live.status().error?.kind, "parse");
    assert.ok(texts.some(t => t.visible && t.text.includes("等待数据修复")));
    data = prefix + JSON.stringify(step(2)) + '\n';
    await live.pollOnce();
    assert.equal(live.status().error, null);
    assert.equal(controller.totalSteps, 2);
    data = '{"__meta__":true,"run_id":"second"}\n' + JSON.stringify(step(9)) + '\n';
    await live.pollOnce();
    assert.equal(live.status().error?.kind, "replaced");
    assert.equal(controller.totalSteps, 2);
    assert.equal(live.status().badgeVisible, false);
  } finally { live.dispose(); globalThis.fetch = saved; }
});
