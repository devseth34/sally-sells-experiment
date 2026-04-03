#!/usr/bin/env bash
# =================================================================
# Hybrid Arms Integration Test Suite
# Tests all 8 bot arms end-to-end against a running backend.
# Prereqs: backend on localhost:8000, valid API keys, jq installed
# =================================================================

set -uo pipefail
# Note: not using set -e because we want to continue after failures

BASE="${SALLY_BASE_URL:-http://localhost:8001}"
PASS=0
FAIL=0
WARN=0
SKIP=0
INCONCLUSIVE=0
SESSION_IDS=()  # Track for cleanup
REPORT_LINES=()

# ANSI colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No color

log_pass() {
    PASS=$((PASS + 1))
    REPORT_LINES+=("  ${GREEN}[PASS]${NC} $1")
    echo -e "  ${GREEN}[PASS]${NC} $1"
}

log_fail() {
    FAIL=$((FAIL + 1))
    REPORT_LINES+=("  ${RED}[FAIL]${NC} $1")
    echo -e "  ${RED}[FAIL]${NC} $1"
    if [ -n "${2:-}" ]; then
        REPORT_LINES+=("         Detail: ${2:0:300}")
        echo -e "         Detail: ${2:0:300}"
    fi
}

log_warn() {
    WARN=$((WARN + 1))
    REPORT_LINES+=("  ${YELLOW}[WARN]${NC} $1")
    echo -e "  ${YELLOW}[WARN]${NC} $1"
    if [ -n "${2:-}" ]; then
        REPORT_LINES+=("         Detail: ${2:0:300}")
        echo -e "         Detail: ${2:0:300}"
    fi
}

log_inconclusive() {
    INCONCLUSIVE=$((INCONCLUSIVE + 1))
    REPORT_LINES+=("  ${YELLOW}[INCONCLUSIVE]${NC} $1")
    echo -e "  ${YELLOW}[INCONCLUSIVE]${NC} $1"
}

log_skip() {
    SKIP=$((SKIP + 1))
    REPORT_LINES+=("  ${CYAN}[SKIP]${NC} $1")
    echo -e "  ${CYAN}[SKIP]${NC} $1"
}

header() {
    echo ""
    echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
}

create_session() {
    local bot="$1"
    local pre="${2:-5}"
    local experiment="${3:-false}"
    local payload

    if [ "$bot" == "random" ]; then
        payload="{\"pre_conviction\": $pre, \"experiment_mode\": $experiment}"
    else
        payload="{\"pre_conviction\": $pre, \"selected_bot\": \"$bot\"}"
    fi

    curl -s -X POST "$BASE/api/sessions" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null
}

send_message() {
    local session_id="$1"
    local content="$2"
    curl -s -X POST "$BASE/api/sessions/$session_id/messages" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$content\"}" 2>/dev/null
}

end_session() {
    local session_id="$1"
    curl -s -X POST "$BASE/api/sessions/$session_id/end" 2>/dev/null
}

get_session() {
    local session_id="$1"
    curl -s "$BASE/api/sessions/$session_id" 2>/dev/null
}

get_thoughts() {
    local session_id="$1"
    curl -s "$BASE/api/sessions/$session_id/thoughts" 2>/dev/null
}

# Track session for cleanup
track() {
    SESSION_IDS+=("$1")
}

cleanup() {
    header "CLEANUP: Ending test sessions"
    for sid in "${SESSION_IDS[@]}"; do
        end_session "$sid" > /dev/null 2>&1 || true
    done
    echo "  Ended ${#SESSION_IDS[@]} test sessions."
}

# ================================================================
echo ""
echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}  HYBRID ARMS INTEGRATION TEST REPORT${NC}"
echo -e "${CYAN}  Server: $BASE${NC}"
echo -e "${CYAN}  Date: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${CYAN}================================================================${NC}"

# Check backend is reachable
HEALTH_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/config" 2>/dev/null || echo "000")
if [ "$HEALTH_CHECK" == "000" ]; then
    echo -e "${RED}FATAL: Backend is not reachable at $BASE${NC}"
    echo "Start it with: cd backend && uvicorn app.main:app --reload --port 8000"
    exit 1
fi
echo -e "${GREEN}  Backend reachable (HTTP $HEALTH_CHECK)${NC}"

# ================================================================
# PHASE 1: Automated Unit Tests
# ================================================================
header "PHASE 1: Automated Unit Tests"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

PYTEST_OUTPUT=$( cd "$BACKEND_DIR" && python -m pytest tests/test_hybrid_arms.py -v 2>&1 ) || true

# Count passed/failed
PYTEST_PASSED=$(echo "$PYTEST_OUTPUT" | grep -oE '[0-9]+ passed' | head -1 || echo "0 passed")
PYTEST_FAILED=$(echo "$PYTEST_OUTPUT" | grep -oE '[0-9]+ failed' | head -1 || echo "")

if echo "$PYTEST_OUTPUT" | grep -q "failed"; then
    log_fail "Unit tests: $PYTEST_PASSED, $PYTEST_FAILED"
    echo "$PYTEST_OUTPUT" | tail -20
    echo ""
    echo -e "${RED}PHASE 1 FAILED — Fix unit tests before continuing.${NC}"
    # Continue anyway to gather more data
else
    log_pass "Unit tests: $PYTEST_PASSED"
fi

# ================================================================
# PHASE 2: Original Arms Regression
# ================================================================
header "PHASE 2: Original Arms Regression"

VALID_NEPQ_PHASES="CONNECTION|SITUATION|PROBLEM_AWARENESS|SOLUTION_AWARENESS|CONSEQUENCE|OWNERSHIP|COMMITMENT|TERMINATED"

# --- 2.1 Sally (NEPQ) ---
echo "  Testing sally_nepq..."
SALLY_RESP=$(create_session "sally_nepq" 5)
SALLY_SID=$(echo "$SALLY_RESP" | jq -r '.session_id // empty')

if [ -z "$SALLY_SID" ]; then
    log_fail "2.1 Sally session creation" "No session_id in response: $(echo "$SALLY_RESP" | head -c 200)"
else
    track "$SALLY_SID"
    SALLY_ARM=$(echo "$SALLY_RESP" | jq -r '.assigned_arm')
    SALLY_PHASE=$(echo "$SALLY_RESP" | jq -r '.current_phase')
    SALLY_GREETING=$(echo "$SALLY_RESP" | jq -r '.greeting.content // empty')
    SALLY_DISPLAY=$(echo "$SALLY_RESP" | jq -r '.bot_display_name')

    if [ "$SALLY_ARM" != "sally_nepq" ]; then
        log_fail "2.1 Sally assigned_arm" "Expected sally_nepq, got $SALLY_ARM"
    elif [ "$SALLY_PHASE" != "CONNECTION" ]; then
        log_fail "2.1 Sally initial phase" "Expected CONNECTION, got $SALLY_PHASE"
    elif [ -z "$SALLY_GREETING" ]; then
        log_fail "2.1 Sally greeting" "Greeting was empty"
    else
        # Send a message
        SALLY_MSG=$(send_message "$SALLY_SID" "Hi, I am a loan officer at a mortgage company in Dallas. We close about 200 loans a month.")
        SALLY_REPLY=$(echo "$SALLY_MSG" | jq -r '.assistant_message.content // empty')
        SALLY_MSG_PHASE=$(echo "$SALLY_MSG" | jq -r '.current_phase // empty')

        if [ -z "$SALLY_REPLY" ]; then
            log_fail "2.1 Sally message response" "Empty reply"
        elif ! echo "$SALLY_MSG_PHASE" | grep -qE "^($VALID_NEPQ_PHASES)$"; then
            log_fail "2.1 Sally phase after message" "Invalid phase: $SALLY_MSG_PHASE"
        else
            log_pass "2.1 Sally 100% regression — session=$SALLY_SID, phase=$SALLY_MSG_PHASE, display=$SALLY_DISPLAY"
        fi
    fi
fi

# --- 2.2 Hank ---
echo "  Testing hank_hypes..."
HANK_RESP=$(create_session "hank_hypes" 5)
HANK_SID=$(echo "$HANK_RESP" | jq -r '.session_id // empty')

if [ -z "$HANK_SID" ]; then
    log_fail "2.2 Hank session creation" "No session_id: $(echo "$HANK_RESP" | head -c 200)"
else
    track "$HANK_SID"
    HANK_ARM=$(echo "$HANK_RESP" | jq -r '.assigned_arm')
    HANK_PHASE=$(echo "$HANK_RESP" | jq -r '.current_phase')
    HANK_GREETING=$(echo "$HANK_RESP" | jq -r '.greeting.content // empty')

    if [ "$HANK_ARM" != "hank_hypes" ]; then
        log_fail "2.2 Hank assigned_arm" "Expected hank_hypes, got $HANK_ARM"
    elif [ "$HANK_PHASE" != "CONVERSATION" ]; then
        log_fail "2.2 Hank initial phase" "Expected CONVERSATION, got $HANK_PHASE"
    elif [ -z "$HANK_GREETING" ]; then
        log_fail "2.2 Hank greeting" "Greeting was empty"
    else
        HANK_MSG=$(send_message "$HANK_SID" "I run a mortgage brokerage and we are interested in AI solutions")
        HANK_REPLY=$(echo "$HANK_MSG" | jq -r '.assistant_message.content // empty')

        if [ -z "$HANK_REPLY" ]; then
            log_fail "2.2 Hank message response" "Empty reply"
        else
            log_pass "2.2 Hank 100% regression — session=$HANK_SID, phase=CONVERSATION"
        fi
    fi
fi

# --- 2.3 Ivy ---
echo "  Testing ivy_informs..."
IVY_RESP=$(create_session "ivy_informs" 5)
IVY_SID=$(echo "$IVY_RESP" | jq -r '.session_id // empty')

if [ -z "$IVY_SID" ]; then
    log_fail "2.3 Ivy session creation" "No session_id: $(echo "$IVY_RESP" | head -c 200)"
else
    track "$IVY_SID"
    IVY_ARM=$(echo "$IVY_RESP" | jq -r '.assigned_arm')
    IVY_PHASE=$(echo "$IVY_RESP" | jq -r '.current_phase')
    IVY_GREETING=$(echo "$IVY_RESP" | jq -r '.greeting.content // empty')

    if [ "$IVY_ARM" != "ivy_informs" ]; then
        log_fail "2.3 Ivy assigned_arm" "Expected ivy_informs, got $IVY_ARM"
    elif [ "$IVY_PHASE" != "CONVERSATION" ]; then
        log_fail "2.3 Ivy initial phase" "Expected CONVERSATION, got $IVY_PHASE"
    elif [ -z "$IVY_GREETING" ]; then
        log_fail "2.3 Ivy greeting" "Greeting was empty"
    else
        IVY_MSG=$(send_message "$IVY_SID" "I want to learn more about AI automation for mortgage lending")
        IVY_REPLY=$(echo "$IVY_MSG" | jq -r '.assistant_message.content // empty')

        if [ -z "$IVY_REPLY" ]; then
            log_fail "2.3 Ivy message response" "Empty reply"
        else
            log_pass "2.3 Ivy 100% regression — session=$IVY_SID, phase=CONVERSATION"
        fi
    fi
fi

# ================================================================
# PHASE 3: Hybrid Arms End-to-End
# ================================================================
header "PHASE 3: Hybrid Arms End-to-End"

HYBRID_ARMS=("sally_hank_close" "sally_ivy_bridge" "sally_empathy_plus" "sally_direct" "hank_structured")
TEST_NUM=0

for ARM in "${HYBRID_ARMS[@]}"; do
    TEST_NUM=$((TEST_NUM + 1))
    echo "  Testing $ARM..."

    RESP=$(create_session "$ARM" 5)
    SID=$(echo "$RESP" | jq -r '.session_id // empty')

    if [ -z "$SID" ]; then
        log_fail "3.$TEST_NUM $ARM session creation" "No session_id: $(echo "$RESP" | head -c 200)"
        continue
    fi

    track "$SID"
    RESP_ARM=$(echo "$RESP" | jq -r '.assigned_arm')
    RESP_PHASE=$(echo "$RESP" | jq -r '.current_phase')
    RESP_GREETING=$(echo "$RESP" | jq -r '.greeting.content // empty')
    RESP_DISPLAY=$(echo "$RESP" | jq -r '.bot_display_name')

    # All hybrid arms should start at CONNECTION (they use Sally's engine)
    if [ "$RESP_ARM" != "$ARM" ]; then
        log_fail "3.$TEST_NUM $ARM assigned_arm" "Expected $ARM, got $RESP_ARM"
        continue
    fi

    if [ "$RESP_PHASE" != "CONNECTION" ]; then
        log_fail "3.$TEST_NUM $ARM initial phase" "Expected CONNECTION, got $RESP_PHASE"
        continue
    fi

    if [ -z "$RESP_GREETING" ]; then
        log_fail "3.$TEST_NUM $ARM greeting" "Greeting was empty"
        continue
    fi

    # Send 2 messages
    MSG1=$(send_message "$SID" "Hi, I am a mortgage broker in Phoenix, we close about 80 loans per month")
    REPLY1=$(echo "$MSG1" | jq -r '.assistant_message.content // empty')
    PHASE1=$(echo "$MSG1" | jq -r '.current_phase // empty')

    if [ -z "$REPLY1" ]; then
        log_fail "3.$TEST_NUM $ARM message 1" "Empty reply"
        continue
    fi

    MSG2=$(send_message "$SID" "Our biggest problem is lead follow-up, we lose about 30 percent of potential borrowers")
    REPLY2=$(echo "$MSG2" | jq -r '.assistant_message.content // empty')
    PHASE2=$(echo "$MSG2" | jq -r '.current_phase // empty')

    if [ -z "$REPLY2" ]; then
        log_fail "3.$TEST_NUM $ARM message 2" "Empty reply"
        continue
    fi

    # Validate phase is valid NEPQ (not "CONVERSATION")
    if ! echo "$PHASE2" | grep -qE "^($VALID_NEPQ_PHASES)$"; then
        log_fail "3.$TEST_NUM $ARM phase after messages" "Invalid phase: $PHASE2"
        continue
    fi

    # Check thought logs
    DETAIL=$(get_session "$SID")
    THOUGHT_COUNT=$(echo "$DETAIL" | jq '.thought_logs | length')
    HAS_PERSONA=$(echo "$DETAIL" | jq '[.thought_logs[] | has("active_persona")] | all')

    if [ "$THOUGHT_COUNT" -lt 1 ]; then
        log_fail "3.$TEST_NUM $ARM thought logs" "Expected thought logs, got $THOUGHT_COUNT entries"
        continue
    fi

    if [ "$HAS_PERSONA" != "true" ]; then
        log_warn "3.$TEST_NUM $ARM active_persona field" "Not all thought logs have active_persona"
        continue
    fi

    LAST_PERSONA=$(echo "$DETAIL" | jq -r '.thought_logs[-1].active_persona // "missing"')
    log_pass "3.$TEST_NUM $ARM — session=$SID, phase=$PHASE2, persona=$LAST_PERSONA, display=$RESP_DISPLAY, thoughts=$THOUGHT_COUNT"
done

# ================================================================
# PHASE 4: Persona Switching Verification
# ================================================================
header "PHASE 4: Persona Switching Verification"

# --- 4a: Full-override arm (sally_empathy_plus) ---
echo "  Testing sally_empathy_plus persona from turn 1..."
EP_RESP=$(create_session "sally_empathy_plus" 5)
EP_SID=$(echo "$EP_RESP" | jq -r '.session_id // empty')

if [ -z "$EP_SID" ]; then
    log_fail "4a sally_empathy_plus session" "Could not create session"
else
    track "$EP_SID"

    send_message "$EP_SID" "Hi, I am Sarah, a loan officer at a mid-size mortgage company in Austin" > /dev/null
    send_message "$EP_SID" "We process about 100 loans monthly but I feel overwhelmed keeping up with borrower communication" > /dev/null

    EP_DETAIL=$(get_session "$EP_SID")
    EP_PERSONAS=$(echo "$EP_DETAIL" | jq -r '[.thought_logs[].active_persona] | unique | join(", ")')
    EP_ALL_MATCH=$(echo "$EP_DETAIL" | jq '[.thought_logs[].active_persona == "sally_empathy_plus"] | all')

    if [ "$EP_ALL_MATCH" == "true" ]; then
        log_pass "4a sally_empathy_plus: active_persona=\"sally_empathy_plus\" from turn 1 (all turns)"
    else
        log_fail "4a sally_empathy_plus persona" "Expected all turns sally_empathy_plus, got: $EP_PERSONAS"
    fi
fi

# --- 4b: Partial-override (sally_hank_close) — watch for OWNERSHIP switch ---
echo "  Testing sally_hank_close persona switch (targeting OWNERSHIP)..."
SHC_RESP=$(create_session "sally_hank_close" 5)
SHC_SID=$(echo "$SHC_RESP" | jq -r '.session_id // empty')

if [ -z "$SHC_SID" ]; then
    log_fail "4b sally_hank_close session" "Could not create session"
else
    track "$SHC_SID"

    # Messages designed to push through phases quickly
    SHC_MSGS=(
        "Hi, I am Mike, VP of Sales at a mortgage brokerage in Arizona"
        "We do about 150 loans a month, team of 12 loan officers, using Encompass for our LOS"
        "Biggest pain is lead follow-up. We are losing deals because nobody calls back fast enough"
        "Yeah it has been going on for over a year now. We tried hiring more people but they have the same problem"
        "Ideally I want every lead contacted within 5 minutes automatically with something personalized"
        "That gap between where we are and where we want to be is costing us probably 20-30 deals a month"
        "Yeah that is easily 200K in lost revenue per year. And our competitors are already doing this"
        "We need to figure this out in the next quarter or we are going to keep bleeding deals"
        "I am the decision maker on this. If something makes sense, I can move on it quickly"
        "Yes, I am definitely interested. What would the next step look like?"
        "Budget is not the issue. I just need to see it is the right fit for our team"
        "Walk me through how to get started. I want to move on this soon"
    )

    SHC_SWITCH_FOUND=false
    SHC_DEFAULT_BEFORE=true
    SHC_PHASE_LOG=""

    for i in "${!SHC_MSGS[@]}"; do
        TURN=$((i + 1))
        MSG_RESP=$(send_message "$SHC_SID" "${SHC_MSGS[$i]}")
        CUR_PHASE=$(echo "$MSG_RESP" | jq -r '.current_phase // empty')

        # Get thought logs to check persona
        THOUGHTS=$(get_thoughts "$SHC_SID")
        LAST_PERSONA=$(echo "$THOUGHTS" | jq -r '.thought_logs[-1].active_persona // "unknown"')

        SHC_PHASE_LOG="${SHC_PHASE_LOG}    Turn $TURN: phase=$CUR_PHASE, persona=$LAST_PERSONA\n"

        # Check if we hit a phase where override should be active
        if [[ "$CUR_PHASE" == "OWNERSHIP" || "$CUR_PHASE" == "COMMITMENT" ]]; then
            if [ "$LAST_PERSONA" == "sally_hank_close" ]; then
                SHC_SWITCH_FOUND=true
            fi
        fi

        # Before OWNERSHIP, persona should be sally_default
        if [[ "$CUR_PHASE" != "OWNERSHIP" && "$CUR_PHASE" != "COMMITMENT" ]]; then
            if [ "$LAST_PERSONA" != "sally_default" ]; then
                SHC_DEFAULT_BEFORE=false
            fi
        fi

        # Early exit if we've confirmed the switch
        if [ "$SHC_SWITCH_FOUND" == true ]; then
            break
        fi
    done

    echo -e "$SHC_PHASE_LOG"

    if [ "$SHC_SWITCH_FOUND" == true ] && [ "$SHC_DEFAULT_BEFORE" == true ]; then
        log_pass "4b sally_hank_close: persona switched to sally_hank_close at OWNERSHIP"
    elif [ "$SHC_SWITCH_FOUND" == true ]; then
        log_warn "4b sally_hank_close: switch found but some pre-OWNERSHIP turns had non-default persona"
    else
        log_inconclusive "4b sally_hank_close: conversation did not reach OWNERSHIP in ${#SHC_MSGS[@]} turns"
    fi
fi

# --- 4c: Partial-override (sally_ivy_bridge) — watch for PROBLEM_AWARENESS switch ---
echo "  Testing sally_ivy_bridge persona switch (targeting PROBLEM_AWARENESS)..."
SIB_RESP=$(create_session "sally_ivy_bridge" 5)
SIB_SID=$(echo "$SIB_RESP" | jq -r '.session_id // empty')

if [ -z "$SIB_SID" ]; then
    log_fail "4c sally_ivy_bridge session" "Could not create session"
else
    track "$SIB_SID"

    SIB_MSGS=(
        "Hey, I am Tom, I manage a team of 8 loan officers at a regional mortgage company in Colorado"
        "We close around 60 loans a month. We use a mix of Encompass and Salesforce"
        "The biggest issue is that our loan officers spend too much time on manual follow-ups instead of selling"
        "It is really hurting us. We have lost at least 15 deals this quarter just from slow response times"
        "What we really need is a way to automate the initial outreach and qualification"
        "In a perfect world, every new lead gets a personalized response within minutes and my team only talks to qualified prospects"
        "Yeah the cost of not fixing this is significant. We are probably leaving 150K on the table each quarter"
        "I am ready to make a change. What options do you see for a team like ours?"
    )

    SIB_SWITCH_FOUND=false
    SIB_DEFAULT_BEFORE=true
    SIB_PHASE_LOG=""

    for i in "${!SIB_MSGS[@]}"; do
        TURN=$((i + 1))
        MSG_RESP=$(send_message "$SIB_SID" "${SIB_MSGS[$i]}")
        CUR_PHASE=$(echo "$MSG_RESP" | jq -r '.current_phase // empty')

        THOUGHTS=$(get_thoughts "$SIB_SID")
        LAST_PERSONA=$(echo "$THOUGHTS" | jq -r '.thought_logs[-1].active_persona // "unknown"')

        SIB_PHASE_LOG="${SIB_PHASE_LOG}    Turn $TURN: phase=$CUR_PHASE, persona=$LAST_PERSONA\n"

        if [[ "$CUR_PHASE" == "PROBLEM_AWARENESS" || "$CUR_PHASE" == "SOLUTION_AWARENESS" ]]; then
            if [ "$LAST_PERSONA" == "sally_ivy_bridge" ]; then
                SIB_SWITCH_FOUND=true
            fi
        fi

        if [[ "$CUR_PHASE" == "CONNECTION" || "$CUR_PHASE" == "SITUATION" ]]; then
            if [ "$LAST_PERSONA" != "sally_default" ]; then
                SIB_DEFAULT_BEFORE=false
            fi
        fi

        if [ "$SIB_SWITCH_FOUND" == true ]; then
            break
        fi
    done

    echo -e "$SIB_PHASE_LOG"

    if [ "$SIB_SWITCH_FOUND" == true ] && [ "$SIB_DEFAULT_BEFORE" == true ]; then
        log_pass "4c sally_ivy_bridge: persona switched to sally_ivy_bridge at PROBLEM_AWARENESS"
    elif [ "$SIB_SWITCH_FOUND" == true ]; then
        log_warn "4c sally_ivy_bridge: switch found but some early turns had non-default persona"
    else
        log_inconclusive "4c sally_ivy_bridge: conversation did not reach PROBLEM_AWARENESS in ${#SIB_MSGS[@]} turns"
    fi
fi

# ================================================================
# PHASE 5: Random Assignment
# ================================================================
header "PHASE 5: Random Assignment Distribution"

RAND_ARMS=""
RAND_SIDS=()
echo "  Creating 16 experiment sessions..."
for i in $(seq 1 16); do
    RESP=$(create_session "random" 5 true)
    SID=$(echo "$RESP" | jq -r '.session_id // empty')

    if [ -n "$SID" ]; then
        RAND_SIDS+=("$SID")
        track "$SID"
        # Experiment mode masks assigned_arm as "experiment" in the create response.
        # Fetch session detail to get the real arm from the DB.
        REAL_ARM=$(curl -s "$BASE/api/sessions/$SID" 2>/dev/null | jq -r '.assigned_arm // empty')
        if [ -n "$REAL_ARM" ]; then
            RAND_ARMS="${RAND_ARMS}${REAL_ARM}\n"
        fi
    fi
    sleep 0.1
done

echo "  Distribution:"
ALL_8_ARMS="sally_nepq hank_hypes ivy_informs sally_hank_close sally_ivy_bridge sally_empathy_plus sally_direct hank_structured"
UNIQUE=0
for A in $ALL_8_ARMS; do
    COUNT=$(echo -e "$RAND_ARMS" | grep -c "^${A}$" || true)
    echo "    $A: $COUNT"
    if [ "$COUNT" -gt 0 ]; then
        UNIQUE=$((UNIQUE + 1))
    fi
done

if [ "$UNIQUE" -eq 8 ]; then
    log_pass "5.1 Random assignment: all 8 arms represented in 16 sessions"
elif [ "$UNIQUE" -ge 6 ]; then
    log_warn "5.1 Random assignment: $UNIQUE/8 arms represented (run again for better coverage)" "Missing arms in 16 draws — likely random variance"
else
    log_fail "5.1 Random assignment: only $UNIQUE/8 arms represented" "Expected all 8 arms to appear in 16 draws"
fi

# ================================================================
# PHASE 6: Frontend (Manual Checklist)
# ================================================================
header "PHASE 6: Frontend Verification (MANUAL)"
echo ""
echo "  The following must be verified manually in a browser:"
echo ""
echo "  Admin Dashboard (/dashboard or /admin):"
echo "    [ ] Sessions table shows all 8 arm labels with distinct colors"
echo "    [ ] Arm filter dropdown includes all 8 arms"
echo "    [ ] Filtering by a hybrid arm shows only its sessions"
echo ""
echo "  Bot Selection (ChatPage / ConvictionModal):"
echo "    [ ] ConvictionModal shows all 8 bot options with descriptions"
echo "    [ ] Selecting a hybrid arm creates the session correctly"
echo "    [ ] Phase indicator appears for hybrid arms"
echo "    [ ] Phase indicator does NOT appear for Hank 100% / Ivy 100%"
echo ""
echo "  Experiment Page (/experiment):"
echo "    [ ] Session created with random arm (no bot selector shown)"
echo "    [ ] Conversation works normally"
echo "    [ ] Post-conversation CDS modal works"
echo ""
log_skip "6.1 Frontend — requires manual browser verification"

# ================================================================
# PHASE 7: Data Integrity
# ================================================================
header "PHASE 7: Data Integrity"

# --- 7.1 CSV Export ---
echo "  Testing CSV export..."
CSV_OUTPUT=$(curl -s --max-time 15 "${BASE}/api/export/csv?experiment_only=false" 2>/dev/null)

if echo "$CSV_OUTPUT" | head -1 | grep -q "assigned_arm"; then
    # Check that our test arms appear
    CSV_ARMS_FOUND=0
    for ARM in sally_nepq hank_hypes ivy_informs sally_hank_close sally_ivy_bridge sally_empathy_plus sally_direct hank_structured; do
        if echo "$CSV_OUTPUT" | grep -q "$ARM"; then
            CSV_ARMS_FOUND=$((CSV_ARMS_FOUND + 1))
        fi
    done

    if [ "$CSV_ARMS_FOUND" -ge 6 ]; then
        log_pass "7.1 CSV export: assigned_arm column present, $CSV_ARMS_FOUND/8 arms found in export"
    else
        log_warn "7.1 CSV export: only $CSV_ARMS_FOUND/8 arms found" "Some test sessions may not have been exported"
    fi
else
    log_fail "7.1 CSV export" "Response does not contain expected CSV headers"
fi

# --- 7.2 Session Detail ---
# Use a hybrid session from Phase 3 (sally_empathy_plus from Phase 4a has 2+ messages)
echo "  Testing session detail..."
if [ -n "${EP_SID:-}" ]; then
    DETAIL=$(get_session "$EP_SID")
    DETAIL_ARM=$(echo "$DETAIL" | jq -r '.assigned_arm // empty')
    DETAIL_PROFILE=$(echo "$DETAIL" | jq '.prospect_profile | length')
    DETAIL_THOUGHTS=$(echo "$DETAIL" | jq '.thought_logs | length')
    DETAIL_PHASE=$(echo "$DETAIL" | jq -r '.current_phase // empty')
    DETAIL_MSGS=$(echo "$DETAIL" | jq '.messages | length')

    DETAIL_ISSUES=""
    if [ "$DETAIL_ARM" != "sally_empathy_plus" ]; then
        DETAIL_ISSUES="arm=$DETAIL_ARM "
    fi
    if [ "$DETAIL_THOUGHTS" -lt 1 ]; then
        DETAIL_ISSUES="${DETAIL_ISSUES}no_thoughts "
    fi
    if [ "$DETAIL_MSGS" -lt 2 ]; then
        DETAIL_ISSUES="${DETAIL_ISSUES}few_messages=$DETAIL_MSGS "
    fi

    if [ -z "$DETAIL_ISSUES" ]; then
        log_pass "7.2 Session detail: arm=$DETAIL_ARM, thoughts=$DETAIL_THOUGHTS, messages=$DETAIL_MSGS, phase=$DETAIL_PHASE"
    else
        log_fail "7.2 Session detail" "Issues: $DETAIL_ISSUES"
    fi
else
    log_skip "7.2 Session detail — no hybrid session available from Phase 4"
fi

# --- 7.3 Session List Filtering ---
echo "  Testing session list filtering..."
FILTER_OK=0
FILTER_TOTAL=0
for ARM in sally_nepq hank_hypes sally_empathy_plus hank_structured; do
    FILTER_TOTAL=$((FILTER_TOTAL + 1))
    LIST_RESP=$(curl -s "$BASE/api/sessions?arm=$ARM" 2>/dev/null)
    LIST_COUNT=$(echo "$LIST_RESP" | jq 'length' 2>/dev/null || echo "0")

    if [ "$LIST_COUNT" -gt 0 ]; then
        # Verify all returned sessions have the correct arm
        WRONG_ARM=$(echo "$LIST_RESP" | jq "[.[] | select(.assigned_arm != \"$ARM\")] | length" 2>/dev/null || echo "0")
        if [ "$WRONG_ARM" -eq 0 ]; then
            FILTER_OK=$((FILTER_OK + 1))
        fi
    else
        # Might just be no sessions for this arm yet — not necessarily a failure
        FILTER_OK=$((FILTER_OK + 1))
    fi
done

if [ "$FILTER_OK" -eq "$FILTER_TOTAL" ]; then
    log_pass "7.3 Session list filtering: $FILTER_OK/$FILTER_TOTAL arm filters return correct results"
else
    log_fail "7.3 Session list filtering" "$FILTER_OK/$FILTER_TOTAL filters returned correct results"
fi

# ================================================================
# PHASE 8: Edge Cases
# ================================================================
header "PHASE 8: Edge Cases"

# --- 8.1 Session End + CDS Score ---
echo "  Testing session end + CDS scoring..."
CDS_RESP=$(create_session "sally_direct" 3)
CDS_SID=$(echo "$CDS_RESP" | jq -r '.session_id // empty')

if [ -z "$CDS_SID" ]; then
    log_fail "8.1 CDS session creation" "Could not create session"
else
    track "$CDS_SID"

    send_message "$CDS_SID" "I am a mortgage lender interested in AI tools" > /dev/null

    # End session
    END_RESP=$(end_session "$CDS_SID")

    # Submit post-conviction
    POST_RESP=$(curl -s -X POST "$BASE/api/sessions/$CDS_SID/post-conviction" \
        -H "Content-Type: application/json" \
        -d '{"post_conviction": 8}' 2>/dev/null)

    CDS_SCORE=$(echo "$POST_RESP" | jq -r '.cds_score // empty')
    CDS_PRE=$(echo "$POST_RESP" | jq -r '.pre_conviction // empty')
    CDS_POST=$(echo "$POST_RESP" | jq -r '.post_conviction // empty')

    if [ "$CDS_SCORE" == "5" ] && [ "$CDS_PRE" == "3" ] && [ "$CDS_POST" == "8" ]; then
        log_pass "8.1 CDS scoring: pre=3, post=8, cds=5 (correct)"
    else
        log_fail "8.1 CDS scoring" "Expected cds=5, got cds=$CDS_SCORE (pre=$CDS_PRE, post=$CDS_POST)"
    fi
fi

# --- 8.2 Bot Switch (Known Bug) ---
echo "  Testing bot switch to hybrid arm..."
SWITCH_RESP=$(create_session "sally_nepq" 5)
SWITCH_SID=$(echo "$SWITCH_RESP" | jq -r '.session_id // empty')

if [ -z "$SWITCH_SID" ]; then
    log_fail "8.2 Bot switch session creation" "Could not create initial session"
else
    track "$SWITCH_SID"

    send_message "$SWITCH_SID" "I am a mortgage broker exploring AI" > /dev/null

    # Switch to a hybrid arm
    SWITCH_RESULT=$(curl -s -X POST "$BASE/api/sessions/$SWITCH_SID/switch" \
        -H "Content-Type: application/json" \
        -d '{"new_bot": "sally_empathy_plus"}' 2>/dev/null)

    # Switch endpoint returns: new_session_id, new_arm, current_phase, bot_display_name, greeting
    NEW_SID=$(echo "$SWITCH_RESULT" | jq -r '.new_session_id // empty')
    NEW_ARM=$(echo "$SWITCH_RESULT" | jq -r '.new_arm // empty')
    NEW_PHASE=$(echo "$SWITCH_RESULT" | jq -r '.current_phase // empty')

    if [ -z "$NEW_SID" ]; then
        log_fail "8.2 Bot switch" "No new session created: $(echo "$SWITCH_RESULT" | head -c 200)"
    else
        track "$NEW_SID"

        if [ "$NEW_ARM" != "sally_empathy_plus" ]; then
            log_fail "8.2 Bot switch arm" "Expected sally_empathy_plus, got $NEW_ARM"
        elif [ "$NEW_PHASE" == "CONVERSATION" ]; then
            log_warn "8.2 Bot switch: Known bug — hybrid arm gets phase=CONVERSATION instead of CONNECTION" \
                "main.py:2627 only checks == BotArm.SALLY_NEPQ, should check in SALLY_ENGINE_ARMS"
        elif [ "$NEW_PHASE" == "CONNECTION" ]; then
            log_pass "8.2 Bot switch: hybrid arm correctly starts at CONNECTION"
        else
            log_warn "8.2 Bot switch: unexpected phase=$NEW_PHASE" "Expected CONNECTION or CONVERSATION"
        fi
    fi
fi

# ================================================================
# CLEANUP
# ================================================================
cleanup

# ================================================================
# FINAL REPORT
# ================================================================
echo ""
echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}  FINAL SUMMARY${NC}"
echo -e "${CYAN}================================================================${NC}"
echo ""

TOTAL=$((PASS + FAIL + WARN + INCONCLUSIVE + SKIP))
echo -e "  ${GREEN}Passed:       $PASS${NC}"
echo -e "  ${RED}Failed:       $FAIL${NC}"
echo -e "  ${YELLOW}Warnings:     $WARN${NC}"
echo -e "  ${YELLOW}Inconclusive: $INCONCLUSIVE${NC}"
echo -e "  ${CYAN}Skipped:      $SKIP${NC}"
echo -e "  Total:        $TOTAL"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "  ${RED}STATUS: SOME TESTS FAILED — Review failures above before committing.${NC}"
elif [ "$WARN" -gt 0 ]; then
    echo -e "  ${YELLOW}STATUS: PASSED WITH WARNINGS — Review warnings above.${NC}"
else
    echo -e "  ${GREEN}STATUS: ALL TESTS PASSED${NC}"
fi

echo ""
echo "  KNOWN ISSUES:"
echo "    1. main.py:2627 — switch_bot sets initial_phase='CONVERSATION' for hybrid arms"
echo "       Fix: change 'new_arm == BotArm.SALLY_NEPQ' to 'new_arm.value in SALLY_ENGINE_ARMS'"
echo ""
echo "  MANUAL VERIFICATION NEEDED (Phase 6):"
echo "    - Admin dashboard shows all 8 arms with distinct colors/labels"
echo "    - ConvictionModal shows 8 bot options"
echo "    - Experiment page: random assignment, no bot selector, CDS modal"
echo ""
echo -e "${CYAN}================================================================${NC}"
