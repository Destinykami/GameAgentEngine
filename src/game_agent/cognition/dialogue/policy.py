"""对话历史路由及字符预算：确定性规则，无模型或数据库依赖。"""
from __future__ import annotations

import re


CONTEXT_CHAR_BUDGET = 3000
HISTORY_PATTERN = re.compile(
    r'记得|回忆|以前|从前|上次|当时|曾经|原话|说过|答应|承诺|约定|履行|'
    r'任务.*(?:进度|完成)|(?:进度|完成).*任务|'
    r'\b(?:remember|recall|previous|earlier|promis\w*|last time|used to)\b', re.I)


def needs_history(utterance: str) -> bool:
    """可替换的首版路由；不声称覆盖所有隐含回忆意图。"""
    if re.search(r'别翻旧账|不要翻旧账|别再提|不要再提|stop bringing up', utterance, re.I):
        return False
    return bool(HISTORY_PATTERN.search(utterance))


def fit_budget(records: list[dict], budget: int = CONTEXT_CHAR_BUDGET,
               limit: int = 12) -> list[dict]:
    out, seen = [], set()
    for rec in records:
        key = ('archive' if rec.get('layer') == 'archive' else 'memory', rec.get('id'))
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
        budget -= length
    return out
