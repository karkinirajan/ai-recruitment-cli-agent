# Work done

What this repository was, what was changed, and what still needs a person. Branch: `chore/modernize` (local, nothing pushed).
Start point: `4a4d553`.

## At a glance

- **Was:** a 640-line CLI (published on PyPI as `ai-recruitment-agent` 0.3.2) that reads a folder of CVs and a job description, asks Google Gemini to score each CV and writes
  one page per candidate into a Notion database. It had 44 tests and no lockfile (`requirements.txt` listed bare names). On the **current dependencies it did not work**:
  it named `gemini-1.5-flash`, which Google has retired, so every CV failed with a warning while the command printed "Done" and exited 0; `notion-client` 3 (Notion API
  2025-09-03) has no `databases.query`, so **duplicate detection silently did nothing** (the error was caught and read as "not a duplicate") and `setup-notion` saw no properties; and
  `load_dotenv()` looked next to the installed package instead of the working directory, so the `.env` the README told people to create was never found. It also **trusted the model's
  answer** (a CV could set its own score and category; an invalid e-mail address or a skill containing a comma made Notion refuse the page), put file names and error text into
  terminal markup unescaped (a bracketed file name lost part of its name, error text such as `[/bold]` crashed the run), and had no limit on file size.
- **Now:** all of that fixed and tested. Rewritten into six small modules (settings, extraction, Gemini, Notion, candidate validation, the commands); the score is range-checked and the
  category derived from it; documents are fenced as untrusted data in the prompts; the Notion code speaks data sources; the model is a setting (`GEMINI_MODEL`); the command exits 1 if any
  CV failed and stops after three Gemini failures in a row; 250 tests on the real Notion SDK with only HTTP stubbed, 253 deliberate bugs that the suite fails for, 100% coverage; locked
  dependencies on the latest releases with `uv audit` clean; the wheel builds; CI; README corrected (it described a different set of Notion properties and Python 3.8), `VERSIONS.md`, four docs chapters.
- **Needs a person:** **run it once on a few CVs and a test Notion database**: the Gemini model name (from Google's model list) and the Notion requests were checked against documentation and the SDK, not
  against the live services (no key or integration was available); a person should read the scores before acting on them; push.

## Verified

Run on the final tree, 2026-11-10:

| Gate | Command | Result |
|---|---|---|
| Lint | `uv run ruff check .` | pass (new gate; the rule set is in `pyproject.toml`) |
| Tests | `uv run pytest -q` | 250 passed (44 before; all rewritten: the old ones mocked a Notion client that had a method the real one no longer has) |
| Coverage | temporary `pytest-cov` | 100% of statements (481) and branches (122) |
| Mutation | `tests/mutation/mutate.py` | 253 of 253 killed, on a green baseline (a first run left 25 survivors: 18 missing assertions added, 7 redundant pieces of code simplified) |
| Audit | `uv audit` | no known vulnerabilities in 50 packages |
| Build | `uv build` | sdist and wheel build; the wheel holds the seven modules and the `ai-recruit` entry point; `Requires-Python >=3.11`; `rich` is now a declared dependency |
| Secrets | pattern scan of the tree and all 10 commits | none found (counts only; the one pattern hit in history is a line of code that names an environment variable; `.env*` files were not read: `.env.example` is tracked, as a template) |
| Formatting | | no formatter is configured |

**Not verified:** the live Gemini service (the default model `gemini-3.8-flash` is one of the two Google's model list recommends for new projects; not called); the live Notion API (the
tests run the real `notion-client` SDK with its HTTP layer replaced, so the method names and request shapes are the SDK's, but Notion itself was not contacted); `pip install` of
the published package; the CI workflow (not run).

## Findings and fixes

| Finding | Fix |
|---|---|
| **Retired model** `gemini-1.5-flash`: every CV failed, exit code 0 | `GEMINI_MODEL` setting, default `gemini-3.8-flash`; exit 1 on any failure; stop after 3 Gemini failures in a row |
| **`notion-client` 3 has no `databases.query`**: the duplicate check raised, was caught, and returned "no duplicate"; `setup-notion` read no properties; pages used a `database_id` parent | Rewritten for data sources (`resolve_data_source`, `data_sources.query/update`, a `data_source_id` parent); a failed duplicate check now fails that CV; a database with several data sources asks which |
| **`.env` never found by an installed package** | `find_dotenv(usecwd=True)` |
| **Model output trusted**: score and category could be set by the CV; 1000 or "ninety" went to Notion; an invalid e-mail or a comma in a skill made Notion refuse the page | `candidate.py`: score 0–100 or none (flagged), category derived from the score, text cleaned and bounded, e-mail validated, skills made legal |
| **Prompt injection**: CV and job-description text beside the instructions; the job title and id (model-extracted) put in the next prompt unfenced | Marked, fenced data with a rule; markers inside the text broken up; title and id single-line, bounded and fence-broken. Reduces the risk; the validation is the protection |
| **Rich markup** from file names, errors and model text: `[bold]x.pdf` styled, `[final]` vanished from a name, `[/bold]` in an error crashed the run | Every dynamic value goes through `escape()` |
| **Pretend success** when the Notion library failed to import (`create_notion_page` returned True for no client) | Required imports; no fallback |
| **No file limits**: any size CV, and a DOCX is a zip | 25 MB, 200 MB unpacked, first 50 PDF pages |
| No lockfile; `typer[all]` (extra gone); `rich` and `typing_extensions` imported but undeclared; `pytest-mock` unused; `requires-python >=3.10` (end of life Oct 2026); README said 3.8 | `uv.lock`; declared dependencies; Python 3.11 or newer |
| README: wrong property table (Phone, Experience Years, Strengths, Gaps, ...), `Skills` as text, an example output that the tool never printed | Rewritten from the code |

Details: [docs/02-security.md](docs/02-security.md).

## Changes, file by file

### Source

| File | Was | Now |
|---|---|---|
| `ai_recruitment_agent/main.py` (638 lines) | everything | the two commands, messages and exit codes (330 lines) |
| `settings.py` (new) | module-level `os.getenv` after an import-time `load_dotenv()` | `Settings.load()`, the model setting |
| `extract.py` (new) | text extraction that printed and returned `None` | raises `ExtractionError` with a reason; size, page and unpacked-size limits |
| `gemini.py` (new) | prompt strings and a call that returned `None` on any error | fenced prompts; `GeminiAPIError` vs `GeminiResponseError`; `Screener` |
| `candidate.py` (new) | none | the validation of the model's answer |
| `notion_io.py` (new) | Notion calls with a client that could be `None` | data sources, `NotionError`, `ensure_properties` |
| `main.py` at the repository root | shim | unchanged |

### Configuration and tooling

| File | Was | Now |
|---|---|---|
| `pyproject.toml` | lower bounds from 2023–24, `typer[all]`, Python 3.10 | unbounded dependencies, `rich`, a `dev` group, ruff, Python 3.11 |
| `uv.lock`, `.python-version` (new) | none | locked set; Python 3.14 |
| `requirements.txt` | bare names | removed (superseded by `pyproject.toml` and `uv.lock`; nothing read it; the sdist exclusion for it is gone too) |
| `.github/workflows/ci.yml` (new) | none | Python 3.11 and 3.14: lint, tests, audit, build |
| `.gitignore` | | also ignores `.coverage` and `htmlcov/` |
| `tests/` | 1 file, 44 tests | 7 files, 250 tests, `tests/mutation/` (driver, 253 mutants) |

### Docs

`README.md` rewritten from the code (the owner's structure kept); `VERSIONS.md`, `docs/01` to `04` and this file are new.

## What a person might want to do

1. **Try it on a handful of CVs and a throw-away Notion database**, then read the pages. Confirm the model name works with your key (`GEMINI_MODEL` if not) and that the integration can read and write the database.
2. **Read the scores before acting on them.** The category follows the score and the score is validated, but a CV can still try to talk the model into a plausible number.
3. The tool sends CV contents (personal data) to Google and stores them in Notion.
4. **Push** when satisfied: `git push -u origin chore/modernize` (not done here). The package version (0.3.2) was not changed and nothing was published.

## Known and left alone

- The Gemini and Notion services were not called; the default model is taken from Google's published list.
- A CV can still push the model toward a plausible but wrong score; nothing can detect that.
- Only the first 50 pages of a PDF and the first 12,000 characters of a CV (8,000 of the job description) are sent to the model; before, it was 3,000 and 4,000, silently.
