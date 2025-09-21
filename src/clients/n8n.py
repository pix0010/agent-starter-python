"""Async HTTP client for n8n booking workflows."""
from __future__ import annotations

import os
from typing import Any, Dict

import httpx

def _url(path: str) -> str:
    base = (os.getenv("N8N_BASE") or "").rstrip("/")
    if not base:
        raise RuntimeError("N8N_BASE is not configured")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


async def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    timeout = httpx.Timeout(float(os.getenv("N8N_TIMEOUT", "3.0") or 3.0), connect=0.5)
    user = os.getenv("N8N_USER")
    pwd = os.getenv("N8N_PASS")
    auth = (user, pwd) if (user and pwd) else None
    async with httpx.AsyncClient(timeout=timeout, auth=auth) as cli:
        resp = await cli.post(_url(path), json=payload)
        resp.raise_for_status()
        return resp.json()


async def create_booking(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = os.getenv("N8N_PATH_BOOK", "/api/booking/book")
    return await _post(path, payload)


async def cancel_booking(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = os.getenv("N8N_PATH_CANCEL", "/api/booking/cancel")
    return await _post(path, payload)


async def reschedule_booking(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = os.getenv("N8N_PATH_RESCHEDULE", "/api/booking/reschedule")
    return await _post(path, payload)


async def find_by_phone(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = os.getenv("N8N_PATH_FIND_BY_PHONE", "/api/booking/find-by-phone")
    return await _post(path, payload)
