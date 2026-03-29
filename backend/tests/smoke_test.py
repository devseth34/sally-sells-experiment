#!/usr/bin/env python3
"""
Sally Sells — Production Smoke Test
Run after deploying the 8-fix batch to validate everything works.

Usage:
    python3 smoke_test.py https://your-railway-url.up.railway.app
    
    # or with a local backend:
    python3 smoke_test.py http://localhost:8000
"""

import sys
import json
import time
import requests

if len(sys.argv) < 2:
    print("Usage: python3 smoke_test.py <BACKEND_URL>")
    print("Example: python3 smoke_test.py https://sally-sells-experiment-production.up.railway.app")
    sys.exit(1)

BASE = sys.argv[1].rstrip("/")
PASS = 0
FAIL = 0
WARN = 0
SESSION_IDS = []


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")
        if detail:
            print(f"     → {detail[:200]}")


def warn(name, detail=""):
    global WARN
    WARN += 1
    print(f"  ⚠️  {name}")
    if detail:
        print(f"     → {detail[:200]}")


def create_session(bot=None, experiment=False, name="SmokeTest", email="smoke@test.com"):
    payload = {
        "pre_conviction": 5,
        "participant_name": name,
        "participant_email": email,
    }
    if bot:
        payload["selected_bot"] = bot
    if experiment:
        payload["experiment_mode"] = True
    r = requests.post(f"{BASE}/api/sessions", json=payload)
    r.raise_for_status()
    data = r.json()
    SESSION_IDS.append(data["session_id"])
    return data


def send_msg(session_id, content):
    r = requests.post(f"{BASE}/api/sessions/{session_id}/messages", json={"content": content})
    return r


def end_session(session_id):
    r = requests.post(f"{BASE}/api/sessions/{session_id}/end")
    return r


# ==============================================================
print("\n" + "=" * 60)
print("SALLY SELLS — PRODUCTION SMOKE TEST")
print(f"Backend: {BASE}")
print("=" * 60)

# Health check
print("\n🔌 Health Check")
try:
    r = requests.get(f"{BASE}/", timeout=10)
    test("Backend is reachable", r.status_code == 200, f"Status: {r.status_code}")
except Exception as e:
    print(f"  ❌ Backend unreachable: {e}")
    print("     Cannot continue. Check your URL and deployment.")
    sys.exit(1)


# ==============================================================
# FIX 1: Hank responds with real content (not fallback)
# ==============================================================
print("\n🔧 Fix 1: Hank/Ivy Claude API (CRITICAL)")

try:
    hank_session = create_session(bot="hank_hypes")
    test("Hank session created", hank_session.get("session_id"))

    r = send_msg(hank_session["session_id"], "I am a loan officer in Denver closing about 12 loans a month")
    test("Hank message endpoint returns 200", r.status_code == 200, f"Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        text = data["assistant_message"]["content"]
        is_fallback = "Could you tell me more about what you" in text
        test("Hank gives real response (NOT fallback)", not is_fallback,
             f"Response: {text[:150]}")
        if not is_fallback:
            print(f"     Hank said: \"{text[:120]}...\"")

        # Send a second message to confirm sustained conversation
        r2 = send_msg(hank_session["session_id"], "We mostly do conventional and FHA loans")
        if r2.status_code == 200:
            text2 = r2.json()["assistant_message"]["content"]
            is_fallback2 = "Could you tell me more about what you" in text2
            test("Hank sustained conversation (turn 2)", not is_fallback2,
                 f"Response: {text2[:150]}")
except Exception as e:
    test("Hank session flow", False, str(e))

# Ivy
try:
    ivy_session = create_session(bot="ivy_informs")
    test("Ivy session created", ivy_session.get("session_id"))

    r = send_msg(ivy_session["session_id"], "What exactly does the 100x AI Academy teach?")
    test("Ivy message endpoint returns 200", r.status_code == 200, f"Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        text = data["assistant_message"]["content"]
        is_fallback = "Could you tell me more about what you" in text
        test("Ivy gives real response (NOT fallback)", not is_fallback,
             f"Response: {text[:150]}")
        if not is_fallback:
            print(f"     Ivy said: \"{text[:120]}...\"")
except Exception as e:
    test("Ivy session flow", False, str(e))

# Sally (should still work as before)
try:
    sally_session = create_session(bot="sally_nepq")
    test("Sally session created", sally_session.get("session_id"))

    r = send_msg(sally_session["session_id"], "I'm a mortgage broker in London")
    if r.status_code == 200:
        text = r.json()["assistant_message"]["content"]
        is_fallback = "Could you tell me more about what you" in text
        test("Sally still works (no regression)", not is_fallback,
             f"Response: {text[:150]}")
except Exception as e:
    test("Sally session flow", False, str(e))


# ==============================================================
# FIX 3: Transcript labels
# ==============================================================
print("\n🔧 Fix 3: Transcript Labels")

try:
    r = requests.get(f"{BASE}/api/export/csv")
    test("CSV export endpoint returns 200", r.status_code == 200)

    if r.status_code == 200:
        csv_text = r.text
        # Find a Hank session in the CSV
        lines = csv_text.split("\n")
        hank_lines = [l for l in lines if "hank_hypes" in l]
        if hank_lines:
            # Check if any Hank transcript has "Hank:" label
            sample = hank_lines[0]
            has_hank_label = "Hank:" in sample
            has_sally_bug = "] Sally:" in sample and "hank_hypes" in sample
            test("Hank transcripts use 'Hank:' label", has_hank_label,
                 "Hank label not found in transcript")
            test("Hank transcripts don't use 'Sally:' bug", not has_sally_bug,
                 "Still shows Sally: for Hank sessions")
        else:
            warn("No Hank sessions in CSV yet (new deployment — expected if DB was reset)")

        ivy_lines = [l for l in lines if "ivy_informs" in l]
        if ivy_lines:
            sample = ivy_lines[0]
            has_ivy_label = "Ivy:" in sample
            test("Ivy transcripts use 'Ivy:' label", has_ivy_label)
        else:
            warn("No Ivy sessions in CSV yet")
except Exception as e:
    test("CSV export", False, str(e))


# ==============================================================
# FIX 4: Session timeout + cleanup endpoint
# ==============================================================
print("\n🔧 Fix 4: Session Timeout & Cleanup")

try:
    r = requests.post(f"{BASE}/api/admin/cleanup-stale-sessions")
    test("Cleanup endpoint returns 200", r.status_code == 200, f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"     Cleaned: {data.get('cleaned', '?')} / {data.get('total_active_checked', '?')} active sessions")
except Exception as e:
    test("Cleanup endpoint", False, str(e))


# ==============================================================
# FIX 5: Exit intent detection
# ==============================================================
print("\n🔧 Fix 5: Exit Intent Detection")

try:
    exit_session = create_session(bot="hank_hypes")
    # Send a normal message first
    send_msg(exit_session["session_id"], "I'm a loan officer")
    time.sleep(1)

    # Now say "done"
    r = send_msg(exit_session["session_id"], "done")
    if r.status_code == 200:
        data = r.json()
        test("'done' triggers session_ended", data.get("session_ended") == True,
             f"session_ended={data.get('session_ended')}")
    else:
        test("Exit intent message accepted", False, f"Status: {r.status_code}")
except Exception as e:
    test("Exit intent flow", False, str(e))


# ==============================================================
# FIX 6: Balanced arm allocation
# ==============================================================
print("\n🔧 Fix 6: Balanced Arm Allocation")

try:
    arms_assigned = []
    for i in range(6):
        s = create_session(
            experiment=True,
            name=f"BalanceTest{i}",
            email=f"balance{i}@test.com",
        )
        arms_assigned.append(s.get("assigned_arm", "unknown"))
        time.sleep(0.3)

    # In experiment mode, frontend gets "experiment" as arm — check backend directly
    # We need to check via the session detail or CSV
    # For now, just verify sessions were created
    test("6 experiment sessions created", len(arms_assigned) == 6)

    # Check distribution via metrics or CSV
    r = requests.get(f"{BASE}/api/export/csv")
    if r.status_code == 200:
        csv_text = r.text
        lines = csv_text.split("\n")
        recent_experiment = [l for l in lines if "BalanceTest" in l]
        sally_count = sum(1 for l in recent_experiment if "sally_nepq" in l)
        hank_count = sum(1 for l in recent_experiment if "hank_hypes" in l)
        ivy_count = sum(1 for l in recent_experiment if "ivy_informs" in l)
        print(f"     Distribution: Sally={sally_count}, Hank={hank_count}, Ivy={ivy_count}")
        test("Arms are balanced (each has 2)", sally_count == 2 and hank_count == 2 and ivy_count == 2,
             f"Got Sally={sally_count}, Hank={hank_count}, Ivy={ivy_count} — expected 2/2/2")
except Exception as e:
    test("Balanced allocation", False, str(e))


# ==============================================================
# FIX 7: Hank non-mortgage handling
# ==============================================================
print("\n🔧 Fix 7: Hank Non-Mortgage Persona")

try:
    nm_session = create_session(bot="hank_hypes")
    r = send_msg(nm_session["session_id"], "I'm a retired teacher, not in the mortgage industry at all")
    if r.status_code == 200:
        text = r.json()["assistant_message"]["content"].lower()
        is_delusional = any(w in text for w in [
            "teaching is about to be revolutionized",
            "teachers are perfect candidates",
            "education is being transformed",
        ])
        acknowledges_mismatch = any(w in text for w in [
            "mortgage", "specifically", "fair", "understand",
            "built for", "designed for", "focused on",
        ])
        test("Hank not delusional with non-mortgage user", not is_delusional,
             f"Response: {text[:150]}")
        if acknowledges_mismatch:
            print(f"     Good: Hank acknowledged the mismatch")
        else:
            warn("Hank didn't clearly acknowledge the non-mortgage mismatch",
                 f"Response: {text[:150]}")
except Exception as e:
    test("Non-mortgage handling", False, str(e))


# ==============================================================
# FIX 8: Experiment link injection (turn-based)
# This is harder to test quickly — would need 10+ turns.
# Just verify the env var / code path exists.
# ==============================================================
print("\n🔧 Fix 8: Experiment Link Injection")
print("  ℹ️  Requires 10+ turns to trigger — skipping automated test")
print("  ℹ️  Verify manually: run 10+ turn experiment session, check for invitation link")


# ==============================================================
# FIX 2: Finish & Rate button (frontend — can't test via API)
# ==============================================================
print("\n🔧 Fix 2: Finish & Rate Button")
print("  ℹ️  Frontend-only — verify manually:")
print("     1. Open /experiment in browser")
print("     2. Complete pre-survey, send 3+ messages")
print("     3. Verify green 'Finish & Rate This Conversation' button appears")
print("     4. Click it → PostConvictionModal should open")


# ==============================================================
# CLEANUP: End all test sessions
# ==============================================================
print("\n🧹 Cleaning up test sessions...")
cleaned = 0
for sid in SESSION_IDS:
    try:
        end_session(sid)
        cleaned += 1
    except:
        pass
print(f"  Ended {cleaned}/{len(SESSION_IDS)} test sessions")


# ==============================================================
# SUMMARY
# ==============================================================
print("\n" + "=" * 60)
print(f"RESULTS: {PASS} passed, {FAIL} failed, {WARN} warnings")
print("=" * 60)

if FAIL == 0:
    print("\n🟢 ALL AUTOMATED TESTS PASSED")
    print("   Next steps:")
    print("   1. Manually verify Fix 2 (Finish & Rate button) in browser")
    print("   2. Manually verify Fix 8 (link injection after 10 turns)")
    print("   3. Run cleanup: curl -X POST {BASE}/api/admin/cleanup-stale-sessions")
    print("   4. Launch dry-run Prolific batch (3-5 participants)")
else:
    print(f"\n🔴 {FAIL} TEST(S) FAILED — DO NOT RUN PROLIFIC")
    print("   Check Railway logs for errors and fix before proceeding")

sys.exit(0 if FAIL == 0 else 1)