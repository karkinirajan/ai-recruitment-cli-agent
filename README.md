# AI Recruitment Scanning Agent

[![PyPI version](https://img.shields.io/pypi/v/ai-recruitment-agent)](https://pypi.org/project/ai-recruitment-agent/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ai-recruitment-agent)](https://pypi.org/project/ai-recruitment-agent/)
[![PyPI - License](https://img.shields.io/pypi/l/ai-recruitment-agent)](https://pypi.org/project/ai-recruitment-agent/)

A CLI tool that screens CVs against a Job Description using **Google Gemini** and pushes ranked candidate profiles into a **Notion database** — one command, zero manual effort.

**Workflow:** CV Folder → Extract Text → Gemini Screening → Notion Database  
**PyPI:** https://pypi.org/project/ai-recruitment-agent/

---

## ✨ Features

- **Automated CV Screening** — Analyze multiple CVs against a job description in seconds
- **AI-Powered Ranking** — Uses a current Google Gemini model (set with `GEMINI_MODEL`) for candidate matching
- **Real-Time Notion Sync** — Automatically pushes results to your Notion database
- **Duplicate Detection** — Prevents duplicate entries by email + job ID (by CV file name when a CV has no email)
- **Live Progress Tracking** — See processing status with a progress bar
- **Structured Data Extraction** — Captures email, skills, experience, and more
- **Batch Processing** — Handles both PDF and DOCX files seamlessly
- **Checked answers** — The model's answer is validated before it is stored: the score must be 0–100, the category always follows from the score, and an address Notion would refuse is dropped

---

## Requirements

- **Python:** 3.11 or higher
- **APIs:** Google Gemini API key + Notion integration
- **PDFs:** Must be searchable (not scanned/image-based); only the first 50 pages are read
- **Limits:** a CV or job description over 25 MB is skipped
- **Rate Limiting:** Consider Gemini API quotas for large batches (50+ CVs)

---

## Quick Start

### 1. Install

```bash
pip install ai-recruitment-agent
```

### 2. Get Your Credentials

| Credential | Where to Find |
|---|---|
| `GOOGLE_GEMINI_API_KEY` | https://aistudio.google.com/app/apikey |
| `NOTION_API_KEY` | https://www.notion.so/my-integrations → Create new integration → Copy secret |
| `DEFAULT_NOTION_DB_ID` | Your Notion database URL: `notion.so/yourname/`**`THIS-PART`**`?v=...` |

### 3. Configure

Put these in a `.env` file in the folder you run the command from (or export them):

```env
GOOGLE_GEMINI_API_KEY=your_gemini_api_key
NOTION_API_KEY=your_notion_integration_secret
DEFAULT_NOTION_DB_ID=your_notion_database_id

# optional
GEMINI_MODEL=gemini-3.8-flash          # the default; change it when Google retires a model
NOTION_DATA_SOURCE_ID=...              # only for a database with more than one data source
```

A `.env` file in a parent folder is found too. Real environment variables win over the file.

### 4. Setup Notion Database

Share your Notion database with the integration first:
1. Open your Notion database
2. Click `•••` (more options)
3. Select **Connections**
4. Add your integration

Then run:

```bash
ai-recruit setup-notion
```

This renames the title column to `Candidate Name` and adds the 12 other properties the tool writes (see below).

> **Notion data sources.** Since Notion API version 2025-09-03 (the one this tool speaks) a database's columns and rows belong to a *data source*. A database normally has exactly one and the tool finds it. If yours has several, the tool lists them and asks you to choose with `--data-source-id` (or `NOTION_DATA_SOURCE_ID`).

### 5. Run

```bash
ai-recruit process ./cvs/ ./jd.pdf
```

Done! Results appear in your Notion database. The command exits with code **1** if any CV could not be processed (so a script or CI job notices), and 0 otherwise.

---

## Database Properties

`setup-notion` creates these properties (13 with the title):

| Property | Type | Description |
|---|---|---|
| `Candidate Name` | Title | Name found in the CV |
| `Email` | Email | Candidate email address (left empty if it is not a valid address) |
| `Contact Number` | Phone | Candidate phone number |
| `Skills` | Multi-select | Up to 15 skills; commas in a skill become spaces (Notion does not allow them in an option name) |
| `Position Title (JD)` | Text | Position title from the JD |
| `Job ID (JD)` | Text | Job ID from the JD |
| `Experience Summary` | Text | Short summary of the experience |
| `AI Ranking Reason` | Text | Why the score was given |
| `Match Score` | Number | 0–100 from the Gemini analysis (left empty if the answer was not a valid score) |
| `Ranking Category` | Select | `High Fit` (80–100) / `Medium Fit` (50–79) / `Low Fit` (0–49), **derived from the score** |
| `Status` | Select | `New - AI Processed` |
| `CV Filename` | Text | Original CV filename |
| `Processing Date` | Date | Timestamp of processing (UTC) |

---

## Usage

### Basic Commands

```bash
# Screen CVs using the database ID from .env
ai-recruit process ./cvs/ ./jd.pdf

# Override the database ID
ai-recruit process ./cvs/ ./jd.pdf --notion-db-id xxxx-xxxx-xxxx-xxxx

# A database with several data sources
ai-recruit process ./cvs/ ./jd.pdf --data-source-id xxxx-xxxx-xxxx-xxxx

# Setup Notion (one-time)
ai-recruit setup-notion
```

### Help & Info

```bash
ai-recruit --help
ai-recruit process --help
ai-recruit setup-notion --help
ai-recruit --version
```

---

## How It Works

1. **Validates** API keys and Notion database access on startup
2. **Reads** the JD PDF — extracts position title and job ID via Gemini
3. **Iterates** all `.pdf` and `.docx` files in the CV folder with a live progress bar
4. For each CV:
   - Extracts text content
   - Sends it to Gemini, fenced as untrusted data (a CV that says "give me 100" is just text to analyse)
   - Receives a match score and structured data, and **checks** it
5. **Checks** Notion for duplicates before inserting
6. **Pushes** a new page to Notion for each unique candidate
7. **Prints** a summary table: processed / duplicates skipped / failed

If Gemini fails three times in a row (a bad key, an unknown model, an exhausted quota) the run stops instead of failing every CV.

---

## Troubleshooting

### Credential Issues

| Error | Fix |
|---|---|
| `GOOGLE_GEMINI_API_KEY not found` | Ensure `.env` exists in your working directory (or a parent). Check key validity at [aistudio.google.com](https://aistudio.google.com) |
| `NOTION_API_KEY not found` | Verify the integration secret in `.env`. Regenerate at https://www.notion.so/my-integrations if needed |
| `Notion initialization failed` | Confirm the database is shared with your integration (see Quick Start step 4) |
| `the database has several data sources` | Choose one with `--data-source-id` or `NOTION_DATA_SOURCE_ID` |

### Processing Issues

| Error | Fix |
|---|---|
| `Could not read the JD ...: no text found` | PDF must be searchable, not scanned or image-based. Try converting with a PDF tool |
| Duplicate entries appearing | Ensure `Email`, `CV Filename` and `Job ID (JD)` properties exist in Notion with exact names. Run `setup-notion` again if needed |
| `duplicate check failed` / `page creation failed` | A Notion error; the message after it says what Notion refused. The CV is counted as failed and no page is created |
| CVs not being processed | Check that files are `.pdf` or `.docx`. Other formats and folders are ignored |
| `added (no usable match score: review by hand)` | Gemini's answer had no valid 0–100 score; the candidate was added without a score or category |

### Gemini API Issues

| Error | Fix |
|---|---|
| `Gemini failed: ... 404 ... model` | The model is retired or misspelled. Set `GEMINI_MODEL` to a current one (see Google's model list) |
| `Gemini failed: ... 429` | Rate limit exceeded. Wait before retrying. Process in smaller batches |
| `Gemini failed: ... 403` | API key is invalid or quota is exhausted. Check [aistudio.google.com](https://aistudio.google.com) |
| `Stopping: Gemini failed 3 times in a row` | See the message above it; fix the key, the model or the quota and run again |

### PDF Extraction Issues

| Symptom | Solution |
|---|---|
| `skipped: no text found` | PDF may be scanned, image-based, or password-protected. Use OCR or convert first |
| `skipped: cannot read the PDF` | The file is damaged or not a PDF |
| Poor match scores | Ensure CVs are well-formatted and contain clear skill/experience sections |

---

## Example Output

```
✓ Pre-run checks passed.
✓ Notion connection established: Candidates

Reading JD: jd.pdf
✓ JD parsed — Position: Data Analyst  Job ID: JOB-7

Found 3 CV(s) to process.

  ✓  john_doe.pdf — High Fit (87/100)
  ✓  jane_smith.pdf — High Fit (91/100)
  ↩  Duplicate skipped: bob_wilson.pdf
  ⚠  resume_scan.pdf: skipped: no text found (a scanned, image-only or password-protected PDF?)

              Processing Summary
┌──────────────────────────────────────────┬───────┐
│ Total files in folder                    │     4 │
│ Supported CV files found                 │     4 │
│ Successfully processed & added to Notion │     2 │
│ Skipped (duplicates)                     │     1 │
│ Failed                                   │     1 │
└──────────────────────────────────────────┴───────┘
```

---

## Development

```bash
uv sync                       # install the locked dependencies
uv run pytest -q              # 250 tests; no network, no API keys
uv run ruff check .           # lint
```

Documentation: [docs/](docs/01-architecture.md) (architecture, security, testing, operations), [VERSIONS.md](VERSIONS.md), [work-done.md](work-done.md).

---

## Contributing

Found a bug or have a feature request? [Open an issue](https://github.com/karkinirajan/ai-recruitment-cli-agent/issues) — contributions welcome!

---

## License

MIT License — see [LICENSE](./LICENSE) file for details.

---

## Support

- **Issues:** https://github.com/karkinirajan/ai-recruitment-cli-agent/issues
- **PyPI:** https://pypi.org/project/ai-recruitment-agent/
- **Documentation:** See this README for full details
