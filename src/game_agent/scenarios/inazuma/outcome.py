"""本步稻妻结局判定与旅行者历史回喂。"""

from .judgment import _judge_shogun


def resolve_outcome(w, llm, decisions: dict, now: float) -> tuple[str, bool]:
    shogun = w.get("雷电将军")
    ended = False
    note = ""
    # 结局判定: 将军阵亡 或 被说服 (旅行者本步对将军直接 talk 才计数)
    if shogun.dead:
        note = "★ 雷电将军阵亡! 眼狩令随将军倒台而废止。"
        print(f"   {note}")
        ended = True
    else:
        t_act = decisions.get("旅行者", {})
        if t_act.get("action") == "talk" and t_act.get("target") == "雷电将军":
            trav = w.get("旅行者")
            # B+ 涌现: 将军是否被说服由 LLM 当场裁决 (她的信念+已呈证据+本次往来),
            # 无计数器。裁决驳回时回喂旅行者历史, 让它知道"现在劝没成、该去积累
            # 更多证据", 避免原地反复劝 (与旧双关同样的防卡死回喂)。
            reply = next((ve.reply for ve in w.visual_events
                          if ve.type == "conversation" and ve.actor == "旅行者"
                          and ve.target == "雷电将军"), "")
            revoked, why = _judge_shogun(llm, shogun, trav,
                                         t_act.get("utterance", ""), reply)
            if revoked:
                w.world_event("雷电将军被旅行者说服, 废止眼狩令: 持眼者可保留神之眼",
                              now=now)
                note = f"★ 雷电将军被说服 ({why}), 废止眼狩令!"
                print(f"   {note}")
                ended = True
            else:
                note = f"(将军尚未被说服: {why})" if why else "(将军尚未被说服)"
                print("   " + note)
                trav.record("将军尚未被说服: 证据还不够打动她, "
                            "去城里向更多人取证/目击暴行, 积累更多实证再来劝")
    return note, ended
