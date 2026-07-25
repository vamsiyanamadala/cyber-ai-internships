"""Build and query an H-1B sponsorship index from USCIS data.

Source of truth: the USCIS **H-1B Employer Data Hub** per-fiscal-year CSV files
(https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub).
Download one or more fiscal-year CSVs into ``data/h1b/`` and point the loader at
that folder. A tiny ``data/h1b_employers.sample.csv`` ships with the repo so the
pipeline runs out of the box; replace it with the real files for real coverage.

IMPORTANT — what this can and cannot tell you:
  * It measures **past** petitions, which is the best publicly available proxy
    for "this employer sponsors". It does **not** predict the future, and a
    company with no history here may still sponsor (new/small employers, name
    mismatches). Tune ``min_petitions`` and pick a ``sponsorship_mode`` with
    that tradeoff in mind.
"""

from __future__ import annotations

import csv
import glob
import os
import re
from dataclasses import dataclass, field

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")

# Corporate suffixes / filler stripped during normalization so "Amazon.com
# Services LLC" and "Amazon" resolve to the same key.
_SUFFIXES = {
    "inc", "incorporated", "llc", "llp", "lp", "ltd", "limited", "corp",
    "corporation", "co", "company", "plc", "gmbh", "sa", "ag", "nv", "bv",
    "holdings", "holding", "group", "technologies", "technology", "labs",
    "laboratories", "systems", "solutions", "services", "usa", "us",
    "america", "na", "the", "com", "pbc",
}


def normalize_employer(name: str) -> str:
    """Lowercase, drop punctuation, and strip trailing corporate suffixes."""
    name = (name or "").lower().replace("&", " and ")
    name = _PUNCT.sub(" ", name)
    name = _WS.sub(" ", name).strip()
    tokens = [t for t in name.split(" ") if t]
    # strip suffix tokens from the end
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    # also strip a leading "the"
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    return " ".join(tokens)


# The real USCIS "Employer_Information.csv" is UTF-16, TAB-delimited (despite the
# .csv name), and splits approvals across many columns (New Employment Approval,
# Continuation Approval, Change of Employer Approval, ...). The bundled sample is
# UTF-8, comma-delimited, with simple Initial/Continuing Approval columns. Rather
# than hard-code header names, we detect them structurally so both formats work.

def _detect_encoding(path: str) -> str:
    """Sniff a text encoding from the first bytes (handles USCIS UTF-16)."""
    with open(path, "rb") as fh:
        head = fh.read(4096)
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"          # UTF-16 with a byte-order mark
    if head[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if head and head.count(0) / len(head) > 0.25:
        return "utf-16-le"       # BOM-less UTF-16 (common Windows export)
    return "utf-8-sig"


def _detect_delimiter(sample_line: str) -> str:
    return "\t" if sample_line.count("\t") > sample_line.count(",") else ","


def _find_employer_col(header: list[str]) -> int | None:
    low = [h.strip().lower() for h in header]
    for i, h in enumerate(low):                       # e.g. "Employer (Petitioner) Name"
        if ("employer" in h or "petitioner" in h) and "name" in h:
            return i
    for want in ("employer", "petitioner", "company"):
        for i, h in enumerate(low):
            if h == want:
                return i
    for i, h in enumerate(low):                        # last resort, avoid the
        if ("employer" in h or "petitioner" in h) and \
           "approval" not in h and "denial" not in h:   # "...Employer Approval" cols
            return i
    return None


def _find_approval_cols(header: list[str]) -> list[int]:
    """Every column that counts an approval (any format), excluding denials."""
    low = [h.strip().lower() for h in header]
    return [i for i, h in enumerate(low) if "approval" in h and "denial" not in h]


@dataclass
class SponsorIndex:
    counts: dict[str, int] = field(default_factory=dict)   # normkey -> approvals
    raw_names: dict[str, str] = field(default_factory=dict)  # normkey -> a sample raw name
    min_petitions: int = 1
    # first token -> (best full key, its count). Lets a brand like "Meta"
    # resolve to the legal-name key "meta platforms" without substring false
    # positives (only whole-first-word matches, so "ramp" never hits "rampart").
    by_first: dict[str, tuple[str, int]] = field(default_factory=dict)

    # ---- construction ---------------------------------------------------
    @classmethod
    def from_paths(cls, paths: list[str], min_petitions: int = 1) -> "SponsorIndex":
        idx = cls(min_petitions=min_petitions)
        for path in paths:
            idx._ingest_csv(path)
        idx._build_secondary()
        return idx

    def _build_secondary(self) -> None:
        self.by_first.clear()
        for key, count in self.counts.items():
            ft = key.split(" ", 1)[0]
            best = self.by_first.get(ft)
            if best is None or count > best[1]:
                self.by_first[ft] = (key, count)

    @classmethod
    def from_dir(cls, directory: str, min_petitions: int = 1, sample: str | None = None) -> "SponsorIndex":
        files = sorted(glob.glob(os.path.join(directory, "*.csv")))
        if not files and sample and os.path.exists(sample):
            files = [sample]
        return cls.from_paths(files, min_petitions=min_petitions)

    def _ingest_csv(self, path: str) -> None:
        enc = _detect_encoding(path)
        try:
            with open(path, "r", encoding=enc, errors="replace") as fh:
                first = fh.readline()
        except (LookupError, OSError):
            enc = "utf-8"
            with open(path, "r", encoding=enc, errors="replace") as fh:
                first = fh.readline()
        delim = _detect_delimiter(first)
        with open(path, "r", encoding=enc, errors="replace", newline="") as fh:
            reader = csv.reader(fh, delimiter=delim)
            try:
                header = next(reader)
            except StopIteration:
                return
            emp_i = _find_employer_col(header)
            if emp_i is None:
                return
            appr_cols = _find_approval_cols(header)
            for row in reader:
                if len(row) <= emp_i:
                    continue
                raw = row[emp_i].strip()
                if not raw:
                    continue                       # USCIS masks some names -> skip
                if appr_cols:
                    approvals = sum(_to_int(row[i]) for i in appr_cols if i < len(row))
                else:
                    approvals = 1                  # no approval columns: count presence
                if approvals <= 0:
                    continue                       # only denials/zeros -> not a sponsor
                key = normalize_employer(raw)
                if not key:
                    continue
                self.counts[key] = self.counts.get(key, 0) + approvals
                self.raw_names.setdefault(key, raw)

    # ---- query ----------------------------------------------------------
    def lookup(self, company: str) -> int:
        """Approved petitions on record for ``company`` (0 if none found).

        Tries an exact normalized match, then progressively shorter token
        prefixes so "Palantir Technologies" still resolves to "palantir".
        """
        key = normalize_employer(company)
        if not key:
            return 0
        if key in self.counts:
            return self.counts[key]
        tokens = key.split(" ")
        # try longest-prefix matches (2+ tokens) against known keys
        for n in range(len(tokens) - 1, 1, -1):
            prefix = " ".join(tokens[:n])
            if prefix in self.counts:
                return self.counts[prefix]
        # single distinctive token (len>=4) exact match, to avoid "data"/"tech"
        if len(tokens) == 1 and len(tokens[0]) >= 4 and tokens[0] in self.counts:
            return self.counts[tokens[0]]
        # first-token fallback: brand ("meta") -> legal name key ("meta platforms").
        # Whole-word match on the first token only, so it won't over-match.
        if tokens and len(tokens[0]) >= 4:
            hit = self.by_first.get(tokens[0])
            if hit is not None:
                return hit[1]
        return 0

    def has_history(self, company: str) -> bool:
        return self.lookup(company) >= self.min_petitions

    def __len__(self) -> int:
        return len(self.counts)


def _to_int(value: str) -> int:
    value = (value or "").strip().replace(",", "")
    if not value:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0
