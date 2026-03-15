"""
SMS Integration Test Suite
Tests: basic flow, session persistence, gap resumption, follow-ups, PAUSE, max cap

Run with: python -m tests.test_sms_integration
(from the backend/ directory with the server running on port 8000)
"""

import requests
import time
import json
import sys
import xml.etree.ElementTree as ET

BASE = "http://localhost:8000"
RESULTS = []


def log(test_name: str, passed: bool, details: str = ""):
    status = "✅ PASS" if passed else "❌ FAIL"
    RESULTS.append({"test": test_name, "passed": passed, "details": details})
    print(f"  {status}: {test_name}")
    if details and not passed:
        print(f"         → {details}")


def sms(phone: str, body: str) -> str:
    """Send a simulated SMS and return the response text."""
    r = requests.post(f"{BASE}/api/sms/webhook", data={
        "From": phone,
        "Body": body,
        "To": "+14157070976",
    })
    if r.status_code != 200:
        return f"HTTP_ERROR_{r.status_code}"

    # Parse TwiML XML to extract message text
    try:
        root = ET.fromstring(r.text)
        messages = root.findall("Message")
        return " ".join(m.text or "" for m in messages).strip()
    except ET.ParseError:
        return r.text


def get_sessions() -> list:
    """Get all sessions from the API."""
    r = requests.get(f"{BASE}/api/sessions")
    return r.json() if r.status_code == 200 else []


def get_session_detail(session_id: str) -> dict:
    """Get full session detail."""
    r = requests.get(f"{BASE}/api/sessions/{session_id}")
    return r.json() if r.status_code == 200 else {}


def find_session_by_phone(phone: str) -> dict | None:
    """Find the most recent session for a phone number."""
    sessions = get_sessions()
    for s in sessions:
        # Need to check via detail endpoint since list may not have phone
        detail = get_session_detail(s["id"])
        # Check if this session has matching messages from this phone
        # Actually, we'll use the DB approach via the sessions list
    # Simpler: just get all sessions sorted by start_time desc
    # and find the one that matches our test conversation
    return None


def update_timestamps_back(hours: float, phone: str):
    """Push message timestamps back by N hours for a phone number's session.
    Uses the debug/admin approach via direct SQL if available,
    or we can use a test endpoint.
    """
    # We'll use a Python subprocess to modify timestamps
    import subprocess
    script = f"""
import sys
sys.path.insert(0, '.')
from app.database import _get_engine
from sqlalchemy import text
engine = _get_engine()
with engine.connect() as conn:
    result = conn.execute(text("SELECT id FROM sessions WHERE phone_number = '{phone}' AND sms_state = 'active' ORDER BY start_time DESC LIMIT 1"))
    row = result.fetchone()
    if row:
        sid = row[0]
        seconds = int({hours} * 3600)
        conn.execute(text(f"UPDATE messages SET timestamp = timestamp - {{seconds}} WHERE session_id = '{{sid}}'"))
        conn.execute(text(f"UPDATE sessions SET start_time = start_time - {{seconds}}, last_followup_at = NULL WHERE id = '{{sid}}'"))
        conn.commit()
        print(f"OK:{{sid}}")
    else:
        print("NOSESSION")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd="."
    )
    output = result.stdout.strip()
    if output.startswith("OK:"):
        return output.split(":")[1]
    return None


# ============================================================
# TEST 1: Basic SMS Flow
# ============================================================

def test_basic_flow():
    print("\n═══ TEST 1: Basic SMS Flow ═══")
    phone = "+14155500001"

    # 1a: New user texts in
    resp = sms(phone, "hello")
    has_survey = "1-10" in resp or "1 to 10" in resp
    log("1a. New user gets pre-survey question", has_survey,
        f"Response: {resp[:100]}")

    # 1b: User submits conviction score
    resp = sms(phone, "7")
    has_greeting = len(resp) > 20 and ("HTTP_ERROR" not in resp)
    got_score_ack = "score" in resp.lower() or "thanks" in resp.lower() or "recorded" in resp.lower()
    log("1b. Score accepted + bot greeting returned", has_greeting and got_score_ack,
        f"Response: {resp[:150]}")

    # 1c: User sends a real message
    resp = sms(phone, "I run a mortgage brokerage with 8 agents")
    has_response = len(resp) > 10 and "HTTP_ERROR" not in resp
    log("1c. Bot responds to user message", has_response,
        f"Response: {resp[:150]}")

    # 1d: Another message
    resp = sms(phone, "We spend too much time on manual follow-ups and lose leads")
    has_response = len(resp) > 10 and "HTTP_ERROR" not in resp
    log("1d. Bot responds to second message", has_response,
        f"Response: {resp[:150]}")

    return phone


# ============================================================
# TEST 2: Invalid Pre-Survey Input
# ============================================================

def test_invalid_pre_survey():
    print("\n═══ TEST 2: Invalid Pre-Survey Input ═══")
    phone = "+14155500002"

    # Start session
    sms(phone, "hi")

    # Send non-number
    resp = sms(phone, "banana")
    asks_again = "1" in resp and "10" in resp
    log("2a. Invalid input gets re-prompt", asks_again,
        f"Response: {resp[:100]}")

    # Send out-of-range number
    resp = sms(phone, "15")
    asks_again = "1" in resp and "10" in resp
    log("2b. Out-of-range number gets re-prompt", asks_again,
        f"Response: {resp[:100]}")

    # Send valid number
    resp = sms(phone, "5")
    has_greeting = len(resp) > 20 and "HTTP_ERROR" not in resp
    log("2c. Valid number proceeds to greeting", has_greeting,
        f"Response: {resp[:100]}")


# ============================================================
# TEST 3: Opt-Out Commands
# ============================================================

def test_opt_out():
    print("\n═══ TEST 3: Opt-Out Commands ═══")
    phone = "+14155500003"

    # Create active session
    sms(phone, "hi")
    sms(phone, "6")
    sms(phone, "I'm a loan officer")

    # Test STOP
    resp = sms(phone, "STOP")
    ended = "ended" in resp.lower() or "got it" in resp.lower()
    log("3a. STOP ends session", ended,
        f"Response: {resp[:100]}")

    # Text after STOP should start new or show ended
    resp = sms(phone, "hello again")
    is_new_or_ended = "1-10" in resp or "1 to 10" in resp or "ended" in resp.lower() or "NEW" in resp
    log("3b. Texting after STOP starts fresh or shows ended", is_new_or_ended,
        f"Response: {resp[:100]}")


# ============================================================
# TEST 4: NEW Command
# ============================================================

def test_new_command():
    print("\n═══ TEST 4: NEW Command ═══")
    phone = "+14155500004"

    # Create session
    sms(phone, "hi")
    sms(phone, "8")
    sms(phone, "I'm in mortgage lending")

    # Restart with NEW
    resp = sms(phone, "NEW")
    is_fresh_start = "1-10" in resp or "1 to 10" in resp
    log("4a. NEW restarts with pre-survey", is_fresh_start,
        f"Response: {resp[:100]}")

    # Complete new session setup
    resp = sms(phone, "4")
    has_greeting = len(resp) > 20
    log("4b. New session proceeds normally after NEW", has_greeting,
        f"Response: {resp[:100]}")


# ============================================================
# TEST 5: Session Resumption After Gap
# ============================================================

def test_gap_resumption():
    print("\n═══ TEST 5: Session Resumption After Gap ═══")
    phone = "+14155500005"

    # Create session and have a conversation
    sms(phone, "hi")
    sms(phone, "7")
    sms(phone, "I manage a team of 12 loan officers at a regional bank")
    sms(phone, "Our biggest problem is follow-up speed, we lose deals")

    # Push timestamps back 48 hours
    session_id = update_timestamps_back(48, phone)
    if not session_id:
        log("5a. Timestamp manipulation for gap test", False, "Could not find/update session")
        return

    log("5a. Timestamps pushed back 48 hours", True, f"Session: {session_id}")

    # Text back after the gap
    resp = sms(phone, "Hey sorry I got busy, still interested though")
    has_response = len(resp) > 10 and "HTTP_ERROR" not in resp
    # The bot should NOT ask for pre-survey again (session should resume)
    not_pre_survey = "1-10" not in resp and "1 to 10" not in resp
    log("5b. Session resumes (no pre-survey)", not_pre_survey,
        f"Response: {resp[:150]}")
    log("5c. Bot responds meaningfully after gap", has_response,
        f"Response: {resp[:150]}")


# ============================================================
# TEST 6: PAUSE Command
# ============================================================

def test_pause():
    print("\n═══ TEST 6: PAUSE Command ═══")
    phone = "+14155500006"

    # Create session
    sms(phone, "hi")
    sms(phone, "5")
    sms(phone, "I'm curious about AI for mortgage")

    # Pause follow-ups
    resp = sms(phone, "PAUSE")
    paused = "follow-up" in resp.lower() or "won't send" in resp.lower() or "got it" in resp.lower()
    log("6a. PAUSE acknowledged", paused,
        f"Response: {resp[:100]}")

    # User can still chat normally after PAUSE
    resp = sms(phone, "Actually I have another question about the program")
    has_response = len(resp) > 10 and "HTTP_ERROR" not in resp
    not_pre_survey = "1-10" not in resp
    log("6b. User can still chat after PAUSE", has_response and not_pre_survey,
        f"Response: {resp[:150]}")


# ============================================================
# TEST 7: Follow-Up Trigger (Manual)
# ============================================================

def test_followup_trigger():
    print("\n═══ TEST 7: Follow-Up Trigger ═══")
    phone = "+14155500007"

    # Create session
    sms(phone, "hi")
    sms(phone, "6")
    sms(phone, "I run a small mortgage shop, 3 agents")

    # Push timestamps back so follow-up threshold is met
    session_id = update_timestamps_back(49, phone)  # 49 hours covers all bots
    if not session_id:
        log("7a. Timestamp manipulation for follow-up test", False, "Could not find/update session")
        return

    log("7a. Timestamps pushed back 49 hours", True, f"Session: {session_id}")

    # Trigger follow-up check
    r = requests.post(f"{BASE}/api/debug/trigger-followups")
    trigger_ok = r.status_code == 200
    log("7b. Follow-up trigger endpoint returns 200", trigger_ok,
        f"Status: {r.status_code}, Body: {r.text[:100]}")

    # Check if follow-up message was saved to DB
    time.sleep(3)  # Give background thread time to complete
    detail = get_session_detail(session_id)
    if detail:
        msg_count = detail.get("messages", [])
        # The last message should be an assistant follow-up
        if msg_count:
            last_msg = msg_count[-1] if isinstance(msg_count, list) else None
            if last_msg:
                is_followup = last_msg.get("role") == "assistant"
                log("7c. Follow-up message saved to DB", is_followup,
                    f"Last message role: {last_msg.get('role')}, content: {last_msg.get('content', '')[:100]}")
            else:
                log("7c. Follow-up message saved to DB", False, "Could not parse last message")
        else:
            log("7c. Follow-up message saved to DB", False, "No messages in session detail")
    else:
        log("7c. Follow-up message saved to DB", False, f"Could not fetch session {session_id}")


# ============================================================
# TEST 8: Max Follow-Ups Cap
# ============================================================

def test_max_followups():
    print("\n═══ TEST 8: Max Follow-Ups Cap ═══")
    phone = "+14155500008"

    # Create session
    sms(phone, "hi")
    sms(phone, "9")
    sms(phone, "I need AI help for my lending business")

    session_id = update_timestamps_back(49, phone)
    if not session_id:
        log("8a. Setup for max follow-up test", False, "Could not find session")
        return

    # Send 3 follow-ups
    for i in range(1, 4):
        requests.post(f"{BASE}/api/debug/trigger-followups")
        time.sleep(2)
        # Push timestamps back again for next follow-up
        update_timestamps_back(49, phone)
        time.sleep(1)

    log("8a. Sent 3 follow-up cycles", True)

    # Try a 4th — should NOT send
    requests.post(f"{BASE}/api/debug/trigger-followups")
    time.sleep(2)

    # Check followup_count in session — should be 3, not 4
    # We'll check via the session messages count
    detail = get_session_detail(session_id) if session_id else {}
    messages = detail.get("messages", [])
    assistant_msgs_after_user = 0
    found_user = False
    for m in reversed(messages):
        if m.get("role") == "user" and not found_user:
            found_user = True
        elif m.get("role") == "assistant" and found_user:
            assistant_msgs_after_user += 1

    # At most 3 follow-ups should exist after the last user message
    log("8b. Max 3 follow-ups enforced", assistant_msgs_after_user <= 4,  # 1 bot reply + 3 follow-ups
        f"Assistant messages after last user msg: {assistant_msgs_after_user}")


# ============================================================
# TEST 9: Random Arm Assignment Distribution
# ============================================================

def test_random_assignment():
    print("\n═══ TEST 9: Random Arm Assignment ═══")
    arms = {"sally_nepq": 0, "hank_hypes": 0, "ivy_informs": 0}

    for i in range(12):
        phone = f"+1415550{100 + i}"
        sms(phone, "hi")
        resp = sms(phone, "5")

        # Detect which bot by greeting style
        resp_lower = resp.lower()
        if "sally" in resp_lower or "curious" in resp_lower:
            arms["sally_nepq"] += 1
        elif "hank" in resp_lower or "crush" in resp_lower or "roi" in resp_lower or "🚀" in resp:
            arms["hank_hypes"] += 1
        elif "ivy" in resp_lower or "information" in resp_lower or "neutral" in resp_lower:
            arms["ivy_informs"] += 1

    total = sum(arms.values())
    has_distribution = total > 0 and len([v for v in arms.values() if v > 0]) >= 2
    log("9a. Multiple arms assigned across 12 sessions", has_distribution,
        f"Distribution: {arms}")

    # Check that no single arm got ALL sessions (would indicate broken randomization)
    no_monopoly = all(v < 12 for v in arms.values())
    log("9b. No single arm monopolized all sessions", no_monopoly,
        f"Distribution: {arms}")


# ============================================================
# TEST 10: CDS Monitoring Endpoint
# ============================================================

def test_cds_monitoring():
    print("\n═══ TEST 10: CDS Monitoring Endpoint ═══")

    r = requests.get(f"{BASE}/api/monitoring/cds-summary")
    log("10a. CDS summary endpoint returns 200", r.status_code == 200,
        f"Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        has_arms = "arms" in data
        has_lift = "sally_lift_vs_controls" in data
        has_targets = "target" in data
        log("10b. Response has arms data", has_arms, f"Keys: {list(data.keys())}")
        log("10c. Response has lift calculations", has_lift)
        log("10d. Response has target thresholds", has_targets)


# ============================================================
# REPORT GENERATION
# ============================================================

def generate_report():
    print("\n" + "=" * 60)
    print("SMS INTEGRATION TEST REPORT")
    print("=" * 60)

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = total - passed

    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed}")
    print(f"Pass Rate: {(passed/total*100):.0f}%\n")

    if failed > 0:
        print("FAILURES:")
        print("-" * 40)
        for r in RESULTS:
            if not r["passed"]:
                print(f"  ❌ {r['test']}")
                if r["details"]:
                    print(f"     → {r['details']}")
        print()

    print("ALL RESULTS:")
    print("-" * 40)
    for r in RESULTS:
        status = "✅" if r["passed"] else "❌"
        print(f"  {status} {r['test']}")

    print("\n" + "=" * 60)

    # Write report to file
    report_lines = [
        "# SMS Integration Test Report",
        f"",
        f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total Tests**: {total}",
        f"**Passed**: {passed}",
        f"**Failed**: {failed}",
        f"**Pass Rate**: {(passed/total*100):.0f}%",
        "",
        "## Results",
        "",
    ]

    current_section = ""
    for r in RESULTS:
        test_name = r["test"]
        section = test_name.split(".")[0].strip() if "." in test_name else ""

        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        detail_str = f" — {r['details']}" if r["details"] else ""
        report_lines.append(f"- {status}: {test_name}{detail_str}")

    if failed > 0:
        report_lines.extend([
            "",
            "## Failures",
            "",
        ])
        for r in RESULTS:
            if not r["passed"]:
                report_lines.append(f"- **{r['test']}**: {r['details']}")

    report_lines.extend(["", "---", f"*Generated at {time.strftime('%Y-%m-%d %H:%M:%S')}*"])

    report_path = "tests/SMS_TEST_REPORT.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))

    print(f"\nReport written to: {report_path}")

    return failed == 0


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  SMS INTEGRATION TEST SUITE")
    print("  Testing: basic flow, persistence, follow-ups, PAUSE, cap")
    print("=" * 60)

    # Verify server is running
    try:
        r = requests.get(f"{BASE}/")
        if r.status_code != 200:
            print(f"\n❌ Server not responding (status {r.status_code}). Start with:")
            print("   uvicorn app.main:app --reload --port 8000")
            sys.exit(1)
    except requests.ConnectionError:
        print("\n❌ Cannot connect to server. Start with:")
        print("   uvicorn app.main:app --reload --port 8000")
        sys.exit(1)

    print(f"\n✓ Server is running at {BASE}")

    # Run all tests
    test_basic_flow()
    test_invalid_pre_survey()
    test_opt_out()
    test_new_command()
    test_gap_resumption()
    test_pause()
    test_followup_trigger()
    test_max_followups()
    test_random_assignment()
    test_cds_monitoring()

    # Generate report
    all_passed = generate_report()

    sys.exit(0 if all_passed else 1)
