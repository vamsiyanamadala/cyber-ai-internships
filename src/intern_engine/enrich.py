"""Lightweight enrichment: skill tags and pay extraction from description text."""

from __future__ import annotations

import re

# Ordered so multi-word tokens match before their substrings.
_SKILLS = [
    "Python", "C++", "C#", "Golang", "Go", "Rust", "Java", "Scala", "Kotlin",
    "TypeScript", "JavaScript", "Ruby", "PHP", "Swift",
    "PyTorch", "TensorFlow", "JAX", "Keras", "scikit-learn", "Hugging Face",
    "Pandas", "NumPy", "Spark", "Hadoop", "Kafka", "Airflow",
    "Kubernetes", "Docker", "Terraform", "AWS", "GCP", "Azure",
    "SQL", "PostgreSQL", "MongoDB", "Redis",
    "Linux", "Bash",
    # security stack
    "Splunk", "SIEM", "SOAR", "Wireshark", "Metasploit", "Burp Suite", "Nmap",
    "Kali", "Snort", "Suricata", "CrowdStrike", "Nessus", "OWASP", "MITRE ATT&CK",
    # ml stack
    "LLM", "NLP", "OpenCV", "CUDA", "MLflow", "Ray", "LangChain",
]
_SKILL_PATTERNS = [
    (s, re.compile(rf"(?<![A-Za-z0-9]){re.escape(s)}(?![A-Za-z0-9+#])", re.I))
    for s in _SKILLS
]

_PAY_PATTERNS = [
    re.compile(r"\$\s?\d{2,3}(?:,\d{3})?(?:\.\d+)?\s?(?:-|to|–)\s?\$?\s?\d{2,3}(?:,\d{3})?(?:\.\d+)?\s?(?:/|\bper\b)?\s?(?:hour|hr|year|yr|annum)?", re.I),
    re.compile(r"\$\s?\d{2,3}(?:,\d{3})?(?:\.\d+)?\s?(?:/|\bper\b)\s?(?:hour|hr|year|yr)", re.I),
    re.compile(r"\$\s?\d{2,3}\s?[kK]\b(?:\s?(?:-|to|–)\s?\$?\s?\d{2,3}\s?[kK])?", re.I),
]


def extract_skills(description: str, limit: int = 12) -> list[str]:
    text = description or ""
    found: list[str] = []
    for canonical, pat in _SKILL_PATTERNS:
        if pat.search(text) and canonical not in found:
            found.append(canonical)
        if len(found) >= limit:
            break
    return found


def extract_pay(description: str) -> str:
    text = description or ""
    for pat in _PAY_PATTERNS:
        m = pat.search(text)
        if m:
            return _WS.sub(" ", m.group(0)).strip()
    return ""


_WS = re.compile(r"\s+")
