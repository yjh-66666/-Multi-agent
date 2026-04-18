# Multi Agent Travel Planner

基于 `FastAPI` + `LangGraph` 构建的多智能体出行规划项目，聚焦“自然语言提问 -> 意图识别 -> 票务查询 -> 周边推荐 -> 结果汇总”的完整链路。

## 项目定位

这个子项目演示了一个面向真实业务场景的多 Agent 工作流设计：

- 使用 `IntentAgent` 识别用户意图与槽位信息
- 使用 `SessionSkill` 维护多轮对话上下文
- 使用 `TicketSkill` 对接 12306 票务能力
- 使用 `MapSkill` 检索酒店、美食、景点等 POI
- 使用 `AnalyzeSkill` 对票务结果进行打分排序
- 使用 `LlmSkill` 对结果进行总结与自然语言输出
- 使用 `LangGraph` 将多个节点编排成可控工作流

## 核心能力

- 多轮会话与上下文记忆
- 票务查询与结果解析
- 车次排序与偏好适配
- 目的地周边推荐
- LLM 总结输出与降级兜底
- 可选 Redis 持久化
- 可选 12306 MCP HTTP 接入
- 可选高德地图 API 接入

## 技术栈

- `FastAPI`
- `LangGraph`
- `Pydantic`
- `HTTPX`
- `Redis`（可选）
- `python-dotenv`

## 目录说明

- `main.py`：FastAPI 服务入口与接口装配
- `workflow.py`：多 Agent 工作流编排
- `skills.py`：能力层封装（票务、地图、会话、LLM、分析）
- `schemas.py`：请求与响应模型
- `settings.py`：环境变量配置
- `static/`：前端展示页面
- `tests_api.py`：接口测试示例
- `SKILLS_GUIDE.md`：skills 设计说明

## 工作流概览

```text
用户输入
  -> 意图识别
  -> 槽位补全
  -> 信息澄清（如有必要）
  -> 构建出行对象
  -> 查询票务
  -> 车次排序
  -> POI 推荐
  -> 结果汇总
  -> LLM 生成最终回复
```

## 环境变量

可以通过 `.env` 配置以下变量：

- `LLM_BASE_URL`：大模型服务地址
- `LLM_API_KEY`：大模型 API Key
- `LLM_MODEL`：模型名称，默认 `deepseek-chat`
- `MCP_12306_HTTP_URL`：12306 MCP HTTP 服务地址
- `AMAP_MAPS_API_KEY`：高德地图 API Key
- `AMAP_KEY`：高德地图 API Key 兼容项
- `REDIS_URL`：Redis 连接地址
- `REDIS_PREFIX`：Redis 会话前缀
- `API_KEY_ENABLED`：是否启用 API Key 校验
- `API_KEY_VALUE`：API Key 值

## 本地运行

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 配置环境变量

复制 `.env.example` 为 `.env`，并填写必要配置。

3. 启动服务

```bash
uvicorn main:app --reload --port 8000
```

4. 打开浏览器访问

```text
http://127.0.0.1:8000/
```

## 常用接口

### 健康检查

```http
GET /health
```

### 单次行程规划

```http
POST /plan_trip
```

请求示例：

```json
{
  "origin": "南京",
  "destination": "北京",
  "depart_date": "2025-08-20",
  "people_count": 1,
  "preference": "fast"
}
```

### 多轮对话规划

```http
POST /chat_plan
```

请求示例：

```json
{
  "session_id": null,
  "message": "帮我查南京到北京明天的高铁，并推荐附近酒店",
  "depart_date": null,
  "people_count": null,
  "preference": null
}
```

## 设计亮点

- **职责分离**：agent 负责决策，skill 负责执行，workflow 负责编排
- **可控流程**：使用 `LangGraph` 显式定义节点与流转路径
- **可降级**：MCP / LLM / 高德不可用时有兜底逻辑
- **可扩展**：后续可以很容易新增新的 skill 或 agent 节点

## 面试介绍建议

如果用于面试，可以重点强调以下几点：

1. 你如何将复杂出行任务拆解为多个职责节点
2. 你如何用 `LangGraph` 实现工作流编排
3. 你如何将 MCP、LLM、高德地图与业务系统集成
4. 你如何设计多轮对话与会话持久化
5. 你如何做降级与容错，保证可演示性和稳定性

## 备注

如果需要，你还可以继续补充：

- 架构图
- 时序图
- 接口返回示例
- 部署说明
