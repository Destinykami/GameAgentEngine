# 模型接入与输出解析

状态：已实现并通过离线验证。核对日期：2026-10-23。

2026-10-25 用户确认 [分层记忆](tiered-memory.md) 的对话生成调整：无历史命中仍可正常回答，提示词区分近期背景与主动提及历史。这覆盖下文 complete 空记忆零请求及提示词原文不变的历史规则，其余模型接入契约保持。

## 目标与边界

保留 LLMClient、LLMContext、Embedder、HashEmbedder、RealLLM、RealEmbedder、make_embedder 的正式入口与调用行为。模型适配只负责请求、提示词和输出解释，不访问 NPC、World、记忆库或实验目录。认知组件继续通过已有窄端口调用模型。

将 llm_http.py 拆成 llm_http/ 子包：client.py 组装客户端与公共方法；transport.py 管聊天请求重试和每次尝试统计；parsing.py 管 JSON 提取、整点、计划块和整数解析；dialogue.py、memory.py、planning.py、actions.py 按任务组织原提示词与结果转换；usage.py 管增量统计；__init__.py 按需导出正式类及既有默认常量。保留正在使用的 _chat / _chat_json 请求覆写点，不建立旧解析函数或连接私有字段代理。

models/config.py 集中原 LLM/embedding 默认值和每实例 EndpointConfig。models/transport.py 只负责标准库 POST JSON 编解码及 Authorization；重试仍由各适配器决定。RealEmbedder 保留单独的向量排序、归一化、懒维度与回退工厂，避免把向量响应或重试规则与聊天混成一种协议。

## 保持的规则

- 默认地址、模型名、超时、重试次数、温度、token 上限、thinking 与提示词原文均不变；不增加环境变量、命令行优先级、校验或自动探测。
- 各客户端持有独立配置。RealLLM.stats 保留原可变字典、计数与 reset_stats 换新字典行为，API key 不进入诊断或日志。
- 聊天每次尝试按原位置计数，失败也计数；响应缺 choices 的尝试保留原可能先记成功 usage、再记失败的行为；不在重构中修正计数口径。退避仍依次 1s/2s，最终异常文字与捕获范围不变。
- JSON 首次解析失败最多追加一次原修复提示，重试温度 0；传输重试与 JSON 重试各自保持原层次。动作解析失败仍回退 wait，其余任务保持各自异常传播规则。
- complete 无记忆直接返回原文本，零请求；仅 complete 使用构造时 thinking 开关，其余任务原参数不变。
- embedding 仍把输入物化一次、批量发送、按 index 排序并归一化；首次非空响应发现维度，空输入仍请求；捕获异常、退避、零向量处理与 make_embedder 回退行为保持原样。
- 不改变哈希向量、SQLite、记忆重要性权重、认知流程或实验指标。

## 实施与验收

先保存旧适配器，再提取配置、传输、解析与任务函数，迁移导入。用离线 HTTP 替身检查请求体/headers/timeout、退避与统计、坏响应、JSON 修复、embedding 排序/归一化/维度及回退。对照旧客户端各任务的输入提示词、调用参数和结果；复用离线全集、独立导入与安装检查。真实端点、连通性探针和在线评测不运行。

未决项：无。新增模型选择或配置覆盖机制属于功能变更，本轮不纳入。

## 验证记录

372 个离线测试通过（8.65s），包括 10 个 HTTP/重试/向量行为用例及 8 个新增导入隔离用例。504 个任务提示词、参数、结果检查点和 13 个 HTTP、退避、统计、向量检查点与原适配器一致。12 类任务核心在归一请求/解析引用并忽略文档缩进后 AST 一致。没有访问真实模型端点。

仓库外编辑安装导入和独立 wheel 的公开入口、默认值按需加载、离线聊天及 embedding 检查通过；打包产物含全部 9 个聊天子包文件，不含旧 llm_http.py 或 persona_agent。git diff --check 通过。
