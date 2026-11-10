import json
from pathlib import Path

import pytest

from ai_recruitment_agent import main
from tests.helpers import FakeGeminiClient, FakeNotion, make_docx, make_pdf


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """No real keys or .env file can leak into a test; the working directory is empty."""
    for name in ("GOOGLE_GEMINI_API_KEY", "NOTION_API_KEY", "DEFAULT_NOTION_DB_ID", "NOTION_DATA_SOURCE_ID", "GEMINI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main.console, "width", 200)


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("NOTION_API_KEY", "test-notion-key")
    monkeypatch.setenv("DEFAULT_NOTION_DB_ID", "db-1")


def candidate_json(**over) -> str:
    data = {
        "full_name": "Ada Lovelace",
        "email": "ada@example.com",
        "contact_number": "+44 20 7946 0958",
        "skills": ["Python", "Math"],
        "experience_summary": "Wrote the first program.",
        "match_score": 85,
        "ranking_category": "High Fit",
        "ranking_reason": "Strong match.",
    }
    data.update(over)
    return json.dumps(data)


JD_JSON = json.dumps({"position_title": "Analyst", "job_id": "JOB-7"})


@pytest.fixture()
def jd_file(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "jd.pdf", "Analyst needed. Job JOB-7. Python required.")


@pytest.fixture()
def cv_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "cvs"
    folder.mkdir()
    make_pdf(folder / "alice.pdf", "Alice, Python developer")
    make_docx(folder / "bob.docx", ["Bob", "Mathematician"])
    (folder / "notes.txt").write_text("not a cv")
    return folder


@pytest.fixture()
def fake_notion(monkeypatch) -> FakeNotion:
    fake = FakeNotion()

    def make_client(auth):
        fake.auth = auth
        return fake.client

    monkeypatch.setattr(main, "NotionClient", make_client)
    return fake


@pytest.fixture()
def fake_gemini(monkeypatch) -> FakeGeminiClient:
    fake = FakeGeminiClient()
    original = main.Screener

    def factory(api_key, model):
        return original(api_key, model, client=fake)

    monkeypatch.setattr(main, "Screener", factory)
    return fake
