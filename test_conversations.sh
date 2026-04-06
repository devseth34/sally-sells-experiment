#!/usr/bin/env bash
# =============================================================================
# Sally NEPQ Conversation Quality Test Scripts
# =============================================================================

API_BASE="${API_BASE:-http://localhost:8000}"
DELAY="${DELAY:-2}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

create_session() {
    local response
    response=$(curl -s -X POST "$API_BASE/api/sessions" \
        -H "Content-Type: application/json" \
        -d '{"pre_conviction": 5, "selected_bot": "sally_nepq"}')

    SESSION_ID=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])" 2>/dev/null)
    GREETING=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('greeting',{}).get('content','[no greeting]') if isinstance(d.get('greeting'),dict) else d.get('greeting','[no greeting]'))" 2>/dev/null)

    if [ -z "$SESSION_ID" ]; then
        echo -e "${RED}ERROR: Failed to create session. Response:${NC}"
        echo "$response"
        exit 1
    fi

    echo -e "${GREEN}Session created: $SESSION_ID${NC}"
    echo -e "${CYAN}Sally:${NC} $GREETING"
    echo ""
}

send_message() {
    local turn_num="$1"
    local user_msg="$2"
    local expect_note="$3"

    echo -e "${BOLD}--- Turn $turn_num ---${NC}"
    if [ -n "$expect_note" ]; then
        echo -e "${YELLOW}EXPECT: $expect_note${NC}"
    fi
    echo -e "${BOLD}User:${NC} $user_msg"

    local response
    response=$(curl -s -X POST "$API_BASE/api/sessions/$SESSION_ID/messages" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$user_msg\"}")

    local sally_msg phase prev_phase phase_changed
    sally_msg=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['assistant_message']['content'])" 2>/dev/null)
    phase=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['current_phase'])" 2>/dev/null)
    prev_phase=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('previous_phase','?'))" 2>/dev/null)
    phase_changed=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('phase_changed', False))" 2>/dev/null)

    echo -e "${CYAN}Sally:${NC} $sally_msg"
    echo -e "  Phase: $prev_phase -> $phase (changed=$phase_changed)"
    echo ""

    sleep "$DELAY"
}

fetch_thoughts() {
    echo -e "${BOLD}=== THOUGHT LOG SUMMARY ===${NC}"
    local thoughts
    thoughts=$(curl -s "$API_BASE/api/sessions/$SESSION_ID")

    echo "$thoughts" | python3 -c "
import sys, json
data = json.load(sys.stdin)
logs = data.get('thought_logs', [])
for log in logs:
    t = log.get('turn_number', '?')
    comp = log.get('comprehension', {})
    dec = log.get('decision', {})
    print(f\"Turn {t}:\")
    print(f\"  Intent: {comp.get('user_intent','?')}  Richness: {comp.get('response_richness','?')}  Depth: {comp.get('emotional_depth','?')}\")
    print(f\"  Tone: {comp.get('emotional_tone','?')}  Energy: {comp.get('energy_level','?')}\")
    print(f\"  Mirror phrases: {comp.get('prospect_exact_words', [])}\")
    print(f\"  New info: {comp.get('new_information','?')}  Exit eval: {comp.get('exit_evaluation',{}).get('criteria_met_count','?')}/{comp.get('exit_evaluation',{}).get('criteria_total_count','?')}\")
    print(f\"  Decision: {dec.get('action','?')} -> {dec.get('target_phase','?')}\")
    print(f\"  Reason: {dec.get('reason','?')}\")
    print()
" 2>/dev/null

    echo ""
}

test1() {
    echo ""
    echo -e "${BOLD}================================================================${NC}"
    echo -e "${BOLD}  TEST 1: Thin/Disengaged Participant${NC}"
    echo -e "${BOLD}================================================================${NC}"
    echo ""

    create_session

    send_message 1 "just looking to upskill" \
        "Thin response. Sally should still engage warmly."

    send_message 2 "ai and data" \
        "Still thin. 2 of 3 CONNECTION criteria likely met."

    send_message 3 "head of mortgage" \
        "CRITICAL: All 3 CONNECTION criteria met. Engagement gate should HOLD (thin+low energy+retry_count==0)."

    send_message 4 "just been doing it for years" \
        "Gate already fired. Should now advance to SITUATION."

    send_message 5 "20 people" \
        "Thin SITUATION response. Mirror '20 people' naturally."

    send_message 6 "just running around in meetings" \
        "CRITICAL: Empathy directive should fire (frustrated/low energy)."

    send_message 7 "just coordinating" \
        "CRITICAL: Disengagement detection. Should get A/B scenario question."

    send_message 8 "yeah" \
        "If fallback fires, should produce phase-appropriate fallback."

    fetch_thoughts

    echo -e "${GREEN}TEST 1 COMPLETE. Session: $SESSION_ID${NC}"
    echo ""
}

test2() {
    echo ""
    echo -e "${BOLD}================================================================${NC}"
    echo -e "${BOLD}  TEST 2: Engaged Participant${NC}"
    echo -e "${BOLD}================================================================${NC}"
    echo ""

    create_session

    send_message 1 "hey! I saw something about this on LinkedIn and figured I'd check it out. I run a mortgage brokerage and we're trying to figure out how to use AI better" \
        "Rich response. Should satisfy 2-3 CONNECTION criteria. No engagement gate."

    send_message 2 "yeah I'm the CEO, we have about 40 loan officers and a bunch of support staff. been in the industry about 15 years" \
        "Rich, all CONNECTION criteria met. Should ADVANCE without engagement gate."

    send_message 3 "honestly our biggest thing is the loan processing pipeline. we get maybe 200 applications a month and my team spends half their time just chasing documents and doing follow-ups manually" \
        "Rich SITUATION response. Mirror should pick up key phrases."

    send_message 4 "yeah the document chase is brutal. we'll send 3 emails for the same W-2 and then someone uploads a blurry photo and we start over. meanwhile the borrower is getting antsy because it's been 2 weeks" \
        "Rich with emotional depth. Empathy might fire but should feel natural."

    send_message 5 "I mean ideally we'd have something that automatically follows up on missing docs and can read what people upload so my team isn't doing it manually. that would probably save us 20 hours a week across the team" \
        "Rich SOLUTION_AWARENESS. Disengagement detection should NOT fire."

    send_message 6 "yeah if we don't figure this out we're going to keep losing deals. had 3 borrowers go to a competitor last month because we were too slow. that's probably 45k in lost commissions" \
        "Rich CONSEQUENCE material. No new directives should fire."

    fetch_thoughts

    echo -e "${GREEN}TEST 2 COMPLETE. Session: $SESSION_ID${NC}"
    echo ""
}

case "${1:-all}" in
    test1) test1 ;;
    test2) test2 ;;
    all)
        test1
        echo ""
        echo -e "${BOLD}========================================${NC}"
        echo ""
        test2
        echo ""
        echo -e "${BOLD}========================================${NC}"
        echo -e "${GREEN}Both tests complete.${NC}"
        ;;
    *)
        echo "Usage: $0 [test1|test2|all]"
        exit 1
        ;;
esac
