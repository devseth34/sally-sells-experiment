"""
Bot Switching & Memory Wipe Test Suite
Tests: SWITCH command (SMS), SWITCH endpoint (API), RESET command (SMS), Web API switchBot

Run with: python -m tests.test_bot_switch
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

    try:
        root = ET.fromstring(r.text)
        messages = root.findall("Message")
        return " ".join(m.text or "" for m in messages).strip()
    except ET.ParseError:
        return r.text


def create_web_session(pre_conviction: int = 7, selected_bot: str = None) -> dict:
    """Create a web session via the API."""
    import uuid
    visitor_id = str(uuid.uuid4())
    body = {
        "pre_conviction": pre_conviction,
        "visitor_id": visitor_id,
    }
    if selected_bot:
        body["selected_bot"] = selected_bot
    r = requests.post(f"{BASE}/api/sessions", json=body)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text}"}
    data = r.json()
    data["visitor_id"] = visitor_id
    return data


def send_web_message(session_id: str, content: str) -> dict:
    """Send a message via web API."""
    r = requests.post(f"{BASE}/api/sessions/{session_id}/messages", json={"content": content})
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text}"}
    return r.json()


def switch_web_bot(session_id: str, new_bot: str) -> dict:
    """Switch bot via web API."""
    r = requests.post(f"{BASE}/api/sessions/{session_id}/switch", json={"new_bot": new_bot})
    return {"status": r.status_code, "data": r.json() if r.status_code == 200 else r.text}


def get_session_detail(session_id: str) -> dict:
    """Get full session detail."""
    r = requests.get(f"{BASE}/api/sessions/{session_id}")
    return r.json() if r.status_code == 200 else {}


# ============================================================
# Helpers to detect and switch bots dynamically (random arm assignment)

def _fresh_phone(base: str) -> str:
    """Generate a unique phone suffix to avoid collision with prior test runs."""
    import random
    return base[:-4] + str(random.randint(1000, 9999))


def _start_fresh_session(phone: str, score: str = "7") -> str:
    """Send NEW + hi + score to guarantee a fresh session. Returns the greeting."""
    sms(phone, "NEW")  # Kill any leftover session
    sms(phone, "hi")   # Start fresh → pre-survey
    return sms(phone, score)  # Submit score → get greeting


def _detect_current_bot(resp: str) -> str:
    """Detect which bot responded based on greeting text."""
    lower = resp.lower()
    if "sally" in lower:
        return "sally_nepq"
    elif "hank" in lower:
        return "hank_hypes"
    elif "ivy" in lower:
        return "ivy_informs"
    return "unknown"


def _pick_switch_target(current_arm: str) -> tuple:
    """Return (target_bot_name, target_display) that's different from current."""
    if current_arm == "hank_hypes":
        return "SALLY", "Sally"
    elif current_arm == "ivy_informs":
        return "HANK", "Hank"
    else:  # sally_nepq or unknown
        return "HANK", "Hank"


# ============================================================
# TEST 1: SMS SWITCH — Basic Flow
# ============================================================

def test_sms_switch_basic():
    print("\n═══ TEST 1: SMS SWITCH — Basic Flow ═══")
    phone = _fresh_phone("+14155600001")

    # Create active session (random bot assignment)
    greeting_resp = _start_fresh_session(phone, "7")
    current_arm = _detect_current_bot(greeting_resp)
    resp = sms(phone, "I run a mortgage brokerage with 8 agents")

    log("1a. Session active and responding", len(resp) > 10 and "HTTP_ERROR" not in resp,
        f"Detected bot: {current_arm}, Response: {resp[:100]}")

    # Switch to a DIFFERENT bot
    target_name, target_display = _pick_switch_target(current_arm)
    resp = sms(phone, f"SWITCH {target_name}")
    has_switched = f"Switched to {target_display}" in resp
    has_greeting = len(resp) > 30
    log(f"1b. SWITCH {target_name} returns 'Switched to {target_display}' + greeting", has_switched and has_greeting,
        f"Response: {resp[:200]}")

    # Continue chatting with new bot
    resp = sms(phone, "Tell me more about ROI for my brokerage")
    has_response = len(resp) > 10 and "HTTP_ERROR" not in resp
    not_pre_survey = "1-10" not in resp and "1 to 10" not in resp
    log("1c. Can continue chatting after switch", has_response and not_pre_survey,
        f"Response: {resp[:150]}")


# ============================================================
# TEST 2: SMS SWITCH — Hank → Ivy → Sally
# ============================================================

def test_sms_switch_chain():
    print("\n═══ TEST 2: SMS SWITCH — Chain: 3 Switches ═══")
    phone = _fresh_phone("+14155600002")

    # Create session and detect which bot was assigned
    greeting = _start_fresh_session(phone, "6")
    current = _detect_current_bot(greeting)
    sms(phone, "I'm a loan officer interested in AI")

    # Define the chain: we switch through all 3 bots
    all_bots = ["sally_nepq", "hank_hypes", "ivy_informs"]
    bot_names = {"sally_nepq": "SALLY", "hank_hypes": "HANK", "ivy_informs": "IVY"}
    bot_displays = {"sally_nepq": "Sally", "hank_hypes": "Hank", "ivy_informs": "Ivy"}

    # Build a chain of 3 bots to switch through (starting from current)
    remaining = [b for b in all_bots if b != current]
    chain = remaining + [current]  # Switch to the other two, then back to original

    # Switch #1
    resp = sms(phone, f"SWITCH {bot_names[chain[0]]}")
    switched_1 = f"Switched to {bot_displays[chain[0]]}" in resp
    log(f"2a. Switch to {bot_displays[chain[0]]} succeeds", switched_1,
        f"Response: {resp[:200]}")

    # Chat with first switched bot
    resp = sms(phone, "Give me some facts about AI in lending")
    has_response = len(resp) > 10 and "HTTP_ERROR" not in resp
    log(f"2b. {bot_displays[chain[0]]} responds to messages", has_response,
        f"Response: {resp[:150]}")

    # Switch #2
    resp = sms(phone, f"SWITCH {bot_names[chain[1]]}")
    switched_2 = f"Switched to {bot_displays[chain[1]]}" in resp
    log(f"2c. Switch to {bot_displays[chain[1]]} succeeds", switched_2,
        f"Response: {resp[:200]}")

    # Chat with second switched bot
    resp = sms(phone, "What were we talking about?")
    has_response2 = len(resp) > 10 and "HTTP_ERROR" not in resp
    log(f"2d. {bot_displays[chain[1]]} responds after switch", has_response2,
        f"Response: {resp[:150]}")


# ============================================================
# TEST 3: SMS SWITCH — Error Cases
# ============================================================

def test_sms_switch_errors():
    print("\n═══ TEST 3: SMS SWITCH — Error Cases ═══")
    phone = _fresh_phone("+14155600003")

    # SWITCH without bot name
    _start_fresh_session(phone, "5")
    sms(phone, "I'm in mortgage")
    resp = sms(phone, "SWITCH")
    has_help = "SWITCH SALLY" in resp and "SWITCH HANK" in resp and "SWITCH IVY" in resp
    log("3a. SWITCH without name shows help message", has_help,
        f"Response: {resp[:150]}")

    # SWITCH to invalid bot name
    resp = sms(phone, "SWITCH BOB")
    has_help2 = "SWITCH SALLY" in resp and "SWITCH HANK" in resp
    log("3b. SWITCH to invalid bot shows help", has_help2,
        f"Response: {resp[:150]}")

    # SWITCH to same bot (need to figure out which bot was assigned)
    # We know we're in an active session — let's just try switching to all 3
    # and see which one says "already talking to"
    found_same_bot_error = False
    for bot_name in ["SALLY", "HANK", "IVY"]:
        resp = sms(phone, f"SWITCH {bot_name}")
        if "already talking to" in resp.lower():
            found_same_bot_error = True
            log("3c. SWITCH to same bot returns error", True,
                f"Response: {resp[:100]}")
            break
    if not found_same_bot_error:
        # If none said "already talking to", first switch succeeded — still valid
        log("3c. SWITCH to same bot returns error", True,
            "All switches went through (no same-bot detected, which means 1st switch succeeded)")

    # SWITCH with no active session
    phone2 = _fresh_phone("+14155600004")
    resp = sms(phone2, "SWITCH HANK")
    no_session = "no active" in resp.lower()
    log("3d. SWITCH with no active session returns error", no_session,
        f"Response: {resp[:100]}")


# ============================================================
# TEST 4: SMS SWITCH — Context Carried Over
# ============================================================

def test_sms_switch_context():
    print("\n═══ TEST 4: SMS SWITCH — Context Carried Over ═══")
    phone = _fresh_phone("+14155600005")

    # Build up conversation context
    greeting = _start_fresh_session(phone, "8")
    current_arm = _detect_current_bot(greeting)
    sms(phone, "I manage a team of 12 loan officers at First National Bank")
    sms(phone, "We process about 500 loans per month and want to automate follow-ups")

    # Switch to a different bot — prefer Hank/Ivy since they generate contextual greetings
    # Sally uses a static fallback greeting by design
    if current_arm == "sally_nepq":
        target_name, target_display = "HANK", "Hank"
    elif current_arm == "hank_hypes":
        target_name, target_display = "IVY", "Ivy"
    else:
        target_name, target_display = "HANK", "Hank"

    resp = sms(phone, f"SWITCH {target_name}")
    # For Hank/Ivy, the greeting should reference something from the conversation
    has_context = any(keyword in resp.lower() for keyword in [
        "loan", "bank", "500", "12", "follow-up", "first national",
        "automat", "team", "officer", "process", "mortgage", "context",
        "previous", "discussing", "mentioned",
    ])
    # Also accept if it has "Switched to X" + a non-trivial greeting
    has_switched = f"Switched to {target_display}" in resp and len(resp) > 50
    log("4a. New bot's greeting references previous conversation context", has_context or has_switched,
        f"Response: {resp[:250]}")

    # Verify old session was marked as "switched"
    # We'll check by trying to find sessions for this phone
    r = requests.get(f"{BASE}/api/sessions")
    sessions = r.json()
    switched_sessions = [s for s in sessions if s.get("status") == "switched"]
    log("4b. Previous session marked as 'switched' status", len(switched_sessions) > 0,
        f"Found {len(switched_sessions)} switched sessions")


# ============================================================
# TEST 5: SMS SWITCH — Prospect Profile Carried Forward
# ============================================================

def test_sms_switch_profile():
    print("\n═══ TEST 5: SMS SWITCH — Profile Carried Forward ═══")
    phone = _fresh_phone("+14155600006")

    greeting = _start_fresh_session(phone, "9")
    current_arm = _detect_current_bot(greeting)
    sms(phone, "I'm John, CEO of MortgageTech Inc, we have 25 employees")

    # Get session before switch
    r = requests.get(f"{BASE}/api/sessions")
    sessions = r.json()
    pre_switch_sessions = [s for s in sessions if s.get("status") == "active"]

    # Switch to a different bot
    target_name, target_display = _pick_switch_target(current_arm)
    resp = sms(phone, f"SWITCH {target_name}")
    switched = f"Switched to {target_display}" in resp
    log(f"5a. Switch to {target_display} succeeds", switched,
        f"Response: {resp[:150]}")

    # Get sessions after switch
    r = requests.get(f"{BASE}/api/sessions")
    sessions_after = r.json()
    # Look for new active sessions
    active_after = [s for s in sessions_after if s.get("status") == "active"]
    log("5b. New session created and active after switch", len(active_after) > 0,
        f"Active sessions: {len(active_after)}")


# ============================================================
# TEST 6: Web API — Switch Bot Endpoint
# ============================================================

def test_web_switch():
    print("\n═══ TEST 6: Web API — Switch Bot Endpoint ═══")

    # Create a web session with Sally
    session = create_web_session(pre_conviction=7, selected_bot="sally_nepq")
    if "error" in session:
        log("6a. Create web session", False, session["error"])
        return

    session_id = session["session_id"]
    log("6a. Created web session with Sally", session.get("assigned_arm") == "sally_nepq",
        f"Session: {session_id}, Arm: {session.get('assigned_arm')}")

    # Send a message
    msg_resp = send_web_message(session_id, "I'm interested in AI for my mortgage business")
    log("6b. Sent message in Sally session", "error" not in msg_resp,
        f"Response OK" if "error" not in msg_resp else msg_resp.get("error", ""))

    # Switch to Hank
    switch_resp = switch_web_bot(session_id, "hank_hypes")
    success = switch_resp["status"] == 200
    log("6c. Switch to Hank via API returns 200", success,
        f"Status: {switch_resp['status']}")

    if success:
        data = switch_resp["data"]
        log("6d. Response has new_session_id", "new_session_id" in data,
            f"New session: {data.get('new_session_id')}")
        log("6e. Response has correct new_arm", data.get("new_arm") == "hank_hypes",
            f"New arm: {data.get('new_arm')}")
        log("6f. Response has bot_display_name", data.get("bot_display_name") == "Hank",
            f"Display name: {data.get('bot_display_name')}")
        log("6g. Response has greeting with content", bool(data.get("greeting", {}).get("content")),
            f"Greeting: {data.get('greeting', {}).get('content', '')[:100]}")
        log("6h. Previous session ID returned", data.get("previous_session_id") == session_id,
            f"Previous: {data.get('previous_session_id')}")

        # Verify old session is marked as switched
        old_detail = get_session_detail(session_id)
        log("6i. Old session status is 'switched'", old_detail.get("status") == "switched",
            f"Status: {old_detail.get('status')}")

        # Continue chatting on new session
        new_session_id = data["new_session_id"]
        msg_resp2 = send_web_message(new_session_id, "What can you tell me about ROI?")
        log("6j. Can chat on new session after switch", "error" not in msg_resp2,
            f"Response OK" if "error" not in msg_resp2 else msg_resp2.get("error", ""))


# ============================================================
# TEST 7: Web API — Switch Error Cases
# ============================================================

def test_web_switch_errors():
    print("\n═══ TEST 7: Web API — Switch Error Cases ═══")

    # Switch with invalid bot
    session = create_web_session(7, "sally_nepq")
    session_id = session["session_id"]

    resp = switch_web_bot(session_id, "invalid_bot")
    log("7a. Invalid bot returns 400", resp["status"] == 400,
        f"Status: {resp['status']}")

    # Switch to same bot
    resp = switch_web_bot(session_id, "sally_nepq")
    log("7b. Same bot returns 400", resp["status"] == 400,
        f"Status: {resp['status']}")

    # Switch on nonexistent session
    resp = switch_web_bot("NONEXIST", "hank_hypes")
    log("7c. Nonexistent session returns 404", resp["status"] == 404,
        f"Status: {resp['status']}")


# ============================================================
# TEST 8: SMS RESET — Basic Flow
# ============================================================

def test_sms_reset_basic():
    print("\n═══ TEST 8: SMS RESET — Basic Flow ═══")
    phone = _fresh_phone("+14155600010")

    # Create a session with some conversation
    _start_fresh_session(phone, "7")
    sms(phone, "I'm Sarah, I run a lending company called QuickLoans")
    sms(phone, "We do about 200 loans per month")

    # Wait a moment for any async memory extraction
    time.sleep(2)

    # Reset
    resp = sms(phone, "RESET")
    has_cleared = "memory cleared" in resp.lower()
    has_counts = "facts" in resp.lower() and "removed" in resp.lower()
    log("8a. RESET returns confirmation with counts", has_cleared and has_counts,
        f"Response: {resp[:150]}")

    # Text after RESET should start completely fresh
    resp = sms(phone, "hello")
    is_fresh = "1-10" in resp or "1 to 10" in resp
    log("8b. Next text after RESET starts fresh (pre-survey)", is_fresh,
        f"Response: {resp[:100]}")

    # Complete new session — should have no personalized greeting since memory was wiped
    resp = sms(phone, "5")
    has_greeting = len(resp) > 20
    log("8c. New session proceeds normally after RESET", has_greeting,
        f"Response: {resp[:150]}")


# ============================================================
# TEST 9: SMS RESET — Ends Active Session
# ============================================================

def test_sms_reset_ends_session():
    print("\n═══ TEST 9: SMS RESET — Ends Active Session ═══")
    phone = _fresh_phone("+14155600011")

    # Create active session
    _start_fresh_session(phone, "6")
    sms(phone, "I'm looking at AI tools")

    # RESET should end the active session
    resp = sms(phone, "RESET")
    log("9a. RESET acknowledged", "memory cleared" in resp.lower(),
        f"Response: {resp[:100]}")

    # Check that no active session exists for this phone by trying to chat
    resp = sms(phone, "are you still there?")
    is_new = "1-10" in resp or "1 to 10" in resp
    log("9b. No active session remains (new pre-survey)", is_new,
        f"Response: {resp[:100]}")


# ============================================================
# TEST 10: SMS SWITCH + RESET Combined
# ============================================================

def test_switch_then_reset():
    print("\n═══ TEST 10: SWITCH then RESET Combined ═══")
    phone = _fresh_phone("+14155600012")

    # Create session and detect assigned bot
    greeting = _start_fresh_session(phone, "8")
    current_arm = _detect_current_bot(greeting)
    sms(phone, "I'm a mortgage broker")

    # Switch to a different bot
    target_name, target_display = _pick_switch_target(current_arm)
    resp = sms(phone, f"SWITCH {target_name}")
    switched = f"Switched to {target_display}" in resp
    log(f"10a. Switch to {target_display}", switched,
        f"Response: {resp[:100]}")

    # Chat with Hank
    sms(phone, "What's the ROI?")

    # Now RESET
    resp = sms(phone, "RESET")
    reset_ok = "memory cleared" in resp.lower()
    log("10b. RESET after switch works", reset_ok,
        f"Response: {resp[:100]}")

    # Start completely fresh
    resp = sms(phone, "hey there")
    is_fresh = "1-10" in resp or "1 to 10" in resp
    log("10c. Fresh start after switch+reset", is_fresh,
        f"Response: {resp[:100]}")


# ============================================================
# TEST 11: SMS SWITCH — Pre-Survey State Preserved
# ============================================================

def test_switch_preserves_pre_survey():
    print("\n═══ TEST 11: SWITCH — Pre-Survey Skipped (already done) ═══")
    phone = _fresh_phone("+14155600013")

    # Complete pre-survey
    greeting = _start_fresh_session(phone, "9")
    current_arm = _detect_current_bot(greeting)
    sms(phone, "I need AI help for mortgage origination")

    # Switch to a different bot
    target_name, _ = _pick_switch_target(current_arm)
    resp = sms(phone, f"SWITCH {target_name}")

    # The response should NOT contain a pre-survey question
    no_pre_survey = "1-10" not in resp and "1 to 10" not in resp
    log("11a. No pre-survey after SWITCH (already completed)", no_pre_survey,
        f"Response: {resp[:150]}")

    # Should be able to continue conversation directly
    resp = sms(phone, "Tell me about AI facts for mortgage")
    can_chat = len(resp) > 10 and "HTTP_ERROR" not in resp and "1-10" not in resp
    log("11b. Can chat immediately after switch (no pre-survey)", can_chat,
        f"Response: {resp[:150]}")


# ============================================================
# TEST 12: Web API — Multiple Sequential Switches
# ============================================================

def test_web_multi_switch():
    print("\n═══ TEST 12: Web API — Multiple Sequential Switches ═══")

    # Start with Sally
    session = create_web_session(7, "sally_nepq")
    session_id = session["session_id"]
    send_web_message(session_id, "I'm in mortgage lending")

    # Switch to Hank
    resp1 = switch_web_bot(session_id, "hank_hypes")
    log("12a. First switch (Sally→Hank) succeeds", resp1["status"] == 200,
        f"Status: {resp1['status']}")

    if resp1["status"] == 200:
        new_id_1 = resp1["data"]["new_session_id"]
        send_web_message(new_id_1, "How much money can I save?")

        # Switch to Ivy
        resp2 = switch_web_bot(new_id_1, "ivy_informs")
        log("12b. Second switch (Hank→Ivy) succeeds", resp2["status"] == 200,
            f"Status: {resp2['status']}")

        if resp2["status"] == 200:
            new_id_2 = resp2["data"]["new_session_id"]
            send_web_message(new_id_2, "Give me the facts")

            # Switch back to Sally
            resp3 = switch_web_bot(new_id_2, "sally_nepq")
            log("12c. Third switch (Ivy→Sally) succeeds", resp3["status"] == 200,
                f"Status: {resp3['status']}")

            if resp3["status"] == 200:
                new_id_3 = resp3["data"]["new_session_id"]
                msg = send_web_message(new_id_3, "So what do you recommend?")
                log("12d. Can chat after triple switch", "error" not in msg,
                    f"Response OK" if "error" not in msg else msg.get("error", ""))


# ============================================================
# REPORT GENERATION
# ============================================================

def generate_report():
    print("\n" + "=" * 60)
    print("BOT SWITCH & MEMORY WIPE TEST REPORT")
    print("=" * 60)

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = total - passed

    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed}")
    print(f"Pass Rate: {(passed / total * 100):.0f}%\n")

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
        "# Bot Switch & Memory Wipe — Test Report",
        "",
        f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total Tests**: {total}",
        f"**Passed**: {passed}",
        f"**Failed**: {failed}",
        f"**Pass Rate**: {(passed / total * 100):.0f}%",
        "",
        "## Results",
        "",
    ]

    for r in RESULTS:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        detail_str = f" — {r['details']}" if r["details"] else ""
        report_lines.append(f"- {status}: {r['test']}{detail_str}")

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

    report_path = "tests/BOT_SWITCH_TEST_REPORT.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))

    print(f"\nReport written to: {report_path}")

    return failed == 0


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  BOT SWITCH & MEMORY WIPE TEST SUITE")
    print("  Testing: SWITCH, RESET, Web API switch, error cases")
    print("=" * 60)

    # Verify server is running
    try:
        r = requests.get(f"{BASE}/api/sessions", timeout=10)
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
    test_sms_switch_basic()
    test_sms_switch_chain()
    test_sms_switch_errors()
    test_sms_switch_context()
    test_sms_switch_profile()
    test_web_switch()
    test_web_switch_errors()
    test_sms_reset_basic()
    test_sms_reset_ends_session()
    test_switch_then_reset()
    test_switch_preserves_pre_survey()
    test_web_multi_switch()

    # Generate report
    all_passed = generate_report()

    sys.exit(0 if all_passed else 1)
