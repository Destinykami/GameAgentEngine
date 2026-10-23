"""原任务提示词及结果转换；只依赖传入的请求能力。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Sequence

from .parsing import extract_int

def score_importance(request: Callable[..., str], text: str, player_id: str | None = None) -> float:
    who = f" (与玩家 {player_id} 直接相关)" if player_id else ""
    user = ("判断下面这条 NPC 记忆的重要性, 只输出 1 到 10 的整数。\n"
            "1-3 日常琐事, 4-6 一般事件, 7-8 重要关系/冲突, 9-10 重大事件"
            + who + "。\n\n记忆: " + text)
    raw = request("你是一个记忆重要性评估器。", user,
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


def reflection_questions(request: Callable[..., Any], recent: Sequence[str]) -> list[str]:
    mem_lines = "\n".join(f"{i+1}. {m}" for i, m in enumerate(recent[-100:]))
    user = ("以下是 NPC 最近的记忆:\n" + mem_lines
            + "\n\n基于这些, 提出 3 个最值得反思的高层次问题 "
              "(关于人物的兴趣/关系/动机)。\n"
              '输出 JSON 数组, 例如 ["问题1", "问题2", "问题3"]。')
    # 结构化 JSON 任务关思考: 思考 token 会挤爆 max_tokens 导致 JSON 截断
    data = request("你是一个反思问题生成器。", user,
                           think=False, temperature=0.0,
                           _stats_tag="reflection_questions")
    if isinstance(data, list):
        return [str(x) for x in data][:3]
    return []


def reflection_insights(request: Callable[..., Any], evidence: list[tuple[int, str]],
                        n: int = 5) -> list[tuple[str, list[int]]]:
    ev_lines = "\n".join(f"{i}. {c}" for i, c in evidence)
    user = ("以下是编号的记忆证据:\n" + ev_lines
            + "\n\n从这些证据推断出最多 " + str(n)
            + " 条高层 Insight, 并给出每条所依据的证据编号。\n"
              '输出 JSON 数组, 例如 [{"insight": "...", "evidence": [1, 3]}]。')
    data = request("你是一个从证据归纳 Insight 的推理器。", user,
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


def judge_trust(request: Callable[..., str], memories: list[tuple[str, str, float]],
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
    raw = request("你是一个关系信任度评估器, 只输出一个整数。", user,
                     think=False, temperature=0.0, max_tokens=8,
                     _stats_tag="judge_trust").strip()
    return extract_int(raw, -10, 10) / 10.0


def judge_conflict(request: Callable[..., str], reflection: str, observation: str) -> int:
    """判断更晚观察与反思的矛盾强度 0-10。取代词表方向匹配。"""
    user = ("下面是 NPC 的一条关系反思, 和一条更晚发生的观察。\n"
            "反思: " + reflection + "\n"
            "观察: " + observation + "\n\n"
            "判断这条更晚的观察是否与反思矛盾, 输出矛盾强度 0 到 10 的整数:\n"
            "0 = 完全一致/无关, 5 = 部分矛盾(有所削弱), 10 = 强烈矛盾(直接推翻)。\n"
            "只输出整数。")
    raw = request("你是一个记忆矛盾检测器, 只输出一个 0 到 10 的整数。",
                     user, think=False, temperature=0.0, max_tokens=8,
                     _stats_tag="judge_conflict").strip()
    return extract_int(raw, 0, 10, default=0)


def consolidate_observations(request: Callable[..., str], observations: Sequence[str],
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
    return request("你是游戏 NPC 的记忆整理者, 把一天的观察压成情节摘要, 只输出摘要。",
                      user, think=False, temperature=0.2, max_tokens=96,
                      _stats_tag="consolidate_observations").strip()
