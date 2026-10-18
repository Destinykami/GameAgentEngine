# ReviewFixPlan — 审查问题修复实施计划

> **来源**：2026-10-18 对 `Memory / 交互 / Agent 算法` 的独立代码审查（对话记录）。
> **目标 HEAD**：`79291bc`（工作树干净）。
> **状态**：待执行。每项一个 commit，逐项勾选第十二节进度清单。
> **与既有计划的关系**：本计划只修审查发现的缺陷；[NextPlan.md](NextPlan.md) 的
> P3（关系阶段）/ P4（idle 自治）**不在本计划内**，不要混提。

---

## 0. 目标、非目标与铁律

### 0.1 目标

1. 修复会导致**记忆污染、面泄漏、显著性失真、世界状态错误**的 P0 缺陷。
2. 把审查中确认的 P1 缺陷（成本、传闻、身份、API 契约）补齐。
3. 回归闸门必须真实全绿：离线测试在 **多个 `PYTHONHASHSEED`** 下稳定通过，
   6 个真实 LLM 探针继续通过。
4. 每个修复都配一个"修复前会失败、修复后通过"的回归测试。

### 0.2 非目标

- 不做 NextPlan P3/P4（关系阶段、idle 自治、多轮对话终止）。
- 不重写记忆/反思/世界层架构；不做向量持久化；不做大规模性能重构。
- 不为了修 bug 新增默认开启的"功能"；新开关缺省关闭。身份生成复用
  `use_identity_beliefs`，同样缺省关闭（见 F4-4）。
- 不改 `evals/` 的指标定义。行为变化导致指标变化时，重新跑批并在
  `evals/README.md` 记录，不改口径迁就结果。

### 0.3 铁律（沿用 EvalPlan / NextPlan）

- **包内改动纯增量**：新构造参数缺省值 = 现行为；游戏路径不传新参数时行为不变
  （P0 的 bug 修复是显式例外，需在对应条目写明行为变化）。
- **依赖方向单向**：`evals → persona_agent`，包内不 import `evals/tests`。
- **两道闸门**：每次提交前 `pytest tests/ -q` 全绿 + `pytest tests/test_probes.py -q`
  6 探针通过（端点不可达时探针 skip 不算通过，需记录）。
- **一个 commit 只做一件事**：不把"修 bug"和"重命名/重构"混在一起；旧测试
  如果编码了错误行为，**显式改测试并在 commit message 里说明**。

### 0.4 验收口径

```bash
# 离线闸门（至少跑 0 / 24 / 随机三个种子）
PYTHONHASHSEED=0  .venv/bin/python -m pytest tests/ -q
PYTHONHASHSEED=24 .venv/bin/python -m pytest tests/ -q
                  .venv/bin/python -m pytest tests/ -q

# 真实 LLM 探针
.venv/bin/python -m pytest tests/test_probes.py -q
```

通过标准：`0 failed`；探针 `6 passed`（网络不可达时记录 skip 原因，不算绿）。

---

## 1. 问题总表

### P0（本轮必须修）

| ID | 问题 | 主要位置 | 对应审查项 |
|---|---|---|---|
| F0-1 | `HashEmbedder` 用随机加盐的 `hash()`，同文本跨进程不同向量；测试随机红 | [embeddings.py:64-66](persona_agent/embeddings.py#L64-L66) | P0-9 |
| F1-1 | `NPC.speak` 不写对话记忆，只有世界层手工回流 | [npc.py:214-225](persona_agent/npc.py#L214-L225)、[dialogue.py:30-50](persona_agent/dialogue.py#L30-L50) | P0-1 |
| F1-2 | `_save` 对 `player_id=None` 用"不过滤"，自我反思与所有玩家关系反思去重 | [reflection.py:320-341](persona_agent/reflection.py#L320-L341) | P0-2 |
| F1-3 | 反思触发器累积所有观察，但 `reflect_self` 只读共享流；阈值空转/重复烧 LLM | [npc.py:131-132](persona_agent/npc.py#L131-L132)、[npc.py:152-158](persona_agent/npc.py#L152-L158) | P0-3 |
| F1-4 | 对话检索不限当前玩家的面，A 的秘密可进入与 B 的对话 prompt | [dialogue.py:37-39](persona_agent/dialogue.py#L37-L39) | P0-5 |
| F1-5 | 日计划/重规划 context 取全流观察，plan 存共享流；重规划中断观察泄漏玩家名 | [npc.py:269-286](persona_agent/npc.py#L269-L286)、[planning.py:96-143](persona_agent/planning.py#L96-L143) | P0-5 |
| F2-1 | 在场观察每步 merge +1，importance 顶满 10（真实库可见） | [memory.py:441-467](persona_agent/memory.py#L441-L467)、[world.py:351-399](persona_agent/world.py#L351-L399) | P0-4 |
| F3-1 | 死者仍驱动 `tier_of`/`perceive`；`step` 不跳过死 NPC | [world.py:885-907](persona_agent/world.py#L885-L907)、[world.py:975-980](persona_agent/world.py#L975-L980) | P0-6 |
| F3-2 | `step()` 不消费 `_step_social`，社交队列跨步累积且关系反思永不跑 | [world.py:951-983](persona_agent/world.py#L951-L983) | P0-7 |
| F3-3 | `execute_action` 不校验目标距离，可隔空 talk/attack/help/hide | [world.py:611-625](persona_agent/world.py#L611-L625) | P0-8 |
| F3-4 | help/hide 先提交状态后做可失败认知事件；异常直接穿出 | [world.py:744-755](persona_agent/world.py#L744-L755) | P0-8 |
| F3-5 | `step_autonomous` 无 per-agent 异常隔离；`decide_action` 只 catch `ValueError` | [world.py:446-484](persona_agent/world.py#L446-L484)、[llm_real.py:394-413](persona_agent/llm_real.py#L394-L413) | P0-8 |

### P1（下一轮）

| ID | 问题 | 主要位置 |
|---|---|---|
| F1-6 | 自治决策的 `memory_context` 取全流最近 5 条，仍可跨玩家泄漏 | [world.py:785-796](persona_agent/world.py#L785-L796) |
| F2-2 | `observe` 在去重前调 `score_importance`，重复在场每次烧 LLM | [npc.py:112-125](persona_agent/npc.py#L112-L125) |
| F2-3 | `world_event` 对同一事件按 NPC 逐个打分（N 次调用） | [world.py:938-941](persona_agent/world.py#L938-L941) |
| F2-4 | `judge_trust` prompt 无上限，关系流越长 token 线性增长 | [reacting.py:69-78](persona_agent/reacting.py#L69-L78) |
| F4-1 | 传闻转述无条件转发"最新一条"，与当前话题无关 | [world.py:499-537](persona_agent/world.py#L499-L537) |
| F4-2 | 信任判断输入无 hearsay/hop；episode 固化后丢失传闻来源 | [reacting.py:76](persona_agent/reacting.py#L76)、[npc.py:202-207](persona_agent/npc.py#L202-L207) |
| F4-3 | `episode`/`identity` 未配半衰期，落到默认 48h（与原始观察同速） | [memory.py:57-61](persona_agent/memory.py#L57-L61)、[memory.py:534](persona_agent/memory.py#L534) |
| F4-4 | `reflect_identity` 只有测试调用，自治世界从不生成身份信念 | [npc.py:167-170](persona_agent/npc.py#L167-L170)、[world.py:478-481](persona_agent/world.py#L478-L481) |
| F4-5 | 冲突检查只按玩家扫关系反思；共享自我/identity 反思从不失效 | [reflection.py:211-282](persona_agent/reflection.py#L211-L282) |
| F5-1 | `add_npc` 不注册 LLM/persona，自治决策退化为 wait；`load` 不恢复 | [world.py:319-339](persona_agent/world.py#L319-L339)、[world.py:1086-1095](persona_agent/world.py#L1086-L1095) |
| F5-2 | `react` 缓存用 `"接受" in cached` 反解析，婉拒可被缓存成接受 | [npc.py:239-251](persona_agent/npc.py#L239-L251) |
| F5-3 | 浮点计划块通过 `_valid_block` 后 `f"{:02d}"` 崩溃；`make_daily_plan` 返回未校验块 | [planning.py:48-76](persona_agent/planning.py#L48-L76) |
| F5-4 | `use_relationship=False` 时仍调 `judge_trust`，缓存键仍含 trust bucket，消融不干净 | [reacting.py:88](persona_agent/reacting.py#L88)、[npc.py:240-242](persona_agent/npc.py#L240-L242) |

### P2（择机 / 卫生）

| ID | 问题 | 主要位置 |
|---|---|---|
| F6-1 | 检索 importance 未 Min-Max（与模块 docstring/论文不一致）；先改文档，行为调整待评测 | [memory.py:14-17](persona_agent/memory.py#L14-L17)、[memory.py:307](persona_agent/memory.py#L307) |
| F6-2 | "语义缓存"实为精确字符串键；`_cache`/`_value_cache`/`_conflict_cache` 无上限 | [npc.py:239-247](persona_agent/npc.py#L239-L247)、[reacting.py:45](persona_agent/reacting.py#L45) |
| F6-3 | 反思证据未在引擎层二次校验；自定义 LLM 可注入幻影 id | [reflection.py:336-341](persona_agent/reflection.py#L336-L341) |
| F6-4 | `new_observations` 把 merge 当新增 | [world.py:976-978](persona_agent/world.py#L976-L978) |
| F6-5 | 行为链在动作成功前计数；认知失败也推进链 | [world.py:623-624](persona_agent/world.py#L623-L624) |
| F6-6 | `flee` 把视距内所有活实体当威胁 | [world.py:728-736](persona_agent/world.py#L728-L736) |
| F6-7 | `NPC.load`/`World.load` 丢失瞬态：`_reflected_obs`/`_plan_blocks`/`_agent_llms`/`_last_plan_day` | [npc.py:349-372](persona_agent/npc.py#L349-L372)、[world.py:1086-1095](persona_agent/world.py#L1086-L1095) |
| F6-8 | `_vec` 逐条网络嵌入；大世界冷启动 O(n) 次请求 | [memory.py:210-216](persona_agent/memory.py#L210-L216) |
| F6-9 | `NPC.clear_cache` 不清 decider 缓存；`World.close` 不关 NPC 库；`all_invalid` 只读旧列 | [npc.py:312-313](persona_agent/npc.py#L312-L313)、[world.py:1097-1100](persona_agent/world.py#L1097-L1100) |
| F6-10 | merge 方向：富观察可能被稀疏观察保留；亲见/传闻同内容合并保留先入库 hop | [memory.py:441-467](persona_agent/memory.py#L441-L467) |
| F6-11 | 可选：玩家感知改过渡驱动（新出现/换区域才 observe），进一步省 LLM | [world.py:351-399](persona_agent/world.py#L351-L399) |
| F6-12 | 文档漂移：`llm_real` "6 个方法"、OVERVIEW "十一类"、NextPlan 139 测试、`"是是"`、NPC↔NPC 仍称"玩家" | 见各文件 |

---

## 2. 阶段 0 — 先让闸门可信（F0-1）

### 2.1 改法

1. `persona_agent/embeddings.py`
   - 新增 `_stable_hash(tok: str) -> int`：`hashlib.blake2b(tok.encode("utf-8"),
     digest_size=8).digest()` → `int.from_bytes(..., "big")`。
   - `_embed_one` 的桶与符号都改用 `_stable_hash`；删除内建 `hash()`。
   - 在 docstring 里明确"跨进程稳定"，不再用"确定性"这种容易被 `hash()`
     打脸的说法。
2. `tests/test_consolidation.py::test_conflict_scan_skips_consolidated`
   - 该用例测的是冲突扫描，不是观察去重。把 10 条"更晚观察"改成
     `npc.store.add(MemoryRecord(...))` 直接入库（绕过 `observe` 的 0.92 去重），
     或使用语义/词面都明确不同的内容；不要依赖"模板字符串一定不相似"。
   - 断言仍是"10 条都判一次"。
3. 新增 `tests/test_embedding_determinism.py`
   - 用 `subprocess` 以 `PYTHONHASHSEED=0` 和 `=24` 分别启动解释器，
     对同一文本 `embed`，断言向量逐元素相等。
   - 断言两个语义不同文本的余弦显著低于 0.92（不依赖具体数值，留安全边界）。

### 2.2 验收

- 三个种子下 `pytest tests/ -q` 全绿；6 探针通过。
- 现有失败的 `assert 9 == 10` 不再复现。

### 2.3 风险

- 稳定哈希会改变**所有** HashEmbedder 的向量桶/符号。依赖具体相似度数值的
  测试与 `probes`/回退 HashEmbedder 的 eval 需要重新基线；这是预期成本，
  且从此可复现。
- 不改 `RealEmbedder` 行为。

**Commit**：`修复: HashEmbedder 改稳定哈希, 冲突扫描测试与观察去重解耦 (闸门跨种子全绿)`

---

## 3. 阶段 1 — 记忆信息隔离（F1-1 ~ F1-6）

> 本阶段直接决定"自我/面解耦"是否真的成立。建议按 F1-2 → F1-3 → F1-4/5/6
> → F1-1 的顺序提交；F1-1 会改变对话记忆量，最好在隔离修好后再接。

### 3.1 F1-1 `speak` 的对话记忆契约

**决策：采用"speak 默认落库"**（备选是"speak 只读、必须走 world"，但那会让
README/OVERVIEW 的主 API 变成半残；采用前者）。

`NPC.speak` 增加两个参数：

```python
def speak(self, player_id: str, utterance: str, now: float,
          remember: bool = True,
          record_utterance: bool = True) -> str: ...
```

实现顺序：

1. 保持现有 `_advance` + `_reflected_obs` 门控 + `dialogue.reply`。
2. **先拿到 reply**，再写记忆（避免本轮反思把当前话语当旧证据）：
   - `remember and record_utterance and utterance`：
     `observe(f"{player_id} 对我说: {utterance}", now, player_id=player_id)`
   - `remember and reply`：
     `observe(f"我对 {player_id} 说: {reply}", now, player_id=player_id)`
3. 写入走 `observe`，复用 0.92 去重 / importance / last_accessed；不要直接
   `store.add` 绕过记忆卫生。
4. 世界层 `world.execute_action` 的 talk：
   - 目标 NPC 已经通过 `_observe_target_social`/`perceive_action` 观察了玩家
     的 utterance，因此调用 `npc.speak(..., record_utterance=False)`，避免双写；
   - 目标 NPC 的 reply 现在由 `speak` 自己写入（以前只写进 speaker 侧回放），
     双方语义对称；
   - speaker 侧现有"自观察 + 回复回流"保持不变（它负责 A 的记忆）。
5. `DialogueManager` 保持只读；记忆写入集中在 `NPC.speak`，避免两个层各写一份。

**测试** `tests/test_dialogue_memory.py`：
- 直接 `speak` 两轮后，该玩家面里有 utterance/reply 观察，且下一轮 `reply`
  的检索能召回上一轮；
- `record_utterance=False` 时只写自己 reply，不写对方话语；
- world talk 后：目标 B 的该玩家面 = 1 条 incoming（世界层）+ 1 条自己的 reply
  （speak），不出现重复 incoming；
- `remember=False` 时行为与旧版一致。

**行为变化（需在 commit 说明）**：`game_loop.py`/`demo_real.py` 的对话会开始
积累记忆，后续回答可能引用前文；这是修复目标。

### 3.2 F1-2 `_save` 的共享流去重

**改法**：

- `ReflectionEngine._save(..., shared: bool = False)`。
- `reflect_self`、`reflect_identity` 传 `shared=True`；
  `reflect_relationship` 传 `shared=False`。
- 去重查询改为：
  - `shared=True` → `store.all_valid(shared=True, types=[rtype])`
  - `shared=False` → `store.all_valid(player_id=player_id, types=[rtype])`
- 加断言：`shared=True` 时 `player_id` 必须为 `None`；`shared=False` 时
  `player_id` 不得为 `None`（防止未来再踩 E2 陷阱）。

**测试** `tests/test_reflection_streams.py`：
- 关系面已有 `"Aria 是可靠的"`；共享流同义 insight 仍能入库；
- 反向同理；
- 同一流内同义 insight 仍被去重（不破坏原去重收益）；
- identity 池不受影响。

### 3.3 F1-3 反思触发器按流拆分

**改法**：

- `NPC.observe` 只在 `player_id is None`（共享流）时累加
  `_importance_accum`。关系观察的触发由 `speak`/`flush_social` 的
  `_reflected_obs` 门控负责，不需要 importance 计数器。
- 在 `_importance_accum` 初始化处注释清楚语义：**self-reflection 触发器，
  只由共享流观察驱动**；避免下一个人再把它当"全部记忆重要性"。
- 保留 `maybe_reflect_self` 的阈值与清零逻辑；现在输入与消费同流，
  空转消失。

**测试**（扩展 `tests/test_forgetting.py` 或新建 `tests/test_reflection_triggers.py`）：
- 31 条关系观察 → `_importance_accum == 0`，`maybe_reflect_self` 不触发；
- 共享观察照常累积并在阈值后产出共享反思；
- 1 条共享观察 + 多批关系观察：共享反思只产出一次，不反复调用
  `reflection_questions`/`reflection_insights`。

### 3.4 F1-4 对话检索限制在"当前玩家 + 共享流"

**改法**：

- `MemoryStore.retrieve(..., include_shared: bool = False)`：
  - `shared=True`：仍只取 `player_id IS NULL`；
  - `player_id is not None` 且 `include_shared=True`：
    SQL 加 `AND (player_id = ? OR player_id IS NULL)`；
  - 默认 `include_shared=False`，保持反思证据检索等旧调用只取该玩家流。
- `DialogueManager.reply` 传 `player_id=player_id, include_shared=True`。
- `include_player` 的 +0.5 加权保留（当前玩家记忆仍更靠前），但不再允许
  其他玩家的私有记忆进入候选集。

**测试** `tests/test_dialogue_privacy.py`：
- A 的秘密（`player_id="Aria"`）不得出现在与 Bram 的 `LLMContext.memories`；
- 共享世界事件仍可出现；
- Aria 自己的对话仍能召回她的记忆；
- `reflect_relationship` 的证据检索（`include_shared=False`）仍只含该玩家观察。

**产品决策**：如果未来要允许 gossip，必须显式加 `visibility="gossip"` 或
带来源标记的通道，而不是默认放开；本计划不做。

### 3.5 F1-5 计划 context / 重规划中断不跨流

**改法**：

1. `NPC.generate_daily_plan` 与 `NPC.replan` 的世界背景改为：
   `self.store.all_valid(shared=True, types=["observation"])[-10:]`。
2. `PlanningEngine.replan_from_now(..., interruption_player: str | None = None)`
   传给 `_save_obs(..., player_id=interruption_player)`。
   - `_save_obs` 增加 `player_id` 参数；有玩家时写入该玩家面，否则共享流。
3. `NPC.replan(..., interruption_player: str | None = None)` 透传。
4. 世界层：
   - 挨打方重规划时传 `interruption_player=agent.name`（攻击者）；
   - 行动者自己的重规划 `interruption_player=None`（自己的计划不因自己攻击
     而泄漏他人）；
   - flee/help/hide 视语义决定；help/hide 的受益者若是玩家，可按需传其名，
     但默认不传，先保证不泄漏。

**测试** `tests/test_plan_isolation.py`：
- Aria 的秘密观察不进入 `generate_plan` 的 context（用捕获 LLM）；
- Aria 的秘密不进入 `replan` 的 context；
- 重规划的中断观察 `player_id` 正确（受害者面），共享流里没有玩家名；
- 共享世界事件仍进入 context（不误伤正常世界背景）。

### 3.6 F1-6 自治决策上下文按可见对象过滤（P1）

**改法**：`World.step_autonomous` 构造 `memory_context` 时，不再直接取
`npc.store.all_valid()[-5:]`，而是过滤：

```python
visible = {e.name for e in self.entities.values()
           if e is not agent and not e.dead
           and distance(agent, e) <= self.perception_radius}
mems = [m.content for m in npc.store.all_valid()
        if m.player_id is None or m.player_id in visible][-5:]
```

**测试**：A 的私有秘密不在 B 的 `perception`（用捕获 LLM）；共享世界事件仍在。

**Commit（阶段 1）**：
- `修复: 反思去重/_save 显式区分共享流, 自我反思不再被关系反思吞掉 (F1-2)`
- `修复: 反思触发器只累积共享流观察, 关系观察不再空转 self 触发器 (F1-3)`
- `修复: 对话/计划/决策上下文按当前玩家+共享流隔离, 堵住跨玩家泄漏 (F1-4/5/6)`
- `修复: NPC.speak 默认把对话写入关系记忆流, 单 NPC API 不再失忆 (F1-1)`

---

## 4. 阶段 2 — 记忆显著性 + 成本（F2-1 ~ F2-4）

### 4.1 F2-1 merge 强化限速 + F2-2 去重前置

**决策：不做"每次 merge 都 +1"，改为时间窗强化；同时把重要性打分移到去重之后。**
（可选的过渡驱动感知放 F6-11，先把这两个低成本修复落地。）

#### F2-1 merge 限速

1. `MemoryRecord` 增加 `last_reinforced: float | None = None`。
2. `MemoryStore` schema 增加 `last_reinforced REAL`；旧库迁移：
   `ALTER TABLE ... ADD COLUMN last_reinforced REAL`，并
   `UPDATE memory SET last_reinforced = COALESCE(last_accessed, timestamp)
   WHERE last_reinforced IS NULL`。
3. 同步所有读写点：`add()` 的 INSERT 列表、`_row_to_rec()` 的列
   （新增字段必须放在 SELECT * 的最后一列，或在 `_row_to_rec` 用列名映射），
   `merge_observation()` 的 SELECT、`all_invalid()` 若需要也读全列。
4. `add()` 写入 `last_reinforced = rec.last_reinforced or rec.timestamp`。
5. `merge_observation(mem_id, now)`：
   - 读取 `importance, last_reinforced`；
   - `reinforce = last_reinforced is None or now - last_reinforced >= MERGE_REINFORCE_INTERVAL`
     （常量建议 `6.0` 游戏小时，可配置）；
   - `reinforce` 时 `new_imp = min(10.0, imp + 1.0)` 且 `last_reinforced = now`；
     否则 `new_imp = imp`、`last_reinforced` 不变；
   - 无论是否 reinforce，都刷新 `last_accessed = now`（重复发生仍是回忆，
     保留 recency 语义）。
6. `base_importance` 只在 reinforce 时抬到 `new_imp`，否则保持原基线。

**测试**（更新 `tests/test_forgetting.py`）：
- 两次相邻 merge（间隔 1h）→ importance 不变，`last_accessed` 刷新；
- 间隔 ≥ 6h 的 merge → +1；
- 30 次每 6h merge → 收敛 10（替换现有"30 次立即 +1"断言）；
- 迁移：旧库无 `last_reinforced` 时能打开，且首轮不会立刻 +1。

#### F2-2 去重前置

`NPC.observe` 改为：

```python
dup = self.store.find_similar_observation(content, player_id)
if dup is not None:
    self.store.merge_observation(dup.id, now)
    return dup.id
importance = self.llm.score_importance(content, player_id)
...
```

- merge 分支不需要 importance（F2-1 已确认），所以重复在场**零 LLM**。
- 新观察仍打分一次；`find_similar_observation` 的嵌入复用现有 `_vec_cache`，
  不额外增加 LLM。
- 若担心 new observation 被嵌入两次（去重一次 + add 一次），在 F6-8 里加
  content→vec 缓存；本阶段先不扩大改动。

**测试**（更新 `tests/test_social_layer.py::test_social_perception_llm_cost`）：
- 首次 perceive（玩家 + NPC 出现）= 2 次 importance；
- 第二次同内容 perceive = **0** 次增量（旧断言是 1 次，属于错误行为）；
- 玩家换区域/换描述时重新打分。

### 4.2 F2-3 `world_event` 只打一次分

**改法**：

- `NPC.observe(..., importance: float | None = None)`：传入时跳过
  `score_importance`；`None` 保持旧行为。
- `World.world_event`：
  - 目标 NPC 列表非空时，用第一个 NPC 的 `llm.score_importance(desc, None)`
    打一次分（`player_id=None`，分数与 NPC 无关；温度 0）；
  - 对每个 NPC 调 `observe(desc, now, importance=importance)`；
  - 若没有目标 NPC，则不调用 LLM（仍记录 visual event）。
- 注意：不同 NPC 的 LLM 对象可能不同，但同一事件的世界重要性以第一个为准；
  若未来需要 per-NPC 重要性，再单独加参数。

**测试**：
- 3 个 NPC 的 `CountingLLM` 合计 importance 调用 = 1（旧为 3）；
- 世界事件观察仍按 0.92 去重合并；
- 无 NPC 时不调用。

### 4.3 F2-4 信任判断输入封顶

**改法**：

- `JUDGE_TRUST_MAX_MEMORIES = 30`。
- `ReactionDecider.relationship_trust` 选择：
  - 反思/identity/episode 按时间倒序取前 10（高阶认知优先保留）；
  - 观察按时间倒序取前 20；
  - 合并后按原顺序（或时间正序）送入 `judge_trust`；总数 ≤ 30。
- 关系流较短时行为不变（不超过上限）。
- 在 docstring 写明"信任不是全量扫描，而是高阶认知 + 近期证据的窗口"。

**测试** `tests/test_trust_scaling.py`：
- 120 条关系观察后，捕获的 `judge_trust` 输入 ≤ 30；
- 最新一条观察一定在输入里；
- 反思/identity 优先保留；
- 关系流不变时签名缓存仍命中（不重复调用）。

**Commit（阶段 2）**：
- `修复: 观察 merge 强化按时间窗限速, 在场记忆不再顶满 importance (F2-1)`
- `优化: 重要性打分移到观察去重之后, 重复在场零 LLM (F2-2)`
- `优化: world_event 单次打分 + 信任判断输入封顶 (F2-3/F2-4)`

---

## 5. 阶段 3 — 世界状态与交互鲁棒性（F3-1 ~ F3-5）

### 5.1 F3-1 死亡实体退出认知

1. `World.tier_of`：遍历玩家时跳过 `ent.dead`。
2. `World.perceive`：跳过 `ent.dead`（玩家和 NPC 都跳）；`social_perception`
   的 `current` 集合也已过滤 dead NPC，确认。
3. `World.step`：感知/反思循环加 `if self.entities[name].dead: continue`，
   与 `step_autonomous`、`world_event` 对齐。
4. `World.schedule_tiers` 对 dead NPC 可保持 idle（或不调用），避免尸体档位
   影响统计；建议显式 `return "idle"` 或跳过。

**测试** `tests/test_dead_entities.py`：
- dead player 不再影响 `tier_of`；`perceive` 返回 `[]`；
- dead NPC 在 `step` 中不新增记忆、不反思；
- alive NPC 行为不变。

### 5.2 F3-2 `step` 消费社交队列

在 `World.step` 的感知/反思循环之后、`save` 之前调用 `self.flush_social(now)`。
`flush_social` 已有 try/finally，异常也清空。

**测试**：
- `social_perception=True`，5 次 `step` 后 `_step_social == []`；
- 首次出现触发关系反思（full 档 + 新观察），重复 step 不重复反思；
- 压缩/idle 档仍按 `_reflected_obs` 门控。

### 5.3 F3-3 动作空间校验

新增 `World._within_reach(agent, target) -> bool`：
- `target is not None and target is not agent and target.is_alive()`；
- `distance(agent, target) <= self.perception_radius`。

在 `execute_action` 的 talk/attack/help/hide 分支入口校验：
- 不满足 → 产出 `VisualEvent(type, success=False, failure_reason="不在可交互范围")`；
- talk 不写 history/utterance 回流，attack 不扣血，help/hide 不写理由。
- `VisualEvent.describe` 为 help/hide 补 `success=False` 文案（目前只处理成功态）。
- `move`/`flee`/`wait` 不受影响；`flee` 的威胁集合仍按 F6-6 处理。

**测试** `tests/test_action_contract.py`：
- 距离 141/视距 1.5 的 talk/attack/help 均 `success=False`，目标血量/记忆不变；
- 同区域动作成功；
- dead target 仍拒绝。

### 5.4 F3-4 help/hide 原子性

把 help/hide 重排为：

1. 构造 `VisualEvent`；
2. 目标 NPC 时先 `_observe_target_social`（可失败，try/except）；
3. 失败 → 返回 `success=False`，不写 `agent.record`/`target.record`/effects；
4. 成功 → 提交 record + effects + emit。

与 attack/talk 的"认知在前后提交"模式一致；非 NPC 目标直接提交。

**测试**：
- `perceive_action` 抛异常时 help/hide 返回 `success=False`，双方 history 不变；
- 成功后 history/effects 正常；
- 目标非 NPC 时直接成功（无认知事件）。

### 5.5 F3-5 故障隔离

1. `RealLLM.decide_action`：
   - `except (ValueError, RuntimeError)` → fallback wait（`RuntimeError` 是
     `_chat` 重试耗尽后的网络/HTTP 错误）；保留原始 reason 便于日志。
2. `World.step_autonomous`：
   - 决策循环每个 agent 包 try/except，失败降级
     `{"action":"wait","reason":"决策异常: ..."}`，不阻塞其余 agent；
   - 日计划循环每个 NPC 包 try/except；
   - 重感知/`maybe_reflect_self` 每个 NPC 包 try/except。
3. `World.step`：
   - `generate_daily_plan`/`perceive`/`maybe_reflect_self` 每个 NPC 包 try/except，
     失败记录后继续（可选 `self.last_errors` 列表，不改变返回值）。
4. `World.world_event`：每个 NPC 的 `observe` 包 try/except，单个失败不影响其余。
5. `execute_action` 的 help/hide 按 F3-4 处理；talk/attack 已有保护。

**测试** `tests/test_error_isolation.py`：
- 一个 agent 的 `decide_action` 抛 `RuntimeError`，其余 agent 仍被决策/执行；
- 一个 NPC 的计划生成抛错，其余 NPC 仍规划；
- `step` 中一个 NPC 的 `perceive` 抛错，其余 NPC 仍感知；
- `decide_action` 网络错误返回 wait（不穿出）。

**Commit（阶段 3）**：
- `修复: 死者退出档位/感知/step, 死亡语义一致 (F3-1)`
- `修复: step 消费 _step_social, 关系反思不再跨步积压 (F3-2)`
- `修复: 动作空间距离校验 + help/hide 原子性 (F3-3/F3-4)`
- `修复: 自治循环/计划/感知的 per-agent 故障隔离 (F3-5)`

---

## 6. 阶段 4 — 社会语义与身份（F4-1 ~ F4-5）

### 6.1 F4-1 传闻转述只在相关时发生

**改法**：

1. `MemoryStore.retrieve(..., hearsay_only: bool = False)`：
   SQL 加 `AND hearsay = 1`（与 `types` 可组合）。
2. `World._spread_rumor` 的转述路径：
   - 不再 `max(pending, timestamp)` 无条件取最新；
   - 用 `speaker_npc.store.retrieve(query=line, now=self.clock, top_k=1,
     types=["observation"], hearsay_only=True, min_relevance=0.15,
     mark_accessed=False)` 找**与当前话题相关**的传闻；
   - 没有相关传闻 → 不转述。
3. 转述内容保留来源链：
   `f"{speaker.name} 告诉我: {latest['content']}"`；
   `player_id=latest["player_id"]`，`hop=latest["hop"] + 1`，`hearsay=True`。
4. `_step_social` 记为 `(listener_npc, latest["player_id"] or speaker.name)`，
   让听者形成对传闻对象的认知（而不是对无关第三方）。

**测试** `tests/test_rumor_semantics.py`：
- A 持有关于 C 的传闻，A 与 B 聊天气 → B 不新增 C 的传闻；
- A 与 B 聊与传闻相关的话题 → B 收到 hop+1、内容含 "A 告诉我" 的传闻；
- 3 跳封顶仍生效；
- 无关转述不再污染关系反思队列。

### 6.2 F4-2 信任与固化保留传闻来源

1. `ReactionDecider.relationship_trust` 送入 `judge_trust` 的内容带来源标记：
   - `f"[传闻{hop}跳] {content}"`（hop≥1）；亲见不加。
   - 保持 `judge_trust` 三参签名不变（内容层标注），避免全面改 stub/测试；
     若后续需要结构化，再把签名扩成四元组。
2. `RealLLM.judge_trust` prompt 增加一句：带 `[传闻N跳]` 的证据应降低可信度，
   N 越大越不可信。
3. `NPC.consolidate` 生成 episode 时：
   - `hearsay = any(m.hearsay for m in obs)`；
   - `hop = max((m.hop for m in obs if m.hearsay), default=0)`（保守取最远来源）。
4. `merge_observation` 来源合并：
   - 新观察是亲见（`hearsay=False`）且旧记录是传闻 → 升级旧记录为亲见
     （`hearsay=0, hop=0`）；
   - 新观察是传闻且旧记录是亲见 → 保持亲见，不降级。
   这需要 `merge_observation` 接受 `hearsay/hop` 或读取新观察；建议加参数
   `new_hearsay: bool = False, new_hop: int = 0`，由 `observe` 传入。

**测试**：
- 信任 prompt 捕获到 `[传闻2跳]` 前缀；
- episode 的 `hearsay=True`、`hop=2`；
- 先传闻后亲见 merge → 记录变为亲见；先亲见后传闻 → 仍亲见。

### 6.3 F4-3 episode/identity 半衰期

`FORGET_HALF_LIVES` 增加：

```python
"episode": 168.0,   # 固化摘要: 与反思同档
"identity": 336.0,  # 身份信念: 最稳定
```

**测试**：
- 同等 importance/age 下，episode 保留高于 observation，identity 高于
  reflection；
- 30 天模拟后 identity 不触底（或明显高于 observation）；
- 现有 observation/reflection/plan 的衰减断言不变。

### 6.4 F4-4 身份信念生成接线

**改法**：

- `World._maybe_consolidate` 在 `npc.consolidate(self.clock)` 之后：
  ```python
  if self._use_identity_beliefs:
      npc.reflect_identity(self.clock)
  ```
- `_use_identity_beliefs` 保持缺省 `False`（P2 功能开关，缺省行为不变）；
  开启时同时负责"生成 + 注入决策上下文"，语义自洽。
- 在 docstring 写明：身份生成成本 = 每 NPC 每晚最多 1 次
  `reflection_insights`（同固化窗口），不是每步。
- `world_auto_sim.py` 若要演示身份层，显式传 `use_identity_beliefs=True`；
  否则保持现行为。

**测试** `tests/test_identity_lifecycle.py`：
- `World(consolidation=True, use_identity_beliefs=True)` 跑一次固化时刻后，
  NPC 共享流出现 `type="identity"`；
- 关闭开关时零 identity；
- 身份信念进入 `decide_agent` 的 perception（捕获 LLM）；
- 固化为空（无观察）时不产生 identity、不报错。

### 6.5 F4-5 共享/identity 反思的冲突检查

**改法**：

1. `ReflectionEngine.check_conflicts(store, player_id, now, shared: bool = False)`；
   `_check_conflicts_llm`/`_check_conflicts_heuristic` 同步加参数。
2. `shared=True` 时：
   - reflections：`all_valid(shared=True, types=["reflection"])` +
     `all_valid(shared=True, types=["identity"])`；
   - observations：`all_valid(shared=True, types=["observation"], consolidated=False)`
     + `all_valid(shared=True, types=["episode"])`；
   - 仍然只检查更晚证据、K=10 窗口、confidence floor，成本受控。
3. 触发点：
   - `NPC.maybe_reflect_self` 在 `reflect_self` 后调用一次
     `check_conflicts(..., shared=True)`；
   - `World._maybe_consolidate` 在 `consolidate` 后调用一次（episode 是新证据）；
   - `World.step`/`step_autonomous` 的非 idle NPC 可每个清晨/固化时检查，
     不必每步扫（成本考虑）。
4. 若担心过度失效，加 `shared_conflict_policy` 开关（缺省 `"full"`）；
   但先按现策略实现，用测试观察效果。

**测试**：
- 共享自我反思 `"我信任外来者"` + 更晚共享观察 `"外来者偷走了我的东西"`
  → 反思失效/衰减（取决于 LLM stub 的矛盾分）；
- identity 同意；
- 关系面冲突检查行为不变；
- 重跑幂等（confidence 不复合衰减）。

**Commit（阶段 4）**：
- `修复: 传闻只在话题相关时转述, 并保留来源链 (F4-1)`
- `修复: 信任判断标注传闻跳数, episode 继承传闻来源 (F4-2)`
- `修复: episode/identity 半衰期与身份生成接线 (F4-3/F4-4)`
- `修复: 共享/identity 反思纳入冲突检查 (F4-5)`

---

## 7. 阶段 5 — API 契约与一致性（F5-1 ~ F5-4）

### 7.1 F5-1 `add_npc` 注册自治 agent

**决策：新增显式 `autonomous: bool = False`，缺省保持现行为；**
`world_auto_sim` 改为 `autonomous=True`，删除私有 `_agent_llms` 写法。

1. `World.add_npc(..., autonomous: bool = False)`：
   - 创建/加载 NPC 后，若 `autonomous`：
     `self._agent_llms[name] = llm`；`self._agent_personas[name] = persona_traits`。
2. 新增公开 `World.register_agent(name, llm, persona_traits=None)`：
   - 校验实体存在；供已加载/特殊构造的世界补注册。
3. `World.save` 的 NPC 注册表旁记录 `agent_npcs`（name 列表）；
   `World.load(llm=..., agent_llms: dict | None = None)`：
   - 若 `agent_llms` 提供，按 name 补注册；
   - 若 meta 标记为 autonomous 且传入单一 `llm`，用该 llm 补注册；
   - 否则不注册（保持旧行为，调用方可 `register_agent`）。
4. `examples/world_auto_sim.py` 改用 `autonomous=True`；`world_demo.py`/
   `world_sim.py` 不用自治可保持默认 False。

**测试** `tests/test_api_registration.py`：
- `add_npc(autonomous=True)` 后 `decide_agent` 不再返回 `"无 LLM"`；
- 默认 `add_npc` 行为与旧版一致（仍 wait）；
- `register_agent` 后生效；
- world save/load + `agent_llms` 恢复后 NPC 仍能决策。

### 7.2 F5-2 `react` 缓存保存决策对象

**改法**：

- `NPC._cache: dict[str, ReactionDecision]`（或 tuple `(react, action, utility)`）。
- 命中时返回 `ReactionDecision(react=cached.react, action=cached.action,
  utility=cached.utility, reason="语义缓存命中")`；不再从 action 文本反解析。
- 缓存键保留 `event|player|trust_bucket|plan[:20]`，但 trust_bucket 在
  `use_relationship=False` 时不参与（见 F5-4）。

**测试**：
- 事件 `"邀请你接受一场切磋"` 首次婉拒，二次命中仍 `react=False`、
  utility 不丢；
- 接受事件缓存命中仍 `react=True`；
- 缓存只在 full 档写入（现行为）。

### 7.3 F5-3 计划块归一化 + 返回校验后块

**改法**：

1. `PlanningEngine._valid_block` 只接受"整数值"（`int` 或
   `float.is_integer()`；排除 `bool`），返回 `tuple[int, int] | None` 或
   保持 bool + 单独 `_as_hour`；推荐：
   ```python
   @staticmethod
   def _as_hour(v) -> int | None:
       if isinstance(v, bool): return None
       if isinstance(v, int): return v
       if isinstance(v, float) and v.is_integer(): return int(v)
       return None
   ```
   `make_daily_plan`/`replan_from_now` 先归一化，再校验 `0 <= s < e <= 24`。
2. `make_daily_plan` 维护 `validated: list[tuple[int,int,str]]`，与 `top_ids`
   一一对应；返回 `top_ids, validated`（不再返回原始 `top_blocks`）。
3. `replan_from_now` 的 `clamped` 已是校验后块，保持。
4. 子任务 clamp 后同样归一化。

**测试**（扩展 `tests/test_plan_parsing.py`）：
- `(7.5, 9.5)` 被丢弃，不崩；
- `(7.0, 9.0)` 正常；
- `(25, 26)`/`(10, 9)` 丢弃；
- `npc._plan_blocks` 只含真正入库的合法块。

### 7.4 F5-4 消融开关真正跳过 trust

**改法**：

- `ReactionDecider` 暴露 `use_relationship` 属性（或 `uses_relationship()`）。
- `decide`：
  ```python
  if self._use_relationship:
      trust = self.relationship_trust(player_id)
      trust_mod = max(0.0, 1.0 + trust)
  else:
      trust = 0.0
      trust_mod = 1.0
  ```
- `NPC.react`：
  - 仅 `decider.use_relationship` 时计算 `trust`/`trust_bucket`；
  - 关闭时缓存键不带 trust 维度（固定 `"-"`）。
- `trust_toward` 仍可独立调用（不受开关影响），保持 API。

**测试**：
- `use_relationship=False` 时 `judge_trust` 调用数 = 0；
- 开/关两种情况下同一事件对 P/Q 的 action 是否符合预期；
- 缓存键在关闭时不随 trust 变化。

**Commit（阶段 5）**：
- `修复: add_npc 自治注册 + load 恢复 agent 注册表 (F5-1)`
- `修复: react 缓存保存决策对象, 不再从自然语言反解析 (F5-2)`
- `修复: 计划块归一化/校验后返回, 浮点块不崩 (F5-3)`
- `修复: use_relationship 消融真正跳过 trust 计算与缓存维度 (F5-4)`

---

## 8. 阶段 6 — 卫生与文档（F6）

按价值排序，可合并成 1-2 个 commit：

1. **F6-1**：把 [memory.py](persona_agent/memory.py) 顶部注释改成真实实现：
   importance 用绝对 `/10`，recency/relevance 用 Min-Max；说明这是有意的
   权重选择。若之后要做论文对齐，单独开评测任务，不在本次改行为。
2. **F6-2**：把"语义缓存"改名为"决策缓存"（注释/docstring），
   `_cache`/`_value_cache`/`_conflict_cache` 加 LRU/上限（如 512/256），
   或至少在 doc 里写明无上限及其适用规模。
3. **F6-3**：`ReflectionEngine._save` 校验 evidence：只保留
   `store` 中存在且 `valid=1` 的 id；可选再校验同流/类型。自定义 LLM 的
   幻影 id 不再入库。
4. **F6-4**：`World.step` 的 `new_observations` 用 `memory_count` 前后差
   （merge 不增加），或改名为 `observations_touched` 并文档化。
5. **F6-5**：`_chain_update` 移到各动作成功提交之后；失败的认知事件不计链。
6. **F6-6**：`flee` 的威胁集合加谓词（如 `other.kind == "player"` 或
   `other.role` 敌对集合）；没有敌意模型时至少在 doc 里说明"所有可见实体
   都视为威胁"。
7. **F6-7**：`NPC.save` 持久化 `_reflected_obs`、`_plan_blocks`（meta），
   `NPC.load` 恢复；`_last_sweep` 初始化为 `_game_time`。`World.save` 记录
   `_last_plan_day`/`_last_consolidate_day`，`load` 恢复。
8. **F6-8**：`MemoryStore` 加批量 `_ensure_vecs(recs)`：一次 `embed(texts)`
   补齐 miss，再写回 `_vec_cache`；`retrieve`/`_save` 去重前调用。
9. **F6-9**：`NPC.clear_cache` 调 `self.decider.clear_cache()`；
   `World.close` 关闭各 NPC `store`；`all_invalid` 改用 `_row_to_rec` 或读全列。
10. **F6-10**：merge 时若新内容更丰富（长度/信息量），更新 content 并清
    `_vec_cache`；来源合并按 F4-2 规则。注意更新向量缓存。
11. **F6-11（可选）**：`World.perceive` 的玩家感知改 transition-driven：
    维护 `_player_seen`（per NPC），只在"新进入视距/换区域/档位变化"时
    `observe`，离开时记一条"离开"（可选）。这是 F2-1/F2-2 之后的进一步
    优化；先用计数测试验证收益，再决定是否默认开启。
12. **F6-12**：文档对齐：
    - `llm_real.py` "全部 6 个方法" → 12；
    - `OVERVIEW.md` "十一类" → 十二类，补 `consolidate_observations`；
    - `NextPlan.md` "139 离线测试" → 实际数（执行时更新）；
    - `reflection.py` `"是是什么样"` → `"是什么样"`；
    - `perceive_action` prompt 对 NPC↔NPC 使用"对方"而非"玩家"；
    - `MemoryRecord` 顶部字段说明补 `base_*`/`hearsay`/`hop`/`consolidated`/
      `last_reinforced`。

**Commit**：`卫生: P2 项与文档对齐 (证据校验/缓存上限/metrics/文档计数)`

---

## 9. 回归测试清单（按文件）

建议新增/修改的测试文件：

| 文件 | 覆盖 |
|---|---|
| `tests/test_embedding_determinism.py` | F0-1 跨进程稳定 |
| `tests/test_dialogue_memory.py` | F1-1 speak 落库/参数/世界对称 |
| `tests/test_reflection_streams.py` | F1-2 共享/关系去重隔离 |
| `tests/test_reflection_triggers.py` | F1-3 触发器按流 |
| `tests/test_dialogue_privacy.py` | F1-4 对话检索隔离 |
| `tests/test_plan_isolation.py` | F1-5 计划 context/中断 |
| `tests/test_memory_salience.py` | F2-1 merge 限速/importance |
| `tests/test_cost_gates.py` | F2-2/F2-3 去重前置/world_event 单次打分 |
| `tests/test_trust_scaling.py` | F2-4 trust 输入上限 |
| `tests/test_dead_entities.py` | F3-1 死亡语义 |
| `tests/test_step_social.py` | F3-2 step flush |
| `tests/test_action_contract.py` | F3-3/F3-4 距离/原子性 |
| `tests/test_error_isolation.py` | F3-5 异常隔离 |
| `tests/test_rumor_semantics.py` | F4-1/F4-2 转述/来源 |
| `tests/test_identity_lifecycle.py` | F4-3/F4-4/F4-5 半衰期/生成/冲突 |
| `tests/test_api_registration.py` | F5-1 add_npc/load |
| `tests/test_react_cache.py` | F5-2 缓存决策 |
| `tests/test_plan_float.py` | F5-3 浮点/返回块 |
| `tests/test_ablation_flags.py` | F5-4 trust 跳过 |

### 9.1 已知需要更新的旧断言（故意行为变化）

- `tests/test_forgetting.py`
  - `test_repeated_observation_merges_plus_one_not_double_count`：
    改为"1h 内不 +1；≥6h 才 +1"。
  - `test_merge_reinforcement_caps_at_ten`：
    改为"每 6h 一次，30 次后到 10"。
  - `test_merge_raises_decay_baseline`：
    首次 merge 改为 `now>=6`（否则无强化），或显式设
    `last_reinforced` 后再 merge。
  - `test_recalled_memory_decays_slower`：注释里的 "5.0→6.0" 改为 6h 窗口
    语义；断言本身（高于下限）通常仍成立，但不要依赖 +1。
- `tests/test_social_layer.py`
  - `test_social_perception_full_tier_rich`：合并 +1 的断言改为
    "6h 内不 +1，只刷新 last_accessed"；另加一条 ≥6h 的 +1 用例。
  - `test_social_perception_llm_cost`：
    第二次同内容 perceive 的 importance 调用从 +1 改为 **0**（去重前置）。
- `tests/test_consolidation.py::test_conflict_scan_skips_consolidated`：
  改用直接 `store.add` 或明确不同内容，避免依赖 HashEmbedder 去重。
- 任何 `add_npc` 后假设 `decide_agent` 返回 wait 的测试：
  默认 `autonomous=False` 时不变；`autonomous=True` 的测试显式改。
- `tests/test_world.py`/`tests/test_obs_dedup.py` 中依赖"每次 perceive 都
  +1 importance"的断言：按 F2-1 更新。
- `tests/test_persistence.py`：新增字段后重复 save/load 仍通过（schema 迁移
  测试补充 `last_reinforced` 旧库场景）。

---

## 10. 提交序列（建议）

```
1. fix(embeddings): stable hash + green suite under seeds        [F0-1]
2. fix(reflection): shared-stream scoped dedup + trigger split   [F1-2/F1-3]
3. fix(privacy): dialogue/plan/decision scoped to player+shared  [F1-4/F1-5/F1-6]
4. fix(dialogue): speak writes dialogue memory                   [F1-1]
5. fix(memory): rate-limited reinforcement + dedup-first         [F2-1/F2-2]
6. fix(world): dead entities + step flush social                 [F3-1/F3-2]
7. fix(world): proximity/atomicity/error isolation               [F3-3/F3-4/F3-5]
8. fix(cost): world_event once + trust cap                       [F2-3/F2-4]
9. fix(social): rumor relevance + hearsay provenance             [F4-1/F4-2]
10. fix(identity): halflife + trigger + shared conflicts          [F4-3/F4-4/F4-5]
11. fix(api): add_npc registration + react cache + float plan + ablation [F5]
12. chore: P2 hygiene + docs                                      [F6]
```

每个 commit 前：`PYTHONHASHSEED=0/24/random pytest tests/ -q`；
每个阶段结束：`pytest tests/test_probes.py -q` 6 探针。

---

## 11. 风险、回滚与未决决策

### 11.1 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 行为变化导致现有 demo/探针输出漂移 | 探针可能需重新基线 | 每阶段跑探针；把变化写进 commit；不为了过探针回退修复 |
| 稳定哈希改变相似度分布 | 依赖 HashEmbedder 的测试/eval 变 | 重新基线；新增跨进程测试；不依赖具体阈值数值 |
| 对话检索变窄后"千人千面"变化 | 可能减少跨玩家信息引用 | 这是目标；若产品要 gossip，单开显式通道 |
| merge 限速改变 importance 排序 | 检索/决策行为变化 | 用 F2-2 去重前置配合；跑 memory_consistency/eval 对照 |
| 共享冲突检查增加失效 | 自我反思可能减少 | K 窗口 + 置信度地板；先加测试观察，必要时加开关 |
| `autonomous=True` 打开后成本上升 | 自治世界每步多 LLM 决策 | 默认 False；仅示例显式开启；`decision_tier_gate` 仍可用 |
| schema 迁移（`last_reinforced`） | 旧库打开失败 | 沿用 PRAGMA+ALTER 模式；补旧库迁移测试 |

### 11.2 回滚

- 每个 F 项独立 commit；按 commit revert 即可。
- 所有 DB 变更都是**加列**，不删列、不改语义；回滚代码后旧列被忽略，
  数据不丢。
- 身份/冲突/感知等有争议的行为尽量给开关（缺省按本计划）。

### 11.3 需要确认的决策（执行前）

1. **`speak` 契约**：采用"默认落库"（本计划），还是"只读 + 必须走 world"？
   若选后者，F1-1 改为文档/示例约束，不写记忆。
2. **对话隐私**：采用"当前玩家 + 共享流"（本计划），还是允许 NPC 引用其他
   玩家的私有记忆（需显式 gossip 通道）？
3. **感知模式**：先做 merge 限速 + 去重前置（本计划），还是一步到位改
   transition-driven 感知（F6-11）？建议前者先落地，观察指标后再决定。
4. **共享冲突检查**：默认开（本计划）还是加 `shared_conflict_policy` 开关？
   若开，先观察自我反思失效率。
5. **importance 归一化**：本次只改文档（F6-1），还是直接改成 Min-Max？
   建议先文档 + 评测，避免未经验证的排序变化。
6. **merge 强化间隔**：`6.0` 游戏小时是否合适？可按世界步长调，常量集中
   在 `memory.py`。

---

## 12. 进度清单

### P0 完成记录（2026-10-18）

| 范围 | commit |
|---|---|
| F0-1 稳定 HashEmbedder + 可复现闸门 | `fddff5d` |
| F1-2/F1-3 反思双流去重 + 触发器按流 | `b962c9c` |
| F1-4/F1-5/F1-6 对话/计划/决策信息隔离 | `45b942f` |
| F1-1 `speak` 对话落库 | `0eaea4e` |
| F2-1/F2-2 merge 限速 + 去重前置 | `50639e1` |
| F3-1/F3-2 死亡语义 + step 社交队列 | `3db0027` |
| F3-3/F3-4/F3-5 距离/原子性/故障隔离 | `680f57c` |
| F3-5 补漏：动作触发重规划失败隔离 | `0db5ee3` |

闸门实测：`206` 离线测试在 `PYTHONHASHSEED=0/24` 下全绿；全量
`pytest tests/ -q`（含 6 真实 LLM 探针）`212 passed`。

### 阶段 0
- [x] F0-1 稳定 HashEmbedder + 跨进程测试 + 修 flaky 用例

### 阶段 1
- [x] F1-2 `_save` 共享流去重隔离
- [x] F1-3 反思触发器只累积共享观察
- [x] F1-4 对话检索"当前玩家 + 共享流"
- [x] F1-5 计划 context/中断观察不跨流
- [x] F1-6 自治决策上下文按可见对象过滤（P1 顺带完成）
- [x] F1-1 `speak` 默认写对话记忆 + 世界层去重

### 阶段 2
- [x] F2-1 merge 强化时间窗 + `last_reinforced` 迁移
- [x] F2-2 去重前置（重复在场零 LLM）（P1 顺带完成）
- [ ] F2-3 `world_event` 单次打分
- [ ] F2-4 `judge_trust` 输入封顶

### 阶段 3
- [x] F3-1 死亡实体退出档位/感知/step
- [x] F3-2 `step` 消费 `_step_social`
- [x] F3-3 动作距离校验
- [x] F3-4 help/hide 原子性
- [x] F3-5 per-agent 故障隔离

### 阶段 4
- [ ] F4-1 传闻只转述相关话题
- [ ] F4-2 信任/episode 保留 hearsay/hop
- [ ] F4-3 episode/identity 半衰期
- [ ] F4-4 身份信念生成接线
- [ ] F4-5 共享/identity 冲突检查

### 阶段 5
- [ ] F5-1 `add_npc` 自治注册 + load 恢复
- [ ] F5-2 `react` 缓存保存决策对象
- [ ] F5-3 计划块归一化 + 返回校验块
- [ ] F5-4 `use_relationship` 真正跳过 trust

### 阶段 6
- [ ] F6-1 ~ F6-12 卫生项与文档对齐

### 阶段验收
- [x] 三个种子下离线测试全绿（0 / 24 / 随机；206 passed）
- [x] 6 探针通过（全量 212 passed）
- [ ] `evals/memory_consistency.py --smoke` 跑通（行为变化后重新跑）
- [ ] `evals/decision_ablation.py --smoke` 跑通（F5-4 后）
- [x] 在本文件勾选 P0 完成（本记录）
