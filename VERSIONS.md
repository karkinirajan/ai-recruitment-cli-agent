# Versions

What this project runs on, and why, as of 2026-11-10. Everything below was read from `uv.lock`, the installed environment, Google's published model list
and Notion's API documentation on that day; nothing is quoted from memory.

## Runtime

| | Version | Notes |
|---|---|---|
| Python | **3.14** (`.python-version`); `requires-python >=3.11` | It was `>=3.10`, which reached end of life in October 2026, and the README said 3.8. CI runs 3.11 and 3.14. |
| uv | 0.13.7 | Installs and locks everything. |

## Application

The project had **no lockfile**: `requirements.txt` listed bare names and `pyproject.toml` lower bounds from 2023 to 2024. `pyproject.toml` now lists the
dependencies without bounds and `uv.lock` pins them (`requirements.txt` was removed).

| Package | Locked | Was | Notes |
|---|---|---|---|
| typer | 0.29.0 | `typer[all]>=0.9.0` | The `all` extra no longer exists. |
| rich | 15.0.0 | (undeclared) | The code imports `rich` directly; it was only there through typer. |
| python-dotenv | 1.2.4 | `>=1.0.0` | |
| **google-genai** | 3.0.0 | `>=1.0.0` | A major release; `genai.Client(...).models.generate_content(..., config=GenerateContentConfig(response_mime_type=...))` is unchanged. |
| **notion-client** | 3.1.0 | `>=2.0.0` | Speaks Notion API `2025-09-03`: **no `databases.query`**, data sources instead (see [docs/01-architecture.md](docs/01-architecture.md)). |
| pdfplumber | 0.11.10 | `>=0.10.0` | |
| python-docx | 1.2.0 | `>=1.0.0` | |

## Development (`[dependency-groups] dev`)

| Package | Locked | Notes |
|---|---|---|
| pytest | 9.2.0 | |
| ruff | 0.17.4 | New lint gate (`E4 E7 E9 F B I UP`, line length 140, target py311) |

`pytest-mock` was a dev dependency and nothing used it; it is gone.

## The Gemini model

`GEMINI_MODEL` defaults to **`gemini-3.8-flash`**. The code named `gemini-1.5-flash`, which Google has retired; Google's model list (read 2026-11-10) says 2.0 is shut
down, 2.5 Flash is deprecated for new use, and to "use our latest models: 3.5 Flash-Lite or 3.8 Flash" for new projects. The default is one of those two. It is a setting
because Google retires models regularly. **It was not run against the live API** (no key was available).

## Changes made in this pass

- Every package at its latest release; `uv audit` reports no known vulnerabilities.
- Packaging: `[dependency-groups]` instead of `[project.optional-dependencies]` for the tools, a ruff configuration, `requires-python >=3.11`; the classifiers drop 3.10 and add 3.14.
- The CI actions are `actions/checkout@v7` (latest at the time of writing).

## Left alone

Nothing the resolver offered was held back. Re-check with `uv lock --upgrade` and `uv audit` when touching dependencies.
