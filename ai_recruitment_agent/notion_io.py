"""Reading and writing the Notion database.

Notion API version 2025-09-03 (the version `notion-client` 3 speaks) moved a database's schema and rows to *data sources*: pages are created
in, queried from and properties added to a data source, not the database. A database usually has exactly one; `resolve_data_source` finds
it (or asks which, when there are several).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from notion_client import Client
from notion_client.errors import NotionClientErrorBase

from ai_recruitment_agent.candidate import (
    NOT_AVAILABLE,
    NOTION_OPTION_LIMIT,
    Candidate,
    truncate,
)

# `NotionClientError` in the SDK is a type alias for a union of these; the exception base class to catch is NotionClientErrorBase.
NOTION_ERRORS = (NotionClientErrorBase, httpx.HTTPError)
STATUS_NEW = "New - AI Processed"

# The columns the tool writes, as Notion property definitions. `setup-notion` adds the ones a database lacks.
REQUIRED_PROPERTIES: dict[str, Any] = {
    "Email": {"email": {}},
    "Contact Number": {"phone_number": {}},
    "Skills": {"multi_select": {}},
    "Position Title (JD)": {"rich_text": {}},
    "Job ID (JD)": {"rich_text": {}},
    "Experience Summary": {"rich_text": {}},
    "AI Ranking Reason": {"rich_text": {}},
    "Match Score": {"number": {"format": "number"}},
    "Ranking Category": {
        "select": {
            "options": [
                {"name": "High Fit", "color": "green"},
                {"name": "Medium Fit", "color": "yellow"},
                {"name": "Low Fit", "color": "red"},
            ]
        }
    },
    "Status": {"select": {"options": [{"name": STATUS_NEW, "color": "blue"}]}},
    "CV Filename": {"rich_text": {}},
    "Processing Date": {"date": {}},
}
TITLE_PROPERTY = "Candidate Name"


class NotionError(RuntimeError):
    """A Notion call failed, or the database cannot be used; the message is safe to show."""


@dataclass(frozen=True)
class DataSource:
    id: str
    database_title: str


def _title(obj: dict[str, Any], fallback: str) -> str:
    blocks = obj.get("title") or []
    return str(blocks[0].get("plain_text", fallback)) if blocks and isinstance(blocks[0], dict) else fallback


def resolve_data_source(notion: Client, database_id: str, data_source_id: str | None = None) -> DataSource:
    """The data source to use. An explicit id wins; otherwise the database's only data source; a database with several needs `data_source_id`."""
    try:
        if data_source_id:
            source = notion.data_sources.retrieve(data_source_id=data_source_id)
            return DataSource(id=data_source_id, database_title=_title(source, data_source_id))
        database = notion.databases.retrieve(database_id=database_id)
    except NOTION_ERRORS as exc:
        raise NotionError(f"cannot read the Notion database: {exc}") from exc
    sources = [s for s in (database.get("data_sources") or []) if isinstance(s, dict) and s.get("id")]
    title = _title(database, database_id)
    if len(sources) == 1:
        return DataSource(id=str(sources[0]["id"]), database_title=title)
    if not sources:
        raise NotionError("the Notion database has no data source (is the integration connected to it?)")
    listing = ", ".join(f"{s.get('name', '?')} ({s['id']})" for s in sources)
    raise NotionError(f"the database has several data sources: {listing}. Choose one with --data-source-id or NOTION_DATA_SOURCE_ID")


def find_duplicate(notion: Client, data_source_id: str, candidate: Candidate, job_id: str, cv_filename: str) -> bool:
    """Whether this candidate is already in the database for this job: by e-mail address when there is one, otherwise by CV file name."""
    filters: list[dict[str, Any]] = []
    if candidate.email:
        filters.append({"property": "Email", "email": {"equals": candidate.email}})
    elif cv_filename:
        filters.append({"property": "CV Filename", "rich_text": {"equals": truncate(cv_filename)}})
    else:
        return False
    if job_id and job_id != NOT_AVAILABLE:
        filters.append({"property": "Job ID (JD)", "rich_text": {"equals": truncate(job_id)}})
    try:
        response = notion.data_sources.query(
            data_source_id=data_source_id,
            filter={"and": filters} if len(filters) > 1 else filters[0],
            page_size=1,
        )
    except NOTION_ERRORS as exc:
        raise NotionError(f"duplicate check failed: {exc}") from exc
    return bool(response.get("results"))


def candidate_properties(candidate: Candidate, details: dict[str, str], cv_filename: str) -> dict[str, Any]:
    """The Notion page properties for a candidate. Optional columns are left out when the value is missing or invalid."""

    def rich_text(value: str) -> dict[str, Any]:
        return {"rich_text": [{"text": {"content": truncate(str(value))}}]}

    properties: dict[str, Any] = {
        TITLE_PROPERTY: {"title": [{"text": {"content": truncate(candidate.full_name, 200)}}]},
        "CV Filename": rich_text(cv_filename),
        "Position Title (JD)": rich_text(details.get("position_title", NOT_AVAILABLE)),
        "Job ID (JD)": rich_text(details.get("job_id", NOT_AVAILABLE)),
        "Experience Summary": rich_text(candidate.experience_summary),
        "AI Ranking Reason": rich_text(candidate.ranking_reason),
        "Processing Date": {"date": {"start": datetime.now(UTC).isoformat()}},
        "Status": {"select": {"name": STATUS_NEW}},
    }
    if candidate.email:
        properties["Email"] = {"email": candidate.email}
    if candidate.contact_number:
        properties["Contact Number"] = {"phone_number": candidate.contact_number}
    if candidate.skills:
        properties["Skills"] = {"multi_select": [{"name": truncate(s, NOTION_OPTION_LIMIT)} for s in candidate.skills]}
    if candidate.match_score is not None:
        properties["Match Score"] = {"number": candidate.match_score}
    if candidate.ranking_category:
        properties["Ranking Category"] = {"select": {"name": candidate.ranking_category}}
    return properties


def create_candidate_page(
    notion: Client, data_source_id: str, candidate: Candidate, details: dict[str, str], cv_filename: str
) -> None:
    """Add one candidate to the data source."""
    try:
        notion.pages.create(
            parent={"type": "data_source_id", "data_source_id": data_source_id},
            properties=candidate_properties(candidate, details, cv_filename),
        )
    except NOTION_ERRORS as exc:
        raise NotionError(f"page creation failed: {exc}") from exc


def ensure_properties(notion: Client, data_source_id: str) -> list[tuple[str, str]]:
    """Make the data source have every column the tool writes. Returns (what happened, property name) pairs:
    "exists", "added", "renamed" (the title column became "Candidate Name") or "rename-failed"."""
    report: list[tuple[str, str]] = []
    try:
        existing: dict[str, Any] = notion.data_sources.retrieve(data_source_id=data_source_id).get("properties", {})
        names = set(existing)

        title_key = next((k for k, v in existing.items() if isinstance(v, dict) and v.get("type") == "title"), None)
        if title_key == TITLE_PROPERTY:
            report.append(("exists", TITLE_PROPERTY))
        elif title_key:
            try:
                notion.data_sources.update(data_source_id=data_source_id, properties={title_key: {"name": TITLE_PROPERTY}})
                report.append(("renamed", f"{title_key} -> {TITLE_PROPERTY}"))
            except NOTION_ERRORS:
                report.append(("rename-failed", title_key))

        report.extend(("exists", name) for name in REQUIRED_PROPERTIES if name in names)
        missing = {name: spec for name, spec in REQUIRED_PROPERTIES.items() if name not in names}
        if missing:
            notion.data_sources.update(data_source_id=data_source_id, properties=missing)
            report.extend(("added", name) for name in missing)
    except NOTION_ERRORS as exc:
        raise NotionError(f"cannot add the properties: {exc}") from exc
    return report
