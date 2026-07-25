"""Decide whether a posting is a Cybersecurity or AI/ML *early-career* role.

The classifier is intentionally conservative: a role is only kept if it is both
(a) an internship / co-op / apprenticeship, and (b) clearly in one of the two
target domains. Title matches weigh far more than body matches, and a list of
negative terms suppresses common false positives (e.g. "email marketing",
"social media", "AI-powered sales" listings that aren't technical AI roles).
"""

from __future__ import annotations

import re
from typing import Optional

from .models import Category, RoleType

# ---------------------------------------------------------------------------
# Role-type detection
# ---------------------------------------------------------------------------
_ROLE_TYPE_PATTERNS: list[tuple[RoleType, re.Pattern]] = [
    (RoleType.COOP, re.compile(r"\bco[\-\s]?op(s)?\b", re.I)),
    (RoleType.APPRENTICE, re.compile(r"\bapprentice(ship)?s?\b", re.I)),
    (RoleType.INTERN, re.compile(r"\bintern(ship)?s?\b", re.I)),
]

# Phrases that look intern-ish but usually mean a *full-time* role.
_ROLE_TYPE_NEGATIVE = re.compile(
    r"\b(intern(al|ational)|internist|new\s+grad(uate)?\s+(?!intern)|"
    r"early\s+career\s+(?!intern))",
    re.I,
)


def detect_role_type(title: str, description: str = "") -> Optional[RoleType]:
    """Return the role type, favoring signal in the title over the body."""
    for text, is_title in ((title, True), (description, False)):
        if not text:
            continue
        for rtype, pat in _ROLE_TYPE_PATTERNS:
            for m in pat.finditer(text):
                # guard "intern" against "internal"/"international"
                if rtype is RoleType.INTERN:
                    window = text[max(0, m.start() - 2): m.end() + 6]
                    if _ROLE_TYPE_NEGATIVE.search(window):
                        continue
                # only trust body matches for co-op / apprentice, and only
                # trust body "intern" if the title gave us nothing.
                if is_title or rtype in (RoleType.COOP, RoleType.APPRENTICE):
                    return rtype
                if rtype is RoleType.INTERN:
                    return rtype
    return None


# ---------------------------------------------------------------------------
# Domain keyword banks.  Each entry is a compiled, word-boundaried pattern.
# ---------------------------------------------------------------------------
def _kw(*words: str) -> list[re.Pattern]:
    pats = []
    for w in words:
        # allow the caller to pass a raw regex by prefixing "re:"
        if w.startswith("re:"):
            pats.append(re.compile(w[3:], re.I))
        else:
            pats.append(re.compile(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", re.I))
    return pats


CYBER_TERMS = _kw(
    "cybersecurity", "cyber security", "cyber", "infosec", "information security",
    "appsec", "application security", "product security", "offensive security",
    "red team", "blue team", "purple team", "penetration test", "pentest",
    "vulnerability", "threat", "threat intelligence", "threat detection",
    "detection engineering", "incident response", "dfir", "forensics",
    "malware", "reverse engineering", "security operations", "soc analyst",
    "security engineer", "security analyst", "security researcher",
    "network security", "cloud security", "endpoint security", "zero trust",
    "identity and access", "iam", "grc", "governance risk", "compliance",
    "cryptography", "encryption", "security clearance", "siem", "soar",
    "ethical hacking", "exploit", "security architect", "risk management",
    "re:\\bsoc\\b(?!ial)",   # SOC but not "social"
)

CYBER_NEGATIVE = _kw(
    "social security", "job security", "food security", "security deposit",
    "security guard", "national security policy", "border security",
)

AI_TERMS = _kw(
    "machine learning", "deep learning", "artificial intelligence",
    "generative ai", "gen ai", "genai", "llm", "large language model",
    "natural language", "nlp", "computer vision", "reinforcement learning",
    "neural network", "foundation model", "mlops", "ml engineer",
    "ml research", "applied scientist", "research scientist", "data scientist",
    "data science", "pytorch", "tensorflow", "diffusion model", "transformer",
    "speech recognition", "recommendation system", "prompt engineering",
    "ml infrastructure", "ml platform", "ml ops", "ai research", "ai engineer",
    "re:\\bai\\b", "re:\\bml\\b", "re:\\bcv\\b(?=.{0,40}(vision|image))",
)

AI_NEGATIVE = _kw(
    "sales", "marketing", "recruiting", "customer support", "account manager",
)

# Weights: a hit in the title is worth much more than a hit in the body.
_TITLE_WEIGHT = 3
_BODY_WEIGHT = 1
# Minimum score (title + body) to accept a domain.
_THRESHOLD = 3


def _score(patterns: list[re.Pattern], title: str, body: str) -> int:
    score = 0
    for pat in patterns:
        if pat.search(title):
            score += _TITLE_WEIGHT
        elif pat.search(body):
            score += _BODY_WEIGHT
    return score


def _negative_hit(patterns: list[re.Pattern], text: str) -> int:
    return sum(1 for pat in patterns if pat.search(text))


def classify_domain(title: str, description: str = "") -> tuple[Optional[Category], int]:
    """Return the (best domain, score) or (None, 0) if neither clears the bar."""
    title = title or ""
    body = description or ""
    full = f"{title}\n{body}"

    cyber = _score(CYBER_TERMS, title, body) - 2 * _negative_hit(CYBER_NEGATIVE, full)
    ai = _score(AI_TERMS, title, body) - 2 * _negative_hit(AI_NEGATIVE, full)

    # A title-level AI/cyber term is decisive even if negatives appear in the body.
    best_cat, best_score = None, 0
    if cyber >= _THRESHOLD and cyber >= ai:
        best_cat, best_score = Category.CYBER, cyber
    elif ai >= _THRESHOLD and ai > cyber:
        best_cat, best_score = Category.AI, ai
    return best_cat, best_score


def classify(title: str, description: str = "") -> tuple[Optional[Category], Optional[RoleType]]:
    """Full classification. Returns (category, role_type); either may be None.

    A role is only usable downstream when *both* are non-None.
    """
    rtype = detect_role_type(title, description)
    cat, _ = classify_domain(title, description)
    return cat, rtype
