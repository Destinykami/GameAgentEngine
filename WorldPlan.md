# 游戏世界层 (World Layer) 实施计划

在已成型的人人千面 NPC 框架之上加一个**世界层**：多个 NPC + 多个玩家共存于有
空间的世界，NPC 的感知由**空间位置**自动驱动，认知档位由**距离**自动调度
（清掉搁置的债），世界事件影响多个 NPC，全部可持久化、可测试。

## 目标

把"脚本手喂单个 NPC"（`examples/game_loop.py` 模式）升级为**真实可模拟的游戏
世界**：多 NPC 多玩家共存、空间感知自动驱动观察、距离自动调度认知档位、世界
事件多 NPC 联动、全链路可持久化可测试。顺手清掉唯一搁置的债——`set_tier` 手动
→ 距离/注意力自动调度（blog 问题一的核心主张）。

## 现状盘点（plan 的落点）

- `game_loop.py` 模式：脚本把事件翻译成一句自然语言喂 `observe/speak/react`
  ——**单 NPC、手写时间线、无空间、无多 NPC**。
- `NPC` 已具备：observe（自动去重）、speak（非全知+反思门控）、react（LLM 效用
  决策）、set_tier（**手动**）、forget（降权）、持久化（每 NPC 一个 db）。
- **缺口**：多 NPC 注册、空间/位置、自动感知、距离→档位自动调度、世界事件、
  世界状态持久化、模拟循环。
- **要清的债**：`set_tier` 手动 → 距离自动调度。

## 新增模块（沿用扁平约定 `persona_agent/*.py`）

- **`world.py`**：`Location` / `Entity` / `Player` / `World` —— 空间、实体、
  距离度量、档位调度、`step(dt)` 模拟循环。感知生成并入此文件（位置+动作→
  自然语言观察），不单独开文件。
- **世界持久化**：`World.save/load`，世界状态（位置/时钟/事件日志）单独存
  `world.db` 或 `world.json`，与每 NPC 的独立 db 分离。

## 关键 API 契约（先定契约，再实现）

```
Location(name, x, y)                          # 有坐标的空间 (咖啡馆/集市/广场)
Entity(kind, name, location)                  # NPC 或 Player 都是实体
Player(name)                                  # Entity 特化
World(locations)
  .add_npc(name, persona, llm, embedder)      # 复用 NPC.create, 每 NPC 独立 db
  .add_player(name)
  .move(entity, location, now)                # 实体移动
  .tier_of(npc, now) -> full|compressed|idle  # 距离自动调度
  .perceive(npc, now) -> [observations]       # 空间感知→自然语言观察
  .world_event(desc, now, radius=...)         # 世界事件, 范围内 NPC 感知
  .step(dt, now)                              # 推进时钟→算档→感知→按档跑认知
  .save() / World.load(path)                  # 世界状态持久化/恢复
```

## 分阶段交付（每阶段独立可提交可推送）

**阶段 0 — 世界骨架**
`World/Location/Entity/Player` + 游戏时钟 + 位置 + `World.save/load`。
✅ 离线测试：建世界、放实体、移动、保存/加载后位置与时钟一致（stub LLM）。

**阶段 1 — 多 NPC 注册 + 玩家共存**
`add_npc`（复用 `NPC.create`）、`add_player`；世界持有多个 NPC，各自独立记忆流
与面。
✅ 离线测试：同一玩家对两个 NPC 的交互互不污染，跨 NPC 检索隔离。

**阶段 2 — 空间感知 → 观察**（核心）
`perceive(npc, now)`：NPC 感知视距内的玩家动作，生成自然语言观察喂
`npc.observe()`（带 player_id），替代手写 observe。感知粒度随档位变（full=富
细节，compressed=稀疏，idle=无）。
✅ 离线测试：玩家走进 NPC 区域生成关系观察、离开后不生成、近义观察走去重不灌水。

**阶段 3 — 距离→档位自动调度**（清债，blog 问题一落地）
`tier_of(npc, now)` 由位置距离推导档位（同区域/近=full，相邻=compressed，远/
无玩家=idle），`step` 里自动 `set_tier`，替换手动。
✅ 离线测试：玩家在附近升 full、走远降 idle；档位切换影响感知与反思累积
（idle 不累积重要性）。

**阶段 4 — 世界事件**
`world_event(desc, now, radius)`：共享事件（火灾/集市开张/天气），范围内 NPC
作为世界观察（不带 player_id）感知并可 react。
✅ 离线测试：事件只影响半径内 NPC，范围外不受影响。

**阶段 5 — 模拟驱动 + 端到端持久化**
`step(dt, now)` 完整循环（推进时钟→距离调度→空间感知→按档跑 observe/
reflect/react→遗忘清扫→持久化）；`World.load` 跨进程恢复整个世界（含所有 NPC
的记忆与面）。
✅ 离线测试：连续 step 多步，时钟单调、档位正确切换、保存/加载往返一致。

**阶段 6 — 真实 LLM demo 场景 + 集成验证**
`examples/world_demo.py`：小镇场景——咖啡馆 Isabella（外向）、面包师、守卫 3 个
NPC + Aria（友好常客）/Bram（骗子）2 个玩家，跨一天移动、互动、一场火灾。跑
真实 LLM，展示：Isabella 对 Aria 升温、对 Bram 警惕（面隔离）、距离驱动的档位
切换、世界事件的多 NPC 反应。
✅ 真实 LLM 端到端跑通 + 打印关键节点（各 NPC 对各玩家的信任、档位切换日志、
事件反应）。

## 测试与成本策略（延续既有约定）

- **离线**（stub LLM，无网络）：阶段 0-5 的架构确定性。
- **真实 LLM**：仅阶段 6 demo；`probes.py` 可加"世界隔离探针"（同一玩家在
  不同 NPC 上的面独立）。
- **成本**：感知与档位调度纯本地零 LLM；LLM 只发生在 full/compressed 的 NPC 上，
  idle 零 LLM。**距离调度天然让远处 NPC 省认知——blog 成本主张的落地。**

## 不变式（守住）

自我/面解耦 · 每玩家独立记忆流 · 非全知 · 信任调制效用 · 反思门控 · 固化保护 ·
证据只引用观察 · 降权不删除 · **新增：距离决定档位（近处全认知、远处省认知）**。

## 里程碑

0→1→2→**3（清债）**→4→5→**6（真实游戏世界可模拟）**。阶段 3 完成 = "blog
问题一落地"，阶段 6 完成 = "真实游戏世界可模拟"。

## 待定取舍（开写前确认）

1. **场景范围**：小镇 3 NPC + 2 玩家 + 火灾事件（默认设想），还是具体想要的
   场景/职业/剧情？
2. **玩家来源**：demo 用**脚本驱动**（预设走位+台词，可复现可测试，默认），
   还是留**人类实时输入接口**？建议先脚本驱动，人类接口作后续可选。
3. **世界持久化**：单独一个 `world.db`/`world.json`（默认，不破坏"一 NPC 一库"），
   还是并入某个 NPC 的库？
