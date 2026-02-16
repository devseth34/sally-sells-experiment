"""
Google Sheets Logger — Webhook-based conversation logging.

Posts session data to a Google Apps Script web app that appends rows
to a Google Sheet. Uses only stdlib (urllib) — no extra dependencies.

Fire-and-forget via daemon threads so the main request is never blocked.
If GOOGLE_SHEETS_WEBHOOK_URL is not set, logging is silently skipped.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from http.client import HTTPResponse

# dotenv is loaded once in database.py (first import in main.py)

logger = logging.getLogger("sally.sheets")

MAX_CELL_CHARS = 49000  # Google Sheets cell limit is 50,000


def _get_webhook_url() -> str | None:
    url = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL")
    if not url:
        logger.warning("GOOGLE_SHEETS_WEBHOOK_URL not set — sheets logging disabled")
        return None
    return url


def _format_timestamp(ts) -> str:
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OSError):
        return str(ts)


def _build_transcript(messages_data: list[dict]) -> str:
    lines = []
    for m in messages_data:
        role_label = "Sally" if m.get("role") == "assistant" else "Prospect"
        lines.append(f"[{m.get('phase', '?')}] {role_label}: {m.get('content', '')}")
    transcript = "\n".join(lines)
    if len(transcript) > MAX_CELL_CHARS:
        transcript = transcript[:MAX_CELL_CHARS] + "\n...[TRUNCATED]"
    return transcript


def _build_session_row(session_data: dict, messages_data: list[dict]) -> list:
    profile = session_data.get("prospect_profile", {})
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except json.JSONDecodeError:
            profile = {}

    duration = ""
    if session_data.get("end_time") and session_data.get("start_time"):
        try:
            duration = round(float(session_data["end_time"]) - float(session_data["start_time"]))
        except (ValueError, TypeError):
            duration = ""

    return [
        session_data.get("id", ""),
        session_data.get("status", ""),
        session_data.get("current_phase", ""),
        session_data.get("pre_conviction", ""),
        session_data.get("post_conviction", ""),
        session_data.get("cds_score", ""),
        session_data.get("message_count", ""),
        session_data.get("turn_number", ""),
        _format_timestamp(session_data.get("start_time")),
        _format_timestamp(session_data.get("end_time")),
        duration,
        profile.get("name", ""),
        profile.get("role", ""),
        profile.get("company", ""),
        profile.get("industry", ""),
        "; ".join(profile.get("pain_points", [])),
        profile.get("desired_state", ""),
        profile.get("cost_of_inaction", ""),
        "; ".join(profile.get("objections_encountered", [])),
        profile.get("email", ""),
        profile.get("phone", ""),
        _format_timestamp(session_data.get("escalation_sent")),
        session_data.get("payment_status", "pending"),
        _build_transcript(messages_data),
        _format_timestamp(time.time()),
    ]


def _build_hot_lead_row(session_data: dict, messages_data: list[dict]) -> list:
    profile = session_data.get("prospect_profile", {})
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except json.JSONDecodeError:
            profile = {}

    return [
        session_data.get("id", ""),
        "OWNERSHIP",
        session_data.get("pre_conviction", ""),
        session_data.get("turn_number", ""),
        profile.get("name", ""),
        profile.get("role", ""),
        profile.get("company", ""),
        "; ".join(profile.get("pain_points", [])),
        profile.get("cost_of_inaction", ""),
        _build_transcript(messages_data),
        _format_timestamp(time.time()),
    ]


def _build_conversion_row(conversion_data: dict) -> list:
    return [
        conversion_data.get("sally_session_id", ""),
        conversion_data.get("checkout_session_id", ""),
        conversion_data.get("payment_status", ""),
        conversion_data.get("amount", ""),
        conversion_data.get("currency", ""),
        conversion_data.get("customer_email", ""),
        conversion_data.get("prospect_name", ""),
        conversion_data.get("prospect_company", ""),
        conversion_data.get("prospect_role", ""),
        _format_timestamp(time.time()),
    ]


class _PostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow 301/302/303/307/308 redirects while preserving POST method + body."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Build a new POST request to the redirect URL (stdlib default converts to GET)
        new_req = urllib.request.Request(
            newurl,
            data=req.data,
            headers={k: v for k, v in req.header_items()},
            method="POST",
        )
        return new_req


_opener = urllib.request.build_opener(_PostRedirectHandler)


def _post_to_sheets(payload: dict) -> None:
    url = _get_webhook_url()
    if not url:
        return

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with _opener.open(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            logger.info(f"Sheets webhook response: {resp.status} - {body}")
    except urllib.error.HTTPError as e:
        logger.error(f"Sheets webhook HTTP error: {e.code} - {e.read().decode('utf-8', errors='replace')}")
    except Exception as e:
        logger.error(f"Sheets webhook error: {e}")


def fire_sheets_log(target: str, session_data: dict, messages_data: list[dict] | None = None) -> None:
    """Fire-and-forget Google Sheets logging in a background thread.

    Args:
        target: "session", "hot_lead", or "conversion"
        session_data: Plain dict with session fields (or conversion data for "conversion" target)
        messages_data: List of dicts with role, content, phase, timestamp (not needed for "conversion")
    """
    if not os.getenv("GOOGLE_SHEETS_WEBHOOK_URL"):
        return

    def _worker():
        try:
            if target == "session":
                row = _build_session_row(session_data, messages_data or [])
            elif target == "hot_lead":
                row = _build_hot_lead_row(session_data, messages_data or [])
            elif target == "conversion":
                row = _build_conversion_row(session_data)
            else:
                logger.error(f"Unknown sheets log target: {target}")
                return

            _post_to_sheets({"target": target, "row": row})
            logger.info(f"[Session {session_data.get('id', session_data.get('sally_session_id', '?'))}] Logged to Google Sheets ({target})")
        except Exception as e:
            logger.error(f"[Session {session_data.get('id', session_data.get('sally_session_id', '?'))}] Sheets logging failed: {e}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
