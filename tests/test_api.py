"""JSON API with bearer tokens."""

from fastapi.testclient import TestClient


def token(c: TestClient, browser, email: str) -> dict[str, str]:
    assert c.post("/api/v1/auth/code", json={"email": email}).status_code == 202
    code = browser.last_code(email)
    r = c.post("/api/v1/auth/token", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_api_flow(app, browser):
    c = TestClient(app)
    assert c.get("/api/v1/me").status_code == 401
    h = token(c, browser, "staff@harbor.example")
    me = c.get("/api/v1/me", headers=h).json()
    assert me["organization"] == "HBU" and me["access_level"] == 2 and me["quota"] == 200

    assert {w["slug"] for w in c.get("/api/v1/workspaces", headers=h).json()} == {"hbu", "sit"}
    kinds = [s["kind"] for s in c.get("/api/v1/workspaces/hbu/services", headers=h).json()]
    assert kinds == ["course-info", "identity-auth", "gpa-record", "thesis"]
    # Across organizations only public services are listed.
    assert [s["kind"] for s in c.get("/api/v1/workspaces/sit/services", headers=h).json()] == [
        "course-info",
        "thesis",
    ]

    r = c.post(
        "/api/v1/workspaces/hbu/services/gpa-record/query",
        headers={**h, "Idempotency-Key": "k1"},
        json={"values": {"name": "Chen Yu", "id": "H2022003"}},
    )
    assert (
        r.status_code == 200
        and r.json()["rows"][0]["gpa"] == 3.67
        and r.json()["quota_left"] == 197
    )

    hits = c.post(
        "/api/v1/workspaces/sit/thesis/search", headers=h, json={"keywords": "dashboards"}
    ).json()
    assert hits[0]["downloadable"] and hits[0]["price"] == 8
    pdf = c.post(
        "/api/v1/workspaces/sit/thesis/download", headers=h, json={"title": hits[0]["title"]}
    )
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    courses = c.get("/api/v1/workspaces/sit/courses?q=distributed", headers=h).json()
    assert [x["code"] for x in courses] == ["CS340"]


def test_api_errors(app, browser):
    c = TestClient(app)
    h = token(c, browser, "student@harbor.example")
    r = c.post("/api/v1/workspaces/hbu/services/gpa-record/query", headers=h, json={"values": {}})
    assert r.status_code == 403
    assert c.get("/api/v1/audit/verify", headers=h).status_code == 403
    assert c.get("/api/v1/workspaces/nope/courses", headers=h).status_code == 404
    assert c.get("/api/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert c.post("/api/v1/auth/code", json={"email": "who@nowhere.example"}).status_code == 403


def test_api_audit_for_t_admin(app, browser):
    c = TestClient(app)
    h = token(c, browser, "tadmin@edba.example")
    r = c.get("/api/v1/audit/verify", headers=h).json()
    assert r["ok"] and r["checked"] > 10
    events = c.get("/api/v1/audit/events?action=auth.login", headers=h).json()
    assert events[0]["actor"] == "tadmin@edba.example"


def test_openapi_lists_endpoints(app):
    spec = TestClient(app).get("/api/openapi.json").json()
    assert "/api/v1/workspaces/{slug}/thesis/download" in spec["paths"]
    assert not any(
        p.startswith("/org") for p in spec["paths"]
    )  # UI routes stay out of the API schema
