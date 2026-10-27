# 通用对局回放与狼人杀界面

状态：已实现并完成离线、构建与浏览器验收（2026-10-26）。关联：[多游戏接入](game-integration.md)、[回放与可视化](visualization.md)、[模型适配](model-adapters.md)。

## 目标与边界

为不依赖空间地图的游戏提供只读回放：每局运行输出公共时间线与直播文件，浏览器消费后展示席位、阶段、存活、发言、投票与结局。首个消费者是简化狼人杀；稻妻像素回放器保留，不改造为通用场景。

原则：

- 回放不驱动游戏、不修改 NPC、不重新结算；事实源仍是 `GameEvent` 与 `WerewolfWorld.snapshot()`。
- 公共时间线只含 `channel == 'public'` 的事件；私密身份、查验反馈和狼人夜间目标默认不进入公共文件。
- 上帝视角是本地调试/演示能力：单独文件、显式加载、不自动混入公共记录。
- 前端不解析模型原始输出，只读运行器整理后的结构化步骤。
- 首版覆盖狼人/预言家/女巫/猎人/村民、狼人密谈与投票（含自刀）、公开发言、投票/弃票、淘汰、猎人开枪和胜负；不扩展更多角色或复杂规则，不评估策略质量。

## 数据契约

公共文件 `werewolf_timeline.json`：

```json
{
  "schema_version": 1,
  "game": "werewolf",
  "instance_id": "werewolf-...",
  "seats": ["1号", "2号", "3号", "4号", "5号", "6号", "7号", "8号", "9号", "10号"],
  "max_rounds": 16,
  "persona_seed": 42,
  "steps": [
    {
      "step": 0,
      "round": 1,
      "phase": "night",
      "version": 0,
      "alive": ["1号", "2号", "3号", "4号", "5号", "6号", "7号", "8号", "9号", "10号"],
      "events": [
        {"id": "opening", "type": "announcement", "content": "对局开始。席位：..."}
      ],
      "votes": {},
      "winner": null
    }
  ]
}
```

- `step` 从 0 递增；`version` 使用 `WerewolfWorld` 的状态版本，便于和适配器快照对齐。
- `phase` 取值 `wolf_talk / wolf_vote / seer / witch / speech / vote / hunter / finished`；夜间先狼人密谈和投票，再预言家、女巫；`hunter` 表示猎人出局后的开枪选择阶段。
- `events` 只包含公共事件；`public_speech` 额外带 `actor` 与 `text`，`vote_result` 额外带 `votes`，`elimination` 额外带 `target`，`hunter_shot`/`hunter_pass` 记录猎人开枪或放弃，`game_over` 额外带 `winner`。公共时间线不包含 `wolf_chat`/`wolf_result`/`inspection_result`/`witch_result`。
- `votes` 为 `{投票者: 目标或 null}`，`null` 表示弃票；由运行器从 `vote_result` 原文确定性解析，不猜模型意图。
- 直播文件 `werewolf_live.jsonl` 首行 meta、每步一行、末行 `__done__`，断行/坏行由前端原位重试。

上帝文件 `werewolf_god.json` 使用同样的步骤结构，额外包含：

```json
{"roles": {"1号": "wolf", "2号": "seer"}, "personas": {"1号": {"social": 0.63, "goal_oriented": 0.17}}, "events": [{"channel": "private", "recipients": ["2号"]}]}
```

- 默认只写到运行目录；`--god` 才复制到前端可访问目录。
- 前端 `?god` 或按钮显式请求；未找到时提示，不回退到猜测身份。
- 公共时间线不得出现 `role_assignment`、`inspection_result`、`wolf_result`、`wolf_chat`、`wolf_target`、`witch_result` 或 `roles` 字段。

## 运行器

新增 `game_agent/runners/werewolf_replay.py` 与薄入口 `examples/werewolf_visual.py`：

- 复用 `WerewolfWorld`、`WerewolfAdapter`、`GameSession` 和 `TimelineWriter`。
- 默认使用 `DemoModel`（离线、确定性）；`--real-model` 才构造 `RealLLM`。
- 每个席位默认随机生成 `social`/`goal_oriented` 人格；`--persona-seed` 可复现，种子和人格写入上帝文件。
- 每次 `session.step()` 后取 `world.snapshot()`，记录阶段/轮次/存活/胜负；开场事件在第一次 `step()` 投递前捕获，避免丢失。
- 公共步骤只保留公共事件；上帝步骤保留全部频道及接收者。
- 公共产物写 `werewolf_timeline.json` 与 `werewolf_live.jsonl`；数据库、适配器快照和 `werewolf_god.json` 留在运行目录。
- 结束时写 `adapter-state.private.json` 主持人快照；异常时保留未完成直播文件，不写成功结束标记。
- 不修改 `WerewolfWorld` 的规则、事件文本或私有快照格式；投票解析放在回放运行器，属于展示适配。

## 前端

新增独立页面 `visualization/werewolf.html` 与 `visualization/src/werewolf/`：

- 10 席位（默认 5×2 网格）：姓名、存活/淘汰、上帝视角下的身份；淘汰置灰。
- 顶部显示第几轮、夜晚/发言/投票/结束、存活人数和胜负。
- 主区域为公开记录：发言、票型、淘汰、公告；当前步高亮。
- 播放控制：上一步/下一步/播放/暂停/进度条；默认加载 `public/werewolf_timeline.json`。
- `?timeline=<file>` 指定其他样本；`?live` 轮询 `werewolf_live.jsonl` 并跟随最新步；收到 `__done__` 停止。
- `?god` 或按钮加载 `werewolf_god.json`：显示真实身份、查验反馈和狼人目标；私密事件只在上帝面板出现。
- 不引入 Phaser：桌游界面用 DOM/CSS 更直接；Vite 多页面入口同时构建 `index.html` 与 `werewolf.html`。
- 不改变稻妻回放器的 `Timeline` 类型、场景或素材；狼人杀使用自己的轻量类型。

## 验收

- 离线运行器：公共时间线不含任何私密事件或角色表；上帝文件包含角色与私密事件；直播首 meta/末 done；阶段、存活、票型、胜负与 `WerewolfWorld` 快照一致。
- 前端：`npm run build` 通过；本地静态服务器加载 `werewolf.html` 无 console 错误；可逐步回放、切换上帝视角、显示淘汰和结局。
- 直播：运行器写一行后前端能增加一步并跟随；done 后停止。
- 真实模型仅验证链路，不评价博弈质量；不修改游戏规则、模型提示词或核心协议。
- 未运行项：多人实时观战、公开部署的上帝视角权限、完整狼人杀角色扩展。

## 实施与验证

实现入口：

- `src/game_agent/runners/werewolf_replay.py`：公共时间线/直播/上帝文件；`examples/werewolf_visual.py` 薄入口。
- `visualization/werewolf.html`、`visualization/src/werewolf/{data,main}.ts`、`style.css`。
- `tests/test_werewolf_replay.py` 与 `visualization/tools/test_werewolf.ts`。

2026-10-26 验收结果：

- Python 离线全集 **584 项通过、6 项真实端点测试跳过**；覆盖狼人密谈/投票（含自刀）、女巫看见目标、猎人、10 人默认配置、随机人格和发言去同质化提示。
- 前端 **14 项测试通过**（原有 10 项 + 狼人杀 4 项）；`npm run build` 通过并同时产出 `index.html` / `werewolf.html`。
- 独立 Chromium 检查：加载 50 步真实模型样本，10 个席位；公共日志不含私密事件；`?god` 显示 10 个身份、随机人格和女巫/狼人密谈反馈；分两次追加直播行可依次从 1 步增到 2 步，done 后隐藏 LIVE；无 console/page 错误。
- 真实模型运行 `examples/werewolf_visual.py --real-model --god --persona-seed 42` 完成一局（10 人、好人胜、50 步），公共与上帝文件分离，样本写入 `visualization/public/`。
- 未运行仓库既有 `npm run e2e` 全量套件；未做真实多人实时观战或公开部署权限验证。

## 非目标

- 不做实时对战服务、房间系统、玩家操作 API。
- 不把私密角色表嵌入公共时间线。
- 不为狼人杀引入像素地图、角色立绘或 Phaser 场景。
- 不改 `GameSession` 的决策/投递顺序，不重跑模型输出。
