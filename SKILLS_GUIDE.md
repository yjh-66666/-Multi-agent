# Multi Agent 项目 Skills 说明

## 项目框架

- FastAPI：HTTP API 服务
- LangGraph：多 Agent 工作流编排
- Pydantic / pydantic-settings：数据与配置模型
- httpx：外部 API 调用
- Redis（可选）：会话持久化

## Skills 总览（对应 `skills.py`）

1. `SessionSkill`：会话状态管理（内存 + Redis）
2. `Mcp12306HttpClient`：调用 12306 MCP HTTP 工具
3. `TicketSkill`：票务检索与结果解析
4. `MapSkill`：高德 POI（酒店/美食/景点）
5. `AnalyzeSkill`：车次打分排序
6. `LlmSkill`：大模型总结与 fallback
7. `IntentAgent`：意图抽取（LLM 优先，规则兜底）

## Skills 与工作流关系

`workflow.py` 中通过 LangGraph 编排：

- 意图识别 -> 槽位补全 -> 查票 -> 排序 -> POI -> 汇总回复

即：Skill 提供能力，Workflow 负责编排。

## 维护建议

后续新增 Skill 时，建议同步补充：

- 能力边界
- 输入输出
- 环境变量依赖
- 失败兜底策略
- 调用示例
