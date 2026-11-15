"""Shared boundary between scientific source explanation and unsupported safety/gravity inference.

The NASA sources in GeNAIus describe what was *measured* in ISS microgravity and uncrewed
Cygnus tests. They do not support (a) judgements that something is safe/unsafe or safer than
something else for people, (b) claims about harm to a crew, or (c) transferring results to
Moon/Mars/partial or Earth gravity. Questions that ask for those inferences are routed to a
deterministic abstention; questions that ask what was measured or reported are not.

Patterns operate on folded ASCII-lowercase text (see `service._fold_text`). Both the Core
evidence gate (`service.evaluate_abstention_gate`) and the SAFFIRE IV–VI case gate use them, so
the rule is defined once instead of as per-sentence exceptions.
"""
from __future__ import annotations

import re

# Target environments the corpus never measured.
GRAVITY_TARGET_RE = re.compile(
    r"\b(?:moon|lunar|mars|martian|partial[\s-]+gravity|reduced[\s-]+gravity|planetary\s+surface\w*"
    r"|1/6\s*g|3/8\s*g|0\.16\s*g|0\.38\s*g"
    r"|ay\s+(?:yuzeyi\w*|yercekimi\w*|habitati\w*|ussu\w*|gorev\w*)|mars\w*\s+(?:yuzeyi\w*|yercekimi\w*|habitati\w*|ussu\w*)"
    r")\b"
)

# Asking for a safety verdict, comparison or rule compliance (not "what fire-safety experiments exist").
SAFETY_JUDGMENT_RE = re.compile(
    r"\b(?:is\s+(?:it|this|that|\w+)\s+(?:\w+\s+){0,3}safe|how\s+safe|safe\s+(?:for|to|enough)|safer|safest|unsafe"
    r"|safety\s+(?:compare\w*|comparison|rules?|standards?|requirements?|limits?|margin\w*|rating|score|ranking|verdict|case)"
    r"|compare\w*\s+(?:\w+\s+){0,6}safety|safety\s+(?:of|for|in|on)\s+(?:\w+\s+){0,3}(?:crew|astronauts?|humans?|people|habitat\w*|mission\w*|cabin\w*)"
    r"|guvenli\s+mi|daha\s+guvenli|en\s+guvenli|guvenlik\s+(?:karsilastir\w*|kural\w*|standart\w*))\b"
)

# Asking whether people were or would be harmed.
CREW_HARM_RE = re.compile(
    r"\b(?:kill(?:ed|s)?|die[ds]?|death|deaths|dead|fatal\w*|lethal|injur\w*|poison\w*|harm(?:ed|ful)?|endanger\w*"
    r"|survive[ds]?|survival|hurt)\b.{0,40}\b(?:crew|astronauts?|humans?|people|occupants?)\b"
    r"|\b(?:crew|astronauts?|humans?|people|occupants?)\b.{0,40}\b(?:kill(?:ed)?|die[ds]?|died|death|fatal\w*|lethal|injur\w*"
    r"|poison\w*|harm(?:ed)?|survive[ds]?|survival|hurt)\b"
    r"|\b(?:murettebat\w*|astronot\w*)\b.{0,40}\b(?:ol\w*|zarar\w*|zehirlen\w*)\b"
)

SOURCE_SCOPE_NOTE = (
    "What the sources support: measured results from ISS microgravity (BASS-II, FLEX) and uncrewed Cygnus "
    "(SAFFIRE IV–VI) tests, with their units, conditions and citations. Ask, for example, what was measured, "
    "under which oxygen/pressure/flow conditions, or how detection timing was reported."
)


def asks_gravity_transfer(folded: str) -> bool:
    return bool(GRAVITY_TARGET_RE.search(folded))


def asks_safety_judgment(folded: str) -> bool:
    return bool(SAFETY_JUDGMENT_RE.search(folded))


def asks_crew_harm(folded: str) -> bool:
    return bool(CREW_HARM_RE.search(folded))
