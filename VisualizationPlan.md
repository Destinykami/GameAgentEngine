# 稻妻城自治世界可视化计划

> 状态：调研完成，待实现
>
> 目标：在不破坏现有 Python 世界模拟、非全知认知和自治决策时序的前提下，为 `world_auto_sim.py` 建立一个类似《星露谷物语》的像素风 2D 场景，并用 NPC 活动、移动动画和对话气泡把世界演出来。
>
> 核心参考：Generative Agents: Interactive Simulacra of Human Behavior 的 Smallville 沙盒。该项目使用 Phaser 构建浏览器场景，导入环境 Sprite、角色 Sprite、地图和碰撞地图；服务器以 JSON 维护 Agent 位置、动作和交互对象，再由前端渲染和动画。

---

## 1. 总览

### 1.1 当前系统

当前项目由三层组成：

```text
persona_agent/world.py
    世界状态、Location、Entity、NPC、感知、决策、动作、反思、持久化

examples/world_auto_sim.py
    创建稻妻城世界、注册 NPC、推进自治时间步、生成 timeline.json

examples/replay.py
    读取 timeline.json，进行终端和自包含 HTML 文本回放
```

当前世界已经具备：

- 6 个有二维区域坐标的地点
- 旅行者 + 5 个 NPC
- 感知范围和认知档位
- LLM 驱动的 Agent 决策
- `move/talk/attack/flee/help/hide/wait` 动作
- 日计划和重大动作后的重规划
- 对话、记忆、关系、信任和反思
- 血量、攻击、防御、死亡状态
- 每天 09:00、14:00、19:00 的稀疏自治步
- `data/auto_sim/timeline.json` 时间线回放

### 1.2 当前缺口

当前的 `Location` 是区域级位置，不是 tile 或像素位置；`move()` 是区域间瞬移。时间线中的事件是中文字符串，缺乏结构化的行动者、目标、起点、终点、对话轮次和状态变化字段。

因此，当前系统不能直接表现：

- 连续行走
- 碰撞和寻路
- 朝向与行走帧
- NPC 在某地点执行的具体活动
- 活动的开始、结束和进度
- 可可靠绑定到角色的对话气泡
- 气泡显示时长、换行和优先级

### 1.3 目标形态

最终形成以下结构：

```text
Python 自治世界
        │
        │ 生成模拟状态和结构化视觉事件
        ▼
视觉投影 / 回放数据层
        │
        │ JSON
        ▼
Phaser 浏览器端
        ├── Tiled 像素地图
        ├── 场景图层
        ├── NPC Sprite
        ├── 移动 / 活动动画
        ├── 对话气泡
        ├── 时间线控制器
        └── 事件日志和状态面板
```

第一阶段的产品定义是：

> **稻妻城自治世界的像素风事件回放器**

不是立即把后端改造成一个实时可操作的完整游戏。

---

## 2. 总体设计原则

### 2.1 世界模拟与渲染解耦

Python 世界负责：

- Agent 感知
- Agent 决策
- 动作合法性
- 战斗数值
- 记忆和信任
- 关系反思
- 时间推进
- 世界状态持久化

Phaser 前端负责：

- 地图绘制
- Sprite 绘制
- 场景层级
- 动画
- 气泡和 UI
- 播放、暂停和逐步回放
- 将离散状态变化视觉化

渲染器不能反向修改世界状态，也不能根据动画帧重新触发 Agent 决策。

### 2.2 保留自治 step 的时序

`World.step_autonomous()` 的时序必须保持：

```text
advance
→ schedule_tiers
→ 早晨生成日计划
→ 所有存活 Agent 在同一时刻决策
→ 按 entities 注册顺序执行
→ 重感知
→ 自我反思
→ flush_social
→ save
```

参考：[persona_agent/world.py](persona_agent/world.py)，尤其是 `step_autonomous()`。

前端可以把一个 step 拆成数秒的动画，但那只是表现层插值。它不能在第一个角色移动后就让其他角色重新决策。

### 2.3 模拟坐标和渲染坐标分离

保留现有 `Location.x/y` 用于：

- 感知距离
- full/compressed/idle 档位
- 世界事件半径
- 现有测试和规则

新增视觉映射用于：

- Tiled 地图位置
- Sprite 像素坐标
- 气泡锚点
- 活动点
- 摄像机位置

不要直接把 Tiled 像素坐标用于现有欧氏距离，否则调整美术布局会意外改变 Agent 的认知行为。

### 2.4 事件成功后才表现副作用

`talk` 和 `attack` 都是先生成目标 NPC 的认知事件，成功后才提交回复、历史、伤害和奖励。因此：

- talk 失败时不显示已完成的对话气泡
- attack 失败时不显示伤害或死亡动画
- 状态奖励不应伪装成对话内容
- 关系反思在 step 末尾完成，不能提前显示为即时信任变化

---

## 3. 推荐技术路线

## 3.1 第一选择：Phaser + Tiled

### Phaser

使用 Phaser 作为浏览器端 2D 场景运行时，原因：

- 与 Generative Agents 的 Smallville 实现路线一致
- 原生支持 Tilemap、Sprite、动画、Tween 和摄像机
- 适合读取 JSON 回放数据
- 适合快速制作播放/暂停/逐帧控制
- 浏览器中容易展示和分享
- 不需要把 Python 世界迁移到新的游戏引擎

参考：

- [Phaser Tilemap API](https://docs.phaser.io/api-documentation/class/tilemaps-tilemap)
- [Phaser Sprite](https://docs.phaser.io/phaser/concepts/gameobjects/sprite)
- [Phaser Animations](https://docs.phaser.io/phaser/concepts/animations)
- [Phaser Tweens](https://docs.phaser.io/phaser/concepts/tweens)
- [Phaser Pixel Art Guide](https://github.com/phaserjs/phaser/blob/master/docs/Phaser%204%20Pixel%20Art%20Guide/Phaser%204%20Pixel%20Art%20Guide.md)

### Tiled

使用 Tiled 编辑地图和对象层，保存：

- 地面层
- 建筑层
- 装饰层
- 前景层
- 碰撞层
- 地点对象
- NPC 出生点
- 活动点
- 对话气泡锚点
- 路径点

参考：

- [Tiled Objects](https://doc.mapeditor.org/en/stable/manual/objects/)
- [Tiled Layers](https://doc.mapeditor.org/en/stable/manual/layers/)
- [Tiled Custom Properties](https://doc.mapeditor.org/en/stable/manual/custom-properties/)

### 像素显示约束

第一版建议：

- 使用固定的低分辨率逻辑画布
- 使用整数倍缩放
- 关闭纹理线性过滤
- 启用像素对齐 / round pixels
- 尽量不对 Sprite 做非整数缩放
- 统一 tile 尺寸和角色基线
- 气泡文字使用明确的像素字体或清晰的低分辨率字体

Phaser 的 `pixelArt` / `roundPixels` 应在前端配置中统一设置，不能让每个 Sprite 自己决定显示策略。

## 3.2 暂不推荐直接使用 Godot

Godot 4 的 TileMapLayer、TileSet、Navigation 和编辑器能力很强，更适合最终的独立桌面游戏。但当前项目是 Python 模拟器，第一阶段如果使用 Godot，需要额外处理：

- Python 与 Godot 的状态桥接
- JSON 或网络同步
- 新项目结构
- 实时运行与离线回放的边界
- 后端持久化和前端场景状态的双向契约

因此建议：

```text
第一阶段：Phaser 只读回放器
第二阶段：Phaser 结构化事件和活动投影
第三阶段：根据实时交互需求重新评估 Godot
```

---

## 4. 分阶段具体路线

## Phase 0：视觉原型，不改世界代码

### 目标

证明现有 `timeline.json` 可以驱动一个像素风场景。

### 输入

```text
data/auto_sim/timeline.json
```

### 输出

一个可以在浏览器中打开的 Phaser 页面，至少支持：

- 显示稻妻城地图占位图
- 显示 6 个地点
- 显示 6 个实体
- 使用不同颜色或临时 Sprite 区分 NPC
- 根据每个 step 的 `states[name].loc` 更新角色所在地点
- 地点变化时使用 Tween 表现移动
- 显示 day、moment、clock
- 显示当前事件日志
- 显示血量、死亡和旅行者进度
- 支持播放、暂停、上一帧、下一帧
- 支持播放速度调整

### 地点初始映射

第一版可先使用静态的视觉锚点：

```text
稻妻主城  → 中央街区
治疗堂    → 主城东侧
锻造坊    → 治疗堂东侧
眼狩署    → 主城北侧
神樱庭    → 地图北方高地
城外官道  → 地图右下方出口
```

这些是渲染映射，不应修改 `Location` 的模拟坐标。

### 验收标准

- 可以连续播放完整 timeline
- 角色永远显示在对应 `loc` 的视觉锚点
- step 之间不跳错角色
- 死亡角色正确隐藏或显示死亡状态
- 回放不会修改 `world.db` 或 NPC 数据库
- 不需要调用 LLM
- 不需要运行 `world_auto_sim.py`

---

## Phase 1：地图和视觉实体

### 目标

用真实的俯视像素地图替换占位图，并建立稳定的渲染坐标层。

### 建议目录

```text
visualization/
├── README.md
├── package.json
├── index.html
├── public/
│   ├── maps/
│   │   ├── inazuma.tmx
│   │   ├── inazuma.json
│   │   └── tilesets/
│   ├── sprites/
│   │   ├── traveler/
│   │   ├── tao-yin/
│   │   ├── gang-lang/
│   │   ├── xiao-mei/
│   │   ├── enforcer/
│   │   └── shogun/
│   └── fonts/
├── src/
│   ├── main.ts
│   ├── config.ts
│   ├── scenes/
│   │   ├── BootScene.ts
│   │   ├── InazumaScene.ts
│   │   └── OverlayScene.ts
│   ├── data/
│   │   ├── timelineLoader.ts
│   │   ├── schema.ts
│   │   └── locationAnchors.ts
│   ├── entities/
│   │   ├── AgentSprite.ts
│   │   └── AgentRegistry.ts
│   ├── animation/
│   │   ├── movement.ts
│   │   └── activityAnimation.ts
│   ├── dialogue/
│   │   ├── SpeechBubble.ts
│   │   └── DialogueQueue.ts
│   └── ui/
│       ├── PlaybackControls.ts
│       ├── EventLog.ts
│       └── StatusPanel.ts
└── tools/
    └── validate_timeline.ts
```

目录名可根据最终前端工具链调整；重点是把数据、场景、实体、动画、气泡和 UI 分开。

### 地图图层

建议至少使用以下 Tiled 图层：

```text
Ground          地面和道路
Buildings       建筑主体
Collision       不可行走区域
LocationMarks   地点对象和视觉锚点
ActivitySpots   活动点，例如铁砧、病床、书桌
Foreground      覆盖角色的树、屋檐、前景装饰
```

### 视觉坐标映射

Tiled 对象层中给每个地点配置：

```json
{
  "name": "治疗堂",
  "class": "LocationAnchor",
  "properties": {
    "world_location": "治疗堂",
    "spawn_x": 320,
    "spawn_y": 224,
    "bubble_x": 320,
    "bubble_y": 176
  }
}
```

第一版可以直接使用 Phaser 中的映射表；稳定后再迁移到 Tiled 自定义属性。

---

## Phase 2：结构化视觉事件

### 目标

不再依赖解析中文事件字符串，为动画和气泡建立稳定事件协议。

### 保留兼容性

原有字段继续保留：

```json
{
  "events": ["原始中文事件字符串"],
  "states": {"...": "..."}
}
```

新增字段并行存在：

```json
{
  "visual_events": [
    {
      "id": "day-01-step-02-event-01",
      "type": "conversation",
      "clock": 14.0,
      "actor": "旅行者",
      "target": "桃音",
      "location": "治疗堂",
      "success": true,
      "utterance": "你知道眼狩令造成了什么吗？",
      "reply": {
        "speaker": "桃音",
        "text": "许多持眼者因此流离失所。"
      },
      "effects": [
        {
          "type": "reason_added",
          "actor": "旅行者",
          "value": "..."
        }
      ]
    }
  ]
}
```

### 事件类型

第一版至少定义：

| type | 必要字段 | 前端表现 |
|---|---|---|
| `move` | actor, from, to | 路径或地点间 Tween |
| `conversation` | actor, target, utterance, reply | 双方靠近、气泡 |
| `attack` | actor, target, damage, target_dead | 受击、伤害数字、死亡 |
| `help` | actor, target | 帮助动作、正向提示 |
| `hide` | actor, target | 藏匿动作、状态提示 |
| `flee` | actor, from, to | 快速离开、逃跑动画 |
| `world_event` | description, location/radius | 场景横幅或环境特效 |
| `schedule_change` | actor, activity, reason | 活动图标或状态更新 |
| `relationship_update` | actor, target, result | 仅在 step 末显示关系变化 |
| `death` | actor/target, cause | 死亡动画和状态锁定 |

### 事件顺序

同一个 step 的视觉事件必须保留后端实际执行顺序：

```text
动作成功事件
→ 状态变化
→ 被攻击者 / 目标反应
→ 重规划或活动中断
→ step 末关系反思
→ note / 结局提示
```

前端可以为了播放效果设置事件间的短暂延迟，但不能重排因果顺序。

### 失败事件

建议保留失败动作但明确标识：

```json
{
  "type": "conversation",
  "success": false,
  "failure_reason": "认知事件生成失败",
  "actor": "旅行者",
  "target": "桃音"
}
```

失败事件只进入日志，不触发完成态气泡、奖励或伤害动画。

---

## Phase 3：NPC 活动投影

### 目标

让 NPC 不只是站在地点上，而是在地点内表现出日常活动。

### 重要边界

当前后端的日计划和重规划并没有完整写入 timeline；因此 Phase 3 的活动应明确标记为：

```text
视觉活动投影
```

它可以根据计划、角色、地点和动作推断或配置，但不能冒充后端已经模拟了每一分钟的连续行为。

### 活动数据结构

建议未来在 timeline step 或独立 activity stream 中保存：

```json
{
  "actor": "刚郎",
  "activity": "smithing",
  "label": "锻造武器",
  "location": "锻造坊",
  "start_clock": 14.0,
  "end_clock": 19.0,
  "status": "active",
  "interruptible": true,
  "animation": "hammer",
  "anchor": "anvil-01"
}
```

### 角色活动映射

| NPC | 地点 | 默认视觉活动 | 动画表现 |
|---|---|---|---|
| 桃音 | 治疗堂 | 治疗伤者 / 整理药材 | 面向病床，治疗或待机 |
| 刚郎 | 锻造坊 | 锻造武器 | 面向铁砧，锤击循环 |
| 小梅 | 稻妻主城 | 阅读 / 整理典籍 | 书桌旁阅读循环 |
| 执行官 | 眼狩署 / 街道 | 巡逻 / 搜捕 | 沿路径点行走 |
| 雷电将军 | 神樱庭 | 坐镇 / 观望 | 固定位置待机，环境特效 |
| 旅行者 | 各地点 | 行走 / 对话 / 战斗 | 由实际事件驱动 |

### 活动中断

以下后端动作应触发活动表现切换：

```text
attack       → 被攻击或进入战斗
counterattack → 战斗
flee         → 逃跑
help         → 帮助动作
hide         → 藏匿动作
```

`talk/move/wait` 默认不打断日计划，除非后端未来显式产生 `schedule_change`。

同一步发生“被攻击 → 重规划”时，前端应把新活动视为该 step 的后续状态，而不是下一天才开始。

---

## Phase 4：对话气泡

### 目标

将 `talk` 事件表现为角色之间的短暂对话，而不是把整条事件字符串放到日志中。

### 气泡模型

```text
SpeechBubble
├── speaker
├── recipient
├── text
├── anchor_world_position
├── created_at_visual_time
├── duration
├── priority
├── line_wrap_width
├── state: entering | visible | leaving | done
└── style: player | npc | system
```

### 显示顺序

一次成功对话建议按以下顺序：

```text
行动者靠近目标
→ 行动者气泡
→ NPC 回复气泡
→ 系统状态变化提示
```

例如：

```text
旅行者：你知道眼狩令造成了什么吗？
桃音：许多持眼者因此流离失所。
系统：旅行者获得一条理由
```

“理由增加”“攻击力提升”“信任反思完成”等应使用系统提示，不放进角色气泡正文。

### 气泡显示策略

- 一次只显示一个主要对话序列
- 长文本自动换行和分段
- 回复含换行时保留段落或按句拆分
- 气泡锚点跟随 Sprite，而不是固定在屏幕上
- 气泡超出画布顶部时自动翻转或向下偏移
- 多个 NPC 同时对话时使用队列
- 战斗、死亡和结局提示可以抢占普通闲聊，但必须记录优先级

### 实现选择

第一版建议使用 Phaser Canvas 内的图形和文字：

- 与像素地图同一摄像机
- 可控制深度和遮挡
- 可实现像素边框、尾巴和阴影
- 不需要处理 DOM 与 Canvas 的层级差异

Phaser DOM Element 可作为以后高分辨率设置面板的选择，但不建议用于第一版角色气泡。

---

## 5. 参考结构

## 5.1 推荐仓库结构

```text
persona_agent/
├── persona_agent/                 # 现有 Python 世界和认知框架
│   ├── world.py
│   ├── npc.py
│   ├── dialogue.py
│   └── ...
├── examples/
│   ├── world_auto_sim.py          # 自治模拟入口
│   └── replay.py                  # 旧文本回放，保持兼容
├── data/
│   └── auto_sim/
│       ├── timeline.json          # 原始兼容时间线
│       ├── visual_timeline.json   # 结构化视觉时间线
│       └── world.db
├── visualization/                 # 新增的独立前端项目
│   ├── package.json
│   ├── index.html
│   ├── public/
│   │   ├── maps/
│   │   ├── sprites/
│   │   ├── tilesets/
│   │   └── fonts/
│   ├── src/
│   │   ├── main.ts
│   │   ├── config.ts
│   │   ├── scenes/
│   │   ├── data/
│   │   ├── entities/
│   │   ├── animation/
│   │   ├── dialogue/
│   │   └── ui/
│   └── tools/
│       └── validate_timeline.ts
├── docs/
│   └── visualization-plan.md      # 本计划的最终归档位置（可选）
└── tests/
    └── ...
```

本计划文件建议暂时放在仓库根目录，正式实现时可以复制或移动到 `docs/`，但不要让前端实现反向依赖文档路径。

## 5.2 前端模块职责

### `timelineLoader`

职责：

- 读取 JSON
- 校验版本和必需字段
- 规范化旧时间线
- 提供 step 游标
- 不负责绘制

### `schema`

职责：

- 定义 `Timeline`
- 定义 `TimelineStep`
- 定义 `AgentSnapshot`
- 定义 `VisualEvent`
- 定义 `ActivityProjection`
- 运行基础数据校验

### `AgentRegistry`

职责：

- 按名称维护 Sprite
- 将后端角色名映射到 Sprite 资源
- 更新可见性、死亡状态和名称标签
- 不做世界规则判断

### `movement`

职责：

- 将 `from/to` 转为视觉坐标
- 创建 Tween 或路径动画
- 管理移动期间的 Sprite 朝向
- 不修改后端状态

### `activityAnimation`

职责：

- 将 `activity` 映射为动画 key
- 处理待机、锻造、治疗、阅读、巡逻等循环
- 处理动作中断
- 保持活动表现和后端快照分离

### `SpeechBubble`

职责：

- 创建和销毁气泡
- 自动换行
- 跟随角色锚点
- 处理进入、停留和离场动画
- 管理优先级和队列

### `PlaybackController`

职责：

- 播放/暂停
- 上一步/下一步
- 跳转到指定 step
- 调整现实播放速度
- 区分游戏时间和现实时间

---

## 6. 数据契约草案

### 6.1 顶层结构

```json
{
  "schema_version": 1,
  "world": {
    "name": "稻妻城",
    "coordinate_system": "location-name",
    "render_map": "inazuma-v1"
  },
  "config": {
    "reason_needed": 3,
    "attack_needed": 20,
    "persuade_n": 5
  },
  "steps": []
}
```

### 6.2 Step 结构

```json
{
  "step_id": "day-01-14",
  "day": 1,
  "moment": 14.0,
  "clock": 14.0,
  "events": [],
  "visual_events": [],
  "activities": [],
  "states": {},
  "note": "",
  "persuade": 0,
  "decree_ended": false,
  "shogun_dead": false
}
```

### 6.3 实体快照扩展方向

当前字段保持兼容，未来可增加：

```json
{
  "health": 80,
  "loc": "治疗堂",
  "render_anchor": "clinic-taoyin",
  "dead": false,
  "kind": "npc",
  "role": "vision_holder,healer",
  "activity": "healing",
  "facing": "right",
  "animation": "idle",
  "bubble_anchor": "head"
}
```

注意：`render_anchor/activity/facing/animation` 属于视觉字段，不应自动参与后端认知和战斗计算。

---

## 7. 测试和验证路线

### 7.1 数据层验证

为视觉时间线增加离线校验工具，检查：

- 每个 step 有单调不回退的 `clock`
- 每个实体都存在于初始注册表或有明确新增来源
- `loc` 必须是已知地点
- `from/to` 与相邻快照一致
- `attack.damage` 为非负数
- `target_dead=true` 时目标快照必须死亡
- 成功 talk 必须包含 actor、target 和文本
- 失败动作不得包含成功的 effects
- 事件 ID 在整个 timeline 中唯一
- 事件顺序号不重复

### 7.2 前端验证

至少覆盖：

1. 空时间线不会崩溃
2. 只有首帧的时间线可以显示
3. 角色位置与 `states` 一致
4. 角色死亡后不再播放普通活动
5. move 事件不丢失、不重复播放
6. 同一步多个事件按顺序执行
7. 长对话自动换行
8. 多个气泡按队列显示
9. 暂停时动画和气泡都暂停
10. 快速跳步后不会留下旧气泡或旧 Tween
11. 缺少可选视觉字段时使用默认表现
12. 原始旧版 timeline 仍可回放

### 7.3 端到端验证

建议顺序：

```text
用现有 data/auto_sim/timeline.json
→ 启动前端
→ 播放到包含移动的 step
→ 播放到包含对话的 step
→ 播放到包含攻击/死亡的 step
→ 播放到结局 step
```

第一阶段不要求真实 LLM、不要求重新运行自治模拟。前端应当是纯离线回放器。

---

## 8. 素材策略

### 8.1 原型阶段

先使用以下任一方案：

- 彩色矩形角色
- 自制简单 16×16 占位 Sprite
- 公共领域或明确允许开发使用的临时素材
- 纯色 tile 验证地图层和碰撞层

不要在许可证尚未确认时把第三方素材提交进仓库。

### 8.2 候选素材

- [Sprout Lands](https://cupnooble.itch.io/sprout-lands-asset-pack)：俯视角、16-bit、角色动画；免费版和付费版许可不同，需按页面要求使用和署名。
- [Serene Village](https://limezu.itch.io/serenevillagerevamped)：16×16 俯视角村庄素材，页面标注 CC BY 4.0。
- [Pixel Art Top Down Village](https://cainos.itch.io/pixel-art-top-down-village)：32×32 俯视角村庄素材，页面说明可用于商业和非商业项目，但不得重新分发或转售。
- [Japanese Village & Farming](https://pozac.itch.io/japanese-village-farming-top-down-2d-pixel-art-asset-pack)：更接近日式村落，但应单独核对完整许可和素材范围。

素材选择标准：

- tile 尺寸一致
- 角色基线一致
- 支持至少四方向或可接受简化
- 有待机和行走帧
- 地图、建筑和角色色彩风格统一
- 明确允许当前项目的使用和修改方式

---

## 9. 关键取舍和风险

### 9.1 离散 step 不是连续模拟

09:00 到 14:00 之间的行走和活动只能是视觉插值。前端不能宣称它知道这五个游戏小时里每一分钟发生了什么。

### 9.2 不从中文字符串长期解析语义

短期兼容可以显示原始 `events`，但正式动画必须使用结构化 `visual_events`。否则中文文本格式变化会导致角色、气泡和奖励错配。

### 9.3 不把 render 坐标用于认知距离

视觉地图可以任意调整；模拟空间坐标必须保持稳定。

### 9.4 不把后端内部计划直接当作已完成活动

如果计划没有持久化或没有进入 timeline，只能作为活动投影。真正需要可回放的活动必须被写入明确的数据字段。

### 9.5 不把状态奖励塞进气泡

对话文本、NPC 回复、系统提示和状态效果分开渲染，避免用户误以为 NPC 说出了系统内部奖励。

### 9.6 暂不引入实时通信

第一阶段采用离线 JSON 回放。只有在需要人类实时干预或服务器持续运行时，才考虑：

- WebSocket
- SSE
- 后端 HTTP API
- 实时事件队列

---

## 10. 里程碑

### M0：调研和契约

- [x] 读 `world_auto_sim.py`
- [x] 读 `world.py`
- [x] 读 `replay.py`
- [x] 确认 Smallville 使用 Phaser
- [x] 确认 Tiled / 地图 / 碰撞 / JSON 状态思路
- [x] 明确模拟坐标与渲染坐标分离
- [x] 确定第一版前端构建工具（Vite + TypeScript + Phaser）
- [x] 确定视觉时间线 schema（`schema_version=1`, `data/schema.ts`）

### M1：占位像素回放器

- [x] 建立独立 `visualization/` 前端目录
- [x] 读取旧版 `timeline.json`
- [x] 绘制 6 个地点
- [x] 绘制 6 个实体占位 Sprite
- [x] 实现播放、暂停、逐步和速度控制
- [x] 实现地点变更 Tween
- [x] 实现状态面板和事件日志

### M2：真实地图和角色

- [x] 制作或导入 Tiled 地图（`art/groundMap.ts` 60×34 确定性像素布局, 原创无第三方）
- [x] 加入 Ground、Buildings、Collision 等图层（地面整图 + 建筑/活动点/樱树/灯笼独立 Sprite）
- [x] 建立地点锚点和活动点（6 地点锚点不变 + 铁砧/病床/书桌/鸟居活动点）
- [x] 加入角色 Sprite 和基础动画（`characters.ts` idle/walk 帧, AgentSprite 播 idle/walk）
- [x] 启用像素风渲染设置（config.ts pixelArt/roundPixels, 整数坐标）
- [x] 验证前景遮挡和角色层级（全部 setDepth(round(y)) y-sort, E2E 断言深度=round(y)）

### M3：结构化视觉事件

- [x] 设计并冻结 `schema_version`（=1, `data/schema.ts`）
- [x] 生成 `visual_events`（引擎 `VisualEvent`）
- [x] 生成 move/talk/attack/death/world_event 事件
- [x] 保留旧 `events` 字段兼容（describe() 派生, replay.py 不变）
- [x] 增加 timeline 校验工具（`tools/validate_timeline.ts`）
- [x] 用结构化事件替换中文字符串解析

### M4：气泡和活动

- [x] 实现气泡组件（`dialogue/SpeechBubble.ts`）
- [x] 实现气泡队列和优先级（成功对话才显示, 跳步清旧气泡, 双方错开）
- [x] 分离 NPC 回复和系统提示（气泡正文 vs 金色浮动系统提示）
- [x] 增加活动投影数据（`data/activityProjection.ts` 按角色+地点映射, 标记视觉投影）
- [x] 实现锻造、治疗、阅读、巡逻、坐镇动画（hammer/heal/read 帧 + 巡逻往返 + 坐镇光环）
- [x] 实现活动中断和重新规划视觉表现（attack/flee/help/hide 中断, talk/move/wait 不打断）

### M5：稳定性和扩展

- [ ] 完整回放现有 9/10 天样本
- [ ] 覆盖移动、对话、帮助、攻击、逃跑、死亡和结局
- [ ] 验证旧回放不回归
- [ ] 记录素材许可证和来源
- [ ] 评估实时 API 或 WebSocket 是否必要
- [ ] 决定是否需要 Godot 或继续 Phaser

---

## 11. 第一版完成定义

第一版完成时，用户打开浏览器即可看到：

1. 一张稻妻城俯视像素地图。
2. 旅行者、桃音、刚郎、小梅、执行官、雷电将军在对应地点活动。
3. 时间线按照 Day / 时刻推进。
4. 角色在地点变化时移动，而不是无解释地瞬移。
5. 对话事件显示为对应角色头顶的气泡。
6. 攻击、受伤、死亡和结局有明确动画或视觉提示。
7. 右侧或底部有事件日志和播放控制。
8. 暂停、逐帧和调速不会破坏事件顺序。
9. 不需要 LLM 运行即可回放已有结果。
10. 后端 `world.py` 的自治决策和持久化逻辑不被前端依赖或修改。

---

## 12. 结论

最稳妥的实现不是先把现有世界改造成完整实时游戏，而是沿用 Smallville 的分层思路：

```text
现有 Python Agent 世界
    → 结构化视觉状态
    → Phaser + Tiled 场景
    → Sprite / Tween / 活动动画
    → 对话气泡和回放 UI
```

先完成只读回放器，再增加结构化事件和活动投影，最后才考虑 tile 级实时移动、碰撞、寻路和玩家交互。这样可以尽快验证像素场景的视觉方向，同时保护现有世界的非全知认知、记忆、信任、自治决策和严格事件时序。
