"""Demo campus + bank gateway (same contract as the v3 lab server, under new paths)."""

from __future__ import annotations

import copy
import threading
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from edba.gateway import data
from edba.gateway.pdf import render_pdf

_lock = threading.Lock()
_accounts = copy.deepcopy(data.ACCOUNTS)
_transfers: dict[str, dict[str, Any]] = {}


def reset() -> None:
    global _accounts
    with _lock:
        _accounts = copy.deepcopy(data.ACCOUNTS)
        _transfers.clear()


def _campus(code: str) -> str:
    if code not in data.STUDENTS:
        raise HTTPException(404, f"unknown campus {code}")
    return code


def _find(bank: str, name: str, number: str) -> dict[str, Any] | None:
    for a in _accounts:
        if a["bank"] == bank and a["name"] == name and a["number"] == number:
            return a
    return None


app = FastAPI(
    title="E-DBA demo gateway", version="1.0", docs_url="/docs", openapi_url="/openapi.json"
)


async def _payload(request: Request) -> dict[str, Any]:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        body = await request.json()
        return body if isinstance(body, dict) else {}
    form = await request.form()
    return {k: v for k, v in form.items()}


@app.post("/campus/{code}/student/record")
async def student_record(code: str, request: Request) -> JSONResponse:
    body = await _payload(request)
    for s in data.STUDENTS[_campus(code)]:
        if (
            s["id"] == str(body.get("id", "")).strip()
            and str(s["name"]).lower() == str(body.get("name", "")).strip().lower()
        ):
            return JSONResponse(
                {k: s[k] for k in ("name", "enroll_year", "graduation_year", "gpa")}
            )
    return JSONResponse({"error": "no such student"}, status_code=404)


@app.post("/campus/{code}/student/authenticate")
async def student_authenticate(code: str, request: Request) -> dict[str, str]:
    body = await _payload(request)
    sid, name = str(body.get("id", "")).strip(), str(body.get("name", "")).strip().lower()
    photo = body.get("photo")
    ok = any(
        s["id"] == sid and str(s["name"]).lower() == name for s in data.STUDENTS[_campus(code)]
    )
    if ok and isinstance(photo, UploadFile):
        await photo.read()  # a real registry would run face matching here
    return {"status": "verified" if ok else "not verified"}


@app.post("/campus/{code}/thesis/search")
async def thesis_search(code: str, request: Request) -> list[dict[str, str]]:
    body = await _payload(request)
    words = [w for w in str(body.get("keywords", "")).lower().split() if w]
    hits = []
    for t in data.THESES[_campus(code)]:
        hay = (t["title"] + " " + t["abstract"]).lower()
        if words and all(w in hay for w in words):
            hits.append(t)
    return hits


@app.get("/campus/{code}/thesis/pdf")
def thesis_pdf(code: str, title: str) -> Response:
    for t in data.THESES[_campus(code)]:
        if t["title"].lower() == title.strip().lower():
            pdf = render_pdf(
                t["title"],
                [
                    f"{t['author']} · {t['year']}",
                    "",
                    t["abstract"],
                    "",
                    f"Served by the {code} campus repository via E-DBA.",
                ],
            )
            return Response(pdf, media_type="application/pdf")
    raise HTTPException(404, "no such thesis")


@app.post("/bank/authenticate")
def bank_authenticate(body: dict[str, str]) -> dict[str, str]:
    a = _find(body.get("bank", ""), body.get("account_name", ""), body.get("account_number", ""))
    ok = a is not None and a["password"] == body.get("password")
    return {"status": "success" if ok else "failure"}


@app.post("/bank/transfer")
def bank_transfer(
    body: dict[str, Any], idempotency_key: str | None = Header(None)
) -> dict[str, Any]:
    with _lock:
        if idempotency_key and idempotency_key in _transfers:
            return _transfers[idempotency_key]
        src = _find(
            body.get("from_bank", ""), body.get("from_name", ""), body.get("from_account", "")
        )
        dst = _find(body.get("to_bank", ""), body.get("to_name", ""), body.get("to_account", ""))
        amount = float(body.get("amount", 0))
        result: dict[str, Any]
        if src is None or src["password"] != body.get("password"):
            result = {"status": "failure", "reason": "invalid payer credentials"}
        elif dst is None:
            result = {"status": "failure", "reason": "unknown payee account"}
        elif amount <= 0:
            result = {"status": "failure", "reason": "amount must be positive"}
        elif src["balance"] < amount:
            result = {"status": "failure", "reason": "insufficient funds"}
        else:
            src["balance"] -= amount
            dst["balance"] += amount
            result = {"status": "success"}
        if idempotency_key:
            _transfers[idempotency_key] = result
        return result


@app.get("/bank/balances")
def balances() -> list[dict[str, Any]]:
    """Demo-only view of the simulated bank, so settlement can be observed."""
    return [{k: a[k] for k in ("bank", "name", "number", "balance")} for a in _accounts]
