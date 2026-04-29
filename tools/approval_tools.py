"""Human approval gate — PostgreSQL backend + polling."""

from __future__ import annotations

import time
import uuid

from runtime_config import get_approval_timeout_s
from tools import state_store

CATEGORIES = {"BET_PROPOSAL", "RISK_CHANGE", "PIPELINE_CHANGE"}
_VALID_STATUSES = {"approved", "rejected", "modified"}


def add_approval_request(category: str, decision: dict, reason: str) -> str:
    """Aggiunge una richiesta di approvazione su DB. Ritorna l'ID."""
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category}. Must be one of {CATEGORIES}")
    req_id = str(uuid.uuid4())[:8]
    return state_store.add_pending_approval(
        req_id=req_id,
        category=category,
        decision=decision,
        reason=reason,
    )


def get_pending_approvals() -> list[dict]:
    """Restituisce le richieste con status='pending'."""
    return state_store.list_pending_approvals()


def resolve_approval(req_id: str, status: str, note: str | None = None) -> None:
    """Aggiorna lo status di una richiesta."""
    if status not in _VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {_VALID_STATUSES}")
    state_store.resolve_pending_approval(req_id, status, note=note)


def request_human_approval(
    category: str,
    decision: dict,
    reason: str,
    timeout_s: int | None = None,
    poll_interval_s: float = 2.0,
) -> dict:
    """
    Crea un'approval request e attende la decisione facendo polling su PG.
    Ritorna {"id", "status", "note"}. Status "timeout" se timeout_s scade.
    """
    timeout = timeout_s if timeout_s is not None else get_approval_timeout_s()
    req_id = add_approval_request(category, decision, reason)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = state_store.get_approval_status(req_id)
        if current and current["status"] != "pending":
            return {
                "id": req_id,
                "status": current["status"],
                "note": current["user_note"],
            }
        time.sleep(poll_interval_s)
    note = f"Approval timed out after {timeout}s"
    state_store.resolve_pending_approval(req_id, "timed_out", note=note)
    return {"id": req_id, "status": "timeout", "note": None}
