"""
Invitation Link Utility

Builds tracked invitation URLs for the 100x AI Academy invitation page.
Each link includes UTM parameters and session context so we can attribute
signups back to the specific bot arm, channel, and conversation.
"""

import os
from urllib.parse import urlencode

INVITATION_URL = os.getenv(
    "INVITATION_URL",
    "https://www.100x.inc/academy/mortgage-ai-agents",
)


def build_invitation_url(
    session_id: str,
    arm: str,
    channel: str = "web",
) -> str:
    """
    Build a tracked invitation URL with query params for attribution.

    Returns something like:
        https://www.100x.inc/academy/mortgage-ai-agents?ref=ABC123&arm=sally_nepq&channel=web&utm_source=sally_sells&utm_medium=sally_nepq&utm_campaign=phase1b
    """
    params = {
        "ref": session_id,
        "arm": arm,
        "channel": channel,
        "utm_source": "sally_sells",
        "utm_medium": arm,
        "utm_campaign": "phase1b",
    }
    return f"{INVITATION_URL}?{urlencode(params)}"
