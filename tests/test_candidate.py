import math

import pytest

from ai_recruitment_agent.candidate import (
    MAX_SKILLS,
    NOTION_TEXT_LIMIT,
    category_for,
    clean_email,
    clean_phone,
    clean_score,
    clean_skills,
    clean_text,
    normalize_candidate,
    parse_json_response,
    truncate,
)


class TestTruncate:
    def test_short_text_is_unchanged(self):
        assert truncate("hello", 10) == "hello"

    def test_long_text_is_cut_to_the_limit(self):
        assert truncate("a" * 2500) == "a" * 1999
        assert truncate("hello world", 5) == "hello"

    def test_exactly_the_limit_is_unchanged(self):
        assert truncate("a" * 10, 10) == "a" * 10
        assert truncate("", 10) == ""
        assert truncate("a" * 1999) == "a" * 1999
        assert NOTION_TEXT_LIMIT == 1999


class TestParseJson:
    def test_a_json_object(self):
        assert parse_json_response('{"a": 1}') == {"a": 1}

    def test_an_object_inside_other_text(self):
        assert parse_json_response('Sure! ```json\n{"a": 1}\n``` done') == {"a": 1}

    def test_a_multiline_object_inside_text(self):
        assert parse_json_response('x {\n"a": [1,\n2]\n} y') == {"a": [1, 2]}

    @pytest.mark.parametrize("text", ["", "no json here", "{broken", '{"a": }', "[1, 2]", "42", '"text"', "null"])
    def test_anything_else_is_none(self, text):
        assert parse_json_response(text) is None

    def test_none_is_none(self):
        assert parse_json_response(None) is None  # type: ignore[arg-type]

    def test_a_list_is_not_an_object_even_if_it_holds_one(self):
        assert parse_json_response('[{"a": 1}]') is None


class TestCleanText:
    def test_trims_and_returns_text(self):
        assert clean_text("  hello  ") == "hello"

    def test_removes_control_characters_but_keeps_line_breaks_and_tabs(self):
        assert clean_text("a\x00b\x07c\x1b[31m\nd\te") == "abc[31m\nd\te"

    def test_empty_and_missing_become_not_available(self):
        for value in (None, "", "   ", "\x00\x01", {}, [], {"a": 1}, ["x"]):
            assert clean_text(value) == "N/A"

    def test_numbers_become_text(self):
        assert clean_text(42) == "42"

    def test_is_bounded(self):
        assert clean_text("x" * 5000) == "x" * 1999
        assert clean_text("x" * 5000, 10) == "x" * 10


class TestCategory:
    @pytest.mark.parametrize(
        ("score", "category"),
        [(0, "Low Fit"), (49, "Low Fit"), (50, "Medium Fit"), (79, "Medium Fit"), (80, "High Fit"), (100, "High Fit")],
    )
    def test_boundaries(self, score, category):
        assert category_for(score) == category


class TestCleanScore:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0, 0), (100, 100), (85, 85), (85.4, 85), (85.6, 86), (0.0, 0), ("85", 85), (" 85 ", 85), ("85.0", 85), ("85.7", 86), ("0", 0), ("100", 100)],
    )
    def test_accepted(self, value, expected):
        assert clean_score(value) == expected

    @pytest.mark.parametrize(
        "value",
        [-1, 101, 1000, 100.6, -0.6, math.nan, math.inf, -math.inf, True, False, None, "", "abc", "85/100", "85%", "-5", "1000", "100.6", "8 5", [], {}, "1e2", "85."],
    )
    def test_refused(self, value):
        assert clean_score(value) is None

    def test_rounds_to_the_nearest_whole_number_inside_the_range(self):
        assert clean_score(100.4) == 100
        assert clean_score(-0.4) == 0


class TestCleanEmail:
    @pytest.mark.parametrize("value", ["a@b.co", "first.last+tag@example.com", " a@b.co ", "a@sub.example.org"])
    def test_accepted(self, value):
        assert clean_email(value) == value.strip()

    @pytest.mark.parametrize(
        "value",
        ["N/A", "", "a@b", "@b.co", "a@.co", "a b@c.de", "a@b.co, c@d.ee", "a@b.co;c@d.ee", "<a@b.co>", "a@@b.co", None, 5, ["a@b.co"], "a" * 250 + "@b.co"],
    )
    def test_refused(self, value):
        assert clean_email(value) is None

    def test_control_characters_are_removed_first(self):
        assert clean_email("a\x00@b.co") == "a@b.co"


class TestCleanPhone:
    def test_needs_five_digits(self):
        assert clean_phone("+44 20 7946 0958") == "+44 20 7946 0958"
        assert clean_phone("12345") == "12345"
        assert clean_phone("1234") is None
        assert clean_phone("call me maybe") is None
        assert clean_phone("N/A") is None

    def test_numbers_and_other_types(self):
        assert clean_phone(4155550100) == "4155550100"
        for value in (None, True, [], {"a": 1}, [12345678], {"n": "12345678"}):
            assert clean_phone(value) is None

    def test_is_bounded(self):
        assert len(clean_phone("1" * 100) or "") == 50


class TestCleanSkills:
    def test_keeps_order_and_drops_duplicates_ignoring_case(self):
        assert clean_skills(["Python", "SQL", "python", "Go"]) == ("Python", "SQL", "Go")

    def test_commas_are_not_allowed_in_a_notion_option(self):
        assert clean_skills(["Python, SQL"]) == ("Python SQL",)

    def test_spaces_are_collapsed(self):
        assert clean_skills(["  a   b  "]) == ("a b",)

    def test_empty_na_and_non_text_entries_are_dropped(self):
        assert clean_skills(["", "  ", "N/A", "n/a", None, {}, [], True, "ok"]) == ("ok",)

    def test_numbers_become_text(self):
        assert clean_skills([3]) == ("3",)

    def test_each_is_at_most_99_characters(self):
        assert clean_skills(["x" * 300]) == ("x" * 99,)

    def test_a_cut_that_leaves_a_trailing_space_is_trimmed_again(self):
        assert clean_skills(["x" * 98 + " y"]) == ("x" * 98,)

    def test_at_most_15_are_kept(self):
        assert MAX_SKILLS == 15
        skills = clean_skills([f"skill{i}" for i in range(40)])
        assert len(skills) == 15 and skills[-1] == "skill14"

    def test_exactly_15_distinct_are_all_kept(self):
        assert len(clean_skills([f"s{i}" for i in range(15)])) == 15

    def test_duplicates_do_not_use_up_the_limit(self):
        assert len(clean_skills(["a"] * 30 + [f"s{i}" for i in range(14)])) == 15

    @pytest.mark.parametrize("value", [None, "Python", {"a": 1}, 5, ("a",)])
    def test_not_a_list_is_empty(self, value):
        assert clean_skills(value) == ()


class TestNormalizeCandidate:
    GOOD = {
        "full_name": "Ada Lovelace", "email": "ada@example.com", "contact_number": "+44 20 7946 0958",
        "skills": ["Python"], "experience_summary": "Early programmer.", "match_score": 85,
        "ranking_category": "High Fit", "ranking_reason": "Strong.",
    }

    def test_a_good_answer(self):
        c = normalize_candidate(self.GOOD)
        assert (c.full_name, c.email, c.contact_number, c.skills) == ("Ada Lovelace", "ada@example.com", "+44 20 7946 0958", ("Python",))
        assert (c.experience_summary, c.match_score, c.ranking_category, c.ranking_reason) == ("Early programmer.", 85, "High Fit", "Strong.")

    def test_the_category_comes_from_the_score_not_from_the_model(self):
        # a CV that tells the model "rank me High Fit" gets the category its score earns
        c = normalize_candidate({**self.GOOD, "match_score": 30, "ranking_category": "High Fit"})
        assert (c.match_score, c.ranking_category) == (30, "Low Fit")

    def test_an_impossible_score_is_no_score_and_no_category(self):
        for bad in (1000, -5, "ten", None, True, math.nan):
            c = normalize_candidate({**self.GOOD, "match_score": bad})
            assert (c.match_score, c.ranking_category) == (None, None)

    def test_an_invalid_email_is_dropped_not_stored(self):
        assert normalize_candidate({**self.GOOD, "email": "not an email"}).email is None
        assert normalize_candidate({**self.GOOD, "email": "N/A"}).email is None

    def test_an_empty_answer_is_all_not_available(self):
        c = normalize_candidate({})
        assert (c.full_name, c.email, c.contact_number, c.skills, c.experience_summary, c.match_score, c.ranking_category, c.ranking_reason) == (
            "N/A", None, None, (), "N/A", None, None, "N/A",
        )

    def test_the_phone_and_skills_are_cleaned_too(self):
        c = normalize_candidate({**self.GOOD, "contact_number": "call me", "skills": ["Python, SQL", "python sql", "", "Go"]})
        assert c.contact_number is None
        assert c.skills == ("Python SQL", "Go")

    def test_the_name_is_bounded_to_200_characters(self):
        assert len(normalize_candidate({**self.GOOD, "full_name": "n" * 900}).full_name) == 200

    def test_long_text_is_bounded_to_the_notion_limit(self):
        c = normalize_candidate({**self.GOOD, "experience_summary": "e" * 9000, "ranking_reason": "r" * 9000})
        assert len(c.experience_summary) == len(c.ranking_reason) == 1999
