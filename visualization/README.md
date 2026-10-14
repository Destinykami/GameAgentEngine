# 稻妻城回放器 (visualization/)

基于 Phaser 的像素风只读回放器，可视化 `稻妻城多智能体自治世界模拟` 跑出来的时间线。
实现 [`../VisualizationPlan.md`](../VisualizationPlan.md) 的 M0–M2 里程碑。

**数据来源是引擎产出的结构化 `visual_events`**（`persona_agent/world.py::VisualEvent`），
前端不再解析中文事件串。中文串只是 `VisualEvent.describe()` 的派生产物，仅作兜底。

## 目录

```
visualization/
├── index.html              # #game 容器
├── package.json            # dev / build / preview / validate / e2e
├── tsconfig.json           # strict, noUnusedLocals, bundler resolution
├── vite.config.ts          # base "./", 端口 5173
├── public/
│   ├── stub_timeline.json  # 确定性 stub 时间线 (由 tools/gen_stub_timeline.py 生成)
│   ├── real_timeline.json  # 真实 9/10 天旧格式样本 (data/auto_sim/timeline.json 拷贝, M5 回放)
│   ├── live.jsonl          # 直播增量文件 (运行时产物, 引擎每步 append; gitignore, 不入库)
│   └── assets/             # 地图素材: tiny-town-tilemap.png (Kenney CC0) + TinyTown-LICENSE.txt
├── tools/
│   ├── gen_stub_timeline.py   # 生成 stub 时间线 (复用真实引擎, 脚本化决策, 无 LLM)
│   ├── validate_timeline.ts   # 数据层 schema/不变量校验
│   ├── mock_live_source.mjs   # 模拟"运行中模拟"逐步写 live.jsonl (E2E 直播段用)
│   └── e2e_playwright.mjs     # 无头 chromium 端到端验证
└── src/
    ├── main.ts / config.ts    # Phaser 入口与全局显示约束 (960x540, pixelArt)
    ├── data/                  # schema.ts, timelineLoader.ts (+ 旧格式归一化), legacyEvents.ts (回退解析), liveSource.ts (直播轮询), locationAnchors.ts
    ├── PlaybackController.ts  # 播放/暂停/上一步/下一步/调速 (纯逻辑, 可单测)
    ├── scenes/InazumaScene.ts # 单场景: 地图+实体+HUD+播放+M2交互, 消费 visual_events
    ├── entities/              # AgentSprite (像素角色动画/血条/名牌/移动/活动), AgentRegistry
    ├── dialogue/              # SpeechBubble (气泡), DamagePopup (伤害数字弹出)
    ├── art/                   # 像素素材: townTiles(真实tile索引) / groundMap / buildings / characters(原创) / activityFrames / ArtFactory
    ├── data/                  # + activityProjection.ts (Phase 3 视觉活动投影映射)
    └── ui/                    # StatusPanel / EventLog / PlaybackControls / DetailCard / TimelineScrubber
```

## 运行

```bash
cd visualization

# 1. 生成确定性 stub 时间线 (无 LLM, 复用真实 World 引擎)
../.venv/bin/python tools/gen_stub_timeline.py

# 2. 校验时间线 (schema_version / 地点合法 / damage 非负 / target_dead 一致 / 失败无成功态字段)
npm install            # 首次; 缓存用 --cache ./.npm-cache 绕开 root 属主问题
npm run validate

# 3. 本地开发 (热重载) 或构建 + 预览
npm run dev            # http://localhost:5173
npm run build && npm run preview

# 4. 无头浏览器端到端验证 (需先装 chromium)
npm run e2e
```

## 端到端验证 (`npm run e2e`)

无头 chromium 加载构建产物，直接驱动 `window.__REPLAY__.controller`，断言：

**M1 回放**
- 页面加载无 console/page 错误；`schema_version=1`、14 步、6 实体
- 初始站位：旅行者@稻妻主城、将军@神樱庭（sprite 像素位置 = 地点锚点）
- 手动逐步后旅行者 **移动落到治疗堂锚点**（位移 > 0，移动 Tween 生效）
- day2：桃音 `dead=true` + 致死 `attack`（`target_dead=true`，`damage` 非负）
- 最后一步：`decree_ended=true`、`persuade=3`、非阵亡、note 含"废止"眼狩令

**M2 交互**
- 对话气泡：seek 到对话步，行动者气泡文本=台词、目标回复气泡文本=NPC回复，锚定 sprite；
  跳回无对话步气泡消失（快速跳步不留旧气泡）
- 点击实体详情卡：点旅行者 → 卡打开，名字/地点/血量/类型正确；点空白 → 收起
- 时间轴拖拽寻址：点时间轴中点 → 跳到约中间步；拖到右端 → 跳到末尾

**M3 像素地图**
- 像素角色播 idle 动画（`idle_<name>`），移动途中播 walk（`walk_<name>`），到位回 idle
- y-sort 深度层级：角色深度 = round(y)，随 y 递增 → 角色与建筑/樱树按 y 排序，
  走过屋顶/树后正确遮挡（前景遮挡排序基础）

**Phase 3 视觉活动投影**
- 各 NPC 按 (角色+地点) 推断日常活动：刚郎@锻造坊 播锻造锤击、桃音@治疗堂 播治疗、
  小梅@稻妻主城 播阅读、将军@神樱庭 坐镇待机（均断言实际动画 key）
- 详情卡显示活动标签（如"锻造武器 (视觉投影)"）
- 活动中断：step2 桃音被攻击 → 治疗中断（实际回 idle）；刚郎未被攻击 → 继续锻造
- 全程无残留错误

**M5 真实样本回放（旧格式不回归）**
- 真实 9/10 天样本 `public/real_timeline.json`（`data/auto_sim/timeline.json` 拷贝）是**旧格式**：
  只有中文 `events` 串，无 `visual_events`/`schema_version`/`world`。加载器 `normalizeTimeline`
  回退解析中文串（`legacyEvents.ts`）填 `visual_events` + 合成 world，再走统一校验。
- 用 `?timeline=real_timeline.json` 加载，断言：31 步、day=10、`decree_ended=true`、`persuade=5`、
  note 含"废止"；回退解析后 visual_events 覆盖 move/conversation/help/attack/flee + 致死
  attack `target_dead` + dead 态（桃音）；对话气泡可见；step20 桃音 dead。

**直播跟随（运行中实时可视化，不只是跑完回放）**
- 引擎 `examples/world_auto_sim.py` 每跑完一步就 append 一行 JSON 到 `live.jsonl`
  （首行 meta、每步一个 TimelineStep、末行 done），与最终 `timeline.json` 并存。
- 前端 `?live` 模式每秒轮询 `live.jsonl`：收到 meta + 首步即建场景，之后每来新步
  `addStep` + 时间轴增刻度 + 自动跳到最新步跟随，右上角红色脉冲 **LIVE** 标记；
  收到 done 行停止轮询、隐藏标记，时间线完整可往回拖（切回普通回放）。
- 用法：先起 `npm run dev`（vite dev 直接 serve `public/`，引擎写入的
  `public/live.jsonl` 实时可见），再开 `http://localhost:5173/?live`，然后跑模拟
  （`.venv/bin/python examples/world_auto_sim.py`）即可边跑边看。
  （`vite preview` 从 `dist/` serve，运行时写入的 `public/live.jsonl` 不在 dist 里，
  故直播需 dev 模式；E2E 用 `tools/mock_live_source.mjs` 逐步写 `dist/live.jsonl` 模拟。）
- E2E 断言：LIVE 标记可见；步数随轮询增长（逐步接入）；自动跟随最新步
  （index = total-1）；done 后时间线完整（14 步）且 LIVE 标记隐藏（切回放）。

截图落在 `e2e_shots/`。

> 环境坑：无头 chromium 需系统库 `libnspr4/libnss3/libasound2`；本机 sudo 要密码，
> 用 `apt-get download` + `dpkg -x` 解到 `syslibs/` 再 `LD_LIBRARY_PATH` 指过去。
> CJK 字体装到 `~/.fonts`（Noto Sans CJK）否则中文显示为方块。

## 设计要点（对应计划）

- **数据事实源**：前端只消费 `visual_events`（结构化），`events` 中文串仅作兜底。
  系统效果（理由/锻刀/目击/结局）是独立字段，渲染为系统提示行而非气泡正文。
- **模拟/渲染坐标分离**：`location`（名称）→ `locationAnchors.ts` 像素锚点，严格分开。
- **事件成功后才表现副作用**：`attack.success=false` 不渲染受击/死亡；死亡由
  `target_dead` + `states[].dead` 双重确认。
- **像素显示约束**：统一在 `config.ts` 设 `pixelArt`/`roundPixels`/整数倍缩放，
  不让每个 Sprite 自己决定。
- **单场景**：地图+实体+HUD+播放全在一个 `InazumaScene`，避免多场景时钟不进更新相位
  （`scene.add`+`start/launch` 会让 timer/tween 不 tick）。
- **播放控制**：`PlaybackController` 纯逻辑类；`onStep`（步变化→应用状态）与
  `onTransport`（播放/暂停→冻结/解冻 Tween）严格分离，手动逐步不冻死移动动画。
- **M2 对话气泡**：`SpeechBubble` 锚定 sprite 头顶、自动换行、淡入淡出，区分
  player（蓝边）/npc（灰白边）/system（金边）风格；同地点对话双方气泡左右错开不重叠。
  只有成功对话才显示气泡（`success===false` 不显示完成态）；系统效果（理由/锻刀/目击）
  用独立浮动金色提示，不塞进气泡正文（计划 §4/§9.5）。
- **M2 点击详情卡**：点实体弹出只读详情卡（名字/生死/地点/血量/攻击/身份/类型 +
  旅行者证据理由），点空白收起。用**几何判定**区分"点实体"与"点空白"，不依赖事件触发
  顺序（Phaser 场景级 pointerdown 先于 sprite onClick 触发，标记会残留误判）。
- **M2 时间轴拖拽**：顶部时间轴每步一个刻度 + 金色播放头，点击/拖动跳到任意 step。
  由**场景级输入**统一驱动（独立游戏对象的 `setInteractive` 在此无头环境不生效，
  Zone/Rectangle 的 input 均不触发，只有场景级 pointerdown 可靠）。
- **M2 伤害弹出**：成功攻击时目标头顶弹出 `-N`（致死红色 `✝` 强化），上飘淡出。
- **reason_count 源头完整**：引擎 `VisualEvent.to_dict()` 对 `witnessed` 事件也输出
  `reason_count`（此前只输出 `reason_added` 分支），前端不再显示"现 undefined 条"。
- **M3 像素素材（混合来源，许可证已记录）**：地图改用公开素材 **Kenney "Tiny Town"**
  （CC0 公共领域，无需署名，许可证见 `public/assets/TinyTown-LICENSE.txt`）——地面/道路/
  六建筑/樱树/灯笼/井/栅栏/蘑菇/松树全部真实 tile（`art/townTiles.ts` 定义 tile 下标，
  `ArtFactory` 用 `drawImage` 从 tilemap 烘焙；场景自行 fetch tilemap 为 HTMLImageElement，
  不依赖 Phaser 纹理解码，因无头 WebGL 下 `texture.source.data` 可能为 null）。
  **角色帧（idle/walk）与活动点道具（铁砧/病床/书桌/鸟居）保留原创像素**（`characters` /
  `activityFrames` / `palette`）——角色需要行走动画，公开 tile 无动画。樱树 = 圆树 tile 染粉。
  混合策略：地图用公开素材（美观、无许可证风险），角色/活动道具用原创（动画、辨识度）。
- **UI 美化（稻妻主题）**：状态面板加**血量条**（按血量比例变绿/黄/红）+ 金色题头线，
  旅行者理由/攻移到页脚；事件记录加金色题头；播放按钮加圆角深色底 + 金色描边；详情卡改
  金色边框（阵亡红边）。统一深底 `0x1c1c24` + 金色 `0xd9a441` 题头，呼应稻妻城风格。
- **M3 Ground/Buildings 分层 + y-sort 遮挡**：地面是一张整图（depth 0），建筑/活动点/樱树/
  灯笼是独立 Sprite，角色也是独立 Sprite，全部 `setDepth(round(y))` 参与同一深度空间 →
  按 y 排序，角色从屋顶/树后走过时正确遮挡（计划 §M3 前景遮挡与角色层级）。
- **M3 角色动画**：`AgentSprite` 用 `Phaser.GameObjects.Sprite` 播 `idle_<name>`（呼吸两帧）
  与 `walk_<name>`（迈腿两帧）；`moveTo` 途中切 walk、到位回 idle，暂停时 `anims.pause()` 冻结。
- **M3 活动点**：铁砧/病床/书桌/鸟居是 NPC 日常活动锚点（计划 Phase 3 活动投影的基础），
  作为前景道具参与 y-sort。
- **Phase 3 视觉活动投影**：`data/activityProjection.ts` 按 (角色, 地点) 映射默认活动
  （桃音治疗/刚郎锻造/小梅阅读/执行官巡逻/将军坐镇），**明确标记为视觉投影**——按角色+地点+
  动作推断，不冒充后端已模拟每一分钟连续行为（计划 §Phase 3 重要边界）。活动帧
  （hammer/heal/read）在 `art/activityFrames.ts` 原创像素，ArtFactory 烘焙成循环动画。
- **Phase 3 活动中断**：`INTERRUPT_TYPES`（attack/flee/help/hide/counterattack）触发表现切换，
  attack 对行动者和目标都中断；talk/move/wait/conversation 不打断日计划。死/被中断 → 停活动。
- **Phase 3 巡逻/坐镇**：执行官在巡逻地点沿两点往返（moveTo 播 walk + update 检测停下切点）；
  将军坐镇播 idle + 脚下紫色脉冲光环（环境特效，非战斗）。
- **点选改几何判定**：详情卡点选从"每个 sprite 的 onClick 闭包"改为场景 pointerdown 里
  `spriteAt()` 几何识别（命中区含指针者取 y-sort 最上层）。per-sprite input 闭包捕获名字不可靠
  （曾出现点谁都开旅行者卡），几何判定绕开 Phaser 的 per-sprite 命中/闭包异常。
