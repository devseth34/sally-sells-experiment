"""
Session Legitimacy Score (SLS) — 0 to 100.

Computed from raw message data only. No LLM calls, no Layer 1 dependency.
Works identically for all bot arms (Sally, Hank, Ivy, hybrids).

Signals:
1. Total user words (0-35)
2. Substantive message ratio (0-25)
3. Longest single message (0-20)
4. Topic relevance (0-15)
5. Duplicate content flag (auto-zero)

Thresholds:
  70-100: Verified
  40-69:  Marginal
  0-39:   Suspect
"""

import re
from typing import Optional

MORTGAGE_KEYWORDS = [
    'mortgage', 'loan', 'broker', 'lender', 'lending', 'officer', 'originator',
    'underwriting', 'borrower', 'closing', 'pre-qual', 'refinanc', 'compliance',
    'pipeline', 'lead', 'crm', 'encompass', 'los', 'disclosure', 'appraisal',
    'title', 'escrow', 'fha', 'va loan', 'conventional', 'jumbo', 'rate',
    'origination', 'processor', 'branch manager',
]

BUSINESS_KEYWORDS = [
    'business', 'company', 'team', 'revenue', 'clients', 'sales', 'marketing',
    'workflow', 'automat', 'manual', 'process', 'follow-up', 'followup', 'roi',
    'ai', 'artificial intelligence', 'tool', 'software', 'tech', 'customer',
    'operations', 'efficiency', 'staff', 'hire', 'cost', 'budget',
]

OFF_TOPIC_SIGNALS = [
    'completing a study', 'finish this survey', 'prolific', 'mturk',
    'not in mortgage', 'not a mortgage', 'i work for the government',
    'theatre', 'theater', 'how do i finish',
]


def compute_legitimacy_score(
    user_messages: list[str],
    all_user_content_hashes: Optional[set] = None,
) -> dict:
    """
    Compute Session Legitimacy Score from user messages.

    Args:
        user_messages: List of user message strings (content only, no bot messages).
        all_user_content_hashes: Optional set of content hashes from other sessions
                                 for duplicate detection. If the current session's
                                 content hash is in this set, it's a duplicate.

    Returns:
        dict with keys:
            score: int (0-100)
            tier: str ("verified", "marginal", "suspect")
            word_score: int
            substance_score: int
            max_msg_score: int
            topic_score: int
            is_duplicate: bool
            is_off_topic: bool
            total_words: int
            turn_count: int
            details: str (human-readable explanation)
    """
    if not user_messages:
        return {
            "score": 0,
            "tier": "suspect",
            "word_score": 0,
            "substance_score": 0,
            "max_msg_score": 0,
            "topic_score": 0,
            "is_duplicate": False,
            "is_off_topic": False,
            "total_words": 0,
            "turn_count": 0,
            "details": "No user messages",
        }

    # Parse basics
    word_counts = [len(m.split()) for m in user_messages]
    total_words = sum(word_counts)
    all_text = ' '.join(m.lower() for m in user_messages)

    # --- Signal 1: Total user words (0-35) ---
    if total_words >= 100:
        word_score = 35
    elif total_words >= 60:
        word_score = 28
    elif total_words >= 40:
        word_score = 22
    elif total_words >= 25:
        word_score = 16
    elif total_words >= 15:
        word_score = 10
    elif total_words >= 8:
        word_score = 5
    else:
        word_score = 0

    # --- Signal 2: Substantive message ratio (0-25) ---
    # What % of messages have more than 3 words?
    substantive_count = sum(1 for w in word_counts if w > 3)
    substantive_pct = substantive_count / len(user_messages)
    substance_score = round(substantive_pct * 25)

    # --- Signal 3: Longest single message (0-20) ---
    max_words = max(word_counts)
    if max_words >= 30:
        max_msg_score = 20
    elif max_words >= 20:
        max_msg_score = 16
    elif max_words >= 12:
        max_msg_score = 12
    elif max_words >= 7:
        max_msg_score = 8
    elif max_words >= 4:
        max_msg_score = 4
    else:
        max_msg_score = 0

    # --- Signal 4: Topic relevance (0-15) ---
    mortgage_hits = sum(1 for kw in MORTGAGE_KEYWORDS if kw in all_text)
    business_hits = sum(1 for kw in BUSINESS_KEYWORDS if kw in all_text)
    topic_hits = mortgage_hits + business_hits
    if topic_hits >= 5:
        topic_score = 15
    elif topic_hits >= 3:
        topic_score = 12
    elif topic_hits >= 2:
        topic_score = 8
    elif topic_hits >= 1:
        topic_score = 4
    else:
        topic_score = 0

    # --- Signal 5: Off-topic detection ---
    is_off_topic = any(signal in all_text for signal in OFF_TOPIC_SIGNALS)

    # --- Signal 6: Duplicate detection ---
    content_hash = '|||'.join(m.lower().strip() for m in user_messages)
    is_duplicate = False
    if all_user_content_hashes is not None and content_hash in all_user_content_hashes:
        is_duplicate = True

    # --- Final score ---
    total_score = word_score + substance_score + max_msg_score + topic_score

    # Penalties
    if is_duplicate:
        total_score = 0  # Auto-zero
    if is_off_topic:
        total_score = max(0, total_score - 30)  # Heavy penalty

    total_score = min(100, max(0, total_score))  # Clamp

    # Tier
    if total_score >= 70:
        tier = "verified"
    elif total_score >= 40:
        tier = "marginal"
    else:
        tier = "suspect"

    # Human-readable details
    details_parts = []
    if is_duplicate:
        details_parts.append("DUPLICATE content across sessions")
    if is_off_topic:
        details_parts.append("Off-topic signals detected")
    if total_words < 15:
        details_parts.append(f"Very low word count ({total_words})")
    if substantive_pct < 0.3:
        details_parts.append(f"Most messages are 1-3 words ({substantive_pct:.0%} substantive)")
    if topic_hits == 0:
        details_parts.append("No mortgage/business keywords found")
    details = "; ".join(details_parts) if details_parts else "Engagement looks legitimate"

    return {
        "score": total_score,
        "tier": tier,
        "word_score": word_score,
        "substance_score": substance_score,
        "max_msg_score": max_msg_score,
        "topic_score": topic_score,
        "is_duplicate": is_duplicate,
        "is_off_topic": is_off_topic,
        "total_words": total_words,
        "turn_count": len(user_messages),
        "details": details,
    }


def extract_user_messages_from_transcript(transcript: str) -> list[str]:
    """Extract user messages from the stored transcript string."""
    matches = re.findall(r'Prospect: (.+?)(?=\n\[|$)', transcript, re.DOTALL)
    return [m.strip() for m in matches if m.strip()]
