"""What the screening model says about a CV, checked before it is believed or sent anywhere.

The model's answer is text produced after reading a document that anyone can write, so nothing in it is trusted: scores are range-checked,
the category is derived from the score (never taken from the model), free text is cleaned and bounded, and an e-mail address that Notion
would refuse is dropped instead of failing the whole page.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

NOTION_TEXT_LIMIT = 1999  # Notion rich_text hard limit
NOTION_OPTION_LIMIT = 99  # Notion select / multi-select option names
MAX_SKILLS = 15
HIGH_FIT_FROM = 80
MEDIUM_FIT_FROM = 50

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL = re.compile(r"^[^@\s,;<>()\[\]\\]+@[^@\s,;<>()\[\]\\]+\.[^@\s,;<>()\[\]\\]+$")
NOT_AVAILABLE = "N/A"


def truncate(text: str, limit: int = NOTION_TEXT_LIMIT) -> str:
    """Cut text to a limit."""
    return text[:limit]


def clean_text(value: Any, limit: int = NOTION_TEXT_LIMIT) -> str:
    """Text from the model: control characters removed, trimmed, bounded; "N/A" when nothing is left."""
    if value is None or isinstance(value, (dict, list)):
        return NOT_AVAILABLE
    text = _CONTROL.sub("", str(value)).strip()
    return truncate(text, limit) if text else NOT_AVAILABLE


def parse_json_response(text: str | None) -> dict[str, Any] | None:
    """Parse a JSON object from a model response, falling back to the first {...} span; None if there is none."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def category_for(score: int) -> str:
    """The ranking category for a score: High Fit from 80, Medium Fit from 50, otherwise Low Fit."""
    if score >= HIGH_FIT_FROM:
        return "High Fit"
    if score >= MEDIUM_FIT_FROM:
        return "Medium Fit"
    return "Low Fit"


def clean_score(value: Any) -> int | None:
    """A whole score from 0 to 100, or None. Accepts 85, 85.4 (rounded) and "85"; refuses booleans, NaN, and anything outside the range."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"\d+(\.\d+)?", text):
            return None
        value = float(text)
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    score = round(value)
    return score if 0 <= score <= 100 else None


def clean_email(value: Any) -> str | None:
    """An e-mail address Notion will accept, or None."""
    if not isinstance(value, str):
        return None
    text = _CONTROL.sub("", value).strip()
    return text if len(text) <= 254 and _EMAIL.match(text) else None


def clean_phone(value: Any) -> str | None:
    """A phone number: free text of at least five digits (Notion accepts any text), or None."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = _CONTROL.sub("", str(value)).strip()
    return text[:50] if sum(ch.isdigit() for ch in text) >= 5 else None


def clean_skills(value: Any) -> tuple[str, ...]:
    """Skills for a Notion multi-select: commas are not allowed in an option name, so they become spaces; duplicates, empty and "N/A"
    entries are dropped; each is at most 99 characters; at most 15 are kept."""
    if not isinstance(value, list):
        return ()
    skills: list[str] = []
    seen: set[str] = set()
    for item in value:
        if item is None or isinstance(item, (dict, list, bool)):
            continue
        text = re.sub(r"\s+", " ", _CONTROL.sub("", str(item)).replace(",", " ")).strip()[:NOTION_OPTION_LIMIT].strip()
        key = text.casefold()
        if not text or key == NOT_AVAILABLE.casefold() or key in seen:
            continue
        seen.add(key)
        skills.append(text)
        if len(skills) == MAX_SKILLS:
            break
    return tuple(skills)


@dataclass(frozen=True)
class Candidate:
    full_name: str
    email: str | None
    contact_number: str | None
    skills: tuple[str, ...]
    experience_summary: str
    match_score: int | None
    ranking_category: str | None
    ranking_reason: str


def normalize_candidate(raw: dict[str, Any]) -> Candidate:
    """Turn the model's JSON into a Candidate whose every field is safe to store."""
    score = clean_score(raw.get("match_score"))
    return Candidate(
        full_name=clean_text(raw.get("full_name"), 200),
        email=clean_email(raw.get("email")),
        contact_number=clean_phone(raw.get("contact_number")),
        skills=clean_skills(raw.get("skills")),
        experience_summary=clean_text(raw.get("experience_summary")),
        match_score=score,
        ranking_category=category_for(score) if score is not None else None,
        ranking_reason=clean_text(raw.get("ranking_reason")),
    )
