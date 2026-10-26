import "./style.css";
import {
  completeLines, loadGod, loadTimeline, phaseLabel, privateEvents, publicEvents,
  type WerewolfEvent, type WerewolfGod, type WerewolfStep, type WerewolfTimeline,
  votesText,
} from "./data";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("缺少 #app 容器");

app.innerHTML = `
  <div class="ww-app">
    <header class="ww-header">
      <div>
        <h1>狼人杀 <span>对局回放</span></h1>
        <p id="subtitle" class="ww-subtitle">加载中…</p>
      </div>
      <div id="status" class="ww-status"></div>
    </header>
    <main class="ww-main">
      <section class="ww-table">
        <div class="ww-table-title"><span>席位</span><span id="round-label"></span></div>
        <div id="seats" class="ww-seats"></div>
        <div class="ww-votes"><span>票型</span><span id="votes"></span></div>
        <div id="winner" class="ww-winner" hidden></div>
      </section>
      <aside class="ww-side">
        <div class="ww-panel-head"><span>公开记录</span><span id="live-badge" class="ww-live" hidden>LIVE</span></div>
        <div id="log" class="ww-log"></div>
        <div id="god-panel" class="ww-god" hidden>
          <div class="ww-panel-head"><span>上帝视角</span><span class="ww-god-tag">仅本地</span></div>
          <div id="god-roles" class="ww-god-roles"></div>
          <div id="god-events" class="ww-god-events"></div>
        </div>
      </aside>
    </main>
    <footer class="ww-controls">
      <button id="prev" type="button">上一步</button>
      <button id="play" type="button">播放</button>
      <button id="next" type="button">下一步</button>
      <input id="scrubber" type="range" min="0" max="0" value="0" step="1" aria-label="步骤" />
      <span id="step-label" class="ww-step-label"></span>
      <button id="god" type="button">上帝视角</button>
    </footer>
  </div>`;

const ui = {
  subtitle: document.querySelector<HTMLParagraphElement>("#subtitle")!,
  status: document.querySelector<HTMLDivElement>("#status")!,
  round: document.querySelector<HTMLSpanElement>("#round-label")!,
  seats: document.querySelector<HTMLDivElement>("#seats")!,
  votes: document.querySelector<HTMLSpanElement>("#votes")!,
  winner: document.querySelector<HTMLDivElement>("#winner")!,
  log: document.querySelector<HTMLDivElement>("#log")!,
  liveBadge: document.querySelector<HTMLSpanElement>("#live-badge")!,
  godPanel: document.querySelector<HTMLDivElement>("#god-panel")!,
  godRoles: document.querySelector<HTMLDivElement>("#god-roles")!,
  godEvents: document.querySelector<HTMLDivElement>("#god-events")!,
  prev: document.querySelector<HTMLButtonElement>("#prev")!,
  play: document.querySelector<HTMLButtonElement>("#play")!,
  next: document.querySelector<HTMLButtonElement>("#next")!,
  scrubber: document.querySelector<HTMLInputElement>("#scrubber")!,
  stepLabel: document.querySelector<HTMLSpanElement>("#step-label")!,
  godButton: document.querySelector<HTMLButtonElement>("#god")!,
};

let timeline: WerewolfTimeline | null = null;
let god: WerewolfGod | null = null;
let index = 0;
let timer: number | null = null;
let liveTimer: number | null = null;
let liveSeen = 0;
let liveDone = false;
let liveMode = false;
let lastError = "";

const ROLE_LABEL: Record<string, string> = {
  wolf: "狼人", seer: "预言家", villager: "村民",
};

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, cls = "", text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function winnerLabel(winner: string | null): string {
  if (winner === "wolves") return "狼人阵营胜利";
  if (winner === "good") return "好人阵营胜利";
  if (winner === "draw") return "平局";
  return "对局进行中";
}

function eventLabel(event: WerewolfEvent): string {
  switch (event.type) {
    case "public_speech": return "发言";
    case "vote_result": return "票型";
    case "elimination": return "淘汰";
    case "game_over": return "结局";
    case "announcement": return "公告";
    case "inspection_result": return "查验";
    case "wolf_result": return "狼人";
    case "role_assignment": return "身份";
    default: return event.type;
  }
}

function eventText(event: WerewolfEvent): string {
  if (event.type === "public_speech" && event.text) {
    return `${event.actor ?? ""}：${event.text}`;
  }
  if (event.type === "game_over" && event.winner) {
    return `对局结束：${winnerLabel(event.winner)}`;
  }
  return event.content;
}

function stepEventLabel(step: WerewolfStep): string {
  if (step.events.some((event) => event.type === "game_over")) return "结局";
  if (step.events.some((event) => event.type === "vote_result")) return "投票";
  if (step.events.some((event) => event.type === "public_speech")) return "发言";
  if (step.events.some((event) => event.type === "elimination")) return "淘汰";
  return phaseLabel(step);
}

function renderSeats(step: WerewolfStep): void {
  if (!timeline) return;
  ui.seats.replaceChildren();
  for (const seat of timeline.seats) {
    const dead = !step.alive.includes(seat);
    const card = el("div", `ww-seat${dead ? " dead" : ""}`);
    const head = el("div", "ww-seat-head");
    head.append(el("span", "ww-seat-name", seat), el("span", "ww-seat-state", dead ? "已淘汰" : "存活"));
    card.append(head);
    const role = god?.roles?.[seat];
    if (role) card.append(el("span", `ww-role role-${role}`, ROLE_LABEL[role] ?? role));
    const vote = step.votes[seat];
    if (vote !== undefined) {
      card.append(el("span", "ww-vote", `投票 → ${vote ?? "弃票"}`));
    }
    ui.seats.append(card);
  }
}

function renderLog(step: WerewolfStep): void {
  if (!timeline) return;
  const events = publicEvents(timeline.steps, index);
  ui.log.replaceChildren();
  let cursor = 0;
  for (const current of timeline.steps.slice(0, index + 1)) {
    const header = el("div", "ww-step-head", `${stepEventLabel(current)}${current.step === step.step ? " · 当前" : ""}`);
    ui.log.append(header);
    const count = current.events.filter((event) => event.channel === "public" || !event.channel).length;
    for (const event of events.slice(cursor, cursor + count)) {
      const row = el("div", `ww-event${event.type === "game_over" ? " final" : ""}`);
      row.append(el("span", "ww-event-type", eventLabel(event)));
      row.append(el("span", "ww-event-text", eventText(event)));
      ui.log.append(row);
    }
    cursor += count;
  }
  requestAnimationFrame(() => { ui.log.scrollTop = ui.log.scrollHeight; });
}

function renderGod(step: WerewolfStep): void {
  if (!god) {
    ui.godPanel.hidden = true;
    ui.godButton.textContent = "上帝视角";
    return;
  }
  ui.godPanel.hidden = false;
  ui.godButton.textContent = "关闭上帝视角";
  ui.godRoles.replaceChildren();
  for (const [seat, role] of Object.entries(god.roles)) {
    ui.godRoles.append(el("span", `ww-role role-${role}`, `${seat}：${ROLE_LABEL[role] ?? role}`));
  }
  ui.godEvents.replaceChildren();
  const events = privateEvents(step);
  if (events.length === 0) {
    ui.godEvents.append(el("div", "ww-muted", "本步无新的私密反馈"));
  } else {
    for (const event of events) {
      const row = el("div", "ww-event private");
      row.append(el("span", "ww-event-type", eventLabel(event)));
      row.append(el("span", "ww-event-text", eventText(event)));
      ui.godEvents.append(row);
    }
  }
}

function render(): void {
  if (!timeline || timeline.steps.length === 0) {
    ui.subtitle.textContent = liveMode ? "等待模拟开始…（直播）" : "加载中…";
    return;
  }
  index = Math.max(0, Math.min(index, timeline.steps.length - 1));
  const step = timeline.steps[index];
  document.body.dataset.phase = step.phase;
  ui.subtitle.textContent = `${timeline.instance_id} · 共 ${timeline.steps.length} 步 · 公共回放`;
  ui.status.textContent = `${phaseLabel(step)} · 存活 ${step.alive.length}/${timeline.seats.length}`;
  ui.round.textContent = `第 ${step.round} 轮`;
  renderSeats(step);
  ui.votes.textContent = votesText(step.votes);
  ui.winner.hidden = !step.winner;
  ui.winner.textContent = winnerLabel(step.winner);
  renderLog(step);
  renderGod(god?.steps[index] ?? step);
  ui.scrubber.max = String(Math.max(0, timeline.steps.length - 1));
  ui.scrubber.value = String(index);
  ui.stepLabel.textContent = `${index + 1} / ${timeline.steps.length}`;
  ui.prev.disabled = index === 0;
  ui.next.disabled = index >= timeline.steps.length - 1;
  if (lastError) ui.status.textContent = lastError;
}

function setIndex(next: number): void {
  if (!timeline) return;
  index = Math.max(0, Math.min(next, timeline.steps.length - 1));
  render();
}

function stopPlay(): void {
  if (timer !== null) window.clearInterval(timer);
  timer = null;
  ui.play.textContent = "播放";
}

function togglePlay(): void {
  if (timer !== null) {
    stopPlay();
    return;
  }
  if (!timeline) return;
  if (index >= timeline.steps.length - 1) index = 0;
  ui.play.textContent = "暂停";
  timer = window.setInterval(() => {
    if (!timeline || index >= timeline.steps.length - 1) {
      stopPlay();
      return;
    }
    setIndex(index + 1);
  }, 1200);
}

async function toggleGod(): Promise<void> {
  if (god) {
    god = null;
    render();
    return;
  }
  try {
    const url = new URL("werewolf_god.json", document.baseURI).href;
    god = await loadGod(url);
    lastError = "";
  } catch (error) {
    lastError = `上帝视角不可用：${String(error)}`;
  }
  render();
}

function startLive(): void {
  liveMode = true;
  ui.liveBadge.hidden = false;
  ui.subtitle.textContent = "等待模拟开始…（直播）";
  const liveUrl = new URL("werewolf_live.jsonl", document.baseURI).href;
  const poll = async (): Promise<void> => {
    if (liveDone) return;
    try {
      const response = await fetch(liveUrl, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const text = await response.text();
      const lines = completeLines(text);
      for (; liveSeen < lines.length; liveSeen += 1) {
        const line = lines[liveSeen].trim();
        if (!line) continue;
        let record: Record<string, unknown>;
        try {
          record = JSON.parse(line) as Record<string, unknown>;
        } catch {
          throw new Error(`直播第 ${liveSeen + 1} 行解析失败，等待文件修复`);
        }
        if (record.__done__ === true) {
          liveDone = true;
          ui.liveBadge.hidden = true;
          break;
        }
        if (record.__meta__ === true) {
          timeline = {
            schema_version: 1, game: "werewolf",
            instance_id: String(record.instance_id ?? "live"),
            seats: Array.isArray(record.seats) ? record.seats.map(String) : [],
            max_rounds: Number(record.max_rounds ?? 16),
            steps: [],
          };
          continue;
        }
        if (!timeline) {
          throw new Error("直播首行不是 meta");
        }
        timeline.steps.push(record as unknown as WerewolfStep);
        index = timeline.steps.length - 1;
      }
      lastError = "";
      render();
    } catch (error) {
      lastError = `直播读取失败：${String(error)}`;
      render();
    }
  };
  void poll();
  liveTimer = window.setInterval(() => { void poll(); }, 1000);
  window.addEventListener("beforeunload", () => {
    if (liveTimer !== null) window.clearInterval(liveTimer);
  });
}

async function start(): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  ui.prev.addEventListener("click", () => setIndex(index - 1));
  ui.next.addEventListener("click", () => setIndex(index + 1));
  ui.play.addEventListener("click", togglePlay);
  ui.scrubber.addEventListener("input", () => setIndex(Number(ui.scrubber.value)));
  ui.godButton.addEventListener("click", () => { void toggleGod(); });

  if (params.has("live")) {
    startLive();
    return;
  }
  const file = params.get("timeline") ?? "werewolf_timeline.json";
  try {
    timeline = await loadTimeline(new URL(file, document.baseURI).href);
    index = 0;
    render();
    if (params.has("god")) await toggleGod();
  } catch (error) {
    lastError = `加载失败：${String(error)}`;
    render();
  }
}

void start();

// 浏览器端调试/E2E：只读时间线、上帝数据和当前步。
(window as unknown as Record<string, unknown>).__WEREWOLF_REPLAY__ = {
  get timeline() { return timeline; },
  get god() { return god; },
  get index() { return index; },
};
