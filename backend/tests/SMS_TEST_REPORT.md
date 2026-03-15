# SMS Integration Test Report

**Date**: 2026-03-15 22:13:55
**Total Tests**: 27
**Passed**: 27
**Failed**: 0
**Pass Rate**: 100%

## Results

- ✅ PASS: 1a. New user gets pre-survey question — Response: Hey! Welcome to 100x. Before we chat, quick question:

On a scale of 1-10, how likely are you to inv
- ✅ PASS: 1b. Score accepted + bot greeting returned — Response: Thanks! Score recorded.

Hi, I'm Ivy from 100x. I can provide balanced information about the AI Discovery Workshop — what it covers, how it compares t
- ✅ PASS: 1c. Bot responds to user message — Response: Thanks for that context. A mortgage brokerage with 8 agents would likely have specific AI opportunities around lead qualification, document processing
- ✅ PASS: 1d. Bot responds to second message — Response: That's exactly the type of problem AI can help solve - automated follow-up sequences, lead scoring, and nurturing workflows are well-established use c
- ✅ PASS: 2a. Invalid input gets re-prompt — Response: Please reply with a number from 1 to 10.

1 = not at all likely, 10 = extremely likely
- ✅ PASS: 2b. Out-of-range number gets re-prompt — Response: Please reply with a number from 1 to 10.

1 = not at all likely, 10 = extremely likely
- ✅ PASS: 2c. Valid number proceeds to greeting — Response: Thanks! Score recorded.

Hey! Great to connect! I'm Hank from 100x. We help companies save millions 
- ✅ PASS: 3a. STOP ends session — Response: Got it, conversation ended. Text anytime to start a new one.
- ✅ PASS: 3b. Texting after STOP starts fresh or shows ended — Response: Hey! Welcome to 100x. Before we chat, quick question:

On a scale of 1-10, how likely are you to inv
- ✅ PASS: 4a. NEW restarts with pre-survey — Response: Hey! Welcome to 100x. Before we chat, quick question:

On a scale of 1-10, how likely are you to inv
- ✅ PASS: 4b. New session proceeds normally after NEW — Response: Thanks! Score recorded.

Hey there! I'm Sally from 100x. Super curious to learn about you. What brou
- ✅ PASS: 5a. Timestamps pushed back 48 hours — Session: 218EF48F
- ✅ PASS: 5b. Session resumes (no pre-survey) — Response: Hey, good to hear from you again! No worries - I know how crazy banking gets!

So you were losing deals on follow-up speed - that $864K annually we ca
- ✅ PASS: 5c. Bot responds meaningfully after gap — Response: Hey, good to hear from you again! No worries - I know how crazy banking gets!

So you were losing deals on follow-up speed - that $864K annually we ca
- ✅ PASS: 6a. PAUSE acknowledged — Response: Got it, I won't send any more follow-ups. You can still text me anytime to continue our conversation
- ✅ PASS: 6b. User can still chat after PAUSE — Response: Of course. What would you like to know about the AI Discovery Workshop program?
- ✅ PASS: 7a. Timestamps pushed back 49 hours — Session: DEE7C7EC
- ✅ PASS: 7b. Follow-up trigger endpoint returns 200 — Status: 200, Body: {"status":"ok","message":"Follow-up check completed"}
- ✅ PASS: 7c. Follow-up message saved to DB — Last message role: assistant, content: Hi again! Just wanted to mention I'm still here if you have any questions about how AI might work at
- ✅ PASS: 8a. Sent 3 follow-up cycles
- ✅ PASS: 8b. Max 3 follow-ups enforced — Assistant messages after last user msg: 1
- ✅ PASS: 9a. Multiple arms assigned across 12 sessions — Distribution: {'sally_nepq': 5, 'hank_hypes': 7, 'ivy_informs': 0}
- ✅ PASS: 9b. No single arm monopolized all sessions — Distribution: {'sally_nepq': 5, 'hank_hypes': 7, 'ivy_informs': 0}
- ✅ PASS: 10a. CDS summary endpoint returns 200 — Status: 200
- ✅ PASS: 10b. Response has arms data — Keys: ['arms', 'sally_lift_vs_controls', 'experiment_session_counts', 'target']
- ✅ PASS: 10c. Response has lift calculations
- ✅ PASS: 10d. Response has target thresholds

---
*Generated at 2026-03-15 22:13:55*