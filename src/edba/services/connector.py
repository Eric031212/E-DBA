"""Outbound calls to organizations' own systems and to the bank gateway.

Requests are built from an ``ApiEndpoint``'s flat input schema; ``file`` fields
are sent as multipart, everything else as JSON (POST) or query string (GET).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from edba.config import Settings
from edba.errors import DomainError, UpstreamError
from edba.models import ApiEndpoint

FIELD_TYPES = {"string", "int", "float", "bool", "file"}

_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Route all outbound HTTP through ``transport`` (tests, in-process demo gateway)."""
    global _transport
    _transport = transport


def client(settings: Settings) -> httpx.Client:
    return httpx.Client(timeout=settings.connector_timeout_seconds, transport=_transport)


def check_url(settings: Settings, url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise DomainError("Base URL must be an http(s) URL with a host name.")
    allowed = settings.allowed_hosts
    if allowed and u.hostname.lower() not in allowed:
        raise DomainError(f"Host {u.hostname} is not on the connector allow-list.")


def parse_schema(raw: str | dict[str, Any], *, allow_empty: bool = False) -> dict[str, str]:
    """Validate a flat ``{"field": "type"}`` schema (a trailing ``?`` marks optional output)."""
    if isinstance(raw, str):
        raw = raw.strip()
        if raw in ("", '""', "{}"):
            if allow_empty:
                return {}
            raise DomainError("Schema cannot be empty.")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise DomainError(f"Schema is not valid JSON: {e.msg}") from e
    else:
        data = raw
    if data == "" and allow_empty:
        return {}
    if not isinstance(data, dict):
        raise DomainError('Schema must be a JSON object like {"name": "string"}.')
    out: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not k.strip("?").replace("_", "").isalnum():
            raise DomainError(f"Invalid field name {k!r}.")
        if v not in FIELD_TYPES:
            raise DomainError(f"Field {k!r}: type must be one of {', '.join(sorted(FIELD_TYPES))}.")
        out[k] = v
    if not out and not allow_empty:
        raise DomainError("Schema cannot be empty.")
    return out


def coerce(schema: dict[str, str], values: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, typ in schema.items():
        if typ == "file":
            continue
        raw = (values.get(name) or "").strip()
        if raw == "":
            raise DomainError(f"{name} is required.")
        try:
            if typ == "int":
                out[name] = int(raw)
            elif typ == "float":
                out[name] = float(raw)
            elif typ == "bool":
                out[name] = raw.lower() in ("1", "true", "yes", "y", "on")
            else:
                out[name] = raw
        except ValueError as e:
            raise DomainError(f"{name} must be of type {typ}.") from e
    return out


@dataclass
class UploadedFile:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


def call(
    settings: Settings,
    ep: ApiEndpoint,
    values: dict[str, str],
    files: dict[str, UploadedFile] | None = None,
) -> httpx.Response:
    check_url(settings, ep.base_url)
    payload = coerce(ep.input_schema, values)
    files = {
        k: f for k, f in (files or {}).items() if f.content and ep.input_schema.get(k) == "file"
    }
    try:
        with client(settings) as c:
            if ep.method == "GET":
                r = c.get(ep.url, params=payload)
            elif files:
                r = c.request(
                    ep.method,
                    ep.url,
                    data={k: str(v) for k, v in payload.items()},
                    files={k: (f.filename, f.content, f.content_type) for k, f in files.items()},
                )
            else:
                r = c.request(ep.method, ep.url, json=payload)
    except httpx.HTTPError as e:
        raise UpstreamError(f"Could not reach {ep.base_url}: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        detail = ""
        try:
            body = r.json()
            if isinstance(body, dict):
                detail = str(body.get("error") or body.get("detail") or "")
        except ValueError:
            pass
        raise UpstreamError(
            f"The organization's API answered HTTP {r.status_code}"
            + (f": {detail}" if detail else ".")
        )
    return r


def call_json(
    settings: Settings,
    ep: ApiEndpoint,
    values: dict[str, str],
    files: dict[str, UploadedFile] | None = None,
) -> Any:
    r = call(settings, ep, values, files)
    try:
        data = r.json()
    except ValueError as e:
        raise UpstreamError("The organization's API did not return JSON.") from e
    if isinstance(data, dict) and data.get("error"):
        raise UpstreamError(str(data["error"]))
    return data


def call_pdf(settings: Settings, ep: ApiEndpoint, values: dict[str, str]) -> bytes:
    r = call(settings, ep, values)
    if not r.content.startswith(b"%PDF"):
        raise UpstreamError("The organization's API did not return a PDF.")
    return r.content


# ---------------------------------------------------------------- bank gateway


def bank_authenticate(
    settings: Settings, bank: str, account_name: str, account_no: str, password: str
) -> bool:
    body = {
        "bank": bank,
        "account_name": account_name,
        "account_number": account_no,
        "password": password,
    }
    try:
        with client(settings) as c:
            r = c.post(settings.bank_gateway_url.rstrip("/") + "/bank/authenticate", json=body)
        return r.status_code == 200 and r.json().get("status") == "success"
    except (httpx.HTTPError, ValueError) as e:
        raise UpstreamError("The bank gateway is unreachable.") from e


def bank_transfer(
    settings: Settings, body: dict[str, Any], idempotency_key: str
) -> tuple[bool, str]:
    try:
        with client(settings) as c:
            r = c.post(
                settings.bank_gateway_url.rstrip("/") + "/bank/transfer",
                json=body,
                headers={"Idempotency-Key": idempotency_key},
            )
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise UpstreamError("The bank gateway is unreachable.") from e
    ok = data.get("status") == "success"
    return ok, "" if ok else str(data.get("reason") or "transfer refused")
