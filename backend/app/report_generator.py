"""
PDF Report Generator for Sally Sells Experiment

Generates a professional research report with:
- CDS score analysis (per-arm, per-platform)
- Funnel metrics and completion rates
- Transcript quality insights (via Claude API)
- Statistical summaries and recommendations
"""

import io
import os
import logging
from datetime import datetime
from typing import Optional

from anthropic import Anthropic
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

logger = logging.getLogger("sally.report")

# Colors
BLUE = HexColor("#3b82f6")
GREEN = HexColor("#10b981")
RED = HexColor("#ef4444")
GRAY = HexColor("#71717a")
DARK = HexColor("#18181b")
LIGHT_GRAY = HexColor("#e4e4e7")
WHITE = HexColor("#ffffff")


def _escape_xml(text: str) -> str:
    """Escape XML-special characters for ReportLab Paragraph safety."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _get_claude_client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return Anthropic(api_key=api_key)


def _build_styles():
    """Build custom paragraph styles for the report."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=22,
        spaceAfter=6,
        textColor=DARK,
    ))
    styles.add(ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=GRAY,
        spaceAfter=20,
    ))
    styles.add(ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading1"],
        fontSize=14,
        textColor=DARK,
        spaceBefore=16,
        spaceAfter=8,
        borderWidth=0,
    ))
    styles.add(ParagraphStyle(
        "SubHeading",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=DARK,
        spaceBefore=10,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=DARK,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "Insight",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=DARK,
        leftIndent=12,
        borderColor=BLUE,
        borderWidth=1,
        borderPadding=8,
        backColor=HexColor("#eff6ff"),
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "SmallGray",
        parent=styles["Normal"],
        fontSize=8,
        textColor=GRAY,
    ))

    return styles


def _compute_stats(sessions: list) -> dict:
    """Compute all statistical summaries from session data."""
    stats = {
        "total": len(sessions),
        "by_arm": {},
        "by_platform": {},
        "by_status": {},
        "overall_cds": [],
        "funnel": {
            "total": len(sessions),
            "with_messages": 0,
            "with_5plus_messages": 0,
            "completed": 0,
            "with_cds": 0,
        },
    }

    for s in sessions:
        arm = s.get("assigned_arm", "unknown")
        platform = s.get("platform") or "organic"
        status = s.get("status", "unknown")
        cds = s.get("cds_score")

        # Arm stats
        if arm not in stats["by_arm"]:
            stats["by_arm"][arm] = {"total": 0, "cds_scores": [], "pre_scores": [], "post_scores": [], "message_counts": [], "statuses": {}}
        stats["by_arm"][arm]["total"] += 1
        if cds is not None:
            stats["by_arm"][arm]["cds_scores"].append(cds)
            stats["overall_cds"].append(cds)
        if s.get("pre_conviction") is not None:
            stats["by_arm"][arm]["pre_scores"].append(s["pre_conviction"])
        if s.get("post_conviction") is not None:
            stats["by_arm"][arm]["post_scores"].append(s["post_conviction"])
        stats["by_arm"][arm]["message_counts"].append(s.get("message_count", 0))
        stats["by_arm"][arm]["statuses"][status] = stats["by_arm"][arm]["statuses"].get(status, 0) + 1

        # Platform stats
        if platform not in stats["by_platform"]:
            stats["by_platform"][platform] = {"total": 0, "cds_scores": [], "completion_count": 0}
        stats["by_platform"][platform]["total"] += 1
        if cds is not None:
            stats["by_platform"][platform]["cds_scores"].append(cds)
        if status == "completed":
            stats["by_platform"][platform]["completion_count"] += 1

        # Status stats
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

        # Funnel
        mc = s.get("message_count", 0)
        if mc > 0:
            stats["funnel"]["with_messages"] += 1
        if mc >= 5:
            stats["funnel"]["with_5plus_messages"] += 1
        if status == "completed":
            stats["funnel"]["completed"] += 1
        if cds is not None:
            stats["funnel"]["with_cds"] += 1

    return stats


def _mean(values: list) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def _get_transcript_insights(sessions_with_transcripts: list) -> str:
    """Use Claude API to generate qualitative insights from transcripts."""
    # Select up to 10 transcripts with CDS scores for analysis
    scored = [s for s in sessions_with_transcripts if s.get("cds_score") is not None and s.get("transcript")]
    if not scored:
        scored = [s for s in sessions_with_transcripts if s.get("transcript")]
    sample = scored[:10]

    if not sample:
        return "Insufficient transcript data for qualitative analysis."

    transcript_block = ""
    for s in sample:
        arm = s.get("assigned_arm", "unknown")
        cds = s.get("cds_score", "N/A")
        pre = s.get("pre_conviction", "N/A")
        post = s.get("post_conviction", "N/A")
        transcript = s.get("transcript", "")
        # Truncate long transcripts
        if len(transcript) > 2000:
            transcript = transcript[:2000] + "... [truncated]"
        transcript_block += f"\n---\nArm: {arm} | Pre: {pre} | Post: {post} | CDS: {cds}\n{transcript}\n"

    prompt = f"""You are a research analyst reviewing AI sales experiment transcripts.
Analyze these conversation transcripts from a CDS (Conviction Delta Score) experiment with 3 bot arms:
- Sally (NEPQ structured sales methodology)
- Hank (aggressive traditional sales)
- Ivy (neutral information only)

CDS = post_conviction - pre_conviction (scale 1-10). Higher CDS means the bot was more persuasive.

TRANSCRIPTS:
{transcript_block}

Provide a concise analysis covering:
1. KEY PATTERNS: What conversation patterns correlate with higher CDS scores? (2-3 sentences)
2. SALLY vs CONTROLS: How does Sally's NEPQ approach differ qualitatively from Hank/Ivy? (2-3 sentences)
3. FAILURE MODES: What causes low or negative CDS? Common problems across bots? (2-3 sentences)
4. PARTICIPANT EXPERIENCE: How engaged were participants? Any signs of frustration or confusion? (2-3 sentences)
5. RECOMMENDATIONS: Top 3 specific, actionable improvements for the next iteration. (bullet points)

Be data-driven and specific. Reference actual conversation moments where possible. Keep total response under 400 words."""

    try:
        client = _get_claude_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"[Report] Claude insight generation failed: {e}")
        return f"Insight generation failed: {str(e)}"


def generate_pdf_report(
    sessions_data: list[dict],
    filters_description: str = "",
    include_insights: bool = True,
) -> bytes:
    """
    Generate a PDF report from session data.

    Args:
        sessions_data: List of session dicts (same shape as CSV export rows)
        filters_description: Human-readable description of active filters
        include_insights: Whether to call Claude API for transcript insights

    Returns:
        PDF file contents as bytes
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = _build_styles()
    story = []

    now_str = datetime.now().strftime("%B %d, %Y at %H:%M")
    stats = _compute_stats(sessions_data)

    # ========== TITLE PAGE ==========
    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph("Sally Sells CDS Experiment", styles["ReportTitle"]))
    story.append(Paragraph("Phase 1B Results Report", styles["ReportSubtitle"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Generated: {now_str}", styles["SmallGray"]))
    if filters_description:
        story.append(Paragraph(f"Filters: {_escape_xml(filters_description)}", styles["SmallGray"]))
    story.append(Paragraph(f"Sessions analyzed: {stats['total']}", styles["SmallGray"]))
    story.append(PageBreak())

    # ========== EXECUTIVE SUMMARY ==========
    story.append(Paragraph("1. Executive Summary", styles["SectionHeading"]))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY, spaceAfter=8))

    overall_mean = _mean(stats["overall_cds"])
    n_cds = len(stats["overall_cds"])
    story.append(Paragraph(
        f"Across {stats['total']} total sessions, {n_cds} produced valid CDS scores "
        f"(completion rate: {round(n_cds / stats['total'] * 100, 1) if stats['total'] else 0}%). "
        f"The overall mean CDS is <b>{overall_mean if overall_mean is not None else 'N/A'}</b>.",
        styles["ReportBody"],
    ))

    # Per-arm summary table
    arm_table_data = [["Arm", "Sessions", "CDS Scores", "Mean CDS", "Mean Pre", "Mean Post", "Completion %"]]
    arm_display = {"sally_nepq": "Sally (NEPQ)", "hank_hypes": "Hank (Aggressive)", "ivy_informs": "Ivy (Neutral)"}

    for arm_key in ["sally_nepq", "hank_hypes", "ivy_informs"]:
        arm = stats["by_arm"].get(arm_key, {})
        if not arm:
            continue
        n = arm["total"]
        cds_n = len(arm["cds_scores"])
        mean_cds = _mean(arm["cds_scores"])
        mean_pre = _mean(arm["pre_scores"])
        mean_post = _mean(arm["post_scores"])
        comp_pct = round(arm["statuses"].get("completed", 0) / n * 100, 1) if n else 0
        arm_table_data.append([
            arm_display.get(arm_key, arm_key),
            str(n),
            str(cds_n),
            str(mean_cds) if mean_cds is not None else "\u2014",
            str(mean_pre) if mean_pre is not None else "\u2014",
            str(mean_post) if mean_post is not None else "\u2014",
            f"{comp_pct}%",
        ])

    if len(arm_table_data) > 1:
        t = Table(arm_table_data, colWidths=[1.5*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch, 1*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f4f4f5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), DARK),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))

    # Sally lift
    sally_cds = _mean(stats["by_arm"].get("sally_nepq", {}).get("cds_scores", []))
    if sally_cds is not None:
        for control_key, control_label in [("hank_hypes", "Hank"), ("ivy_informs", "Ivy")]:
            control_cds = _mean(stats["by_arm"].get(control_key, {}).get("cds_scores", []))
            if control_cds is not None:
                lift = round(sally_cds - control_cds, 2)
                direction = "higher" if lift > 0 else "lower" if lift < 0 else "equal"
                story.append(Paragraph(
                    f"Sally's CDS is <b>{'+' if lift > 0 else ''}{lift}</b> points {direction} than {control_label}.",
                    styles["ReportBody"],
                ))

    # ========== PLATFORM BREAKDOWN ==========
    story.append(Paragraph("2. Source Platform Breakdown", styles["SectionHeading"]))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY, spaceAfter=8))

    plat_table = [["Platform", "Sessions", "CDS Scores", "Mean CDS", "Completion Rate"]]
    for plat, pdata in sorted(stats["by_platform"].items()):
        n = pdata["total"]
        cds_n = len(pdata["cds_scores"])
        mean = _mean(pdata["cds_scores"])
        comp = round(pdata["completion_count"] / n * 100, 1) if n else 0
        plat_table.append([
            plat.capitalize(),
            str(n),
            str(cds_n),
            str(mean) if mean is not None else "\u2014",
            f"{comp}%",
        ])

    if len(plat_table) > 1:
        t = Table(plat_table, colWidths=[1.3*inch, 0.9*inch, 0.9*inch, 0.9*inch, 1.2*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f4f4f5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), DARK),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))

    # ========== FUNNEL ==========
    story.append(Paragraph("3. Session Funnel", styles["SectionHeading"]))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY, spaceAfter=8))

    f = stats["funnel"]
    funnel_table = [
        ["Stage", "Count", "% of Total"],
        ["Sessions Created", str(f["total"]), "100%"],
        ["Sent 1+ Messages", str(f["with_messages"]), f"{round(f['with_messages'] / f['total'] * 100, 1) if f['total'] else 0}%"],
        ["Sent 5+ Messages", str(f["with_5plus_messages"]), f"{round(f['with_5plus_messages'] / f['total'] * 100, 1) if f['total'] else 0}%"],
        ["Completed Survey", str(f["with_cds"]), f"{round(f['with_cds'] / f['total'] * 100, 1) if f['total'] else 0}%"],
    ]
    t = Table(funnel_table, colWidths=[2*inch, 1*inch, 1*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f4f4f5")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # ========== CDS DISTRIBUTION ==========
    story.append(Paragraph("4. CDS Score Distribution", styles["SectionHeading"]))
    story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY, spaceAfter=8))

    if stats["overall_cds"]:
        cds_values = sorted(stats["overall_cds"])
        story.append(Paragraph(
            f"Range: {min(cds_values)} to {max(cds_values)} | "
            f"Mean: {_mean(cds_values)} | "
            f"Median: {cds_values[len(cds_values)//2]} | "
            f"N = {len(cds_values)}",
            styles["ReportBody"],
        ))

        # Distribution table
        dist = {}
        for v in cds_values:
            dist[v] = dist.get(v, 0) + 1
        dist_table = [["CDS Score", "Count", "% of Scored"]]
        for score in sorted(dist.keys()):
            pct = round(dist[score] / len(cds_values) * 100, 1)
            dist_table.append([str(score), str(dist[score]), f"{pct}%"])
        t = Table(dist_table, colWidths=[1*inch, 1*inch, 1.2*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f4f4f5")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No CDS scores available for the selected filters.", styles["ReportBody"]))

    # ========== TRANSCRIPT INSIGHTS ==========
    if include_insights:
        story.append(PageBreak())
        story.append(Paragraph("5. Transcript Analysis (AI-Generated)", styles["SectionHeading"]))
        story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY, spaceAfter=8))
        story.append(Paragraph(
            "The following insights were generated by Claude (Sonnet) from a sample of up to 10 scored transcripts.",
            styles["SmallGray"],
        ))
        story.append(Spacer(1, 8))

        insights = _get_transcript_insights(sessions_data)
        # Split insights into paragraphs.
        # IMPORTANT: escape XML-special chars to prevent ReportLab parser crashes.
        for para in insights.split("\n"):
            para = para.strip()
            if not para:
                continue
            if para.startswith("**") or para.startswith("#"):
                # Heading — strip markdown, escape remaining text
                clean = _escape_xml(para.replace("**", "").replace("#", "").strip())
                story.append(Paragraph(clean, styles["SubHeading"]))
            elif para.startswith("- ") or para.startswith("* "):
                story.append(Paragraph(f"  {_escape_xml(para)}", styles["ReportBody"]))
            else:
                story.append(Paragraph(_escape_xml(para), styles["ReportBody"]))

    # ========== FOOTER ==========
    story.append(Spacer(1, 24))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT_GRAY, spaceAfter=8))
    story.append(Paragraph(
        f"Report generated by Sally Sells Experiment System | {now_str} | "
        f"Total sessions: {stats['total']} | CDS scores: {len(stats['overall_cds'])}",
        styles["SmallGray"],
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
