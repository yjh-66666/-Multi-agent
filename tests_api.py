from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_health_envelope():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["code"] == "ok"
    assert "data" in body
    assert body["data"]["workflow_engine"] == "langgraph"


def test_chat_plan_clarification():
    payload = {"message": "帮我查高铁"}
    resp = client.post("/chat_plan", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] in {"success", "need_clarification"}
    assert "data" in body


def test_chat_plan_full_flow():
    payload = {"message": "南京到长沙明天高铁", "preference": "fast"}
    resp = client.post("/chat_plan", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "assistant_text" in data
    assert "session_id" in data
