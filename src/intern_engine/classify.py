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

# New-grad / entry-level full-time signals. Title signals are trusted directly;
# body signals must be explicit. Senior signals veto (so a "Senior … mentors new
# grads" posting is not mistaken for entry-level).
_NEWGRAD_TITLE = re.compile(
    r"\b(new[\s\-]?grad(uate)?s?|recent\s+grad(uate)?|(university|college)\s+grad"
    r"(uate)?|grad(uate)?\s+(engineer|analyst|developer|scientist|program|scheme|"
    r"associate|hire)|entry[\s\-]?level|early[\s\-]?career|campus\s+hire|junior)\b",
    re.I,
)
_NEWGRAD_BODY = re.compile(
    r"\b(new\s+grad(uate)?s?|recent\s+graduate|new\s+college\s+grad(uate)?s?|"
    r"grad(uate)?\s+(program|scheme|rotational\s+program)|entry[\s\-]?level|"
    r"0[\s\-]?(?:to|\-)[\s\-]?2\s+years?)\b",
    re.I,
)
# Titles that are never early-career, whatever the description says. This veto
# applies to EVERY role type: a "Sr. Security Engineer" posting whose boilerplate
# mentions an internship programme is not an internship.
_SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|leader|manager|director|head\s+of|"
    r"vice\s+president|vp|architect|distinguished|fellow|expert|"
    r"II|III|IV|2|3)\b")          # case-SENSITIVE for roman numerals / levels
_SENIOR_TITLE_CI = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|leader|manager|director|head\s+of|"
    r"vice\s+president|architect|distinguished|expert)\b", re.I)

# Explicit body evidence. A bare mention of "internship" somewhere in a long
# description means nothing; these patterns require the posting to be talking
# about ITSELF as an internship / co-op / apprenticeship.
_BODY_EXPLICIT: list[tuple[RoleType, re.Pattern]] = [
    (RoleType.COOP, re.compile(
        r"\bco[\-\s]?op\s+(program|programme|position|student|term|opportunity|role|assignment)\b"
        r"|\b(this|our|the)\s+co[\-\s]?op\b", re.I)),
    (RoleType.APPRENTICE, re.compile(
        r"\bapprenticeship\s+(program|programme|position|opportunity|role)\b"
        r"|\b(this|our|the)\s+apprenticeship\b", re.I)),
    (RoleType.INTERN, re.compile(
        r"\b(summer|fall|autumn|winter|spring)\s+intern(ship)?\b"
        r"|\bintern(ship)?\s+(program|programme|position|opportunity|role|cohort)\b"
        r"|\b(this|our|the)\s+internship\b"
        r"|\bas\s+an?\s+intern\b"
        r"|\bintern(ship)?\s+will\s+(be|have|work)\b", re.I)),
]

_SENIOR_YEARS = re.compile(
    r"\b(?:[3-9]|[12]\d)\+?\s*(?:years|yrs)\b|\b\d+\+\s*(?:years|yrs)\b", re.I
)

# Cap how much description text we scan. Domain and role-type signals appear
# near the top of a posting; scanning full multi-KB HTML bodies for every one of
# thousands of postings is the dominant cost, so we bound it.
_MAX_BODY_CHARS = 4000


def is_senior_title(title: str) -> bool:
    """True when the title itself marks the role as senior or levelled.

    Exposed so the pipeline can refuse a source-declared role type for such a
    posting: amazon.jobs sets `is_intern` on some senior listings, and that hint
    must not resurrect a role the title has already ruled out.
    """
    t = (title or "").strip()
    return bool(_SENIOR_TITLE.search(t) or _SENIOR_TITLE_CI.search(t))


def _intern_word_is_real(text: str, match: re.Match) -> bool:
    """Reject 'internal' / 'international' / 'internist' style matches."""
    window = text[max(0, match.start() - 2): match.end() + 6]
    return not _ROLE_TYPE_NEGATIVE.search(window)


def detect_role_type(title: str, description: str = "") -> Optional[RoleType]:
    """Return the early-career role type, or None.

    Evidence order: the TITLE decides. Only when the title is silent do we look
    at the body, and then only for phrases where the posting describes *itself*
    as an internship / co-op / apprenticeship. Senior or levelled titles are
    rejected outright, which is what stops "Sr. Security Engineer" postings whose
    boilerplate mentions an internship from being listed as one.
    """
    t = (title or "").strip()
    body = (description or "")[:_MAX_BODY_CHARS]

    # 1. hard veto on seniority / level in the title
    if _SENIOR_TITLE.search(t) or _SENIOR_TITLE_CI.search(t):
        return None

    # 2. title evidence (strongest)
    for rtype, pat in _ROLE_TYPE_PATTERNS:
        m = pat.search(t)
        if m and (rtype is not RoleType.INTERN or _intern_word_is_real(t, m)):
            return rtype
    if _NEWGRAD_TITLE.search(t):
        return RoleType.NEWGRAD

    # 3. body evidence, only if explicit and not contradicted by experience asks
    if _SENIOR_YEARS.search(body):
        return None
    for rtype, pat in _BODY_EXPLICIT:
        m = pat.search(body)
        if m and (rtype is not RoleType.INTERN or _intern_word_is_real(body, m)):
            return rtype
    if _NEWGRAD_BODY.search(body):
        return RoleType.NEWGRAD
    return None


# ---------------------------------------------------------------------------
# Domain keyword banks.  Each entry is a compiled, word-boundaried pattern.
# ---------------------------------------------------------------------------
def _combined(patterns: list[re.Pattern]) -> re.Pattern:
    """Fuse many patterns into one alternation.

    Scrubbing negative phrases used one re.sub per phrase per field, which meant
    ~60 passes over every posting body. One fused pattern does it in a single
    pass and is the difference between a slow run and a fast one at scale.
    """
    return re.compile("|".join(f"(?:{p.pattern})" for p in patterns), re.I)


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
    # bare "security" counts (a "Security Software Engineer" is a security role);
    # CYBER_NEGATIVE below screens out social/job/food/physical-security noise.
    "security", "security engineer", "security engineering", "security analyst",
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
    "security guard", "security officer", "physical security",
    "national security policy", "border security", "security clearance required",
)

AI_TERMS = _kw(
    "machine learning", "deep learning", "artificial intelligence",
    "applied scientist", "applied science", "research scientist",
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

# One fused pattern per domain, used for scrubbing (see classify_domain).
# Role-function phrases that disqualify a posting outright when they appear in
# the TITLE: these describe what the job IS, so no amount of domain vocabulary in
# the body makes an "AI Sales Engineer" a technical AI role. Deliberately NOT
# including bare "recruiting", because Amazon posts genuine ML internships under
# org names like "PhD Student Science Recruiting".
_DISQUALIFY_TITLE = _kw(
    "sales", "marketing", "account executive", "account manager",
    "customer support", "customer success", "recruiter", "recruiting coordinator",
    "talent acquisition", "business development", "technical writer",
    "solutions consultant", "sales engineer", "sales development",
)

_DISQUALIFY_TITLE_RE = _combined(_DISQUALIFY_TITLE)

# Weights: a hit in the title is worth much more than a hit in the body.
_TITLE_WEIGHT = 3
_BODY_WEIGHT = 1
# Minimum score (title + body) to accept a domain.
# General software engineering. Deliberately checked LAST so that a security or
# ML role keeps its more specific domain rather than collapsing into "Software".
SOFTWARE_TERMS = _kw(
    "software engineer", "software engineering", "software developer",
    "software development", "software dev", "sde", "swe", "programmer",
    "backend", "back end", "frontend", "front end", "full stack", "fullstack",
    "web developer", "web development", "mobile developer", "ios developer",
    "android developer", "platform engineer", "systems engineer",
    "distributed systems", "embedded software", "firmware", "devops",
    "site reliability", "sre", "cloud engineer", "infrastructure engineer",
    "data engineer", "database engineer", "api", "compiler", "operating system",
    "quality assurance", "qa engineer", "test engineer", "sdet",
    "computer science", "python", "java", "c++", "golang", "javascript",
    "typescript", "react", "kubernetes", "docker",
)
# Things that mention software words but aren't software engineering roles.
SOFTWARE_NEGATIVE = _kw(
    "software sales", "sales engineer", "account executive", "recruiter",
    "technical writer", "customer success", "solutions consultant",
    "business development", "marketing", "product marketing",
    "supply chain", "mechanical engineer", "civil engineer", "chemical engineer",
)

# One fused pattern per domain, used for scrubbing in classify_domain.
CYBER_NEGATIVE_RE = _combined(CYBER_NEGATIVE)
AI_NEGATIVE_RE = _combined(AI_NEGATIVE)
SOFTWARE_NEGATIVE_RE = _combined(SOFTWARE_NEGATIVE)

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
    if _DISQUALIFY_TITLE_RE.search(title):
        return None, 0          # the title says this is a sales/marketing/HR role
    full = f"{title}\n{body}"

    def _scrub(negative_re: re.Pattern, text: str) -> str:
        """Remove negative phrases before scoring, rather than penalising after.

        Subtracting a penalty conflated two different problems. "Social Security
        Analyst" contains the domain word itself, so it needs the phrase removed;
        Amazon's "... PhD Student Science Recruiting" org name merely mentions a
        negative word alongside a genuine domain term, and a flat penalty wrongly
        dropped every one of those ML internships. Scrubbing handles both: the
        phrase stops contributing signal, and untouched domain terms still count.
        """
        return negative_re.sub(" ", text)

    def _domain(terms: list[re.Pattern], negative_re: re.Pattern) -> int:
        return _score(terms, _scrub(negative_re, title), _scrub(negative_re, body))

    cyber = _domain(CYBER_TERMS, CYBER_NEGATIVE_RE)
    ai = _domain(AI_TERMS, AI_NEGATIVE_RE)
    soft = _domain(SOFTWARE_TERMS, SOFTWARE_NEGATIVE_RE)

    # A title-level AI/cyber term is decisive even if negatives appear in the body.
    # Software is the fallback domain, so a security or ML role keeps its specific
    # label and only genuinely general engineering roles land in "Software".
    best_cat, best_score = None, 0
    if cyber >= _THRESHOLD and cyber >= ai:
        best_cat, best_score = Category.CYBER, cyber
    elif ai >= _THRESHOLD and ai > cyber:
        best_cat, best_score = Category.AI, ai
    elif soft >= _THRESHOLD:
        best_cat, best_score = Category.SOFTWARE, soft
    return best_cat, best_score


# Cap how much description text we scan. Domain and role-type signals appear
# near the top of a posting; scanning full multi-KB HTML bodies for every one of
# thousands of postings is the dominant cost, so we bound it.
_MAX_BODY_CHARS = 4000


def classify(title: str, description: str = "") -> tuple[Optional[Category], Optional[RoleType]]:
    """Full classification. Returns (category, role_type); either may be None.

    A role is only usable downstream when *both* are non-None. Role type is
    checked first and, when absent, the more expensive domain scan is skipped —
    the large majority of postings on a company board are full-time roles, so
    this avoids the bulk of the work.
    """
    body = (description or "")[:_MAX_BODY_CHARS]
    rtype = detect_role_type(title, body)
    if rtype is None:
        return None, None
    cat, _ = classify_domain(title, body)
    return cat, rtype
