import re

import pytest
from typer.testing import CliRunner

from ai_recruitment_agent import __version__, main
from ai_recruitment_agent.main import app
from tests.conftest import JD_JSON, candidate_json
from tests.helpers import make_docx, make_pdf

runner = CliRunner()


def exited(result, code: int) -> bool:
    """The command ended by exiting with `code`, not by crashing (a crash also has a non-zero exit code in CliRunner)."""
    return result.exit_code == code and (result.exception is None or isinstance(result.exception, SystemExit))


def flat(output: str) -> str:
    """Output with each run of whitespace (including line wraps) as one space."""
    return re.sub(r"\s+", " ", output)


class TestBasics:
    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert result.output.strip() == f"ai-recruitment-agent v{__version__}"
        assert runner.invoke(app, ["-V"]).output.strip() == f"ai-recruitment-agent v{__version__}"

    def test_no_arguments_shows_the_banner_and_the_settings(self):
        result = runner.invoke(app, [])
        out = flat(result.output)
        assert result.exit_code == 0
        for needle in ("AI Recruitment Scanning Agent", "ai-recruit process", "GOOGLE_GEMINI_API_KEY", "NOTION_API_KEY", "DEFAULT_NOTION_DB_ID", "GEMINI_MODEL", "NOTION_DATA_SOURCE_ID"):
            assert needle in out

    def test_help_lists_both_commands(self):
        out = flat(runner.invoke(app, ["--help"]).output)
        assert "process" in out and "setup-notion" in out

    def test_process_help_mentions_the_options(self):
        out = flat(runner.invoke(app, ["process", "--help"]).output)
        assert "--notion-db-id" in out and "--data-source-id" in out


class TestProcessConfiguration:
    def test_every_missing_setting_is_listed_and_the_exit_code_is_1(self, cv_folder, jd_file):
        result = runner.invoke(app, ["process", str(cv_folder), str(jd_file)])
        out = flat(result.output)
        assert exited(result, 1)
        assert "GOOGLE_GEMINI_API_KEY not found" in out
        assert "NOTION_API_KEY not found" in out
        assert "Notion Database ID is not provided" in out

    def test_a_database_id_on_the_command_line_satisfies_the_check(self, cv_folder, jd_file, monkeypatch):
        monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "g")
        monkeypatch.setenv("NOTION_API_KEY", "n")
        out = flat(runner.invoke(app, ["process", str(cv_folder), str(jd_file), "--notion-db-id", "db-9"]).output)
        assert "Notion Database ID is not provided" not in out

    def test_a_data_source_id_alone_satisfies_the_check(self, cv_folder, jd_file, monkeypatch):
        monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "g")
        monkeypatch.setenv("NOTION_API_KEY", "n")
        out = flat(runner.invoke(app, ["process", str(cv_folder), str(jd_file), "--data-source-id", "ds-9"]).output)
        assert "Notion Database ID is not provided" not in out

    def test_a_folder_that_does_not_exist_is_refused_by_the_parser(self, jd_file, tmp_path):
        result = runner.invoke(app, ["process", str(tmp_path / "nope"), str(jd_file)])
        assert result.exit_code == 2

    def test_the_keys_are_read_from_a_dotenv_file_in_the_working_directory(self, cv_folder, jd_file, tmp_path, fake_notion, fake_gemini):
        (tmp_path / ".env").write_text("GOOGLE_GEMINI_API_KEY=g\nNOTION_API_KEY=n\nDEFAULT_NOTION_DB_ID=db-1\n")
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(full_name="Bob")]
        result = runner.invoke(app, ["process", str(cv_folder), str(jd_file)])
        assert result.exit_code == 0, result.output


class TestProcess:
    def run(self, cv_folder, jd_file, *extra):
        return runner.invoke(app, ["process", str(cv_folder), str(jd_file), *extra])

    def test_a_clean_run_adds_every_cv(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(full_name="Bob", email="bob@example.com", match_score=55)]
        result = self.run(cv_folder, jd_file)
        out = flat(result.output)
        assert result.exit_code == 0, result.output
        assert "Notion connection established: Candidates" in out
        assert "Position: Analyst Job ID: JOB-7" in out
        assert "Found 2 CV(s) to process." in out
        assert "alice.pdf — High Fit (85/100)" in out
        assert "bob.docx — Medium Fit (55/100)" in out
        assert "2 candidate(s) added to Notion database Candidates" in out
        pages = fake_notion.of("POST", "pages")
        assert len(pages) == 2
        assert all(p["body"]["parent"] == {"type": "data_source_id", "data_source_id": "ds-1"} for p in pages)

    def test_the_summary_table(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        out = self.run(cv_folder, jd_file).output
        rows = {m.group(1).strip(): m.group(2) for m in re.finditer(r"│ (.+?)\s*│\s*(\d+) │", out)}
        assert rows == {
            "Total files in folder": "3",
            "Supported CV files found": "2",
            "Successfully processed & added to Notion": "2",
            "Skipped (duplicates)": "0",
            "Failed": "0",
        }

    def test_a_folder_named_like_a_cv_is_not_screened(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        (cv_folder / "archive.pdf").mkdir()
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        out = flat(self.run(cv_folder, jd_file).output)
        assert "Found 2 CV(s) to process." in out
        assert "archive.pdf" not in out

    def test_without_an_email_the_duplicate_check_uses_the_file_name_and_the_job_id(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, candidate_json(email="N/A"), candidate_json(email="N/A")]
        self.run(cv_folder, jd_file)
        queries = [c["body"]["filter"] for c in fake_notion.of("POST", "data_sources/ds-1/query")]
        assert queries[0] == {
            "and": [
                {"property": "CV Filename", "rich_text": {"equals": "alice.pdf"}},
                {"property": "Job ID (JD)", "rich_text": {"equals": "JOB-7"}},
            ]
        }
        assert queries[1]["and"][0]["rich_text"]["equals"] == "bob.docx"

    def test_the_notion_key_from_the_settings_is_used(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        self.run(cv_folder, jd_file)
        assert fake_notion.auth == "test-notion-key"

    def test_only_pdf_and_docx_are_screened_in_name_order(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        make_pdf(cv_folder / "Zed.PDF", "Zed")
        fake_gemini.answers = [JD_JSON] + [candidate_json(email=f"{i}@example.com") for i in range(3)]
        self.run(cv_folder, jd_file)
        names = [p["body"]["properties"]["CV Filename"]["rich_text"][0]["text"]["content"] for p in fake_notion.of("POST", "pages")]
        assert names == ["Zed.PDF", "alice.pdf", "bob.docx"]

    def test_the_model_named_in_the_settings_is_used(self, configured, cv_folder, jd_file, fake_notion, fake_gemini, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        self.run(cv_folder, jd_file)
        assert {c["model"] for c in fake_gemini.calls} == {"gemini-custom"}

    def test_the_default_model_is_used_otherwise(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        self.run(cv_folder, jd_file)
        assert {c["model"] for c in fake_gemini.calls} == {"gemini-3.8-flash"}

    def test_a_duplicate_is_skipped(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_notion.results = [{"id": "existing"}]
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        result = self.run(cv_folder, jd_file)
        out = flat(result.output)
        assert result.exit_code == 0
        assert "Duplicate skipped: alice.pdf" in out and "Duplicate skipped: bob.docx" in out
        assert not fake_notion.of("POST", "pages")
        assert "0 candidate(s) added" in out

    def test_an_unreadable_cv_is_reported_and_the_run_ends_with_exit_code_1(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        (cv_folder / "scan.pdf").write_text("not a pdf at all")
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        result = self.run(cv_folder, jd_file)
        out = flat(result.output)
        assert exited(result, 1)
        assert "scan.pdf: skipped: cannot read the PDF" in out
        assert "1 CV(s) could not be processed" in out
        assert len(fake_notion.of("POST", "pages")) == 2  # the others were still added

    def test_a_cv_with_square_brackets_in_its_name_is_printed_as_it_is(self, configured, tmp_path, jd_file, fake_notion, fake_gemini):
        folder = tmp_path / "odd"
        folder.mkdir()
        make_pdf(folder / "CV [final].pdf", "text")
        make_pdf(folder / "[bold]styled.pdf", "text")
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        result = self.run(folder, jd_file)
        out = flat(result.output)
        assert result.exit_code == 0, result.output
        assert "CV [final].pdf — High Fit" in out  # a name in brackets used to lose the bracketed part
        assert "[bold]styled.pdf — High Fit" in out

    def test_error_text_with_markup_is_shown_as_text_and_does_not_crash_the_run(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, RuntimeError("quota [/bold] exceeded [red]now"), candidate_json(email="b@example.com")]
        result = self.run(cv_folder, jd_file)
        out = flat(result.output)
        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "quota [/bold] exceeded [red]now" in out

    def test_a_gemini_answer_that_is_not_json_fails_only_that_cv(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, "I cannot do that", candidate_json(email="b@example.com")]
        result = self.run(cv_folder, jd_file)
        out = flat(result.output)
        assert result.exit_code == 1
        assert "alice.pdf: Gemini analysis failed: the answer was not a JSON object" in out
        assert len(fake_notion.of("POST", "pages")) == 1

    def test_three_gemini_failures_in_a_row_stop_the_run(self, configured, tmp_path, jd_file, fake_notion, fake_gemini):
        folder = tmp_path / "many"
        folder.mkdir()
        for i in range(5):
            make_pdf(folder / f"cv{i}.pdf", f"cv {i}")
        fake_gemini.answers = [JD_JSON] + [RuntimeError("404 models/x is not found")] * 5
        result = self.run(folder, jd_file)
        out = flat(result.output)
        assert exited(result, 1)
        assert "Stopping: Gemini failed 3 times in a row" in out and "GEMINI_MODEL" in out
        assert len(fake_gemini.calls) == 1 + 3  # the job description and three CVs, not five
        assert "Failed 3" in out.replace("│", " ") or " 3 CV(s) could not be processed" in out

    def test_a_cv_that_never_reached_gemini_does_not_break_the_streak(self, configured, tmp_path, jd_file, fake_notion, fake_gemini):
        folder = tmp_path / "streak"
        folder.mkdir()
        make_pdf(folder / "cv0.pdf", "a")
        make_pdf(folder / "cv1.pdf", "b")
        (folder / "cv2.pdf").write_text("unreadable")  # skipped before Gemini is asked
        make_pdf(folder / "cv3.pdf", "c")
        make_pdf(folder / "cv4.pdf", "d")
        boom = RuntimeError("503")
        fake_gemini.answers = [JD_JSON, boom, boom, boom, candidate_json(email="a@example.com")]
        result = self.run(folder, jd_file)
        assert "Stopping" in flat(result.output)
        assert len(fake_gemini.calls) == 1 + 3  # cv0, cv1 and cv3; cv4 is never reached

    def test_answers_that_are_not_json_never_stop_the_run(self, configured, tmp_path, jd_file, fake_notion, fake_gemini):
        folder = tmp_path / "garbage"
        folder.mkdir()
        for i in range(5):
            make_pdf(folder / f"cv{i}.pdf", f"cv {i}")
        fake_gemini.answers = [JD_JSON] + ["no json at all"] * 5
        result = self.run(folder, jd_file)
        assert exited(result, 1)
        assert "Stopping" not in flat(result.output)
        assert len(fake_gemini.calls) == 6

    def test_a_success_between_failures_resets_the_count(self, configured, tmp_path, jd_file, fake_notion, fake_gemini):
        folder = tmp_path / "mixed"
        folder.mkdir()
        for i in range(5):
            make_pdf(folder / f"cv{i}.pdf", f"cv {i}")
        boom = RuntimeError("503")
        fake_gemini.answers = [JD_JSON, boom, boom, candidate_json(email="a@example.com"), boom, boom]
        result = self.run(folder, jd_file)
        assert "Stopping" not in flat(result.output)
        assert len(fake_gemini.calls) == 6  # every CV was tried

    def test_a_bad_score_is_stored_without_a_score_and_flagged(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, candidate_json(match_score=1000), candidate_json(email="b@example.com")]
        result = self.run(cv_folder, jd_file)
        out = flat(result.output)
        assert result.exit_code == 0
        assert "alice.pdf — added (no usable match score: review by hand)" in out
        props = fake_notion.of("POST", "pages")[0]["body"]["properties"]
        assert "Match Score" not in props and "Ranking Category" not in props

    def test_a_notion_failure_fails_that_cv(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        from tests.helpers import api_error

        fake_notion.fail[("POST", "pages")] = api_error(400, "validation_error")
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        result = self.run(cv_folder, jd_file)
        assert result.exit_code == 1
        assert "page creation failed" in flat(result.output)

    def test_a_failed_duplicate_check_fails_that_cv_instead_of_adding_a_duplicate(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        from tests.helpers import api_error

        fake_notion.fail[("POST", "data_sources/")] = api_error(400, "bad filter")
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        result = self.run(cv_folder, jd_file)
        assert result.exit_code == 1
        assert "duplicate check failed" in flat(result.output)
        assert not fake_notion.of("POST", "pages")

    def test_no_cvs_is_not_an_error(self, configured, tmp_path, jd_file, fake_notion, fake_gemini):
        folder = tmp_path / "empty"
        folder.mkdir()
        (folder / "readme.txt").write_text("x")
        fake_gemini.answers = [JD_JSON]
        result = self.run(folder, jd_file)
        assert result.exit_code == 0
        assert "No supported CV files (.pdf, .docx) found" in flat(result.output)

    def test_an_unreadable_job_description_stops_the_run(self, configured, cv_folder, tmp_path, fake_notion, fake_gemini):
        jd = tmp_path / "bad.pdf"
        jd.write_text("nope")
        result = self.run(cv_folder, jd)
        assert exited(result, 1)
        assert "Could not read the JD bad.pdf: cannot read the PDF" in flat(result.output)
        assert not fake_gemini.calls

    def test_a_job_description_gemini_cannot_read_stops_the_run(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [RuntimeError("403 API key not valid")]
        result = self.run(cv_folder, jd_file)
        assert exited(result, 1)
        assert "Gemini could not read the JD" in flat(result.output) and "API key not valid" in flat(result.output)
        assert not fake_notion.of("POST", "pages")

    def test_a_database_that_cannot_be_read_stops_the_run_before_gemini_is_called(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        from tests.helpers import api_error

        fake_notion.fail[("GET", "databases/")] = api_error(404, "not shared")
        result = self.run(cv_folder, jd_file)
        assert exited(result, 1)
        assert "Notion initialization failed" in flat(result.output)
        assert not fake_gemini.calls

    def test_a_database_with_several_data_sources_asks_which_and_the_option_answers(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_notion.database = {"title": [], "data_sources": [{"id": "a", "name": "One"}, {"id": "b", "name": "Two"}]}
        refused = self.run(cv_folder, jd_file)
        assert exited(refused, 1) and "several data sources" in flat(refused.output)
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        accepted = self.run(cv_folder, jd_file, "--data-source-id", "b")
        assert accepted.exit_code == 0
        assert fake_notion.of("POST", "pages")[0]["body"]["parent"]["data_source_id"] == "b"

    def test_the_data_source_option_wins_over_the_environment(self, configured, cv_folder, jd_file, fake_notion, fake_gemini, monkeypatch):
        monkeypatch.setenv("NOTION_DATA_SOURCE_ID", "env-ds")
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        self.run(cv_folder, jd_file, "--data-source-id", "cli-ds")
        assert fake_notion.of("POST", "pages")[0]["body"]["parent"]["data_source_id"] == "cli-ds"

    def test_a_data_source_id_from_the_environment(self, configured, cv_folder, jd_file, fake_notion, fake_gemini, monkeypatch):
        monkeypatch.setenv("NOTION_DATA_SOURCE_ID", "env-ds")
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        assert self.run(cv_folder, jd_file).exit_code == 0
        assert fake_notion.of("POST", "pages")[0]["body"]["parent"]["data_source_id"] == "env-ds"

    def test_a_database_id_on_the_command_line_is_read(self, configured, cv_folder, jd_file, fake_notion, fake_gemini):
        fake_gemini.answers = [JD_JSON, candidate_json(), candidate_json(email="b@example.com")]
        self.run(cv_folder, jd_file, "-n", "other-db")
        assert fake_notion.of("GET", "databases/other-db")


class TestSetupNotion:
    def test_missing_settings(self):
        result = runner.invoke(app, ["setup-notion"])
        out = flat(result.output)
        assert result.exit_code == 1
        assert "NOTION_API_KEY not found" in out and "Notion Database ID not provided" in out

    def test_a_fresh_database_gets_everything(self, configured, fake_notion):
        result = runner.invoke(app, ["setup-notion"])
        out = flat(result.output)
        assert result.exit_code == 0, result.output
        assert "Connected: Candidates" in out
        assert "Renamed Name -> Candidate Name" in out
        assert out.count("Added:") == 12
        assert "Notion database is ready." in out
        assert "Candidate Name" in fake_notion.properties

    def test_running_it_again_changes_nothing(self, configured, fake_notion):
        runner.invoke(app, ["setup-notion"])
        before = len(fake_notion.of("PATCH", ""))
        out = flat(runner.invoke(app, ["setup-notion"]).output)
        assert out.count("Already exists:") == 13
        assert "Added:" not in out
        assert len(fake_notion.of("PATCH", "")) == before

    def test_a_failed_rename_asks_for_a_manual_step(self, configured, fake_notion):
        from tests.helpers import api_error

        fake_notion.properties = {"Name": {"type": "title"}, **{k: {"type": "x"} for k in main.ensure_properties.__globals__["REQUIRED_PROPERTIES"]}}
        fake_notion.fail[("PATCH", "data_sources/")] = api_error(400)
        result = runner.invoke(app, ["setup-notion"])
        out = flat(result.output)
        assert result.exit_code == 0
        assert "Could not rename the title property 'Name'" in out
        assert "needs one manual step" in out and "Notion database is ready." not in out

    def test_a_notion_error_exits_1(self, configured, fake_notion):
        from tests.helpers import api_error

        fake_notion.fail[("GET", "databases/")] = api_error(404, "gone")
        result = runner.invoke(app, ["setup-notion"])
        assert result.exit_code == 1 and "Notion setup failed" in flat(result.output)

    def test_the_banner_is_only_for_running_without_a_command(self, fake_notion):
        out = flat(runner.invoke(app, ["setup-notion"]).output)
        assert "AI Recruitment Scanning Agent" not in out

    def test_the_options_override_the_environment(self, configured, fake_notion):
        runner.invoke(app, ["setup-notion", "--notion-db-id", "db-x"])
        assert fake_notion.of("GET", "databases/db-x")
        runner.invoke(app, ["setup-notion", "--data-source-id", "ds-x"])
        assert fake_notion.of("GET", "data_sources/ds-x")


@pytest.mark.parametrize("name", ["main.py"])
def test_the_root_shim_still_exposes_the_app(name):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("shim", Path(__file__).resolve().parent.parent / name)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    assert module.app is app


def test_docx_and_pdf_helpers_make_files_the_extractors_can_read(tmp_path):
    from ai_recruitment_agent.extract import extract_text

    assert extract_text(make_docx(tmp_path / "x.docx", ["a"])) == "a"
    assert extract_text(make_pdf(tmp_path / "x.pdf", "b")) == "b"


def test_the_module_can_be_run_directly(monkeypatch, capsys):
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["ai-recruit", "--version"])
    monkeypatch.delitem(sys.modules, "ai_recruitment_agent.main", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("ai_recruitment_agent.main", run_name="__main__")
    assert exit_info.value.code == 0
    assert f"ai-recruitment-agent v{__version__}" in capsys.readouterr().out
