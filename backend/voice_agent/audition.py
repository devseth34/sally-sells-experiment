"""Voice audition: render Sally's sample script across candidate voices.

Purpose (Addendum §B7):
    Before shipping Phase 2, pick 3 non-overlapping TTS voices —
    one each for sally_warm (ElevenLabs), sally_confident (Cartesia),
    and sally_direct (Cartesia). Do it ONCE, lock the choices before
    Day 3, and do NOT swap mid-experiment (invalidates CDS calibration).

Pipeline:
    1. Pull 10 candidate voices from each provider's API (listed by
       their `voices.list()` / `voices.get_all()` endpoints).
    2. Render the SALLY_AUDITION_SCRIPT through each voice at the
       production model we'll ship with:
           - ElevenLabs: `eleven_flash_v2_5`    (~75ms latency)
           - Cartesia:   `sonic-2`              (~90ms latency)
    3. Generate `auditions/index.html` with 20 audio players plus a
       scoring form (warmth / clarity / trust / naturalness, 1-5 each)
       and a free-text notes field per voice. CSV export built in.

Usage:
    python -m backend.voice_agent.audition list     # just list voices, no render
    python -m backend.voice_agent.audition smoke    # 2 voices/provider (cheap sanity check)
    python -m backend.voice_agent.audition render   # full 10+10 render
    python -m backend.voice_agent.audition html     # regenerate HTML from existing MP3s

Cost estimate:
    Full render: 145 words × 20 voices ≈ 2900 words TTS
    - ElevenLabs Flash v2.5: ~$0.50/1k chars → ~$0.75
    - Cartesia Sonic-2:      ~$0.08/1k chars → ~$0.12
    Total: ~$1 for the audition block.

Budget guard:
    Existing MP3s are skipped on re-render. Delete the file to force.

Notes on pronunciation:
    The script below is written WITH lexicon substitutions already
    applied ("Nick Shah" not "Nik Shah", "one hundred X" not "100x").
    This audition doubles as verification that those substitutions
    sound right on each voice. If "Shah" sounds like /ʃɔː/ or /ʃeɪ/
    on any candidate, that voice goes into the "needs phoneme tags"
    bucket — see pronunciation.py.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from dotenv import load_dotenv

# Load env BEFORE importing provider SDKs.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
AUDITIONS_DIR = _HERE / "auditions"
ELEVENLABS_DIR = AUDITIONS_DIR / "elevenlabs"
CARTESIA_DIR = AUDITIONS_DIR / "cartesia"
SCRIPT_PATH = AUDITIONS_DIR / "script.txt"
HTML_PATH = AUDITIONS_DIR / "index.html"

ELEVENLABS_MODEL = "eleven_flash_v2_5"
CARTESIA_MODEL = "sonic-2"

ELEVENLABS_CANDIDATE_COUNT = 10
CARTESIA_CANDIDATE_COUNT = 10
SMOKE_CANDIDATE_COUNT = 2

# ---------------------------------------------------------------------------
# The 145-word audition script.
#
# Pronunciation substitutions pre-applied per pronunciation.py::LEXICON
# (so we test that the SUBSTITUTED forms sound right on each voice):
#   "100x"     -> "one hundred X"
#   "Nik Shah" -> "Nick Shah"   (Shah locked /ʃɑː/ per Nik 2026-04-19)
#   "NEPQ"     -> "N-E-P-Q"
#   "CDS"      -> "C-D-S"
#   "AI"       -> "A-I"
#   "$10,000"  -> "ten thousand dollars"
#   "0.35"     -> "zero point three five"
#   "P&L"      -> "P and L"   (hyphen form rendered as "pandle"/"panel"
#                              on Flash v2.5 — spaces hit letter names)
#
# Coverage:
#   - Warm opening      (greeting, curiosity, openness)
#   - Empathy moment    (mirror, emotional reflection — tests softness)
#   - Confident pivot   (brand/founder reference, specific numbers)
#   - Direct close      (one-beat ask — tests crispness)
# ---------------------------------------------------------------------------
SALLY_AUDITION_SCRIPT = dedent("""\
    Hey there! I'm Sally from one hundred X. Super curious to learn about you. What brought you here today?

    Yeah, I hear you. That sounds really frustrating — like you're stuck and nothing's moving. Walk me through what happened the most recent time.

    Okay, so if I'm tracking this — your team's closing about ten thousand dollars a month less than they should, and you're the one eating the overhead. What's that been costing you personally? Not the P and L. You, mentally.

    Right. Here's the thing. Our founder, Nick Shah, built the N-E-P-Q playbook at one hundred X specifically for mortgage teams in exactly your spot. Thirty-day program, twelve operators per cohort, A-I-driven coaching. We guarantee a C-D-S lift of zero point three five, or we refund you in full.

    So let me ask you straight — are you actually ready to fix this, or is now not the right time?
""").strip()


# ---------------------------------------------------------------------------
# Candidate shape.
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    provider: str       # "elevenlabs" | "cartesia"
    voice_id: str
    name: str
    description: str    # human-friendly blurb for the HTML

    def safe_name(self) -> str:
        """Return a filesystem-safe slug of the voice name."""
        return re.sub(r"[^a-zA-Z0-9_-]+", "_", self.name).strip("_").lower() or "unnamed"

    def filename(self) -> str:
        return f"{self.voice_id}_{self.safe_name()}.mp3"


# ---------------------------------------------------------------------------
# ElevenLabs candidate discovery + rendering.
# ---------------------------------------------------------------------------
def _elevenlabs_client():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY not set in .env")
    from elevenlabs.client import ElevenLabs
    return ElevenLabs(api_key=key)


def list_elevenlabs_voices(limit: int) -> list[Candidate]:
    """Return up to `limit` ElevenLabs candidates, warm/female tilted.

    Strategy: pull every voice visible to this API key (pre-made library
    + anything in the user's voice library), prefer female voices with
    'young'/'middle aged' age, then backfill with whatever's left.
    Default ElevenLabs free tier exposes ~10 pre-made voices, so we
    usually return exactly 10.
    """
    client = _elevenlabs_client()
    resp = client.voices.get_all()
    raw = list(getattr(resp, "voices", resp) or [])

    def score(v) -> int:
        """Higher score = prefer. Tuned for Sally's warm tilt."""
        labels = getattr(v, "labels", {}) or {}
        s = 0
        gender = (labels.get("gender") or "").lower()
        age = (labels.get("age") or "").lower()
        descriptive = (labels.get("description") or labels.get("descriptive") or "").lower()
        if gender == "female":
            s += 3
        if age in ("young", "middle aged", "middle-aged", "middle_aged"):
            s += 2
        if any(w in descriptive for w in ("warm", "friendly", "calm", "soft", "natural")):
            s += 2
        return s

    raw.sort(key=score, reverse=True)

    out: list[Candidate] = []
    for v in raw[:limit]:
        labels = getattr(v, "labels", {}) or {}
        descriptive_bits = [
            labels.get("gender"),
            labels.get("age"),
            labels.get("accent"),
            labels.get("description") or labels.get("descriptive"),
        ]
        description = " · ".join(b for b in descriptive_bits if b) or "—"
        out.append(Candidate(
            provider="elevenlabs",
            voice_id=getattr(v, "voice_id", None) or getattr(v, "id", ""),
            name=getattr(v, "name", "unnamed") or "unnamed",
            description=description,
        ))
    return out


def render_elevenlabs(candidate: Candidate, text: str) -> bytes:
    client = _elevenlabs_client()
    audio = client.text_to_speech.convert(
        voice_id=candidate.voice_id,
        text=text,
        model_id=ELEVENLABS_MODEL,
        output_format="mp3_44100_128",
    )
    return b"".join(audio)


# ---------------------------------------------------------------------------
# Cartesia candidate discovery + rendering.
# ---------------------------------------------------------------------------
def _cartesia_client():
    key = os.environ.get("CARTESIA_API_KEY")
    if not key:
        sys.exit("CARTESIA_API_KEY not set in .env")
    from cartesia import Cartesia
    return Cartesia(api_key=key)


def list_cartesia_voices(limit: int) -> list[Candidate]:
    """Return up to `limit` Cartesia candidates, English pro/natural tilted.

    Cartesia's `voices.list()` returns everything exposed to the key
    (public library + owned). We filter to English and prefer female +
    expressive/natural tags, then backfill.
    """
    client = _cartesia_client()
    raw = list(client.voices.list())

    def lang(v) -> str:
        return (getattr(v, "language", "") or "").lower()

    def score(v) -> int:
        s = 0
        if lang(v).startswith("en"):
            s += 4
        # Cartesia voice objects carry a free-text description; lean on it.
        desc = (getattr(v, "description", "") or "").lower()
        gender = (getattr(v, "gender", "") or "").lower()
        if gender == "feminine" or "female" in desc or "woman" in desc:
            s += 3
        if any(w in desc for w in ("warm", "natural", "professional", "clear", "friendly", "expressive")):
            s += 2
        return s

    raw.sort(key=score, reverse=True)

    out: list[Candidate] = []
    for v in raw[:limit]:
        desc = getattr(v, "description", None) or "—"
        out.append(Candidate(
            provider="cartesia",
            voice_id=getattr(v, "id", ""),
            name=getattr(v, "name", "unnamed") or "unnamed",
            description=desc,
        ))
    return out


def render_cartesia(candidate: Candidate, text: str) -> bytes:
    client = _cartesia_client()
    chunks = client.tts.bytes(
        model_id=CARTESIA_MODEL,
        transcript=text,
        voice={"mode": "id", "id": candidate.voice_id},
        language="en",
        output_format={
            "container": "mp3",
            "sample_rate": 44100,
            "bit_rate": 128000,
        },
    )
    # `bytes()` may return bytes directly or an iterator of chunks;
    # handle both shapes.
    if isinstance(chunks, (bytes, bytearray)):
        return bytes(chunks)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Render driver — one MP3 per candidate, idempotent.
# ---------------------------------------------------------------------------
def render_all(candidates: list[Candidate]) -> None:
    AUDITIONS_DIR.mkdir(parents=True, exist_ok=True)
    ELEVENLABS_DIR.mkdir(parents=True, exist_ok=True)
    CARTESIA_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPT_PATH.write_text(SALLY_AUDITION_SCRIPT, encoding="utf-8")

    for c in candidates:
        target_dir = ELEVENLABS_DIR if c.provider == "elevenlabs" else CARTESIA_DIR
        target = target_dir / c.filename()
        if target.exists():
            print(f"  skip  {c.provider:10} {c.name:30} (already rendered)")
            continue
        print(f"  render {c.provider:10} {c.name:30} ...", end=" ", flush=True)
        try:
            if c.provider == "elevenlabs":
                mp3 = render_elevenlabs(c, SALLY_AUDITION_SCRIPT)
            else:
                mp3 = render_cartesia(c, SALLY_AUDITION_SCRIPT)
        except Exception as exc:  # noqa: BLE001 — we want to keep going on individual failures
            print(f"FAILED: {exc}")
            continue
        target.write_bytes(mp3)
        kb = len(mp3) / 1024
        print(f"ok ({kb:.0f} KB)")


# ---------------------------------------------------------------------------
# HTML generation — no frameworks, works from file:// URLs.
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sally Voice Audition</title>
<style>
  :root {{
    --bg: #0b1220; --fg: #e6edf3; --muted: #8b949e;
    --border: #30363d; --accent: #2f81f7; --row: #161b22; --row2: #0d1117;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 32px 48px; background: var(--bg); color: var(--fg);
         font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  h1 {{ margin: 0 0 4px; }}
  h2 {{ margin: 32px 0 12px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }}
  .script {{ background: var(--row); border: 1px solid var(--border); border-radius: 6px;
             padding: 12px 16px; white-space: pre-wrap; font-size: 13px;
             max-height: 180px; overflow: auto; }}
  .toolbar {{ margin: 16px 0; display: flex; gap: 8px; flex-wrap: wrap; }}
  button {{ background: var(--accent); color: white; border: 0; padding: 8px 14px;
            border-radius: 6px; cursor: pointer; font-weight: 600; }}
  button.secondary {{ background: transparent; color: var(--fg); border: 1px solid var(--border); }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border);
            vertical-align: middle; }}
  th {{ font-size: 12px; color: var(--muted); font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.04em; }}
  tr:nth-child(even) td {{ background: var(--row2); }}
  tr:nth-child(odd) td {{ background: var(--row); }}
  .name {{ font-weight: 600; }}
  .desc {{ color: var(--muted); font-size: 12px; }}
  audio {{ width: 260px; height: 32px; }}
  select, input[type=text] {{ background: var(--row2); color: var(--fg);
         border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px;
         font: inherit; }}
  input[type=text] {{ width: 100%; min-width: 200px; }}
  select {{ width: 54px; text-align: center; }}
  .muted {{ color: var(--muted); }}
  .top3 {{ background: rgba(47,129,247,0.15) !important; }}
</style>
</head>
<body>

<h1>Sally Voice Audition</h1>
<p class="muted">Rendered {candidate_count} voices via {providers}. Script covers warm / empathetic / confident / direct registers and every pronunciation landmine (Shah, NEPQ, CDS, 100x, $10k, 0.35).</p>

<details>
<summary>Audition script (click to expand)</summary>
<div class="script">{script_html}</div>
</details>

<div class="toolbar">
  <button onclick="exportCsv()">Download scores (CSV)</button>
  <button class="secondary" onclick="markTop3()">Auto-highlight top-3 across all providers</button>
  <button class="secondary" onclick="resetScores()">Reset all scores</button>
</div>

{sections}

<p class="muted" style="margin-top:32px">Scoring rubric: 1 = unusable · 2 = weak · 3 = acceptable · 4 = strong · 5 = ship-it. Weighted total = warmth × 1.0 + clarity × 1.2 + trust × 1.3 + naturalness × 1.5 (trust + naturalness weighted highest — these are the hardest to fake).</p>

<script>
function allRows() {{ return Array.from(document.querySelectorAll('tr[data-vid]')); }}

function total(row) {{
  const g = sel => Number(row.querySelector('select[data-metric="'+sel+'"]').value || 0);
  return g('warmth')*1.0 + g('clarity')*1.2 + g('trust')*1.3 + g('naturalness')*1.5;
}}

function recalc() {{
  for (const r of allRows()) {{
    r.querySelector('.total').textContent = total(r).toFixed(2);
  }}
}}

function markTop3() {{
  recalc();
  const rows = allRows().slice().sort((a, b) => total(b) - total(a));
  for (const r of rows) r.classList.remove('top3');
  for (const r of rows.slice(0, 3)) r.classList.add('top3');
}}

function resetScores() {{
  if (!confirm("Clear all scores and notes?")) return;
  for (const el of document.querySelectorAll('select[data-metric]')) el.value = '';
  for (const el of document.querySelectorAll('input[data-notes]')) el.value = '';
  recalc();
  for (const r of allRows()) r.classList.remove('top3');
}}

function exportCsv() {{
  recalc();
  const lines = [['provider','voice_id','name','warmth','clarity','trust','naturalness','weighted_total','notes'].join(',')];
  for (const r of allRows()) {{
    const g = sel => r.querySelector('select[data-metric="'+sel+'"]').value || '';
    const n = (r.querySelector('input[data-notes]').value || '').replaceAll('"','""');
    lines.push([
      r.dataset.provider, r.dataset.vid,
      '"' + (r.dataset.name || '').replaceAll('"','""') + '"',
      g('warmth'), g('clarity'), g('trust'), g('naturalness'),
      total(r).toFixed(2),
      '"' + n + '"',
    ].join(','));
  }}
  const blob = new Blob([lines.join('\\n')], {{ type: 'text/csv' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'sally_audition_scores.csv';
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}}

document.addEventListener('change', e => {{
  if (e.target.matches('select[data-metric]')) recalc();
}});
recalc();
</script>

</body>
</html>
"""

_SECTION_TEMPLATE = """
<h2>{provider_label} <span class="muted" style="font-weight:400">· {model_id}</span></h2>
<table>
  <thead>
    <tr>
      <th style="width:22%">Voice</th>
      <th style="width:26%">Play</th>
      <th>Warm</th>
      <th>Clar</th>
      <th>Trust</th>
      <th>Natural</th>
      <th style="width:10%">Total</th>
      <th>Notes</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
"""


def _score_select(metric: str) -> str:
    opts = "".join(f'<option value="{n}">{n}</option>' for n in ("", "1", "2", "3", "4", "5"))
    return f'<select data-metric="{metric}">{opts}</select>'


def _row_html(c: Candidate) -> str:
    rel = f"{c.provider}/{c.filename()}"
    name_html = (
        f'<div class="name">{_escape(c.name)}</div>'
        f'<div class="desc">{_escape(c.description)}</div>'
    )
    audio_html = f'<audio controls preload="none" src="{rel}"></audio>'
    scores = "".join(
        f"<td>{_score_select(m)}</td>" for m in ("warmth", "clarity", "trust", "naturalness")
    )
    return (
        f'<tr data-vid="{_escape(c.voice_id)}" '
        f'data-provider="{c.provider}" '
        f'data-name="{_escape(c.name)}">'
        f'<td>{name_html}</td>'
        f'<td>{audio_html}</td>'
        f'{scores}'
        f'<td class="total muted">0.00</td>'
        f'<td><input type="text" data-notes placeholder="one-line impression"></td>'
        f'</tr>'
    )


def _escape(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def generate_html(candidates: list[Candidate]) -> None:
    elevenlabs = [c for c in candidates if c.provider == "elevenlabs"]
    cartesia = [c for c in candidates if c.provider == "cartesia"]

    sections = []
    if elevenlabs:
        sections.append(_SECTION_TEMPLATE.format(
            provider_label="ElevenLabs",
            model_id=ELEVENLABS_MODEL,
            rows="\n".join(_row_html(c) for c in elevenlabs),
        ))
    if cartesia:
        sections.append(_SECTION_TEMPLATE.format(
            provider_label="Cartesia",
            model_id=CARTESIA_MODEL,
            rows="\n".join(_row_html(c) for c in cartesia),
        ))

    providers = " + ".join(
        label for label, lst in [("ElevenLabs", elevenlabs), ("Cartesia", cartesia)] if lst
    )

    html = _HTML_TEMPLATE.format(
        candidate_count=len(candidates),
        providers=providers or "—",
        script_html=_escape(SALLY_AUDITION_SCRIPT),
        sections="\n".join(sections),
    )
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"  wrote {HTML_PATH.relative_to(_REPO_ROOT)}")


# ---------------------------------------------------------------------------
# Existing-MP3 scan — lets `html` mode rebuild the page without re-rendering.
# ---------------------------------------------------------------------------
def scan_existing() -> list[Candidate]:
    """Rebuild Candidate list from MP3 filenames already on disk.

    Filenames follow `<voice_id>_<safe_name>.mp3`. Description is lost
    on scan — we just recover name+id for the HTML.
    """
    found: list[Candidate] = []
    for provider_dir, provider in [(ELEVENLABS_DIR, "elevenlabs"), (CARTESIA_DIR, "cartesia")]:
        if not provider_dir.exists():
            continue
        for mp3 in sorted(provider_dir.glob("*.mp3")):
            stem = mp3.stem
            # stem = "<voice_id>_<safe_name>"
            voice_id, _, safe_name = stem.partition("_")
            found.append(Candidate(
                provider=provider,
                voice_id=voice_id,
                name=safe_name.replace("_", " ") or "unnamed",
                description="(recovered from filename)",
            ))
    return found


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cmd_list() -> None:
    print("Pulling candidate voices...")
    el = list_elevenlabs_voices(ELEVENLABS_CANDIDATE_COUNT)
    ca = list_cartesia_voices(CARTESIA_CANDIDATE_COUNT)
    print(f"\nElevenLabs ({len(el)}):")
    for c in el:
        print(f"  {c.voice_id:30} {c.name:25} {c.description}")
    print(f"\nCartesia ({len(ca)}):")
    for c in ca:
        print(f"  {c.voice_id:40} {c.name:25} {c.description}")


def _cmd_smoke() -> None:
    print(f"Smoke test: {SMOKE_CANDIDATE_COUNT} voices per provider.")
    el = list_elevenlabs_voices(SMOKE_CANDIDATE_COUNT)
    ca = list_cartesia_voices(SMOKE_CANDIDATE_COUNT)
    all_c = el + ca
    render_all(all_c)
    generate_html(all_c)
    print(f"\nDone. Open {HTML_PATH.relative_to(_REPO_ROOT)} in a browser.")


def _cmd_render() -> None:
    print(f"Full render: {ELEVENLABS_CANDIDATE_COUNT} EL + {CARTESIA_CANDIDATE_COUNT} CA.")
    el = list_elevenlabs_voices(ELEVENLABS_CANDIDATE_COUNT)
    ca = list_cartesia_voices(CARTESIA_CANDIDATE_COUNT)
    all_c = el + ca
    render_all(all_c)
    generate_html(all_c)
    print(f"\nDone. Open {HTML_PATH.relative_to(_REPO_ROOT)} in a browser.")


def _cmd_html() -> None:
    found = scan_existing()
    if not found:
        sys.exit("No MP3s in auditions/ — run `render` or `smoke` first.")
    generate_html(found)
    print(f"Rebuilt HTML over {len(found)} existing MP3s.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sally voice audition renderer.")
    parser.add_argument("mode", choices=["list", "smoke", "render", "html"])
    args = parser.parse_args()
    {"list": _cmd_list, "smoke": _cmd_smoke, "render": _cmd_render, "html": _cmd_html}[args.mode]()


if __name__ == "__main__":
    main()
