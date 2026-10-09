"""Bounded list discovery + persisted pending details; no provider/retry.

Public list transport is verified separately; tests can inject a fake reader.
"""
from __future__ import annotations

from typing import Any, Callable

from ingest.connectors.myseoul_program import SOURCE, _read_html, detail_identity, normalize_detail
from ingest.myseoul_db import MySeoulObservationAdapter
from ingest.myseoul_list import LIST_URL, ListPage, read_list_page

LIST_LIMIT = 2
DETAIL_LIMIT = 10
HTTP_LIMIT = LIST_LIMIT + DETAIL_LIMIT


def list_entries(result: ListPage, page: int) -> list[dict]:
    if (not isinstance(result, ListPage) or result.complete is not True
            or type(result.page) is not int or result.page != page
            or type(result.page_size) is not int or result.page_size != 10
            or type(result.total) is not int or not 0 <= result.total <= 100000
            or not isinstance(result.items, list)
            or len(result.items) != min(10, max(0, result.total - (page - 1) * 10))):
        raise ValueError("myseoul_list_incomplete")
    entries, seen = [], set()
    for item in result.items:
        if not isinstance(item, dict) or set(item) != {"url", "status"} or not isinstance(item["status"], str) or len(item["status"]) > 100:
            raise ValueError("myseoul_list_invalid")
        center, program, _, canonical = detail_identity(item["url"])
        key = center + ":" + program
        if key in seen:
            raise ValueError("myseoul_list_duplicate")
        seen.add(key)
        state = "closed" if item["status"].strip() in {"신청종료", "신청마감", "접수종료", "접수마감", "모집종료", "예약마감"} else "unknown"
        entries.append({"key": key, "url": canonical, "state": state})
    return entries


def _read_page(reader, http, page):
    before = http.request_count
    result = reader(http, page, 10)
    if http.request_count != before + 1 or http.request_count > HTTP_LIMIT:
        raise RuntimeError("myseoul_list_request_budget_invalid")
    return result


def collect_myseoul(http, rpc: Callable[[str, dict[str, Any]], Any], *, read_page=None) -> dict:
    if read_page is None:
        read_page = read_list_page
    if http.budget != HTTP_LIMIT or http.max_attempts != 1:
        raise ValueError("myseoul_budget_required")
    start = rpc("start_ingest_run", {"p_source_id": SOURCE, "p_lease_seconds": 600})
    if not isinstance(start, list) or len(start) != 1 or not isinstance(start[0], dict):
        raise RuntimeError("myseoul_run_response_invalid")
    if start[0].get("skipped") is True:
        return {"status": "skipped", "reason": start[0].get("skip_reason"), "requests": 0}
    run = start[0].get("run_id")
    if not run:
        raise RuntimeError("myseoul_run_response_invalid")
    store = MySeoulObservationAdapter(rpc)
    try:
        first = _read_page(read_page, http, 1)
        entries = list_entries(first, 1)
        state = rpc("discover_myseoul_list_page", {"p_run_id": run, "p_page": 1, "p_total": first.total, "p_entries": entries})
        if not isinstance(state, dict) or type(state.get("allNew")) is not bool:
            raise RuntimeError("myseoul_discovery_response_invalid")
        if state["allNew"] and len(entries) == 10:
            second = _read_page(read_page, http, 2)
            second_entries = list_entries(second, 2)
            if second.total != first.total or {e["key"] for e in entries}.intersection(e["key"] for e in second_entries):
                raise RuntimeError("myseoul_list_changed_during_read")
            state = rpc("discover_myseoul_list_page", {"p_run_id": run, "p_page": 2, "p_total": second.total, "p_entries": second_entries})
            if not isinstance(state, dict):
                raise RuntimeError("myseoul_discovery_response_invalid")
        pending = rpc("myseoul_pending_details", {"p_run_id": run})
        if not isinstance(pending, list) or len(pending) > DETAIL_LIMIT:
            raise RuntimeError("myseoul_pending_response_invalid")
        seen = set()
        for entry in pending:
            center, program, _, canonical = detail_identity(entry["url"])
            key = center + ":" + program
            if entry["key"] != key or key in seen:
                raise RuntimeError("myseoul_pending_response_invalid")
            seen.add(key)
            try:
                html, _, _ = _read_html(http, canonical)
                record = normalize_detail(html, canonical)
            except Exception:
                result = rpc("record_myseoul_detail_attempt", {"p_run_id": run, "p_key": key, "p_outcome": "detail_failed"})
                if not isinstance(result, dict) or result.get("outcome") != "detail_failed":
                    raise RuntimeError("myseoul_attempt_response_invalid")
                continue
            store.observe(run, [record], None)
            # Unknown writes are never replayed; a later run reconciles source_items.
            result = rpc("record_myseoul_detail_attempt", {"p_run_id": run, "p_key": key, "p_outcome": "processed"})
            if not isinstance(result, dict) or result.get("outcome") != "processed":
                raise RuntimeError("myseoul_attempt_response_invalid")
    except Exception:
        try:
            rpc("finish_myseoul_list_collection", {"p_run_id": run, "p_requests": http.request_count, "p_failed": True})
        except Exception:
            pass  # Lease expires naturally; no forced reset/repeated observation.
        raise RuntimeError("myseoul_collection_failed") from None
    try:
        result = rpc("finish_myseoul_list_collection", {"p_run_id": run, "p_requests": http.request_count, "p_failed": False})
    except Exception:
        # The finish may have committed. Do not replay it or force a failed run.
        raise RuntimeError("myseoul_finish_failed") from None
    if not isinstance(result, dict) or result.get("status") not in {"complete", "incomplete", "failed"}:
        raise RuntimeError("myseoul_finish_response_invalid")
    return {"status": result["status"], "requests": http.request_count, "summary": result.get("summary")}
