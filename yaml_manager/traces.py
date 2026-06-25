"""Best-effort Home Assistant trace/debug views for automations and scripts."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


TRACE_DOMAINS = {"automation", "script"}


def _trace_id(item: dict[str, Any]) -> str:
    if item.get("domain") == "script":
        entity = str(item.get("entityId", ""))
        return entity.split(".", 1)[1] if "." in entity else str(item.get("id", ""))
    return str(item.get("id") or item.get("entityId", "").split(".", 1)[-1])


def _trace_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        value = (
            payload.get("stored_traces")
            or payload.get("traces")
            or payload.get("trace")
            or payload.get("items")
            or []
        )
        if isinstance(value, dict):
            candidates = [
                {"run_id": run_id, **record} if isinstance(record, dict) else {"run_id": run_id, "value": record}
                for run_id, record in value.items()
            ]
        else:
            candidates = value if isinstance(value, list) else []
    else:
        candidates = []
    records: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        run_id = item.get("run_id") or item.get("runId") or item.get("id") or item.get("trace_id")
        timestamp = item.get("timestamp") or item.get("start") or item.get("last_step") or ""
        records.append(
            {
                "runId": str(run_id or ""),
                "timestamp": str(timestamp or ""),
                "state": str(item.get("state") or item.get("script_execution") or item.get("status") or ""),
                "lastStep": str(item.get("last_step") or item.get("lastStep") or ""),
                "error": item.get("error") or item.get("exception") or "",
                "summary": item,
            }
        )
    return records


def trace_index(backend: Any, limit: int = 60) -> dict[str, Any]:
    objects = backend.home_assistant_objects()
    traceable = [
        item for item in objects["objects"]
        if item.get("domain") in TRACE_DOMAINS and _trace_id(item)
    ][:limit]
    entries: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    for item in traceable:
        domain = item["domain"]
        item_id = _trace_id(item)
        try:
            payload = backend.home_assistant_request(f"trace/{domain}/{item_id}")
        except ApiError as exc:
            if exc.status == HTTPStatus.SERVICE_UNAVAILABLE:
                return {
                    "available": False,
                    "message": exc.message,
                    "objects": traceable,
                    "entries": [],
                    "unavailable": [],
                    "summary": {"objects": len(traceable), "traces": 0, "errors": 0},
                }
            unavailable.append({"entityId": item["entityId"], "message": exc.message})
            continue
        records = _trace_records(payload)
        for record in records:
            entries.append(
                {
                    **record,
                    "domain": domain,
                    "itemId": item_id,
                    "entityId": item["entityId"],
                    "alias": item["alias"],
                    "path": item["path"],
                    "line": item["line"],
                }
            )
    entries.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return {
        "available": True,
        "objects": traceable,
        "entries": entries[:200],
        "unavailable": unavailable,
        "summary": {
            "objects": len(traceable),
            "traces": len(entries),
            "errors": sum(bool(item.get("error")) for item in entries),
        },
    }


def trace_detail(backend: Any, raw_domain: Any, raw_item_id: Any, raw_run_id: Any) -> dict[str, Any]:
    domain = raw_domain if isinstance(raw_domain, str) else ""
    item_id = raw_item_id if isinstance(raw_item_id, str) else ""
    run_id = raw_run_id if isinstance(raw_run_id, str) else ""
    if domain not in TRACE_DOMAINS or not item_id or not run_id:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Trace-Domain, Objekt-ID und Run-ID sind erforderlich.")
    payload = backend.home_assistant_request(f"trace/{domain}/{item_id}/{run_id}")
    return {
        "domain": domain,
        "itemId": item_id,
        "runId": run_id,
        "trace": payload,
    }
