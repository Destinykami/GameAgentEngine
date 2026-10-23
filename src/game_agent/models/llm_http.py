"""真实 LLM 客户端: 通过 OpenAI 兼容接口接入 SGLang 部署的模型。

默认接入: http://10.121.39.10:30005 上的 Qwen3.8-27B-Coder/BF16 (SGLang)。
- 用标准库 urllib 发请求, 不引入 openai / requests 依赖。
- 这是思考型模型: 对话默认关思考 (快), 可用 enable_thinking=True 打开;
  打分与结构化 JSON 任务 (反思/规划/判断) **恒关思考** —— 思考 token 会挤爆
  max_tokens 导致 JSON 截断。
  关思考用 SGLang 的 chat_template_kwargs={"enable_thinking": false}。
- 结构化输出 (问题/洞察/计划) 要求模型返回严格 JSON, 并做容错解析。

实现 LLMClient 接口的全部 12 个抽象方法。
注意: 凡含 JSON 示例的 prompt 行用普通字符串拼接, 不用 f-string,
避免 f-string 把 JSON 的 {} 当成表达式。
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from typing import Any, Sequence

from .llm import LLMClient, LLMContext

DEFAULT_BASE_URL = "http://10.121.39.10:30005"
DEFAULT_MODEL = "/data/models/Qwen3.8-27B-Coder/BF16"


def _extract_json(text: str) -> str:
    """从模型输出里抠出 JSON 片段 (容忍 markdown 代码围栏与前后杂字)。"""
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        t = parts[1] if len(parts) > 1 else t
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    for open_c, close_c in (("[", "]"), ("{", "}")):
        s = t.find(open_c)
        e = t.rfind(close_c)
        if s != -1 and e > s:
            return t[s:e + 1]
    return t


def _parse_hour(value: Any) -> int | None:
    """从模型输出提取整点小时。容忍 int / 浮点整数 / "7" / "07:00" (取冒号前);
    解析不出 (None、"早上"等纯文字) 返回 None, 由调用方丢弃整块 —— 不抛异常
    (旧实现 int() 直接炸, 一个坏输出崩掉整个 World.step)。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        head = value.strip().split(":")[0]
        if head.isdigit():
            return int(head)
    return None


def _parse_blocks(items: Any, activity_key: str,
                  lo: int = 0, hi: int = 24) -> list[tuple[int, int, str]]:
    """把模型计划输出解析为合法时间块 (generate_plan / decompose_activity 共用)。

    - 类型容错: "07:00" 这类救得回的救, 救不回的丢弃该块;
    - 范围/顺序: lo <= start < end <= hi, 倒置块、超范围块丢弃;
      日计划边界 (0, 24), 分解子任务边界 = 父块 (start, end);
    - 缺键丢弃: 不再 .get("start", 8) 静默编时间, 宁可少一块不造一块;
    - 全坏返回 [], 调用方按空计划处理 (诚实: "当前正忙"没有块可报)。
    """
    out: list[tuple[int, int, str]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict) or activity_key not in item:
            continue
        s = _parse_hour(item.get("start"))
        e = _parse_hour(item.get("end"))
        if s is None or e is None:
            continue   # 解析不出 / 缺键: 整块丢弃
        if not (lo <= s < e <= hi):
            continue   # 倒置 / 超范围
        out.append((s, e, str(item[activity_key])))
    return out


class RealLLM(LLMClient):
    """OpenAI 兼容 (SGLang) 真实模型客户端。"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL, api_key: str = "",
                 enable_thinking: bool = False,
                 timeout: float = 60.0, max_retries: int = 2) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        # 对话是否开思考 (结构化 JSON 任务恒关思考, 防截断)
        self._think = enable_thinking
        self._timeout = timeout
        self._max_retries = max_retries
        # 用量统计 (实验埋点, 纯增量): 每次 _chat 尝试计一次调用, 从响应读回 usage。
        # by_method 按推理类别分桶, 供调度效率实验拆解成本。计数器不改任何调用行为。
        self.stats: dict[str, Any] = {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_latency_s": 0.0,
            "by_method": {},
        }

    def reset_stats(self) -> None:
        """清零用量统计 (实验跑批之间用)。"""
        self.stats = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                      "total_latency_s": 0.0, "by_method": {}}

    # ------------------------------------------------------------- 底层请求
    def _chat(self, system: str, user: str, *, think: bool = False,
              temperature: float = 0.0, max_tokens: int = 512,
              _stats_tag: str = "unspecified") -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 思考型模型: 按调用决定是否思考
            "chat_template_kwargs": {"enable_thinking": think},
        }
        data = json.dumps(body).encode("utf-8")
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            t0 = time.monotonic()
            try:
                req = urllib.request.Request(
                    self._base_url + "/v1/chat/completions",
                    data=data, method="POST",
                    headers={"Content-Type": "application/json",
                             **({"Authorization": f"Bearer {self._api_key}"}
                                if self._api_key else {})})
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self._record_stats(_stats_tag, time.monotonic() - t0,
                                   payload.get("usage") or {})
                msg = payload["choices"][0]["message"]
                return msg.get("content") or ""
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, OSError, KeyError, json.JSONDecodeError) as e:
                self._record_stats(_stats_tag, time.monotonic() - t0, {})
                last_err = e
                if attempt < self._max_retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise RuntimeError(f"LLM 请求失败: {e}") from e
        raise RuntimeError(f"LLM 请求失败: {last_err}")

    def _record_stats(self, tag: str, latency_s: float, usage: dict) -> None:
        """记一次 _chat 尝试 (失败也耗了服务端资源, 同样记账; usage 缺失记 0)。"""
        p_tok = int(usage.get("prompt_tokens") or 0)
        c_tok = int(usage.get("completion_tokens") or 0)
        s = self.stats
        s["calls"] += 1
        s["prompt_tokens"] += p_tok
        s["completion_tokens"] += c_tok
        s["total_latency_s"] += latency_s
        per = s["by_method"].setdefault(tag, {"calls": 0, "prompt_tokens": 0,
                                              "completion_tokens": 0,
                                              "total_latency_s": 0.0})
        per["calls"] += 1
        per["prompt_tokens"] += p_tok
        per["completion_tokens"] += c_tok
        per["total_latency_s"] += latency_s

    # ------------------------------------------------------------- 通用问答
    def ask(self, question: str, system: str = "", *, think: bool = False,
            temperature: float = 0.0, max_tokens: int = 256) -> str:
        """公开的单轮问答 (供探针裁判、外部逻辑复用)。默认关思考、低温。"""
        return self._chat(system or "你是一个简洁的助手。", question,
                          think=think, temperature=temperature,
                          max_tokens=max_tokens, _stats_tag="ask")

    def _chat_json(self, system: str, user: str, *, think: bool = False,
                   temperature: float = 0.0, max_tokens: int = 2048,
                   _stats_tag: str = "unspecified") -> Any:
        """请求模型返回严格 JSON 并解析; 解析失败则重试一次。"""
        raw = self._chat(system, user, think=think, temperature=temperature,
                         max_tokens=max_tokens, _stats_tag=_stats_tag)
        try:
            return json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            retry = self._chat(system, user + "\n\n只输出 JSON, 不要任何其他文字。",
                               think=think, temperature=0.0, max_tokens=max_tokens,
                               _stats_tag=_stats_tag)
            return json.loads(_extract_json(retry))

    # ------------------------------------------------------------- 对话/反应
    def complete(self, ctx: LLMContext) -> str:
        memories = ctx.memories or []
        if not memories:
            return "我对此没有印象。"

        def _mem_line(m: dict) -> str:
            # 被削弱的反思 (confidence<1) 显式标注置信度, 让 NPC 引用被部分推翻的
            # 信念时带着相应的犹疑; 观察/计划恒 1.0, 保持原样不注水。
            if m.get("type") == "reflection" and m.get("confidence", 1.0) < 0.999:
                return f"- [反思] (置信度{m['confidence']:.2f}) {m['content']}"
            return f"- [{m['type']}] {m['content']}"

        mem_lines = "\n".join(_mem_line(m) for m in memories)
        who = f"当前和你说话的人是 {ctx.player_id}。" if ctx.player_id else ""
        user = (who + "\n你记得的事情 (只准用这些, 没提到的就当不知道):\n"
                + mem_lines + "\n带'置信度'的记忆已被后来的事情部分推翻, "
                "引用时语气要留有余地。\n\n对方说: " + ctx.question
                + "\n\n用第一人称、符合你性格地回应对方。只说一两句。")
        return self._chat(ctx.system or "你是一个游戏 NPC, 只用你记得的事说话。",
                          user, think=self._think, temperature=0.7, max_tokens=256,
                          _stats_tag="complete")

    # ------------------------------------------------------------ 重要性打分
    def score_importance(self, text: str, player_id: str | None = None) -> float:
        who = f" (与玩家 {player_id} 直接相关)" if player_id else ""
        user = ("判断下面这条 NPC 记忆的重要性, 只输出 1 到 10 的整数。\n"
                "1-3 日常琐事, 4-6 一般事件, 7-8 重要关系/冲突, 9-10 重大事件"
                + who + "。\n\n记忆: " + text)
        raw = self._chat("你是一个记忆重要性评估器。", user,
                         think=False, temperature=0.0, max_tokens=8,
                         _stats_tag="score_importance").strip()
        # 提取第一个数字 (可能多位)
        idx = next((i for i, ch in enumerate(raw) if ch.isdigit()), None)
        if idx is None:
            return 5.0
        num = raw[idx:]
        digits = ""
        for ch in num:
            if ch.isdigit():
                digits += ch
            else:
                break
        return max(1.0, min(10.0, float(digits) if digits else 5))

    # -------------------------------------------------------- 反思问题生成
    def reflection_questions(self, recent: Sequence[str]) -> list[str]:
        mem_lines = "\n".join(f"{i+1}. {m}" for i, m in enumerate(recent[-100:]))
        user = ("以下是 NPC 最近的记忆:\n" + mem_lines
                + "\n\n基于这些, 提出 3 个最值得反思的高层次问题 "
                  "(关于人物的兴趣/关系/动机)。\n"
                  '输出 JSON 数组, 例如 ["问题1", "问题2", "问题3"]。')
        # 结构化 JSON 任务关思考: 思考 token 会挤爆 max_tokens 导致 JSON 截断
        data = self._chat_json("你是一个反思问题生成器。", user,
                               think=False, temperature=0.0,
                               _stats_tag="reflection_questions")
        if isinstance(data, list):
            return [str(x) for x in data][:3]
        return []

    # -------------------------------------------------------- 反思洞察生成
    def reflection_insights(self, evidence: list[tuple[int, str]],
                            n: int = 5) -> list[tuple[str, list[int]]]:
        ev_lines = "\n".join(f"{i}. {c}" for i, c in evidence)
        user = ("以下是编号的记忆证据:\n" + ev_lines
                + "\n\n从这些证据推断出最多 " + str(n)
                + " 条高层 Insight, 并给出每条所依据的证据编号。\n"
                  '输出 JSON 数组, 例如 [{"insight": "...", "evidence": [1, 3]}]。')
        data = self._chat_json("你是一个从证据归纳 Insight 的推理器。", user,
                               think=False, temperature=0.0,
                               _stats_tag="reflection_insights")
        valid_ids = {int(i) for i, _ in evidence}      # 传入证据的真实记忆 id
        all_ids = [int(i) for i, _ in evidence]
        out: list[tuple[str, list[int]]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "insight" in item:
                    ev = item.get("evidence", [])
                    raw = [int(x) for x in ev if str(x).lstrip("-").isdigit()]
                    cited = [x for x in raw if x in valid_ids]   # 只留真实存在的编号
                    if not cited:
                        # 模型回纯顺序号 (1,2,3) 或幻影编号: 一条洞察总得有据可查,
                        # 全引传入证据 (宁宽勿断链), 而非入库一堆不存在的 id。
                        cited = list(all_ids)
                    out.append((str(item["insight"]), cited))
        return out[:n]

    # ------------------------------------------------------------- 日计划生成
    def generate_plan(self, persona_traits: dict[str, float],
                      previous_day: str, date: str,
                      context: str = "") -> list[tuple[int, int, str]]:
        ctx_line = ("该 NPC 近期的记忆与所处世界: " + context + "\n") if context else ""
        user = ("为一个 NPC 生成 " + date + " 的一天计划。人格特质: "
                + str(persona_traits) + "。\n" + ctx_line
                + "前一天活动: " + (previous_day or "(无)")
                + "\n结合上述世界背景与人格, 生成 5 到 8 个时间块。"
                  "若世界正处于紧张/危机 (如迫害、搜捕、禁令), 计划应体现谨慎与应对 "
                  "(避开危险地、低调、检查藏匿处、准备应变); 若世界平静, 才是寻常日子。"
                  "输出 JSON 数组, "
                  '例如 [{"start": 7, "end": 9, "activity": "起床"}]。')
        data = self._chat_json("你是一个日程规划器。", user,
                               think=False, temperature=0.3,
                               _stats_tag="generate_plan")
        # 类型容错 + 范围/顺序校验 (0 <= start < end <= 24), 坏块丢弃不崩
        return _parse_blocks(data, "activity", 0, 24)

    # ------------------------------------------------------------ 活动分解
    def decompose_activity(self, activity: str, start: int, end: int) -> \
            list[tuple[int, int, str]]:
        user = ("把活动 '" + activity + "' 从 " + f"{start:02d}" + ":00 到 "
                + f"{end:02d}" + ":00 分解为小时级子任务。\n"
                '输出 JSON 数组, 例如 [{"start": 13, "end": 14, "subtask": "构思"}]。')
        data = self._chat_json("你是一个任务分解器。", user,
                               think=False, temperature=0.0,
                               _stats_tag="decompose_activity")
        # 子任务时间必须落在父块 (start, end) 内: 模型常漂回默认 8 点, 越界即丢
        return _parse_blocks(data, "subtask", start, end)

    # ------------------------------------------------------------ 事件价值判断
    def score_event(self, event: str, persona_traits: dict[str, float],
                    current_plan: str = "") -> tuple[float, float, float]:
        """让 LLM 判断事件价值 (社交/目标/打断代价), 各 0-10。取代关键词死表。"""
        plan_line = ("当前正忙: " + current_plan) if current_plan else "当前没有特别重要的计划。"
        user = ("为一个 NPC 判断下面这个事件的价值。人格特质: "
                + str(persona_traits) + "。\n" + plan_line + "\n\n"
                + "事件: " + event + "\n\n"
                + "判断三个维度, 各打 0 到 10 的整数:\n"
                + "- v_social 社交价值: 这件事对这个人物有多大的社交吸引力/参与价值\n"
                + "- v_goal 目标价值: 这件事与他当前目标/计划的契合度\n"
                + "- c_interrupt 打断代价: 放下手头事去响应这件事的损失\n\n"
                + '输出 JSON, 例如 {"v_social": 8, "v_goal": 1, "c_interrupt": 3}。')
        data = self._chat_json("你是一个事件价值评估器, 只输出 JSON。", user,
                               think=False, temperature=0.0, max_tokens=128,
                               _stats_tag="score_event")
        if not isinstance(data, dict):
            return (3.0, 3.0, 2.0)
        def _clip(key: str, default: float) -> float:
            try:
                return max(0.0, min(10.0, float(data.get(key, default))))
            except (TypeError, ValueError):
                return default
        return (_clip("v_social", 3.0), _clip("v_goal", 3.0),
                _clip("c_interrupt", 2.0))

    # ------------------------------------------------------------ 关系信任度
    def judge_trust(self, memories: list[tuple[str, str, float]],
                    player_id: str) -> float:
        """基于关系记忆判断对玩家的信任度, 返回 -1..1。取代关键词词表。

        memories 是 (类型, 内容, 置信度)。置信度 <1 的反思已被后续证据部分
        矛盾 (信念削弱), prompt 里显式标注并嘱咐少加权。
        """
        def _line(t: str, c: str, conf: float) -> str:
            tag = "" if conf >= 0.999 else f" (置信度{conf:.2f})"
            return f"- [{t}]{tag} {c}"
        mem_lines = "\n".join(_line(t, c, conf) for t, c, conf in memories)
        user = ("以下是 NPC 关于玩家 " + player_id + " 的记忆 (观察与反思):\n"
                + mem_lines + "\n\n带'置信度'标注的反思已被后续证据部分矛盾, "
                "信念被削弱, 判断时应少加权。带'[传闻N跳]'的记忆是转述而非亲见, "
                "可信度按跳数打折, N 越大越不可信。\n\n判断 NPC 对 " + player_id
                + " 的信任度, 只输出 -10 到 10 的整数 (可带负号):\n"
                + "-10 极度不信任/被背叛过, -5 略有戒备, 0 中立/不太了解, "
                + "+5 比较信任, +10 极度信任/很可靠。")
        raw = self._chat("你是一个关系信任度评估器, 只输出一个整数。", user,
                         think=False, temperature=0.0, max_tokens=8,
                         _stats_tag="judge_trust").strip()
        return self._extract_int(raw, -10, 10) / 10.0

    # ------------------------------------------------------------ 矛盾强度
    def judge_conflict(self, reflection: str, observation: str) -> int:
        """判断更晚观察与反思的矛盾强度 0-10。取代词表方向匹配。"""
        user = ("下面是 NPC 的一条关系反思, 和一条更晚发生的观察。\n"
                "反思: " + reflection + "\n"
                "观察: " + observation + "\n\n"
                "判断这条更晚的观察是否与反思矛盾, 输出矛盾强度 0 到 10 的整数:\n"
                "0 = 完全一致/无关, 5 = 部分矛盾(有所削弱), 10 = 强烈矛盾(直接推翻)。\n"
                "只输出整数。")
        raw = self._chat("你是一个记忆矛盾检测器, 只输出一个 0 到 10 的整数。",
                         user, think=False, temperature=0.0, max_tokens=8,
                         _stats_tag="judge_conflict").strip()
        return self._extract_int(raw, 0, 10, default=0)

    # ------------------------------------------------------------ 动作观察
    def perceive_action(self, npc_name: str, player_name: str, action: str,
                        context: str = "") -> str:
        """NPC 把对方的动作观察成自己的描述 (第三人称)。观察内容由 NPC 生成。"""
        ctx_line = ("你目前关于" + player_name + "的记忆: " + context + "\n") if context else ""
        user = ("你是游戏 NPC「" + npc_name + "」。「" + player_name
                + "」刚刚对你做了这样一件事: " + action + "。\n" + ctx_line
                + "\n用第三人称客观描述你观察到的这件事 (一句话): 称自己为你的名字"
                + "「" + npc_name + "」, 称对方为「" + player_name
                + "」, 只描述动作事实, 不加评价、不揣测动机。直接输出这句话。")
        return self._chat("你是游戏 NPC 的观察者, 客观描述你看到的事, 只输出一句话。",
                          user, think=False, temperature=0.4, max_tokens=64,
                          _stats_tag="perceive_action").strip()

    # ------------------------------------------------------------ Agent 决策
    def decide_action(self, agent_name: str, goal: str,
                      persona_traits: dict[str, float], perception: str,
                      history: list[str], state: str) -> dict:
        """Agent 决策下一步动作 (非全知)。输出结构化动作 JSON。"""
        hist = "\n".join(f"- {h}" for h in history[-10:]) or "(无)"
        user = ("你是游戏角色「" + agent_name + "」。你的目标: " + (goal or "(无)")
                + "。人格特质: " + str(persona_traits) + "。\n"
                + "你当前看到的 (非全知, 仅视距内): " + (perception or "(空无一人)") + "\n"
                + "你近期的经历:\n" + hist + "\n"
                + "你的状态: " + state + "\n\n"
                + "基于以上, 决定你下一步做什么。输出 JSON 对象:\n"
                + '{"action": "move"|"talk"|"attack"|"help"|"hide"|"flee"|"wait",'
                + ' "target": "对象名或空", "utterance": "若对话说什么, 否则空",'
                + ' "dest": "若移动去哪区域, 否则空", "reason": "简述理由"}\n'
                + "action 选一个; 只输出 JSON。")
        try:
            data = self._chat_json("你是一个游戏角色决策器, 只输出一个 JSON 对象。",
                                   user, think=False, temperature=0.2,
                                   _stats_tag="decide_action")
        except (ValueError, RuntimeError):
            # 解析失败 (模型截断 JSON 等) 或网络重试耗尽 (RuntimeError) 兜底
            # wait: 一条坏输出/一次超时不能拖垮整个 World.step 自治循环
            # (同 _parse_hour 的防御原则)。
            return {"action": "wait", "target": "", "utterance": "",
                    "dest": "", "reason": "决策解析失败"}
        if isinstance(data, dict) and "action" in data:
            return {"action": str(data.get("action", "wait")),
                    "target": str(data.get("target", "")),
                    "utterance": str(data.get("utterance", "")),
                    "dest": str(data.get("dest", "")),
                    "reason": str(data.get("reason", ""))}
        return {"action": "wait", "target": "", "utterance": "",
                "dest": "", "reason": "解析失败"}

    # ------------------------------------------------------------ 记忆固化
    def consolidate_observations(self, observations: Sequence[str],
                                 player_id: str | None = None) -> str:
        """记忆固化 (第 12 类推理, M1): 一天的原始观察 → 1-3 句情节摘要。

        有损压缩: 保事件/对象/因果, 丢措辞细节。摘要进 episode 记忆, 顶替被吸收
        观察在冲突扫描里的"更晚证据"角色。temperature 0.2 取稳定, max_tokens 96
        够 1-3 句中文。
        """
        scope = ("关于" + player_id) if player_id else "世界与自我"
        obs = "\n".join(f"- {o}" for o in observations) or "(无)"
        user = ("下面是游戏 NPC 今天" + scope + "的原始观察记录:\n" + obs
                + "\n\n把这一天压缩成 1 到 3 句情节摘要: 保留发生的事件、涉及的"
                + "对象和因果关系, 用第三人称客观叙述 (称 NPC 为其名字, 称对方为"
                + "其名字), 不新增事实、不加评价。直接输出摘要文本。")
        return self._chat("你是游戏 NPC 的记忆整理者, 把一天的观察压成情节摘要, 只输出摘要。",
                          user, think=False, temperature=0.2, max_tokens=96,
                          _stats_tag="consolidate_observations").strip()

    @staticmethod
    def _extract_int(raw: str, lo: int, hi: int, default: int = 0) -> int:
        """提取第一个整数并夹到 [lo, hi]; 支持负号; 提不出给 default。"""
        i, n = 0, len(raw)
        while i < n and raw[i] not in "-0123456789":
            i += 1
        if i >= n:
            return default
        sign = 1
        if raw[i] == "-":
            sign = -1
            i += 1
        digits = ""
        while i < n and raw[i].isdigit():
            digits += raw[i]
            i += 1
        if not digits:
            return default
        return max(lo, min(hi, sign * int(digits)))


