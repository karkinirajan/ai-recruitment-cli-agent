# 04. Operations

## Running

| Command | Does |
|---|---|
| `pip install ai-recruitment-agent` | Install the published package |
| `ai-recruit setup-notion` | One time: share the database with the integration first, then add the properties |
| `ai-recruit process CVS/ JD.pdf` | Screen a folder; exit code 1 if any CV failed |
| `uv sync && uv run ai-recruit ...` | Run from a checkout |

## Settings

| Variable | |
|---|---|
| `GOOGLE_GEMINI_API_KEY`, `NOTION_API_KEY`, `DEFAULT_NOTION_DB_ID` | Required (or `--notion-db-id`) |
| `GEMINI_MODEL` | Optional; default `gemini-3.8-flash`. Google retires models regularly, so a `404 ... model` error means set this to a current one |
| `NOTION_DATA_SOURCE_ID` | Only for a Notion database with more than one data source |

They are read from the environment and from a `.env` file in the working directory (or a parent); the environment wins.

## Before relying on this

1. **Run it once on a few CVs against a test database**: the Gemini model name and the Notion data-source requests were checked against documentation and the SDK, not
   against the live services.
2. A person should review the scores. The tool derives the category from the score and validates it, but a model can be wrong or be talked into a high score.
3. Personal data goes to Google and Notion (see [02 Security](02-security.md)).

## CI

`.github/workflows/ci.yml` runs on every push and pull request, on Python 3.11 and 3.14: lint, tests, and (once, on 3.14) `uv audit` and `uv build`.

## Releasing

The version is in `pyproject.toml` and `ai_recruitment_agent/__init__.py` (they must match); this pass did not change it or publish anything.
