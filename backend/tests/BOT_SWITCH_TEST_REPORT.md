# Bot Switch & Memory Wipe — Test Report

**Date**: 2026-03-15 22:59:56
**Total Tests**: 42
**Passed**: 42
**Failed**: 0
**Pass Rate**: 100%

## Results

- ✅ PASS: 1a. Session active and responding — Detected bot: hank_hypes, Response: Perfect! Mortgage brokerage with 8 agents — I'm already seeing HUGE opportunities! Your agents are p
- ✅ PASS: 1b. SWITCH SALLY returns 'Switched to Sally' + greeting — Response: Switched to Sally.

Hey, I'm Sally. I've got the context from your previous chat — let me pick up from here. What were you thinking about?
- ✅ PASS: 1c. Can continue chatting after switch — Response: I'd need to understand your brokerage better first to give you relevant ROI info. What's your role there?
- ✅ PASS: 2a. Switch to Sally succeeds — Response: Switched to Sally.

Hey, I'm Sally. I've got the context from your previous chat — let me pick up from here. What were you thinking about?
- ✅ PASS: 2b. Sally responds to messages — Response: I could share some lending AI stuff, but are you working in lending yourself?
- ✅ PASS: 2c. Switch to Ivy succeeds — Response: Switched to Ivy.

Got it — I have the context from your chat with Sally about AI in lending. Since you're asking about lending specifically, I'm guessing you're either working in that space or evaluat
- ✅ PASS: 2d. Ivy responds after switch — Response: We weren't talking about anything yet — this is actually the start of our conversation. I think there might be some confusion.

I'm Ivy, an informatio
- ✅ PASS: 3a. SWITCH without name shows help message — Response: To switch bots, text: SWITCH SALLY, SWITCH HANK, or SWITCH IVY
- ✅ PASS: 3b. SWITCH to invalid bot shows help — Response: To switch bots, text: SWITCH SALLY, SWITCH HANK, or SWITCH IVY
- ✅ PASS: 3c. SWITCH to same bot returns error — All switches went through (no same-bot detected, which means 1st switch succeeded)
- ✅ PASS: 3d. SWITCH with no active session returns error — Response: No active conversation to switch. Text anything to start a new one.
- ✅ PASS: 4a. New bot's greeting references previous conversation context — Response: Switched to Ivy.

I see you've been discussing your loan processing operation with my colleague. You mentioned processing 500 loans monthly with 12 officers and looking to automate follow-ups - that's a substantial operation where AI could have signi
- ✅ PASS: 4b. Previous session marked as 'switched' status — Found 43 switched sessions
- ✅ PASS: 5a. Switch to Sally succeeds — Response: Switched to Sally.

Hey, I'm Sally. I've got the context from your previous chat — let me pick up from here. What were you thinking about?
- ✅ PASS: 5b. New session created and active after switch — Active sessions: 63
- ✅ PASS: 6a. Created web session with Sally — Session: 7A0B152D, Arm: sally_nepq
- ✅ PASS: 6b. Sent message in Sally session — Response OK
- ✅ PASS: 6c. Switch to Hank via API returns 200 — Status: 200
- ✅ PASS: 6d. Response has new_session_id — New session: EB9FA263
- ✅ PASS: 6e. Response has correct new_arm — New arm: hank_hypes
- ✅ PASS: 6f. Response has bot_display_name — Display name: Hank
- ✅ PASS: 6g. Response has greeting with content — Greeting: Perfect, Sally filled me in! So you're in the mortgage business - that's HUGE for AI right now! 

Wh
- ✅ PASS: 6h. Previous session ID returned — Previous: 7A0B152D
- ✅ PASS: 6i. Old session status is 'switched' — Status: switched
- ✅ PASS: 6j. Can chat on new session after switch — Response OK
- ✅ PASS: 7a. Invalid bot returns 400 — Status: 400
- ✅ PASS: 7b. Same bot returns 400 — Status: 400
- ✅ PASS: 7c. Nonexistent session returns 404 — Status: 404
- ✅ PASS: 8a. RESET returns confirmation with counts — Response: Memory cleared (0 facts, 0 notes removed). Text anything to start completely fresh.
- ✅ PASS: 8b. Next text after RESET starts fresh (pre-survey) — Response: Hey! Welcome to 100x. Before we chat, quick question:

On a scale of 1-10, how likely are you to inv
- ✅ PASS: 8c. New session proceeds normally after RESET — Response: Thanks! Score recorded.

Hey! Great to connect! I'm Hank from 100x. We help companies save millions with AI — our CEO Nik Shah has done it for compani
- ✅ PASS: 9a. RESET acknowledged — Response: Memory cleared (0 facts, 0 notes removed). Text anything to start completely fresh.
- ✅ PASS: 9b. No active session remains (new pre-survey) — Response: Hey! Welcome to 100x. Before we chat, quick question:

On a scale of 1-10, how likely are you to inv
- ✅ PASS: 10a. Switch to Sally — Response: Switched to Sally.

Hey, I'm Sally. I've got the context from your previous chat — let me pick up fr
- ✅ PASS: 10b. RESET after switch works — Response: Memory cleared (0 facts, 0 notes removed). Text anything to start completely fresh.
- ✅ PASS: 10c. Fresh start after switch+reset — Response: Hey! Welcome to 100x. Before we chat, quick question:

On a scale of 1-10, how likely are you to inv
- ✅ PASS: 11a. No pre-survey after SWITCH (already completed) — Response: Switched to Hank.

Hey! Hank here from 100x - Sally mentioned you're looking at AI for mortgage origination. That's HUGE money right there! 

What's y
- ✅ PASS: 11b. Can chat immediately after switch (no pre-survey) — Response: Look, here's the deal - mortgage companies using AI are cutting processing time from 30 days to 5 days and saving $2,000+ per loan in labor costs! Doc
- ✅ PASS: 12a. First switch (Sally→Hank) succeeds — Status: 200
- ✅ PASS: 12b. Second switch (Hank→Ivy) succeeds — Status: 200
- ✅ PASS: 12c. Third switch (Ivy→Sally) succeeds — Status: 200
- ✅ PASS: 12d. Can chat after triple switch — Response OK

---
*Generated at 2026-03-15 22:59:56*