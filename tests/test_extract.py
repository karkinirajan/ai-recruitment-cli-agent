import zipfile

import pytest

from ai_recruitment_agent import extract
from ai_recruitment_agent.extract import ExtractionError, extract_text, extract_text_from_docx, extract_text_from_pdf
from tests.helpers import make_docx, make_pdf


class TestPdf:
    def test_reads_the_text(self, tmp_path):
        assert extract_text_from_pdf(make_pdf(tmp_path / "a.pdf", "Hello (world) \\ backslash")) == "Hello (world) \\ backslash"

    def test_joins_pages_with_newlines_and_skips_pages_without_text(self, tmp_path):
        path = make_pdf(tmp_path / "a.pdf", ["first page", "", "third page"])
        assert extract_text_from_pdf(path) == "first page\nthird page"

    def test_only_the_first_pages_are_read(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extract, "MAX_PDF_PAGES", 2)
        path = make_pdf(tmp_path / "a.pdf", ["one", "two", "three"])
        assert extract_text_from_pdf(path) == "one\ntwo"

    def test_a_pdf_without_text_is_an_error_that_says_why(self, tmp_path):
        with pytest.raises(ExtractionError, match="no text found .*scanned"):
            extract_text_from_pdf(make_pdf(tmp_path / "scan.pdf", [""]))

    def test_a_file_that_is_not_a_pdf_is_an_error(self, tmp_path):
        path = tmp_path / "fake.pdf"
        path.write_text("this is not a pdf")
        with pytest.raises(ExtractionError, match=r"cannot read the PDF \("):
            extract_text_from_pdf(path)

    def test_the_cause_is_chained(self, tmp_path):
        path = tmp_path / "fake.pdf"
        path.write_text("nope")
        with pytest.raises(ExtractionError) as exc:
            extract_text_from_pdf(path)
        assert exc.value.__cause__ is not None

    def test_a_file_over_the_size_limit_is_refused_before_it_is_opened(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extract, "MAX_FILE_BYTES", 100)
        path = tmp_path / "big.pdf"
        path.write_bytes(b"x" * 101)
        with pytest.raises(ExtractionError, match="over the 0 MB limit|MB limit"):
            extract_text_from_pdf(path)

    def test_a_file_exactly_at_the_limit_is_read(self, tmp_path, monkeypatch):
        path = make_pdf(tmp_path / "a.pdf", "text")
        monkeypatch.setattr(extract, "MAX_FILE_BYTES", path.stat().st_size)
        assert extract_text_from_pdf(path) == "text"

    def test_the_limits_are_25_mb_200_mb_and_50_pages(self):
        assert (extract.MAX_FILE_BYTES, extract.MAX_UNPACKED_BYTES, extract.MAX_PDF_PAGES) == (25 * 1024 * 1024, 200 * 1024 * 1024, 50)


class TestDocx:
    def test_reads_paragraphs_and_skips_blank_ones(self, tmp_path):
        path = make_docx(tmp_path / "a.docx", ["Alice", "", "   ", "Engineer"])
        assert extract_text_from_docx(path) == "Alice\nEngineer"

    def test_a_document_without_text_is_an_error(self, tmp_path):
        with pytest.raises(ExtractionError, match="no text found"):
            extract_text_from_docx(make_docx(tmp_path / "a.docx", ["", " "]))

    def test_a_file_that_is_not_a_docx_is_an_error(self, tmp_path):
        path = tmp_path / "fake.docx"
        path.write_text("not a zip")
        with pytest.raises(ExtractionError, match=r"cannot read the DOCX \("):
            extract_text_from_docx(path)

    def test_the_cause_is_chained(self, tmp_path):
        path = tmp_path / "fake.docx"
        path.write_text("not a zip")
        with pytest.raises(ExtractionError) as exc:
            extract_text_from_docx(path)
        assert exc.value.__cause__ is not None

    def test_a_zip_that_is_not_a_document_is_an_error(self, tmp_path):
        path = tmp_path / "other.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("hello.txt", "hi")
        with pytest.raises(ExtractionError, match="cannot read the DOCX"):
            extract_text_from_docx(path)

    def test_a_document_that_unpacks_to_too_much_is_refused(self, tmp_path, monkeypatch):
        path = make_docx(tmp_path / "a.docx", ["text"])
        monkeypatch.setattr(extract, "MAX_UNPACKED_BYTES", 10)
        with pytest.raises(ExtractionError, match="unpacks to more than the allowed size"):
            extract_text_from_docx(path)

    def test_a_document_exactly_at_the_unpacked_limit_is_read(self, tmp_path, monkeypatch):
        path = make_docx(tmp_path / "a.docx", ["text"])
        with zipfile.ZipFile(path) as archive:
            total = sum(i.file_size for i in archive.infolist())
        monkeypatch.setattr(extract, "MAX_UNPACKED_BYTES", total)
        assert extract_text_from_docx(path) == "text"

    def test_a_file_over_the_size_limit_is_refused(self, tmp_path, monkeypatch):
        path = make_docx(tmp_path / "a.docx", ["text"])
        monkeypatch.setattr(extract, "MAX_FILE_BYTES", 10)
        with pytest.raises(ExtractionError, match="MB limit"):
            extract_text_from_docx(path)


class TestExtractText:
    def test_chooses_by_extension_ignoring_case(self, tmp_path):
        assert extract_text(make_pdf(tmp_path / "a.PDF", "pdf text")) == "pdf text"
        assert extract_text(make_docx(tmp_path / "b.DocX", ["docx text"])) == "docx text"

    def test_the_supported_formats(self):
        assert extract.SUPPORTED_CV_FORMATS == {".pdf", ".docx"}
