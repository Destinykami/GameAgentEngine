"""将军裁决提示词与容错；不驱动世界循环。"""

import json

def _parse_json_obj(raw: str) -> dict | None:
    """从模型输出里抠出 JSON 对象 (容忍 markdown 代码围栏与前后杂字); 失败返 None。"""
    t = raw.strip()
    if t.startswith("```"):
        parts = t.split("```")
        t = parts[1] if len(parts) > 1 else t
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except Exception:
            return None
    return None


def _judge_shogun(llm, shogun, traveler, utterance: str, reply: str) -> tuple[bool, str]:
    """B+ 涌现: LLM 当场裁决将军是否被说服到废止眼狩令 (替代计数器)。

    依据 = 她的目标(信念) + 旅行者已呈上的全部证据(累积) + 本次对话往来。极固执、
    空口白话不动摇、需实证且被反复打动 —— 这些约束写进裁决提示, 由 LLM 综合判断。
    返回 (是否被说服, 裁决依据)。无 LLM / 解析失败 → (False, ...) 保守不误判。
    """
    if llm is None or not hasattr(llm, "ask"):
        return False, ""
    evidence = " / ".join(traveler.reasons) if traveler.reasons else "尚未呈上任何证据"
    prompt = (
        f"你裁决雷电将军是否已被说服到废止眼狩令。\n"
        f"她的目标/信念: {shogun.goal}\n"
        f"旅行者已呈上的证据(累积): {evidence}\n"
        f"本次对话旅行者说: {utterance}\n将军答: {reply}\n"
        "综合以上, 她现在是否被充分打动而愿意废止眼狩令? 她极固执重秩序, "
        "空口白话动摇不了她, 需切实的实证且被反复打动才肯。"
        '输出严格 JSON: {"revoked": true|false, "reason": "一句话依据"}'
    )
    try:
        raw = llm.ask(prompt, system="你是将军心志的裁决者, 只输出 JSON。",
                      max_tokens=200)
    except Exception:
        return False, ""
    data = _parse_json_obj(raw)
    if not data:
        return False, ""
    return bool(data.get("revoked", False)), str(data.get("reason", ""))
