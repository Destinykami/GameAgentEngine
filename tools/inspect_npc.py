#!/usr/bin/env python3
"""inspect_npc.py — 只读审查 NPC 的记忆库 (data/<name>.db)。

用法:
  python tools/inspect_npc.py data/Isabella.db                 # 全量转储 (按玩家分组)
  python tools/inspect_npc.py data/Isabella.db --player Aria   # 只看某玩家的关系流
  python tools/inspect_npc.py data/Isabella.db --type reflection
  python tools/inspect_npc.py data/Isabella.db --search 派对
  python tools/inspect_npc.py data/Isabella.db --trust         # 只看信任度汇总
  python tools/inspect_npc.py data/Isabella.db --include-invalid  # 含已失效反思
  python tools/inspect_npc.py data/Isabella.db --json          # 机器可读导出
  python tools/inspect_npc.py --list [data_dir]                # 列出可审查的 NPC

只读: 不写库、不改 last_accessed (不走 retrieve, 直接查表)。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent.reacting import ReactionDecider  # noqa: E402
from persona_agent.reflection import TRUST_WORDS, DISTRUST_WORDS  # noqa: E402


def _open_ro(path: str) -> sqlite3.Connection:
    """以只读 URI 打开, 物理上杜绝误写。"""
    if not os.path.exists(path):
        sys.exit(f"文件不存在: {path}")
    conn = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    return conn


def _rows(conn: sqlite3.Connection, include_invalid: bool = False) -> list[dict]:
    has_base = "base_confidence" in {r[1] for r in conn.execute(
        "PRAGMA table_info(memory)")}
    base_col = ", base_confidence" if has_base else ""
    sql = f"""SELECT id, type, content, timestamp, importance, player_id,
                    evidence, confidence, valid, last_accessed{base_col}
             FROM memory"""
    if not include_invalid:
        sql += " WHERE valid = 1"
    sql += " ORDER BY timestamp, id"
    cols = ("id", "type", "content", "timestamp", "importance", "player_id",
            "evidence", "confidence", "valid", "last_accessed")
    if has_base:
        cols = cols + ("base_confidence",)
    return [dict(zip(cols, r)) for r in conn.execute(sql).fetchall()]


def _meta(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def _trust_map(conn: sqlite3.Connection) -> dict[str, float]:
    """复用运行时同款词表计算信任度 (与 reaction 决策看到的完全一致)。"""
    rows = conn.execute(
        "SELECT DISTINCT player_id FROM memory "
        "WHERE player_id IS NOT NULL AND valid = 1"
    ).fetchall()
    trust = {}
    for (pid,) in rows:
        contents = [r[0] for r in conn.execute(
            "SELECT content FROM memory WHERE player_id = ? AND valid = 1",
            (pid,))]
        pos = sum(1 for c in contents
                  if any(w in c for w in TRUST_WORDS + ("帮助", "帮", "感谢")))
        neg = sum(1 for c in contents
                  if any(w in c for w in DISTRUST_WORDS
                         + ("背叛", "欺骗", "撒谎", "骗", "偷")))
        trust[pid] = (pos - neg) / (pos + neg) if (pos + neg) else 0.0
    return trust


def _group(recs: list[dict]) -> dict[str | None, list[dict]]:
    groups: dict[str | None, list[dict]] = {}
    for r in recs:
        groups.setdefault(r["player_id"], []).append(r)
    return groups


def _fmt_rec(r: dict, content_by_id: dict[int, str]) -> str:
    ev = json.loads(r["evidence"] or "[]")
    bits = [f"[{r['type']:10s} t={r['timestamp']:6.1f} imp={r['importance']:4.1f}"]
    if r["player_id"]:
        bits.append(f"player={r['player_id']}")
    if r["type"] == "reflection":
        base = r.get("base_confidence")
        conf = f"conf={r['confidence']:.2f}" + (f"/{base:.2f}" if base is not None else "")
        bits.append(conf)
        if ev:
            bits.append("证据→" + ",".join(str(i) for i in ev))
    if not r["valid"]:
        bits.append("已失效")
    line = "  " + " ".join(bits) + f"] {r['content']}"
    if ev:
        for i in ev:
            c = content_by_id.get(i)
            if c:
                line += f"\n        └─ #{i} {c[:40]}"
    return line


def dump_human(path: str, args) -> None:
    conn = _open_ro(path)
    meta = _meta(conn)
    recs = _rows(conn, args.include_invalid)
    content_by_id = {r["id"]: r["content"] for r in _rows(conn, True)}
    trust = _trust_map(conn)

    if not args.player and not args.type and not args.search:
        npc = meta.get("npc", {})
        print("═" * 72)
        print(f"NPC: {npc.get('name', '(无元数据)')}   "
              f"库: {os.path.abspath(path)}")
        print(f"人格: {npc.get('persona_traits', {})}   "
              f"游戏时钟: {meta.get('game_time', 0.0):.1f}h")
        total = len(recs)
        by_type = {}
        for r in recs:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        print(f"记忆总数: {total}  "
              f"({', '.join(f'{k} {v}' for k, v in sorted(by_type.items()))})")
        if trust:
            print("信任度: " + "  ".join(
                f"{p} {t:+.2f}" for p, t in sorted(trust.items())))
        print("═" * 72)

    groups = _group(recs)
    if args.player:
        groups = {args.player: groups.get(args.player, [])}
    order = [None] + sorted(p for p in groups if p is not None)
    for pid in order:
        if pid not in groups:
            continue
        label = f"玩家 {pid}" if pid else "世界/自我 (无玩家)"
        t = trust.get(pid) if pid else None
        suffix = f"  信任度 {t:+.2f}" if t is not None else ""
        print(f"\n── {label}{suffix} ──")
        for r in groups[pid]:
            if args.type and r["type"] != args.type:
                continue
            if args.search and args.search not in r["content"]:
                continue
            print(_fmt_rec(r, content_by_id))
    conn.close()


def dump_json(path: str) -> None:
    conn = _open_ro(path)
    out = {
        "db": os.path.abspath(path),
        "meta": _meta(conn),
        "trust": _trust_map(conn),
        "memories": _rows(conn, True),
    }
    for m in out["memories"]:
        m["evidence"] = json.loads(m["evidence"] or "[]")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    conn.close()


def list_npcs(data_dir: str) -> None:
    if not os.path.isdir(data_dir):
        sys.exit(f"目录不存在: {data_dir}")
    dbs = sorted(f for f in os.listdir(data_dir) if f.endswith(".db"))
    if not dbs:
        print(f"({data_dir} 下没有 .db)")
        return
    for f in dbs:
        conn = _open_ro(os.path.join(data_dir, f))
        npc = _meta(conn).get("npc", {})
        n = conn.execute("SELECT COUNT(*) FROM memory WHERE valid=1").fetchone()[0]
        conn.close()
        print(f"{f:24s} {npc.get('name', '(无元数据)'):12s} 记忆 {n} 条")


def main() -> int:
    ap = argparse.ArgumentParser(description="只读审查 NPC 记忆库")
    ap.add_argument("db", nargs="?", help="NPC 的 .db 文件 (如 data/Isabella.db)")
    ap.add_argument("--list", action="store_true", help="列出目录下的 NPC")
    ap.add_argument("--data-dir", default="data", help="--list 的目录 (默认 data/)")
    ap.add_argument("--player", help="只看某玩家的关系流")
    ap.add_argument("--type", choices=["observation", "reflection", "plan"],
                    help="按记忆类型过滤")
    ap.add_argument("--search", help="按内容子串过滤")
    ap.add_argument("--trust", action="store_true", help="只看信任度汇总")
    ap.add_argument("--include-invalid", action="store_true",
                    help="包含已失效的反思")
    ap.add_argument("--json", action="store_true", help="JSON 导出")
    args = ap.parse_args()

    if args.list:
        list_npcs(args.data_dir)
        return 0
    if not args.db:
        ap.error("需要 db 路径, 或用 --list 列出可用 NPC")

    if args.json:
        dump_json(args.db)
    elif args.trust:
        conn = _open_ro(args.db)
        for p, t in sorted(_trust_map(conn).items()):
            print(f"{p:12s} {t:+.2f}")
        conn.close()
    else:
        dump_human(args.db, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
