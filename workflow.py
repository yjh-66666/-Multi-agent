from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from skills import IntentAgent, LlmSkill, SessionState, TrainItem, TripQuery, build_amap_url

logger = logging.getLogger(__name__)


class WorkflowState(TypedDict, total=False):
    message: str
    history: List[Dict[str, str]]
    context: Dict[str, Any]
    intent: Dict[str, Any]
    trip: TripQuery
    trains: List[TrainItem]
    classic_train: Dict[str, Any]
    nearby_hotels: List[Dict[str, Any]]
    nearby_foods: List[Dict[str, Any]]
    nearby_attractions: List[Dict[str, Any]]
    plan: Dict[str, Any]
    assistant_text: str
    need_clarification: bool
    error: str


class EnterpriseTravelWorkflow:
    """企业化多Agent编排：每个节点就是一个职责明确的Agent。"""

    def __init__(self, intent_agent: IntentAgent, llm_skill: LlmSkill, planner: Any) -> None:
        self.intent_agent = intent_agent
        self.llm_skill = llm_skill
        self.planner = planner
        self.graph = self._build_graph()

    def run(self, message: str, session_state: SessionState) -> Dict[str, Any]:
        initial_state: WorkflowState = {
            "message": message,
            "history": session_state.history,
            "context": {
                "origin": session_state.origin,
                "destination": session_state.destination,
                "depart_date": session_state.depart_date,
                "people_count": session_state.people_count,
                "preference": session_state.preference,
            },
        }
        return self.graph.invoke(initial_state)

    def _build_graph(self):
        graph = StateGraph(WorkflowState)

        graph.add_node("intent_agent", self._intent_agent_observed)
        graph.add_node("slot_fill_agent", self._slot_fill_agent_observed)
        graph.add_node("clarify_agent", self._clarify_agent_observed)
        graph.add_node("trip_build_agent", self._trip_build_agent_observed)
        graph.add_node("ticket_agent", self._ticket_agent_observed)
        graph.add_node("ranking_agent", self._ranking_agent_observed)
        graph.add_node("poi_agent", self._poi_agent_observed)
        graph.add_node("plan_assemble_agent", self._plan_assemble_agent_observed)
        graph.add_node("response_agent", self._response_agent_observed)

        graph.set_entry_point("intent_agent")
        graph.add_edge("intent_agent", "slot_fill_agent")
        graph.add_conditional_edges(
            "slot_fill_agent",
            self._route_after_slot_fill,
            {"clarify": "clarify_agent", "go_plan": "trip_build_agent"},
        )
        graph.add_edge("trip_build_agent", "ticket_agent")
        graph.add_edge("ticket_agent", "ranking_agent")
        graph.add_edge("ranking_agent", "poi_agent")
        graph.add_edge("poi_agent", "plan_assemble_agent")
        graph.add_edge("plan_assemble_agent", "response_agent")
        graph.add_edge("response_agent", END)
        graph.add_edge("clarify_agent", END)

        return graph.compile()

    def _observe(self, node_name: str, handler, state: WorkflowState) -> WorkflowState:
        start = time.perf_counter()
        try:
            out = handler(state)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info("agent_node_ok node=%s elapsed_ms=%s", node_name, elapsed_ms)
            return out
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception("agent_node_error node=%s elapsed_ms=%s", node_name, elapsed_ms)
            state["error"] = f"{node_name}_failed:{exc}"
            return state

    def _intent_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("intent_agent", self._intent_agent_node, state)

    def _slot_fill_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("slot_fill_agent", self._slot_fill_agent_node, state)

    def _clarify_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("clarify_agent", self._clarify_agent_node, state)

    def _trip_build_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("trip_build_agent", self._trip_build_agent_node, state)

    def _ticket_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("ticket_agent", self._ticket_agent_node, state)

    def _ranking_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("ranking_agent", self._ranking_agent_node, state)

    def _poi_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("poi_agent", self._poi_agent_node, state)

    def _plan_assemble_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("plan_assemble_agent", self._plan_assemble_agent_node, state)

    def _response_agent_observed(self, state: WorkflowState) -> WorkflowState:
        return self._observe("response_agent", self._response_agent_node, state)

    def _intent_agent_node(self, state: WorkflowState) -> WorkflowState:
        try:
            state["intent"] = self.intent_agent.extract(state["message"])
        except Exception as exc:
            logger.exception("intent_agent failed")
            state["error"] = f"intent_agent_failed:{exc}"
            state["intent"] = {}
        return state

    def _slot_fill_agent_node(self, state: WorkflowState) -> WorkflowState:
        intent = state.get("intent", {})
        context = state.get("context", {})
        message = state.get("message", "")

        origin = intent.get("origin") or context.get("origin")
        destination = intent.get("destination") or context.get("destination")

        if not origin or not destination:
            route = self._parse_route(message) or self._parse_last_two_cities(message)
            origin = origin or route.get("origin")
            destination = destination or route.get("destination")

        depart_date = intent.get("depart_date") or self._parse_depart_date(message) or context.get("depart_date")
        preference = intent.get("preference") or context.get("preference") or "fast"

        people_count = context.get("people_count", 1)
        if intent.get("people_count"):
            try:
                people_count = int(intent.get("people_count"))
            except Exception:
                logger.warning("invalid people_count: %s", intent.get("people_count"))

        state["context"] = {
            "origin": origin,
            "destination": destination,
            "depart_date": depart_date,
            "people_count": people_count,
            "preference": preference,
        }
        state["need_clarification"] = not (origin and destination)
        return state

    @staticmethod
    def _route_after_slot_fill(state: WorkflowState) -> str:
        return "clarify" if state.get("need_clarification") else "go_plan"

    def _trip_build_agent_node(self, state: WorkflowState) -> WorkflowState:
        context = state.get("context", {})
        state["trip"] = TripQuery(
            origin=str(context.get("origin")),
            destination=str(context.get("destination")),
            depart_date=context.get("depart_date"),
            people_count=int(context.get("people_count") or 1),
            preference=str(context.get("preference") or "fast"),
        )
        return state

    def _ticket_agent_node(self, state: WorkflowState) -> WorkflowState:
        trip = state["trip"]
        state["trains"] = self.planner.ticket.search(trip)
        return state

    def _ranking_agent_node(self, state: WorkflowState) -> WorkflowState:
        trip = state["trip"]
        trains = state.get("trains", [])
        for t in trains:
            t.score = self.planner.analyze.score_train(t, trip.preference)
        trains.sort(key=lambda x: x.score, reverse=True)
        state["trains"] = trains
        state["classic_train"] = trains[0].model_dump() if trains else {}
        return state

    def _poi_agent_node(self, state: WorkflowState) -> WorkflowState:
        trip = state["trip"]
        city = trip.destination
        state["nearby_hotels"] = [self._with_link(x.model_dump(), city) for x in self.planner.map.hotels(city)[:3]]
        state["nearby_foods"] = [self._with_link(x.model_dump(), city) for x in self.planner.map.foods(city)[:3]]
        state["nearby_attractions"] = [self._with_link(x.model_dump(), city) for x in self.planner.map.attractions(city)[:3]]
        return state

    def _plan_assemble_agent_node(self, state: WorkflowState) -> WorkflowState:
        trip = state["trip"]
        trains = state.get("trains", [])
        used_date = trip.depart_date or "自动获取当天"
        state["plan"] = {
            "route_summary": f"{trip.origin} -> {trip.destination}（{used_date}）",
            "classic_train": state.get("classic_train") or None,
            "all_trains": [x.model_dump() for x in trains],
            "nearby_hotels": state.get("nearby_hotels", []),
            "nearby_foods": state.get("nearby_foods", []),
            "nearby_attractions": state.get("nearby_attractions", []),
            "analysis": {
                "strategy": "Agent图编排：意图->补槽位->票务->排序->POI->汇总",
                "train_count": len(trains),
            },
            "tips": [
                "本系统支持多轮对话，后续可直接追问。",
                "已为酒店/美食/景点附高德跳转链接。",
                "若配置 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL 将启用大模型总结。",
            ],
        }
        return state

    def _response_agent_node(self, state: WorkflowState) -> WorkflowState:
        state["assistant_text"] = self.llm_skill.summarize(
            state.get("message", ""),
            state.get("plan", {}),
            state.get("history", []),
        )
        return state

    @staticmethod
    def _clarify_agent_node(state: WorkflowState) -> WorkflowState:
        state["assistant_text"] = "请明确出发地和目的地，例如：南京到北京。"
        return state

    @staticmethod
    def _with_link(item: Dict[str, Any], city: str) -> Dict[str, Any]:
        item["amap_url"] = build_amap_url(item.get("name", ""), city)
        return item

    @staticmethod
    def _normalize_date_text(date_text: str) -> Optional[str]:
        date_text = date_text.strip()
        m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", date_text)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{y:04d}-{mo:02d}-{d:02d}"
        m2 = re.search(r"(\d{1,2})月(\d{1,2})日", date_text)
        if m2:
            now = datetime.now()
            mo, d = int(m2.group(1)), int(m2.group(2))
            return f"{now.year:04d}-{mo:02d}-{d:02d}"
        return None

    def _parse_depart_date(self, text: str) -> Optional[str]:
        hit = self._normalize_date_text(text)
        if hit:
            return hit
        if "今天" in text:
            return datetime.now().strftime("%Y-%m-%d")
        if "明天" in text:
            return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        return None

    @staticmethod
    def _clean_place_name(name: str) -> str:
        name = re.sub(r"^(从|由)", "", name)
        name = re.sub(r"(的高铁票|高铁票|高铁|火车票|车票|机票|动车)$", "", name)
        name = name.strip()
        return name.replace("市", "")

    def _parse_route(self, text: str) -> Dict[str, str]:
        text = text.strip()
        m_from = re.search(r"从([\u4e00-\u9fa5]{2,})\s*(?:到|至)\s*([\u4e00-\u9fa5]{2,})", text)
        if m_from:
            return {
                "origin": self._clean_place_name(m_from.group(1)),
                "destination": self._clean_place_name(m_from.group(2)),
            }

        m = re.search(r"([\u4e00-\u9fa5]{2,})\s*(?:到|至)\s*([\u4e00-\u9fa5]{2,})", text)
        if m:
            return {
                "origin": self._clean_place_name(m.group(1)),
                "destination": self._clean_place_name(m.group(2)),
            }
        return {}

    def _parse_last_two_cities(self, text: str) -> Dict[str, str]:
        candidates = [
            x
            for x in re.findall(r"[\u4e00-\u9fa5]{2,5}", text)
            if x not in {"高铁票", "高铁", "车票", "火车票", "今天", "明天"}
        ]
        if len(candidates) >= 2:
            return {
                "origin": self._clean_place_name(candidates[-2]),
                "destination": self._clean_place_name(candidates[-1]),
            }
        return {}
