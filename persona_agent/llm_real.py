"""真实 LLM 客户端: 通过 OpenAI 兼容接口接入 SGLang 部署的模型。

默认接入: http://10.121.39.10:30005 上的 Qwen3.8-27B-Coder/BF16 (SGLang)。
- 用标准库 urllib 发请求, 不引入 openai / requests 依赖。
- 这是思考型模型: 对话/打分默认关思考 (快), 反思/规划开思考 (推理更好)。
  关思考用 SGLang 的 chat_template_kwargs={"enable_thinking": false}。
- 结构化输出 (问题/洞察/计划) 要求模型返回严格 JSON, 并做容错解析。

实现 LLMClient 接口的全部 6 个方法。
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

    # ------------------------------------------------------------- 底层请求
    def _chat(self, system: str, user: str, *, think: bool = False,
              temperature: float = 0.0, max_tokens: int = 512) -> str:
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
            try:
                req = urllib.request.Request(
                    self._base_url + "/v1/chat/completions",
                    data=data, method="POST",
                    headers={"Content-Type": "application/json",
                             **({"Authorization": f"Bearer {self._api_key}"}
                                if self._api_key else {})})
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                msg = payload["choices"][0]["message"]
                return msg.get("content") or ""
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, OSError, KeyError, json.JSONDecodeError) as e:
                last_err = e
                if attempt < self._max_retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise RuntimeError(f"LLM 请求失败: {e}") from e
        raise RuntimeError(f"LLM 请求失败: {last_err}")

    # ------------------------------------------------------------- 通用问答
    def ask(self, question: str, system: str = "", *, think: bool = False,
            temperature: float = 0.0, max_tokens: int = 256) -> str:
        """公开的单轮问答 (供探针裁判、外部逻辑复用)。默认关思考、低温。"""
        return self._chat(system or "你是一个简洁的助手。", question,
                          think=think, temperature=temperature,
                          max_tokens=max_tokens)

    def _chat_json(self, system: str, user: str, *, think: bool = False,
                   temperature: float = 0.0, max_tokens: int = 2048) -> Any:
        """请求模型返回严格 JSON 并解析; 解析失败则重试一次。"""
        raw = self._chat(system, user, think=think, temperature=temperature,
                         max_tokens=max_tokens)
        try:
            return json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            retry = self._chat(system, user + "\n\n只输出 JSON, 不要任何其他文字。",
                               think=think, temperature=0.0, max_tokens=max_tokens)
            return json.loads(_extract_json(retry))

    # ------------------------------------------------------------- 对话/反应
    def complete(self, ctx: LLMContext) -> str:
        memories = ctx.memories or []
        if not memories:
            return "我对此没有印象。"
        mem_lines = "\n".join(
            f"- [{m['type']}] {m['content']}" for m in memories)
        who = f"当前和你说话的人是 {ctx.player_id}。" if ctx.player_id else ""
        user = (who + "\n你记得的事情 (只准用这些, 没提到的就当不知道):\n"
                + mem_lines + "\n\n对方说: " + ctx.question
                + "\n\n用第一人称、符合你性格地回应对方。只说一两句。")
        return self._chat(ctx.system or "你是一个游戏 NPC, 只用你记得的事说话。",
                          user, think=self._think, temperature=0.7, max_tokens=256)

    # ------------------------------------------------------------ 重要性打分
    def score_importance(self, text: str, player_id: str | None = None) -> float:
        who = f" (与玩家 {player_id} 直接相关)" if player_id else ""
        user = ("判断下面这条 NPC 记忆的重要性, 只输出 1 到 10 的整数。\n"
                "1-3 日常琐事, 4-6 一般事件, 7-8 重要关系/冲突, 9-10 重大事件"
                + who + "。\n\n记忆: " + text)
        raw = self._chat("你是一个记忆重要性评估器。", user,
                         think=False, temperature=0.0, max_tokens=8).strip()
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
                               think=False, temperature=0.0)
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
                               think=False, temperature=0.0)
        out: list[tuple[str, list[int]]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "insight" in item:
                    ev = item.get("evidence", [])
                    ev_ids = [int(x) for x in ev if str(x).lstrip("-").isdigit()]
                    out.append((str(item["insight"]), ev_ids))
        return out[:n]

    # ------------------------------------------------------------- 日计划生成
    def generate_plan(self, persona_traits: dict[str, float],
                      previous_day: str, date: str) -> list[tuple[int, int, str]]:
        user = ("为一个 NPC 生成 " + date + " 的一天计划。人格特质: "
                + str(persona_traits) + "。\n前一天活动: " + (previous_day or "(无)")
                + "\n生成 5 到 8 个时间块, 符合人格。输出 JSON 数组, "
                  '例如 [{"start": 7, "end": 9, "activity": "起床"}]。')
        data = self._chat_json("你是一个日程规划器。", user,
                               think=False, temperature=0.3)
        out: list[tuple[int, int, str]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "activity" in item:
                    s = int(item.get("start", 8))
                    e = int(item.get("end", s + 1))
                    out.append((s, e, str(item["activity"])))
        return out

    # ------------------------------------------------------------ 活动分解
    def decompose_activity(self, activity: str, start: int, end: int) -> \
            list[tuple[int, int, str]]:
        user = ("把活动 '" + activity + "' 从 " + f"{start:02d}" + ":00 到 "
                + f"{end:02d}" + ":00 分解为小时级子任务。\n"
                '输出 JSON 数组, 例如 [{"start": 13, "end": 14, "subtask": "构思"}]。')
        data = self._chat_json("你是一个任务分解器。", user,
                               think=False, temperature=0.0)
        out: list[tuple[int, int, str]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "subtask" in item:
                    s = int(item.get("start", start))
                    e = int(item.get("end", start + 1))
                    out.append((s, e, str(item["subtask"])))
        return out
