"""CDS-grade rollup over sally_turns.jsonl.

Consumes the per-turn JSONL sink emitted by the voice runner (see
`metrics.py` → `MetricsSink`) and produces a summary suitable for
Day 6 iteration or downstream CDS aggregation:

  - Per-arm latency percentiles (engine_ms, asr_ms, tts_first_frame_ms)
  - Phase progression — deepest phase reached per session, distribution
  - L1 model usage — primary vs fallback rate
  - Session-level stats — turn count, arm, personality, duration

Schema is whatever `TurnMetrics` emits at write time. This script reads
defensively (`.get()` with defaults) so rows from older or newer schema
versions degrade gracefully rather than crashing the rollup.

Usage:
    python -m backend.voice_agent.cds_rollup
    python -m backend.voice_agent.cds_rollup --path /tmp/other.jsonl
    python -m backend.voice_agent.cds_rollup --arm sally_nepq
    python -m backend.voice_agent.cds_rollup --call AJ_abc123
    python -m backend.voice_agent.cds_rollup --since 2026-04-21
    python -m backend.voice_agent.cds_rollup --since 2026-04-21T12:00 --until 2026-04-21T18:00
    python -m backend.voice_agent.cds_rollup --json > rollup.json
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


PRIMARY_L1_MODEL = "gemini-2.5-flash-lite"

# NEPQ phase order for progression depth. Indexing this list gives a
# monotone "how far did the session get" score. Kept in sync with
# `app.schemas.NepqPhase` — if that enum grows, update here too.
PHASE_ORDER = [
    "CONNECTION",
    "SITUATION",
    "PROBLEM_AWARENESS",
    "SOLUTION_AWARENESS",
    "CONSEQUENCE",
    "OWNERSHIP",
    "COMMITMENT",
    "TERMINATED",
]


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolation percentile. Returns None on empty input.

    Not using numpy/statistics.quantiles to keep the rollup zero-dependency
    (only stdlib), so it runs anywhere Python runs without a venv bootstrap.
    """
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Read JSONL rows, skip blank/malformed lines with a warning."""
    if not path.exists():
        print(f"ERROR: metrics file not found: {path}", file=sys.stderr)
        sys.exit(1)

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARN: skipping malformed line {i}: {e}", file=sys.stderr)
    return rows


def _parse_iso_to_ts(s: str) -> float:
    """Accept either 'YYYY-MM-DD' or full ISO datetime, return unix ts.

    Bare dates become 00:00 local. No TZ awareness because the sink writes
    `time.time()` (unix) and users filter in local wall-clock terms.
    """
    return dt.datetime.fromisoformat(s).timestamp()


def apply_filters(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    out = rows
    if args.arm:
        out = [r for r in out if r.get("arm") == args.arm]
    if args.call:
        out = [r for r in out if r.get("call_id") == args.call]
    if args.since:
        ts = _parse_iso_to_ts(args.since)
        out = [r for r in out if (r.get("timestamp") or 0) >= ts]
    if args.until:
        ts = _parse_iso_to_ts(args.until)
        out = [r for r in out if (r.get("timestamp") or 0) < ts]
    return out


def compute_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Top-level aggregation: overall + per-arm + per-session."""
    if not rows:
        return {"total_turns": 0, "total_sessions": 0, "overall": _empty_block(), "arms": {}, "sessions": {}}

    by_arm: dict[str, list[dict]] = collections.defaultdict(list)
    by_session: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_arm[r.get("arm") or "unknown"].append(r)
        by_session[r.get("call_id") or "unknown"].append(r)

    arm_summaries = {arm: _summarize_rows(arm_rows) for arm, arm_rows in by_arm.items()}

    session_summaries: dict[str, dict[str, Any]] = {}
    for cid, srows in by_session.items():
        srows_sorted = sorted(srows, key=lambda r: r.get("turn_index", 0))
        first, last = srows_sorted[0], srows_sorted[-1]
        session_ended = any(r.get("ended") for r in srows)
        start_ts = first.get("timestamp")
        end_ts = last.get("timestamp")
        session_summaries[cid] = {
            "turns": len(srows_sorted),
            "arm": first.get("arm"),
            "personality": first.get("personality"),
            "deepest_phase": _deepest_phase(srows_sorted),
            "ended_at_phase": _last_phase(srows_sorted),
            "session_ended": session_ended,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "duration_s": (end_ts - start_ts) if (start_ts and end_ts) else None,
        }

    return {
        "total_turns": len(rows),
        "total_sessions": len(by_session),
        "overall": _summarize_rows(rows),
        "arms": arm_summaries,
        "sessions": session_summaries,
    }


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def collect(field: str) -> list[float]:
        return [float(r[field]) for r in rows if r.get(field) is not None]

    engine_ms = collect("engine_ms")
    asr_ms = collect("asr_ms")
    tts_ms = collect("tts_first_frame_ms")
    # Fields added 2026-04-24 — absent on older rows, present going fwd.
    user_latency_ms = collect("user_latency_ms")
    engine_dispatch_ms = collect("engine_dispatch_ms")
    utterance_duration_ms = collect("utterance_duration_ms")

    l1_models = collections.Counter(r.get("l1_model") or "null" for r in rows)
    primary_hits = l1_models.get(PRIMARY_L1_MODEL, 0)
    non_null = sum(v for k, v in l1_models.items() if k != "null")

    phase_changes = sum(1 for r in rows if r.get("phase_changed"))
    phases_reached = collections.Counter(r.get("phase") or "unknown" for r in rows)

    return {
        "turns": len(rows),
        "engine_ms": _latency_stats(engine_ms),
        "asr_ms": _latency_stats(asr_ms),
        "tts_first_frame_ms": _latency_stats(tts_ms),
        "user_latency_ms": _latency_stats(user_latency_ms),
        "engine_dispatch_ms": _latency_stats(engine_dispatch_ms),
        "utterance_duration_ms": _latency_stats(utterance_duration_ms),
        "phase_changes": phase_changes,
        "phases_distribution": dict(phases_reached),
        "l1_model_distribution": dict(l1_models),
        "l1_primary_rate": (primary_hits / non_null) if non_null else None,
        "l1_fallback_rate": (1 - primary_hits / non_null) if non_null else None,
        "tag_director_stats": _tag_director_stats(rows),
    }


def _tag_director_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate tag director observability across the row set.

    `used_count` = turns where Haiku succeeded (`tag_director_used=True`).
    `fallback_count` = turns where the director was attempted but failed
    (so we have a `tag_director_fallback` reason). Latency stats cover
    only attempted calls (regardless of success). Pre-director rows
    that don't have any director fields contribute zero to all counts.
    """
    used_count = sum(1 for r in rows if r.get("tag_director_used") is True)
    # Distinct from used_count: a row with success=False still has a
    # populated fallback_reason (timeout, parse_error, etc.).
    fallback_rows = [
        r for r in rows
        if r.get("tag_director_fallback") and r.get("tag_director_used") is False
    ]
    fallback_count = len(fallback_rows)
    fallback_reasons = collections.Counter(
        r.get("tag_director_fallback") for r in fallback_rows
    )
    # Latency: include any row where the director was attempted (used or
    # fallen-back), since both paths populate latency_ms.
    director_latency = [
        float(r["tag_director_latency_ms"])
        for r in rows
        if r.get("tag_director_latency_ms") is not None
    ]
    return {
        "used_count": used_count,
        "fallback_count": fallback_count,
        "fallback_reasons": dict(fallback_reasons),
        "latency": _latency_stats(director_latency),
    }


def _latency_stats(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "mean": statistics.mean(values) if values else None,
    }


def _empty_block() -> dict[str, Any]:
    return {
        "turns": 0,
        "engine_ms": _latency_stats([]),
        "asr_ms": _latency_stats([]),
        "tts_first_frame_ms": _latency_stats([]),
        "user_latency_ms": _latency_stats([]),
        "engine_dispatch_ms": _latency_stats([]),
        "utterance_duration_ms": _latency_stats([]),
        "phase_changes": 0,
        "phases_distribution": {},
        "l1_model_distribution": {},
        "l1_primary_rate": None,
        "l1_fallback_rate": None,
        "tag_director_stats": {
            "used_count": 0,
            "fallback_count": 0,
            "fallback_reasons": {},
            "latency": _latency_stats([]),
        },
    }


def _deepest_phase(rows: list[dict[str, Any]]) -> str | None:
    """Deepest NEPQ phase by PHASE_ORDER index. Unknown phases ignored."""
    best_idx = -1
    best_name: str | None = None
    for r in rows:
        p = r.get("phase")
        if p in PHASE_ORDER:
            idx = PHASE_ORDER.index(p)
            if idx > best_idx:
                best_idx = idx
                best_name = p
    return best_name


def _last_phase(rows: list[dict[str, Any]]) -> str | None:
    for r in reversed(rows):
        if r.get("phase"):
            return r["phase"]
    return None


# ---- human-readable formatter ----


def format_human(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"CDS rollup — {summary['total_sessions']} sessions, {summary['total_turns']} turns")
    lines.append("=" * 72)

    if summary["total_turns"] == 0:
        lines.append("\n(no data)")
        return "\n".join(lines)

    lines.append("\n--- OVERALL ---")
    _add_latency_block(lines, summary["overall"])
    _add_l1_block(lines, summary["overall"])
    _add_phase_change_line(lines, summary["overall"])

    for arm, arm_sum in sorted(summary["arms"].items()):
        lines.append(f"\n--- ARM: {arm}  ({arm_sum['turns']} turns) ---")
        _add_latency_block(lines, arm_sum)
        _add_l1_block(lines, arm_sum)
        _add_phase_change_line(lines, arm_sum)

    lines.append("\n--- DEEPEST PHASE PER SESSION ---")
    depth_counter = collections.Counter(
        s.get("deepest_phase") or "unknown" for s in summary["sessions"].values()
    )
    total_sess = summary["total_sessions"]
    for phase in PHASE_ORDER:
        n = depth_counter.get(phase, 0)
        if n:
            pct = f"{100*n/total_sess:5.1f}%"
            lines.append(f"  {phase:<22} {n:>3} session(s)  ({pct})")
    unknown_n = depth_counter.get("unknown", 0)
    if unknown_n:
        lines.append(f"  {'unknown':<22} {unknown_n:>3} session(s)")

    lines.append("\n--- SESSIONS ---")
    lines.append(
        f"  {'call_id':<24} {'arm':<16} {'personality':<18} {'turns':>5}  "
        f"{'deepest':<20} {'dur':>6}  {'end':<5}"
    )
    sessions_sorted = sorted(
        summary["sessions"].items(),
        key=lambda kv: kv[1].get("start_ts") or 0,
    )
    for cid, s in sessions_sorted:
        dur = s.get("duration_s")
        dur_s = f"{dur:5.0f}s" if dur is not None else "   —"
        lines.append(
            f"  {cid[:22]:<24} "
            f"{(s.get('arm') or '?')[:14]:<16} "
            f"{(s.get('personality') or '?')[:16]:<18} "
            f"{s['turns']:>5}  "
            f"{(s.get('deepest_phase') or '?'):<20} "
            f"{dur_s:>6}  "
            f"{'yes' if s.get('session_ended') else 'no':<5}"
        )

    return "\n".join(lines)


def _add_latency_block(lines: list[str], block: dict[str, Any]) -> None:
    # user_latency_ms is the user-perceived total (post-2026-04-24 fix);
    # the others decompose it. Shown first so humans see the headline.
    latency_fields = [
        ("user_latency_ms", "USER ↤ 👂"),
        ("engine_dispatch_ms", "dispatch"),
        ("engine_ms", "engine"),
        ("tts_first_frame_ms", "tts"),
        ("asr_ms", "asr_tail"),
        ("utterance_duration_ms", "utter_dur"),
    ]
    for key, label in latency_fields:
        stats = block.get(key, {})
        n = stats.get("n", 0)
        if n == 0:
            continue
        lines.append(
            f"  {label:<10} n={n:<4}  "
            f"p50={_fmt_ms(stats.get('p50'))}  "
            f"p95={_fmt_ms(stats.get('p95'))}  "
            f"mean={_fmt_ms(stats.get('mean'))}"
        )


def _add_l1_block(lines: list[str], block: dict[str, Any]) -> None:
    dist = block.get("l1_model_distribution", {})
    if not dist:
        return
    dist_str = ", ".join(f"{m}={c}" for m, c in sorted(dist.items(), key=lambda kv: -kv[1]))
    lines.append(f"  l1_model: {dist_str}")
    primary = block.get("l1_primary_rate")
    if primary is not None:
        fallback = block.get("l1_fallback_rate") or 0.0
        lines.append(f"  l1 primary={primary:.1%}  fallback={fallback:.1%}")


def _add_phase_change_line(lines: list[str], block: dict[str, Any]) -> None:
    pc = block.get("phase_changes", 0)
    n = block.get("turns", 0)
    if n:
        lines.append(f"  phase_changes: {pc}/{n} turns  ({100*pc/n:.1f}%)")


def _fmt_ms(v: float | None) -> str:
    if v is None:
        return "   n/a"
    return f"{v:7.1f}"


# ---- entrypoint ----


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CDS rollup over sally_turns.jsonl")
    ap.add_argument("--path", default="/tmp/sally_turns.jsonl", help="Path to metrics JSONL file")
    ap.add_argument("--arm", help="Filter to a single arm key (e.g. sally_nepq)")
    ap.add_argument("--call", help="Filter to a single call_id")
    ap.add_argument("--since", help="Include rows at or after this ISO date/time (e.g. 2026-04-21 or 2026-04-21T12:00:00)")
    ap.add_argument("--until", help="Include rows strictly before this ISO date/time")
    ap.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON summary instead of human table")
    args = ap.parse_args(argv)

    rows = load_rows(Path(args.path))
    rows = apply_filters(rows, args)
    summary = compute_summary(rows)

    if args.as_json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(format_human(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
