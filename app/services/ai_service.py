"""Optional Ollama-backed finance assistant (summarized context only)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from sqlalchemy.orm import Session

from app.models import DatabaseInstance, User
from app.services import dashboard_metrics, eom_summary_service, monthly_snapshot_service as mss, wishlist_service

DEFAULT_OLLAMA_MODEL = "minimax-m2.5:cloud"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"

REASON_AUTH_REQUIRED = "ollama_auth_required"
REASON_UNREACHABLE = "ollama_unreachable"
REASON_MODEL_UNAVAILABLE = "model_unavailable"
REASON_TIMEOUT = "timeout"
REASON_UNKNOWN = "unknown"

MSG_AUTH_REQUIRED = "AI is not available right now. Make sure Ollama is running and signed in."
MSG_UNREACHABLE = "AI is not available right now. Make sure Ollama is running."

# Legacy alias
AI_UNAVAILABLE_MSG = MSG_AUTH_REQUIRED

_TOP_N = 5
_CONTEXT_JSON_LIMIT = 12000


@dataclass
class AiOllamaResult:
    ok: bool
    answer: str | None = None
    error: str | None = None
    reason: str | None = None
    can_signin: bool = False
    signin_url: str | None = None

    def to_error_json(self) -> dict[str, Any]:
        return {
            "error": self.error or MSG_AUTH_REQUIRED,
            "reason": self.reason or REASON_UNKNOWN,
            "can_signin": self.can_signin,
        }


def ollama_model() -> str:
    return (os.environ.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL).strip()


def ollama_base_url() -> str:
    return (os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def manual_signin_instructions() -> dict[str, str]:
    """Copy for UI when automatic signin URL is unavailable."""
    return {
        "title": "Ollama sign-in required",
        "intro": f"To use Webable AI with {ollama_model()}, sign in to Ollama Cloud after the containers are running.",
        "signin_cmd": "sudo docker exec -it webable-ollama ollama signin",
        "test_cmd": f"sudo docker exec -it webable-ollama ollama run {ollama_model()}",
        "footer": "After signing in, come back and try your AI message again.",
    }


def build_system_prompt() -> str:
    return (
        "You are a calm, direct personal finance assistant inside a budgeting web app.\n\n"
        "Tone: slightly analytical, plain language. Not childish, not corporate. No guilt, no fake motivation.\n\n"
        "Rules:\n"
        "- Use only the financial context provided below.\n"
        "- Do not invent numbers.\n"
        "- If data is missing, say so clearly.\n"
        "- Do not give professional financial, legal, or tax advice.\n"
        "- Do not mention databases, JSON, SQL, code, or internal systems.\n\n"
        "Format:\n"
        "- A short direct summary first\n"
        "- Bullet points for observations and practical next steps when relevant"
    )


def _ollama_request(method: str, path: str, body: dict | None = None, *, timeout: int = 30) -> dict[str, Any]:
    """HTTP call to Ollama; returns normalized dict (never raises)."""
    url = f"{ollama_base_url()}{path}"
    payload = json.dumps(body if body is not None else {}).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed: dict[str, Any] = json.loads(raw) if raw.strip() else {}
            return {
                "reachable": True,
                "ok": True,
                "status": resp.status,
                "body": parsed,
                "signin_url": parsed.get("signin_url"),
                "error": parsed.get("error", ""),
            }
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            parsed = {"error": raw[:500] if raw else exc.reason}
        if not isinstance(parsed, dict):
            parsed = {"error": str(parsed)}
        return {
            "reachable": True,
            "ok": False,
            "status": exc.code,
            "body": parsed,
            "signin_url": parsed.get("signin_url"),
            "error": str(parsed.get("error") or exc.reason or ""),
        }
    except TimeoutError:
        return {"reachable": True, "ok": False, "reason": REASON_TIMEOUT, "error": "timeout"}
    except (URLError, OSError, json.JSONDecodeError) as exc:
        return {"reachable": False, "ok": False, "reason": REASON_UNREACHABLE, "error": str(exc)}


def _looks_like_auth_error(status: int | None, error_text: str, signin_url: str | None) -> bool:
    if signin_url:
        return True
    if status == 401:
        return True
    text = (error_text or "").lower()
    return any(
        token in text
        for token in (
            "unauthorized",
            "sign in",
            "signin",
            "sign-in",
            "not signed",
            "authentication",
            "authorization",
        )
    )


def _classify_ollama_failure(resp: dict[str, Any]) -> AiOllamaResult:
    signin_url = resp.get("signin_url")
    status = resp.get("status")
    err_text = str(resp.get("error") or "")
    body = resp.get("body") or {}
    if isinstance(body, dict) and not signin_url:
        signin_url = body.get("signin_url")
        err_text = err_text or str(body.get("error") or "")

    if not resp.get("reachable", True):
        return AiOllamaResult(
            ok=False,
            reason=REASON_UNREACHABLE,
            error=MSG_UNREACHABLE,
            can_signin=False,
        )

    if resp.get("reason") == REASON_TIMEOUT:
        return AiOllamaResult(
            ok=False,
            reason=REASON_TIMEOUT,
            error=MSG_AUTH_REQUIRED,
            can_signin=True,
        )

    if _looks_like_auth_error(status, err_text, signin_url):
        return AiOllamaResult(
            ok=False,
            reason=REASON_AUTH_REQUIRED,
            error=MSG_AUTH_REQUIRED,
            can_signin=True,
            signin_url=signin_url,
        )

    err_lower = err_text.lower()
    if status == 404 or "not found" in err_lower:
        return AiOllamaResult(
            ok=False,
            reason=REASON_MODEL_UNAVAILABLE,
            error=MSG_AUTH_REQUIRED,
            can_signin=True,
            signin_url=signin_url,
        )

    return AiOllamaResult(
        ok=False,
        reason=REASON_UNKNOWN,
        error=MSG_AUTH_REQUIRED,
        can_signin=True,
        signin_url=signin_url,
    )


def fetch_ollama_signin_link() -> dict[str, Any]:
    """
    Ask Ollama for a fresh cloud sign-in URL via POST /api/me (official local API).
    Falls back to a minimal cloud generate probe if needed.
    """
    me = _ollama_request("POST", "/api/me", {})
    if me.get("ok"):
        return {"signed_in": True}
    if me.get("signin_url"):
        return {"signin_url": me["signin_url"]}

    probe = _ollama_request(
        "POST",
        "/api/generate",
        {"model": ollama_model(), "prompt": "ping", "stream": False},
        timeout=20,
    )
    if probe.get("signin_url"):
        return {"signin_url": probe["signin_url"]}
    if probe.get("ok"):
        return {"signed_in": True}

    if not me.get("reachable", True) and not probe.get("reachable", True):
        return {"error": "Could not reach Ollama. Make sure the Ollama container is running."}

    return {"error": "Could not generate Ollama signin link."}


def _trim_top_rows(rows: list[dict[str, Any]], limit: int = _TOP_N) -> list[dict[str, str | float]]:
    out: list[dict[str, str | float]] = []
    for row in rows[:limit]:
        out.append(
            {
                "name": str(row.get("name") or ""),
                "amount_eur": round(float(row.get("amount_eur") or 0), 2),
            }
        )
    return out


def summarize_workspace_context(
    db: Session | None,
    user: User,
    instance: DatabaseInstance,
    *,
    include_wishlist: bool = True,
    include_eom: bool = True,
) -> dict[str, Any]:
    """Summarized finance context for one workspace (no raw DB dumps)."""
    month_str = datetime.utcnow().strftime("%Y-%m")
    y, m = mss.month_str_to_parts(month_str)
    py, pm = mss.previous_month(y, m)
    prev_payload = mss.compute_snapshot_payload(
        instance.finance_db_path,
        instance.logic_db_path,
        mss.parts_to_month_str(py, pm),
        include_iefp=bool(user.enable_iefp_mode),
    )
    payload = mss.compute_snapshot_payload(
        instance.finance_db_path,
        instance.logic_db_path,
        month_str,
        include_iefp=bool(user.enable_iefp_mode),
        prev_payload=prev_payload,
    )

    mom: dict[str, Any] | None = None
    comparison = payload.get("comparison") or {}
    if comparison:
        mom = {
            "income_change_eur": comparison.get("income_change"),
            "expenses_change_eur": comparison.get("expenses_change"),
            "savings_change_eur": comparison.get("savings_change"),
            "plain_summary": comparison.get("plain_summary"),
        }

    summary: dict[str, Any] = {
        "workspace": instance.name,
        "month": payload.get("month_label") or month_str,
        "total_income": payload.get("total_income"),
        "total_expenses": payload.get("total_expenses"),
        "current_month_balance": payload.get("net_balance"),
        "safe_to_spend": payload.get("safe_to_spend"),
        "fixed_expenses_percent_of_income": payload.get("fixed_expenses_percent_income"),
        "top_expenses": _trim_top_rows(payload.get("top_expenses") or []),
        "top_income_sources": _trim_top_rows(payload.get("top_income") or []),
    }
    if mom:
        summary["month_over_month"] = mom

    if db is not None and include_wishlist:
        safe = float(payload.get("safe_to_spend") or 0)
        items = wishlist_service.list_items(db, user.id)[:_TOP_N]
        if items:
            summary["wishlist"] = [
                {
                    "name": it.name,
                    "price_eur": round(float(it.price_eur or 0), 2),
                    "affordability": dashboard_metrics.wishlist_affordability(float(it.price_eur or 0), safe)["label"],
                }
                for it in items
            ]

    if db is not None and include_eom:
        try:
            eom = eom_summary_service.build_live_preview(db, instance, user, month_str=month_str)
            lines = [str(x) for x in (eom.get("summary_lines") or [])[:6]]
            if lines:
                summary["eom_summary"] = {
                    "month_label": eom.get("month_label"),
                    "summary_lines": lines,
                }
        except Exception:
            pass

    return summary


def summarize_user_context(db: Session, user: User, instance_id: int | None = None) -> dict[str, Any]:
    """Summarized context across workspaces for the global AI panel."""
    instances_q = db.query(DatabaseInstance).filter(DatabaseInstance.owner_id == user.id)
    if instance_id is not None:
        instances_q = instances_q.filter(DatabaseInstance.id == instance_id)
    instances = instances_q.order_by(DatabaseInstance.created_at.desc()).all()

    return {
        "user": user.username,
        "current_month": datetime.utcnow().strftime("%Y-%m"),
        "workspaces": [summarize_workspace_context(db, user, ins) for ins in instances],
    }


def ask_ollama(question: str, context: dict) -> AiOllamaResult:
    context_block = json.dumps(context, ensure_ascii=False, indent=2)[:_CONTEXT_JSON_LIMIT]
    payload = {
        "model": ollama_model(),
        "stream": False,
        "prompt": f"{build_system_prompt()}\n\nFinancial context:\n{context_block}\n\nUser question:\n{question}",
    }
    resp = _ollama_request("POST", "/api/generate", payload, timeout=90)
    if resp.get("ok"):
        body = resp.get("body") or {}
        answer = ""
        if isinstance(body, dict):
            answer = str(body.get("response") or "").strip()
        return AiOllamaResult(ok=True, answer=answer or "I could not generate a response.")
    return _classify_ollama_failure(resp)


def render_ai_answer(answer: str) -> str:
    cleaned = (answer or "").strip()
    if not cleaned:
        return "- I could not generate a useful answer this time."
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "answer" in parsed:
                cleaned = str(parsed["answer"]).strip()
        except Exception:
            pass
    return cleaned
