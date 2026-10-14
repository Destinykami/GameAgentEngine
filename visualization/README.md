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
│   └── stub_timeline.json  # 确定性 stub 时间线 (由 tools/gen_stub_timeline.py 生成)
├── tools/
│   ├── gen_stub_timeline.py   # 生成 stub 时间线 (复用真实引擎, 脚本化决策, 无 LLM)
│   ├── validate_timeline.ts   # 数据层 schema/不变量校验
│   └── e2e_playwright.mjs     # 无头 chromium 端到端验证
└── src/
    ├── main.ts / config.ts    # Phaser 入口与全局显示约束 (960x540, pixelArt)
    ├── data/                  # schema.ts, timelineLoader.ts, locationAnchors.ts
    ├── PlaybackController.ts  # 播放/暂停/上一步/下一步/调速 (纯逻辑, 可单测)
    ├── scenes/InazumaScene.ts # 单场景: 地图+实体+HUD+播放+M2交互, 消费 visual_events
    ├── entities/              # AgentSprite (血条/名牌/移动/点击), AgentRegistry
    ├── dialogue/              # SpeechBubble (气泡), DamagePopup (伤害数字弹出)
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
- 全程无残留错误

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
