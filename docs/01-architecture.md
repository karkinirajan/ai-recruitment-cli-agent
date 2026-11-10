# 01. Architecture

A command-line tool: read a job description and a folder of CVs, ask Gemini to screen each CV against the job, check the answer, and write one page per
candidate into a Notion database.

```text
ai-recruit process CVS/ JD.pdf
  settings.py    keys and ids from the environment and a .env file in the working directory
  extract.py     PDF / DOCX text (size, page and unpacked-size limits)
  gemini.py      the two prompts (documents fenced as untrusted data) and the one Gemini call
  candidate.py   the model's JSON → a Candidate whose every field is safe to store
  notion_io.py   find the data source, check for a duplicate, create the page, add the properties
  main.py        the typer commands: process, setup-notion; progress, messages, exit codes
```

`ai_recruitment_agent.main:app` is the console script (`ai-recruit`); the repository's root `main.py` only re-exports it.

## One CV, step by step

1. `extract_text` reads the file (`ExtractionError` with a reason if it is too large, damaged, empty or a scan).
2. `Screener.analyse` builds the prompt (the job description and the CV between `<<<...>>>` markers, with a rule that they are data) and calls Gemini
   asking for JSON.
3. `normalize_candidate` checks the answer: the score must be a whole 0–100 number, the category is *derived* from the score, text is cleaned and bounded,
   an invalid e-mail address is dropped, skills are made legal for a Notion multi-select.
4. `find_duplicate` asks the data source for the same e-mail (and job id); with no e-mail it uses the CV file name.
5. `create_candidate_page` writes the page under the data source.

Each failure has a type and a reason: `ExtractionError`, `GeminiAPIError` (the service did not answer), `GeminiResponseError` (it did, but not with a JSON
object), `NotionError`. The command turns them into one line per CV; three `GeminiAPIError`s in a row stop the run.

## Notion data sources

`notion-client` 3 speaks Notion API 2025-09-03, where a database's schema and rows live in a *data source*: `data_sources.query`, `data_sources.update`
and a `data_source_id` page parent replace `databases.query`, `databases.update` and a `database_id` parent. `resolve_data_source` reads the database,
takes its only data source, or lists several and asks for `--data-source-id`.

## Exit codes

0: every CV was processed (or was a duplicate), or the folder had none. 1: a setting is missing, the database or job description could not be read, or
at least one CV failed. 2: a command-line usage error (a folder that does not exist).
