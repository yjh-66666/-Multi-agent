"""multi agent 项目的 Skills 层。

该文件聚合了：
1. 会话管理（SessionSkill，支持内存 + Redis）
2. 12306 MCP HTTP 调用（Mcp12306HttpClient）
3. 票务查询（TicketSkill）
4. POI 检索（MapSkill）
5. 规则打分（AnalyzeSkill）
6. 大模型封装（LlmSkill）
7. 意图抽取（IntentAgent）

详细说明请参考同目录 `SKILLS_GUIDE.md`。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from settings import settings

try:
    import redis  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    redis = None


class TripQuery(BaseModel):
    origin: str
    destination: str
    depart_date: Optional[str] = None
    people_count: int = 1
    preference: str = "fast"


class TrainItem(BaseModel):
    train_code: str
    from_station: str = ""
    to_station: str = ""
    start_time: str
    arrive_time: str
    duration: str
    price: str = "-"
    second_class: str = "-"
    first_class: str = "-"
    score: float = 0.0


class PoiItem(BaseModel):
    name: str
    address: str = ""
    category: str = ""
    amap_url: str = ""


class SessionState(BaseModel):
    origin: Optional[str] = None
    destination: Optional[str] = None
    depart_date: Optional[str] = None
    people_count: int = 1
    preference: str = "fast"
    history: List[Dict[str, str]] = Field(default_factory=list)


class SessionSkill:
    def __init__(self) -> None:
        self._store: Dict[str, SessionState] = {}
        self.redis_url = settings.redis_url
        self.redis_prefix = settings.redis_prefix
        self._redis_client = self._build_redis_client()

    def _build_redis_client(self) -> Optional[Any]:
        if not self.redis_url or redis is None:
            return None
        try:
            return redis.from_url(self.redis_url, decode_responses=True)
        except Exception:
            return None

    def _redis_enabled(self) -> bool:
        return self._redis_client is not None

    def _redis_key(self, sid: str) -> str:
        return f"{self.redis_prefix}{sid}"

    def _redis_get(self, sid: str) -> Optional[SessionState]:
        if not self._redis_enabled():
            return None
        try:
            raw = self._redis_client.get(self._redis_key(sid))
            if isinstance(raw, str) and raw:
                return SessionState.model_validate_json(raw)
        except Exception:
            return None
        return None

    def _redis_set(self, sid: str, state: SessionState) -> None:
        if not self._redis_enabled():
            return
        try:
            self._redis_client.set(self._redis_key(sid), state.model_dump_json())
        except Exception:
            return

    def save(self, session_id: str, state: SessionState) -> None:
        self._store[session_id] = state
        self._redis_set(session_id, state)

    def get_or_create(self, session_id: Optional[str]) -> Tuple[str, SessionState]:
        sid = session_id or f"session-{uuid.uuid4().hex[:10]}"

        if sid in self._store:
            return sid, self._store[sid]

        remote_state = self._redis_get(sid)
        if remote_state is not None:
            self._store[sid] = remote_state
            return sid, remote_state

        state = SessionState()
        self._store[sid] = state
        self._redis_set(sid, state)
        return sid, state


class Mcp12306HttpClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or os.getenv("MCP_12306_HTTP_URL", "")).rstrip("/")

    def enabled(self) -> bool:
        return bool(self.base_url)

    def _call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled():
            return {}
        payload = {"tool": tool_name, "name": tool_name, "arguments": arguments, "input": arguments}
        for url in (self.base_url, f"{self.base_url}/call"):
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(url, json=payload)
                    if resp.status_code < 400:
                        data = resp.json()
                        if isinstance(data, dict):
                            return data
            except Exception:
                continue
        return {}

    def query_tickets(self, from_station: str, to_station: str, date: Optional[str] = None) -> Dict[str, Any]:
        if not date:
            date = self.get_current_date()
        return self._call("query_tickets", {"from_station": from_station, "to_station": to_station, "date": date})

    def get_current_date(self) -> str:
        # 优先通过 MCP 时间工具获取“当前日期”
        data = self._call("get_current_time", {})
        if isinstance(data, dict):
            # 兼容多种返回结构
            for key in ("date", "current_date", "today", "now_date"):
                val = data.get(key)
                if isinstance(val, str) and len(val) >= 10:
                    return val[:10]
            if isinstance(data.get("content"), list):
                for c in data["content"]:
                    if isinstance(c, dict):
                        txt = c.get("text") or ""
                        if isinstance(txt, str):
                            import re
                            m = re.search(r"(\d{4}-\d{2}-\d{2})", txt)
                            if m:
                                return m.group(1)
        return datetime.now().strftime("%Y-%m-%d")

    def health_ping(self) -> bool:
        if not self.enabled():
            return False
        health_url = self.base_url.replace("/mcp", "/health") if self.base_url.endswith("/mcp") else f"{self.base_url}/health"
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.get(health_url)
                return resp.status_code < 400
        except Exception:
            return False


class TicketSkill:
    def __init__(self, mcp_client: Optional[Any] = None) -> None:
        self.mcp_client = mcp_client

    def search(self, q: TripQuery) -> List[TrainItem]:
        if self.mcp_client is not None:
            try:
                raw = self.mcp_client.query_tickets(from_station=q.origin, to_station=q.destination, date=q.depart_date)
                parsed = self._parse_ticket_response(raw)
                if parsed:
                    return parsed
            except Exception:
                pass

        return [
            TrainItem(train_code="G1549", from_station=f"{q.origin}", to_station=f"{q.destination}", start_time="07:21", arrive_time="13:29", duration="06:08", price="553", second_class="有", first_class="12"),
            TrainItem(train_code="G1779", from_station=f"{q.origin}", to_station=f"{q.destination}", start_time="09:02", arrive_time="15:26", duration="06:24", price="545", second_class="5", first_class="有"),
            TrainItem(train_code="G1481", from_station=f"{q.origin}", to_station=f"{q.destination}", start_time="13:10", arrive_time="19:48", duration="06:38", price="531", second_class="有", first_class="有"),
        ]

    def _parse_ticket_response(self, raw: Dict[str, Any]) -> List[TrainItem]:
        rows: List[Dict[str, Any]] = []
        if not isinstance(raw, dict):
            return []

        candidate_keys = ("data", "items", "result", "rows")
        for key in candidate_keys:
            value = raw.get(key)
            if isinstance(value, list):
                rows = value
                break

        if not rows and isinstance(raw.get("content"), list):
            for content_item in raw["content"]:
                if isinstance(content_item, dict) and isinstance(content_item.get("json"), dict):
                    json_payload = content_item["json"]
                    for key in candidate_keys:
                        value = json_payload.get(key)
                        if isinstance(value, list):
                            rows = value
                            break
                    if rows:
                        break

        out: List[TrainItem] = []
        for row in rows[:25]:
            if not isinstance(row, dict):
                continue
            out.append(
                TrainItem(
                    train_code=row.get("trainCode") or row.get("train_code") or row.get("code", ""),
                    from_station=row.get("fromStationName") or row.get("from_station") or "",
                    to_station=row.get("toStationName") or row.get("to_station") or "",
                    start_time=row.get("startTime") or row.get("start_time") or row.get("depart_time", ""),
                    arrive_time=row.get("arriveTime") or row.get("arrive_time") or row.get("arrival_time", ""),
                    duration=row.get("duration") or row.get("cost_time") or "",
                    price=str(row.get("price") or row.get("secondClassPrice") or row.get("ze_price") or "-"),
                    second_class=row.get("secondClassSeat") or row.get("second_class") or row.get("ze_num", "-"),
                    first_class=row.get("firstClassSeat") or row.get("first_class") or row.get("zy_num", "-"),
                )
            )
        return [x for x in out if x.train_code]


class MapSkill:
    """方案A：直接调用高德 Web API。"""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("AMAP_MAPS_API_KEY") or os.getenv("AMAP_KEY", "")

    def enabled(self) -> bool:
        return bool(self.api_key)

    def hotels(self, city: str) -> List[PoiItem]:
        return self._search(city, "酒店", "hotel")

    def foods(self, city: str) -> List[PoiItem]:
        return self._search(city, "美食", "food")

    def attractions(self, city: str) -> List[PoiItem]:
        return self._search(city, "景点", "attraction")

    def _search(self, city: str, keyword: str, category: str) -> List[PoiItem]:
        if self.enabled():
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(
                        "https://restapi.amap.com/v3/place/text",
                        params={
                            "key": self.api_key,
                            "city": city,
                            "keywords": keyword,
                            "offset": 6,
                            "page": 1,
                            "extensions": "base",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    pois = data.get("pois", []) if isinstance(data, dict) else []
                    out = [
                        PoiItem(
                            name=p.get("name", ""),
                            address=p.get("address", ""),
                            category=category,
                        )
                        for p in pois[:6]
                        if p.get("name")
                    ]
                    if out:
                        return out
            except Exception:
                pass

        mock = {
            "hotel": [
                PoiItem(name=f"{city}高铁南站美居酒店", address=f"{city}雨花区", category="hotel"),
                PoiItem(name=f"{city}IFS商圈轻奢酒店", address=f"{city}芙蓉区", category="hotel"),
            ],
            "food": [
                PoiItem(name=f"{city}本地口碑湘菜馆", address=f"{city}开福区", category="food"),
                PoiItem(name=f"{city}人气小龙虾", address=f"{city}天心区", category="food"),
            ],
            "attraction": [
                PoiItem(name=f"{city}橘子洲", address=f"{city}岳麓区", category="attraction"),
                PoiItem(name=f"{city}岳麓山", address=f"{city}岳麓区", category="attraction"),
            ],
        }
        return mock[category]


class AnalyzeSkill:
    @staticmethod
    def score_train(item: TrainItem, preference: str) -> float:
        h, m = item.duration.split(":") if ":" in item.duration else ("6", "0")
        minutes = int(h) * 60 + int(m)
        score = 100 - minutes * 0.08
        if preference == "cheap" and item.second_class not in ("-", "无"):
            score += 8
        if preference == "comfy" and item.first_class not in ("-", "无"):
            score += 6
        if item.second_class == "有" or item.first_class == "有":
            score += 4
        return round(score, 2)


class LlmSkill:
    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "deepseek-chat")

    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key)

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.3) -> Optional[str]:
        if not self.enabled():
            return None
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            return None

    def summarize(self, user_message: str, plan: Dict[str, Any], history: List[Dict[str, str]]) -> str:
        content = self.chat([
            {"role": "system", "content": "按经典班次->全部班次->周边推荐顺序输出中文简洁答复。"},
            {"role": "user", "content": f"消息:{user_message}\n历史:{history[-4:]}\n数据:{plan}"},
        ], temperature=0.3)
        if content:
            return content
        return self._fallback(user_message, plan)

    @staticmethod
    def _fallback(user_message: str, plan: Dict[str, Any]) -> str:
        c = plan.get("classic_train") or {}
        return (
            f"已根据你的需求“{user_message}”完成规划。\n"
            f"经典班次：{c.get('train_code', '暂无')} {c.get('start_time', '')}-{c.get('arrive_time', '')}，历时{c.get('duration', '-')}。\n"
            "下方已附全部班次与周边酒店/美食/景点。"
        )


class IntentAgent:
    """意图识别 Agent：LLM 优先，规则兜底。"""

    def __init__(self, llm: LlmSkill) -> None:
        self.llm = llm

    def extract(self, message: str) -> Dict[str, Any]:
        by_llm = self._extract_by_llm(message)
        if by_llm:
            return by_llm
        return self._extract_by_rules(message)

    def _extract_by_llm(self, message: str) -> Optional[Dict[str, Any]]:
        if not self.llm.enabled():
            return None
        prompt = (
            "请从用户句子中提取出行意图，严格输出JSON，不要任何解释。"
            "字段: origin,destination,depart_date,preference,people_count,intent。"
            "depart_date输出yyyy-MM-dd或null。"
            "intent固定为query_ticket或query_trip。"
        )
        content = self.llm.chat([
            {"role": "system", "content": prompt},
            {"role": "user", "content": message},
        ], temperature=0)
        if not content:
            return None
        try:
            clean = content.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(clean)
            if isinstance(data, dict):
                return {
                    "origin": data.get("origin"),
                    "destination": data.get("destination"),
                    "depart_date": data.get("depart_date"),
                    "preference": data.get("preference"),
                    "people_count": data.get("people_count"),
                    "intent": data.get("intent") or "query_ticket",
                }
        except Exception:
            return None
        return None

    def _extract_by_rules(self, message: str) -> Dict[str, Any]:
        route = self._rule_route(message)
        depart_date = self._rule_date(message)
        preference = "cheap" if "便宜" in message or "省钱" in message else ("comfy" if "舒适" in message else "fast")
        return {
            "origin": route.get("origin"),
            "destination": route.get("destination"),
            "depart_date": depart_date,
            "preference": preference,
            "people_count": 1,
            "intent": "query_ticket",
        }

    @staticmethod
    def _rule_route(text: str) -> Dict[str, str]:
        m = re.search(r"从([\u4e00-\u9fa5]{2,})\s*(?:到|至)\s*([\u4e00-\u9fa5]{2,})", text)
        if m:
            return {"origin": m.group(1).replace("市", ""), "destination": re.sub(r"(高铁票|高铁|车票|火车票)$", "", m.group(2)).replace("市", "")}
        m2 = re.search(r"([\u4e00-\u9fa5]{2,})\s*(?:到|至)\s*([\u4e00-\u9fa5]{2,})", text)
        if m2:
            return {"origin": m2.group(1).replace("市", ""), "destination": re.sub(r"(高铁票|高铁|车票|火车票)$", "", m2.group(2)).replace("市", "")}
        return {}

    @staticmethod
    def _rule_date(text: str) -> Optional[str]:
        m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{y:04d}-{mo:02d}-{d:02d}"
        m2 = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
        if m2:
            now = datetime.now()
            mo, d = int(m2.group(1)), int(m2.group(2))
            return f"{now.year:04d}-{mo:02d}-{d:02d}"
        if "今天" in text:
            return datetime.now().strftime("%Y-%m-%d")
        return None


def build_amap_url(name: str, city: str) -> str:
    return f"https://uri.amap.com/search?keyword={quote(f'{city}{name}')}&city={quote(city)}"
