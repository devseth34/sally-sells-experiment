"""Tests for the PDF report generator — no DB or Claude API required."""
import pytest
from app.report_generator import _build_styles, _compute_stats, _escape_xml, generate_pdf_report


SAMPLE_SESSIONS = [
    {
        "session_id": "s1",
        "assigned_arm": "sally_nepq",
        "platform": "prolific",
        "status": "completed",
        "pre_conviction": 3,
        "post_conviction": 7,
        "cds_score": 4,
        "message_count": 12,
        "turn_number": 6,
        "current_phase": "COMMITMENT",
        "start_time": 1711500000,
        "end_time": 1711501800,
        "transcript": "[CONNECTION] Sally: Hi!\n[CONNECTION] Prospect: Hello",
    },
    {
        "session_id": "s2",
        "assigned_arm": "hank_hypes",
        "platform": "prolific",
        "status": "completed",
        "pre_conviction": 5,
        "post_conviction": 6,
        "cds_score": 1,
        "message_count": 8,
        "turn_number": 4,
        "current_phase": "CONVERSATION",
        "start_time": 1711502000,
        "end_time": 1711503000,
        "transcript": "[CONVERSATION] Hank: Hey!\n[CONVERSATION] Prospect: Hi",
    },
    {
        "session_id": "s3",
        "assigned_arm": "ivy_informs",
        "platform": "organic",
        "status": "abandoned",
        "pre_conviction": 4,
        "post_conviction": None,
        "cds_score": None,
        "message_count": 3,
        "turn_number": 2,
        "current_phase": "CONVERSATION",
        "start_time": 1711504000,
        "end_time": None,
        "transcript": "[CONVERSATION] Ivy: Welcome.\n[CONVERSATION] Prospect: Thanks",
    },
]


class TestBuildStyles:
    def test_no_crash(self):
        """_build_styles() must not raise on duplicate style names."""
        styles = _build_styles()
        assert styles is not None

    def test_custom_styles_present(self):
        styles = _build_styles()
        for name in ["ReportTitle", "ReportSubtitle", "SectionHeading", "SubHeading", "ReportBody", "Insight", "SmallGray"]:
            assert name in styles.byName, f"Missing custom style: {name}"

    def test_built_in_bodytext_untouched(self):
        """The built-in 'BodyText' style should still exist (we don't clobber it)."""
        styles = _build_styles()
        assert "BodyText" in styles.byName


class TestComputeStats:
    def test_empty_sessions(self):
        stats = _compute_stats([])
        assert stats["total"] == 0
        assert stats["overall_cds"] == []
        assert stats["funnel"]["total"] == 0
        assert stats["by_arm"] == {}
        assert stats["by_platform"] == {}

    def test_with_data(self):
        stats = _compute_stats(SAMPLE_SESSIONS)
        assert stats["total"] == 3
        assert len(stats["overall_cds"]) == 2  # s3 has no CDS
        assert stats["funnel"]["with_cds"] == 2
        assert stats["funnel"]["completed"] == 2
        assert stats["funnel"]["with_messages"] == 3
        assert stats["funnel"]["with_5plus_messages"] == 2  # s1 (12), s2 (8)

        # Per-arm
        assert stats["by_arm"]["sally_nepq"]["total"] == 1
        assert stats["by_arm"]["sally_nepq"]["cds_scores"] == [4]
        assert stats["by_arm"]["hank_hypes"]["total"] == 1

        # Per-platform
        assert stats["by_platform"]["prolific"]["total"] == 2
        assert stats["by_platform"]["organic"]["total"] == 1
        assert stats["by_platform"]["prolific"]["completion_count"] == 2


class TestEscapeXml:
    def test_ampersand(self):
        assert _escape_xml("Q&A session") == "Q&amp;A session"

    def test_angle_brackets(self):
        assert _escape_xml("CDS > 3 and CDS < 7") == "CDS &gt; 3 and CDS &lt; 7"

    def test_mixed(self):
        assert _escape_xml("A & B < C > D") == "A &amp; B &lt; C &gt; D"

    def test_no_special_chars(self):
        text = "Normal text without special characters."
        assert _escape_xml(text) == text

    def test_empty_string(self):
        assert _escape_xml("") == ""


class TestGeneratePdf:
    def test_empty_sessions_no_crash(self):
        """PDF generation with no sessions should still produce valid output."""
        pdf = generate_pdf_report([], include_insights=False)
        assert isinstance(pdf, bytes)
        assert len(pdf) > 0
        assert pdf[:5] == b"%PDF-"

    def test_with_sample_data_no_insights(self):
        """PDF with sample data but no Claude call should succeed."""
        pdf = generate_pdf_report(SAMPLE_SESSIONS, include_insights=False)
        assert isinstance(pdf, bytes)
        assert len(pdf) > 100
        assert pdf[:5] == b"%PDF-"

    def test_with_filters_description(self):
        pdf = generate_pdf_report(
            SAMPLE_SESSIONS,
            filters_description="platform=prolific, arm=sally_nepq",
            include_insights=False,
        )
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"

    def test_special_chars_in_filter_description(self):
        """Filter descriptions with XML-unsafe chars should not crash."""
        pdf = generate_pdf_report(
            SAMPLE_SESSIONS,
            filters_description="Q&A test <filter> with >special< chars",
            include_insights=False,
        )
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"
