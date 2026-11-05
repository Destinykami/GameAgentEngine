"""对话历史路由及字符预算：确定性规则，无模型或数据库依赖。"""
from __future__ import annotations

import re


CONTEXT_CHAR_BUDGET = 3000
GREETING_PATTERN = re.compile(
    r'\s*(?:你好|您好|嗨|早上好|晚上好|早安|晚安|谢谢|再见|hello|hi|thanks|bye)'
    r'[\s！!。，,.？?~～]*', re.I)


def needs_history(utterance: str) -> bool:
    """明确寒暄和拒绝翻旧事走背景，其他信息请求允许有界检索。"""
    if re.search(r'别翻旧账|不要翻旧账|别再提|不要再提|stop bringing up', utterance, re.I):
        return False
    return bool(utterance.strip()) and GREETING_PATTERN.fullmatch(utterance) is None


def fit_budget(records: list[dict], budget: int = CONTEXT_CHAR_BUDGET,
               limit: int = 12) -> list[dict]:
    out, seen, covered = [], set(), {}
    for rec in records:
        raw = rec.get('category') == 'raw_archive'
        key = ('archive', rec.get('archive_id'), rec.get('id')) if raw else ('memory', rec.get('id'))
        sources = {(ref['archive_id'], ref['source_id']) for ref in rec.get('source_refs', ())}
        if not raw and sources and sources <= covered.keys():
            text = str(rec.get('content', ''))
            # 片段命中未必涵盖整条观察；只有完整来源或实际重复文本才去重。
            if (all(not covered[source].get('truncated', False) for source in sources)
                    or any(text and text in covered[source]['content'] for source in sources)):
                continue
        if key in seen or len(out) >= max(0, limit) or budget <= 0:
            continue
        seen.add(key)
        text = str(rec.get('content', ''))
        if not text:
            continue
        length = min(len(text), budget, 800)
        # 保留原文片段偏移，截断不伪装为完整原句。
        view = dict(rec, content=text[:length])
        if length < len(text):
            view['truncated'] = True
            if 'start' in view:
                view['end'] = view['start'] + length
        out.append(view)
        if raw:
            covered[(rec.get('archive_id'), rec.get('id'))] = view
        budget -= length
    return out
