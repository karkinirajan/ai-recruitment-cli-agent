# 03. Testing

```bash
uv run pytest -q          # no network, no API keys, a few seconds
uv run ruff check .       # lint
```

## Layout

```text
tests/
  helpers.py            make_pdf / make_docx (real files), FakeNotion, FakeGeminiClient, api_error
  conftest.py           clean environment for every test, the fake clients wired into the CLI
  test_candidate.py     every rule for what the model says: scores, categories, e-mail, phone, skills, JSON parsing
  test_extract.py       PDF and DOCX extraction on real files; the size, page and zip-bomb limits
  test_gemini.py        the prompts (fencing, limits, the rules), the call, error mapping
  test_notion_io.py     data-source resolution, duplicate check, page and property creation
  test_settings.py      environment parsing, .env lookup
  test_cli.py           the commands end to end: process, setup-notion, exit codes, messages
  mutation/             the mutation driver and its list
```

**The Notion tests run the real `notion-client` SDK** with only its HTTP layer replaced (`FakeNotion`): every call goes through the SDK's own endpoint methods and
the request that would be sent is recorded. A call to a method the installed SDK does not have (the old `databases.query`) fails the test, which a `MagicMock` would
have hidden. Gemini is faked at `client.models.generate_content`; PDFs and DOCX files in the tests are real files.

## Coverage

100% of statements and branches over the package (481 statements, 122 branches; measured with a temporary `pytest-cov`, which is not a dependency); the
`if __name__` entry of `main.py` is run by a test through `runpy`.

## Mutation checks

`tests/mutation/mutants.py` holds the deliberate bugs, each `(name, file, old text, new text)`: a threshold shifted, a validation dropped, an error swallowed,
a Notion filter changed, an exit code flipped: 253 in all. The driver applies one at a time and counts it **killed** if the tests then fail. All 253 are killed. (The first
run left 25 survivors: 18 missing assertions, now tests, and 7 pieces of code that were redundant or arbitrary and were simplified: a `truncate` that sliced twice, a `len`
guard the regex made unnecessary, two checks the next line repeated, a loop flag that always had the same value as the failure count, and the like.)

```bash
python3 tests/mutation/mutate.py tests/mutation/mutants.py -- uv run pytest -x -q
```

Rules: the suite must be green first (the driver checks); do not edit the tree while it runs; each pattern must occur exactly once.

## Not tested

The live Gemini and Notion services (no key or integration was available): the model name comes from Google's published model list, the Notion requests are
checked against the SDK's endpoint methods and Notion's upgrade guide, not against the real API.
