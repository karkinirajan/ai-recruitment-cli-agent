import pytest

from ai_recruitment_agent import notion_io
from ai_recruitment_agent.candidate import Candidate
from ai_recruitment_agent.notion_io import (
    REQUIRED_PROPERTIES,
    NotionError,
    candidate_properties,
    create_candidate_page,
    ensure_properties,
    find_duplicate,
    resolve_data_source,
)
from tests.helpers import FakeNotion, api_error

DETAILS = {"position_title": "Analyst", "job_id": "JOB-7"}


def cand(**over) -> Candidate:
    base = dict(
        full_name="Ada Lovelace", email="ada@example.com", contact_number="+44 20 7946 0958", skills=("Python", "Math"),
        experience_summary="Wrote programs.", match_score=85, ranking_category="High Fit", ranking_reason="Strong.",
    )
    base.update(over)
    return Candidate(**base)


class TestResolveDataSource:
    def test_a_database_with_one_data_source(self):
        fake = FakeNotion()
        source = resolve_data_source(fake.client, "db-1")
        assert (source.id, source.database_title) == ("ds-1", "Candidates")
        assert fake.of("GET", "databases/db-1")

    def test_an_explicit_data_source_id_is_used_without_reading_the_database(self):
        fake = FakeNotion()
        source = resolve_data_source(fake.client, "db-1", "ds-9")
        assert source.id == "ds-9"
        assert not fake.of("GET", "databases/")
        assert fake.of("GET", "data_sources/ds-9")

    def test_several_data_sources_ask_which(self):
        fake = FakeNotion(database={"title": [], "data_sources": [{"id": "a", "name": "One"}, {"id": "b", "name": "Two"}]})
        with pytest.raises(NotionError, match=r"several data sources: One \(a\), Two \(b\).*--data-source-id"):
            resolve_data_source(fake.client, "db-1")

    def test_no_data_source(self):
        fake = FakeNotion(database={"title": [], "data_sources": []})
        with pytest.raises(NotionError, match="no data source"):
            resolve_data_source(fake.client, "db-1")

    def test_a_database_without_the_field_has_no_data_source(self):
        with pytest.raises(NotionError, match="no data source"):
            resolve_data_source(FakeNotion(database={"title": []}).client, "db-1")

    def test_entries_without_an_id_are_ignored(self):
        fake = FakeNotion(database={"title": [], "data_sources": [{"name": "x"}, "junk", {"id": "ok", "name": "Real"}]})
        assert resolve_data_source(fake.client, "db-1").id == "ok"

    def test_the_title_falls_back_to_the_id(self):
        fake = FakeNotion(database={"title": [], "data_sources": [{"id": "ds-1"}]})
        assert resolve_data_source(fake.client, "db-1").database_title == "db-1"

    def test_an_api_error_is_a_notion_error_with_the_cause(self):
        fake = FakeNotion()
        fake.fail[("GET", "databases/")] = api_error(404, "not found")
        with pytest.raises(NotionError, match="cannot read the Notion database") as exc:
            resolve_data_source(fake.client, "db-1")
        assert exc.value.__cause__ is not None

    def test_an_error_reading_an_explicit_data_source_is_a_notion_error(self):
        fake = FakeNotion()
        fake.fail[("GET", "data_sources/")] = api_error(404)
        with pytest.raises(NotionError, match="cannot read the Notion database"):
            resolve_data_source(fake.client, "db-1", "ds-9")


class TestFindDuplicate:
    def test_by_email_and_job_id(self):
        fake = FakeNotion(results=[{"id": "p"}])
        assert find_duplicate(fake.client, "ds-1", cand(), "JOB-7", "a.pdf") is True
        call = fake.of("POST", "data_sources/ds-1/query")[0]
        assert call["body"]["filter"] == {
            "and": [
                {"property": "Email", "email": {"equals": "ada@example.com"}},
                {"property": "Job ID (JD)", "rich_text": {"equals": "JOB-7"}},
            ]
        }
        assert call["body"]["page_size"] == 1

    def test_no_match_is_not_a_duplicate(self):
        assert find_duplicate(FakeNotion(results=[]).client, "ds-1", cand(), "JOB-7", "a.pdf") is False

    def test_a_job_id_that_is_not_available_is_not_filtered_on(self):
        fake = FakeNotion()
        find_duplicate(fake.client, "ds-1", cand(), "N/A", "a.pdf")
        assert fake.of("POST", "data_sources/")[0]["body"]["filter"] == {"property": "Email", "email": {"equals": "ada@example.com"}}

    def test_an_empty_job_id_is_not_filtered_on(self):
        fake = FakeNotion()
        find_duplicate(fake.client, "ds-1", cand(), "", "a.pdf")
        assert "and" not in fake.of("POST", "data_sources/")[0]["body"]["filter"]

    def test_without_an_email_the_cv_file_name_is_used(self):
        fake = FakeNotion(results=[{"id": "p"}])
        assert find_duplicate(fake.client, "ds-1", cand(email=None), "JOB-7", "alice.pdf") is True
        assert fake.of("POST", "data_sources/")[0]["body"]["filter"] == {
            "and": [
                {"property": "CV Filename", "rich_text": {"equals": "alice.pdf"}},
                {"property": "Job ID (JD)", "rich_text": {"equals": "JOB-7"}},
            ]
        }

    def test_without_an_email_or_a_file_name_nothing_is_asked(self):
        fake = FakeNotion(results=[{"id": "p"}])
        assert find_duplicate(fake.client, "ds-1", cand(email=None), "JOB-7", "") is False
        assert not fake.calls

    def test_a_failed_check_is_an_error_not_a_silent_no(self):
        fake = FakeNotion()
        fake.fail[("POST", "data_sources/")] = api_error(400, "bad filter")
        with pytest.raises(NotionError, match="duplicate check failed") as exc:
            find_duplicate(fake.client, "ds-1", cand(), "JOB-7", "a.pdf")
        assert exc.value.__cause__ is not None

    def test_long_values_are_cut_to_the_notion_limit(self):
        fake = FakeNotion()
        find_duplicate(fake.client, "ds-1", cand(email=None), "j" * 5000, "f" * 5000)
        filters = fake.of("POST", "data_sources/")[0]["body"]["filter"]["and"]
        assert [len(f["rich_text"]["equals"]) for f in filters] == [1999, 1999]


class TestCandidateProperties:
    def test_every_property_for_a_complete_candidate(self):
        props = candidate_properties(cand(), DETAILS, "ada.pdf")
        assert props["Candidate Name"] == {"title": [{"text": {"content": "Ada Lovelace"}}]}
        assert props["CV Filename"]["rich_text"][0]["text"]["content"] == "ada.pdf"
        assert props["Position Title (JD)"]["rich_text"][0]["text"]["content"] == "Analyst"
        assert props["Job ID (JD)"]["rich_text"][0]["text"]["content"] == "JOB-7"
        assert props["Experience Summary"]["rich_text"][0]["text"]["content"] == "Wrote programs."
        assert props["AI Ranking Reason"]["rich_text"][0]["text"]["content"] == "Strong."
        assert props["Status"] == {"select": {"name": "New - AI Processed"}}
        assert props["Email"] == {"email": "ada@example.com"}
        assert props["Contact Number"] == {"phone_number": "+44 20 7946 0958"}
        assert props["Skills"] == {"multi_select": [{"name": "Python"}, {"name": "Math"}]}
        assert props["Match Score"] == {"number": 85}
        assert props["Ranking Category"] == {"select": {"name": "High Fit"}}
        assert "T" in props["Processing Date"]["date"]["start"] and props["Processing Date"]["date"]["start"].endswith("+00:00")

    def test_optional_columns_are_left_out_when_the_value_is_missing(self):
        props = candidate_properties(cand(email=None, contact_number=None, skills=(), match_score=None, ranking_category=None), DETAILS, "a.pdf")
        for name in ("Email", "Contact Number", "Skills", "Match Score", "Ranking Category"):
            assert name not in props

    def test_a_score_of_zero_is_still_written(self):
        props = candidate_properties(cand(match_score=0, ranking_category="Low Fit"), DETAILS, "a.pdf")
        assert props["Match Score"] == {"number": 0}
        assert props["Ranking Category"] == {"select": {"name": "Low Fit"}}

    def test_text_is_cut_to_the_notion_limit(self):
        props = candidate_properties(cand(experience_summary="e" * 5000, full_name="n" * 500), {"position_title": "p" * 5000, "job_id": "j"}, "f" * 5000)
        assert len(props["Experience Summary"]["rich_text"][0]["text"]["content"]) == 1999
        assert len(props["Position Title (JD)"]["rich_text"][0]["text"]["content"]) == 1999
        assert len(props["CV Filename"]["rich_text"][0]["text"]["content"]) == 1999
        assert len(props["Candidate Name"]["title"][0]["text"]["content"]) == 200

    def test_missing_details_are_not_available(self):
        props = candidate_properties(cand(), {}, "a.pdf")
        assert props["Position Title (JD)"]["rich_text"][0]["text"]["content"] == "N/A"
        assert props["Job ID (JD)"]["rich_text"][0]["text"]["content"] == "N/A"

    def test_skill_names_are_at_most_99_characters(self):
        assert candidate_properties(cand(skills=("s" * 300,)), DETAILS, "a.pdf")["Skills"]["multi_select"][0]["name"] == "s" * 99

    def test_every_property_written_is_one_the_setup_creates(self):
        props = candidate_properties(cand(), DETAILS, "a.pdf")
        assert set(props) <= set(REQUIRED_PROPERTIES) | {"Candidate Name"}
        assert set(REQUIRED_PROPERTIES) <= set(props) | {"unused"}


class TestCreateCandidatePage:
    def test_the_page_is_created_under_the_data_source(self):
        fake = FakeNotion()
        create_candidate_page(fake.client, "ds-1", cand(), DETAILS, "ada.pdf")
        body = fake.of("POST", "pages")[0]["body"]
        assert body["parent"] == {"type": "data_source_id", "data_source_id": "ds-1"}
        assert body["properties"]["Candidate Name"]["title"][0]["text"]["content"] == "Ada Lovelace"

    def test_a_failure_is_a_notion_error_with_the_cause(self):
        fake = FakeNotion()
        fake.fail[("POST", "pages")] = api_error(400, "invalid email")
        with pytest.raises(NotionError, match="page creation failed") as exc:
            create_candidate_page(fake.client, "ds-1", cand(), DETAILS, "ada.pdf")
        assert exc.value.__cause__ is not None


class TestEnsureProperties:
    def test_an_empty_database_gets_everything_and_its_title_renamed(self):
        fake = FakeNotion(properties={"Name": {"type": "title"}})
        report = ensure_properties(fake.client, "ds-1")
        assert report[0] == ("renamed", "Name -> Candidate Name")
        assert sorted(n for w, n in report if w == "added") == sorted(REQUIRED_PROPERTIES)
        assert "Candidate Name" in fake.properties and "Name" not in fake.properties
        for name in REQUIRED_PROPERTIES:
            assert name in fake.properties

    def test_the_rename_and_the_additions_go_to_the_data_source(self):
        fake = FakeNotion(properties={"Name": {"type": "title"}})
        ensure_properties(fake.client, "ds-1")
        patches = fake.of("PATCH", "data_sources/ds-1")
        assert patches[0]["body"] == {"properties": {"Name": {"name": "Candidate Name"}}}
        assert set(patches[1]["body"]["properties"]) == set(REQUIRED_PROPERTIES)

    def test_everything_present_changes_nothing(self):
        props = {"Candidate Name": {"type": "title"}, **{k: v for k, v in REQUIRED_PROPERTIES.items()}}
        fake = FakeNotion(properties=props)
        report = ensure_properties(fake.client, "ds-1")
        assert {w for w, _ in report} == {"exists"}
        assert len(report) == 1 + len(REQUIRED_PROPERTIES)
        assert not fake.of("PATCH", "")

    def test_only_the_missing_ones_are_added(self):
        props = {"Candidate Name": {"type": "title"}, "Email": {"type": "email"}, "Status": {"type": "select"}}
        fake = FakeNotion(properties=props)
        report = ensure_properties(fake.client, "ds-1")
        added = [n for w, n in report if w == "added"]
        assert "Email" not in added and "Status" not in added and len(added) == len(REQUIRED_PROPERTIES) - 2
        assert ("exists", "Email") in report and ("exists", "Status") in report

    def test_a_failed_rename_is_reported_and_setup_goes_on(self):
        fake = FakeNotion(properties={"Name": {"type": "title"}})
        fake.fail[("PATCH", "data_sources/")] = api_error(400)
        with pytest.raises(NotionError):  # the rename fails and so does the add: one error out
            ensure_properties(fake.client, "ds-1")

    def test_a_failed_rename_alone_is_not_fatal(self):
        fake = FakeNotion(properties={"Name": {"type": "title"}, **REQUIRED_PROPERTIES})
        calls = {"n": 0}
        original = fake.client.request

        def flaky(path, method, query=None, body=None, form_data=None, auth=None):
            if method == "PATCH":
                calls["n"] += 1
                raise api_error(400)
            return original(path=path, method=method, query=query, body=body, form_data=form_data, auth=auth)

        fake.client.request = flaky  # type: ignore[method-assign]
        assert ensure_properties(fake.client, "ds-1")[0] == ("rename-failed", "Name")

    def test_reading_the_properties_can_fail(self):
        fake = FakeNotion()
        fake.fail[("GET", "data_sources/")] = api_error(404)
        with pytest.raises(NotionError, match="cannot add the properties") as exc:
            ensure_properties(fake.client, "ds-1")
        assert exc.value.__cause__ is not None

    def test_adding_can_fail(self):
        fake = FakeNotion(properties={"Candidate Name": {"type": "title"}})
        fake.fail[("PATCH", "data_sources/")] = api_error(403)
        with pytest.raises(NotionError, match="cannot add the properties"):
            ensure_properties(fake.client, "ds-1")

    def test_a_database_without_a_title_property_is_not_renamed(self):
        fake = FakeNotion(properties={"Other": {"type": "rich_text"}})
        report = ensure_properties(fake.client, "ds-1")
        assert not any(w in ("renamed", "rename-failed") for w, _ in report)


def test_the_status_option_name_is_the_one_the_page_uses():
    assert notion_io.STATUS_NEW == "New - AI Processed"
    assert REQUIRED_PROPERTIES["Status"]["select"]["options"][0]["name"] == notion_io.STATUS_NEW
    assert [o["name"] for o in REQUIRED_PROPERTIES["Ranking Category"]["select"]["options"]] == ["High Fit", "Medium Fit", "Low Fit"]
    assert len(REQUIRED_PROPERTIES) == 12


def test_a_network_failure_is_a_notion_error_too():
    import httpx

    fake = FakeNotion()
    fake.fail[("GET", "databases/")] = httpx.ConnectError("no route")
    with pytest.raises(NotionError, match="cannot read the Notion database"):
        resolve_data_source(fake.client, "db-1")
