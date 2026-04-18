from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from schemas import ApiResponse
from settings import settings
from skills import (
    AnalyzeSkill,
    IntentAgent,
    LlmSkill,
    MapSkill,
    Mcp12306HttpClient,
    SessionSkill,
    TicketSkill,
    TripQuery,
    build_amap_url,
)
from workflow import EnterpriseTravelWorkflow

logger = logging.getLogger("travel_app")
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] [rid=%(request_id)s] %(message)s",
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


for handler in logging.getLogger().handlers:
    handler.addFilter(RequestIdFilter())


class ChatQuery(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(description="例如：帮我查南京到长沙的高铁")
    depart_date: Optional[str] = None
    people_count: Optional[int] = None
    preference: Optional[str] = None


class TravelOrchestrator:
    def __init__(self, ticket_mcp: Optional[Any] = None) -> None:
        self.ticket = TicketSkill(mcp_client=ticket_mcp)
        self.map = MapSkill()
        self.analyze = AnalyzeSkill()

    def plan(self, q: TripQuery) -> Dict[str, Any]:
        all_trains = self.ticket.search(q)
        for t in all_trains:
            t.score = self.analyze.score_train(t, q.preference)
        all_trains.sort(key=lambda x: x.score, reverse=True)
        classic_train = all_trains[0] if all_trains else None

        city = q.destination
        hotels = [self._with_link(x.model_dump(), city) for x in self.map.hotels(city)[:3]]
        foods = [self._with_link(x.model_dump(), city) for x in self.map.foods(city)[:3]]
        attractions = [self._with_link(x.model_dump(), city) for x in self.map.attractions(city)[:3]]

        used_date = q.depart_date or "自动获取当天"
        return {
            "route_summary": f"{q.origin} -> {q.destination}（{used_date}）",
            "classic_train": classic_train.model_dump() if classic_train else None,
            "all_trains": [x.model_dump() for x in all_trains],
            "nearby_hotels": hotels,
            "nearby_foods": foods,
            "nearby_attractions": attractions,
            "analysis": {
                "strategy": "Agent图编排：意图->补槽位->票务->排序->POI->汇总",
                "train_count": len(all_trains),
            },
            "tips": [
                "本系统支持多轮对话，后续可直接追问。",
                "已为酒店/美食/景点附高德跳转链接。",
                "若配置 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL 将启用大模型总结。",
            ],
        }

    @staticmethod
    def _with_link(item: Dict[str, Any], city: str) -> Dict[str, Any]:
        item["amap_url"] = build_amap_url(item.get("name", ""), city)
        return item


def _ok(request_id: str, data: Any, message: str = "success") -> Dict[str, Any]:
    return ApiResponse(success=True, code="ok", message=message, request_id=request_id, data=data).model_dump()


def _error(code: str, message: str, request_id: str, details: Optional[str] = None, status_code: int = 500) -> JSONResponse:
    payload = ApiResponse(success=False, code=code, message=message, request_id=request_id, data={"details": details}).model_dump()
    return JSONResponse(status_code=status_code, content=payload)


load_dotenv()

app = FastAPI(title=settings.app_name, version=settings.app_version)
session_skill = SessionSkill()
llm_skill = LlmSkill()
intent_agent = IntentAgent(llm_skill)
mcp_12306 = Mcp12306HttpClient(base_url=settings.mcp_12306_http_url or None)
orc = TravelOrchestrator(ticket_mcp=mcp_12306 if mcp_12306.enabled() else None)
workflow = EnterpriseTravelWorkflow(intent_agent=intent_agent, llm_skill=llm_skill, planner=orc)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.time()

    if settings.api_key_enabled and request.url.path not in {"/", "/health", "/static"}:
        provided = request.headers.get("X-API-Key", "")
        if provided != settings.api_key_value:
            return _error("unauthorized", "API Key 无效", request_id, status_code=401)

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        elapsed_ms = round((time.time() - start) * 1000, 2)
        logger.info(
            "request success method=%s path=%s status=%s elapsed_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            extra={"request_id": request_id},
        )
        return response
    except Exception as exc:
        logger.exception("request failed", extra={"request_id": request_id})
        return _error("internal_error", "服务内部错误", request_id, details=str(exc), status_code=500)


base_dir = Path(__file__).resolve().parent
static_dir = base_dir / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(static_dir / "index.html"))


@app.get("/health")
def health(request: Request) -> Dict[str, Any]:
    data = {
        "ok": True,
        "env": settings.app_env,
        "llm_enabled": llm_skill.enabled(),
        "mcp_ticket_enabled": orc.ticket.mcp_client is not None,
        "mcp_ticket_ping": mcp_12306.health_ping() if mcp_12306.enabled() else False,
        "amap_api_enabled": orc.map.enabled(),
        "workflow_engine": "langgraph",
    }
    return _ok(request.state.request_id, data)


@app.post("/plan_trip")
def plan_trip(query: TripQuery, request: Request) -> Dict[str, Any]:
    try:
        result = orc.plan(query)
        result["assistant_text"] = llm_skill.summarize("请规划行程", result, [])
        return _ok(request.state.request_id, result)
    except Exception as exc:
        logger.exception("plan_trip failed", extra={"request_id": request.state.request_id})
        raise HTTPException(status_code=500, detail=f"plan_trip_failed: {exc}") from exc


@app.post("/chat_plan")
def chat_plan(query: ChatQuery, request: Request) -> Dict[str, Any]:
    session_id, state = session_skill.get_or_create(query.session_id)
    state.history.append({"role": "user", "content": query.message})

    if query.depart_date:
        state.depart_date = query.depart_date
    if query.preference:
        state.preference = query.preference
    if query.people_count:
        state.people_count = query.people_count

    try:
        final_state = workflow.run(message=query.message, session_state=state)
        context = final_state.get("context", {})

        state.origin = context.get("origin")
        state.destination = context.get("destination")
        state.depart_date = context.get("depart_date")
        state.preference = context.get("preference") or state.preference
        state.people_count = int(context.get("people_count") or state.people_count or 1)
        session_skill.save(session_id, state)

        assistant_text = final_state.get("assistant_text", "系统繁忙，请稍后再试。")
        state.history.append({"role": "assistant", "content": assistant_text})

        if final_state.get("need_clarification"):
            payload = {
                "assistant_text": assistant_text,
                "session_id": session_id,
                "context": {
                    "origin": state.origin,
                    "destination": state.destination,
                    "depart_date": state.depart_date,
                    "people_count": state.people_count,
                    "preference": state.preference,
                },
            }
            session_skill.save(session_id, state)
            return _ok(request.state.request_id, payload, message="need_clarification")

        plan = final_state.get("plan", {})
        if not isinstance(plan, dict):
            plan = {}

        plan["assistant_text"] = assistant_text
        plan["session_id"] = session_id
        plan["context"] = {
            "origin": state.origin,
            "destination": state.destination,
            "depart_date": state.depart_date,
            "people_count": state.people_count,
            "preference": state.preference,
        }
        session_skill.save(session_id, state)
        return _ok(request.state.request_id, plan)
    except Exception as exc:
        logger.exception("chat_plan failed", extra={"request_id": request.state.request_id})
        raise HTTPException(status_code=500, detail=f"chat_plan_failed: {exc}") from exc
