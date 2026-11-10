"""Test doubles and file builders. Nothing here touches the network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from docx import Document
from notion_client import Client


def make_pdf(path: Path, pages: list[str] | str) -> Path:
    """Write a small valid PDF with one line of text per page (an empty string makes a page with no text)."""
    texts = [pages] if isinstance(pages, str) else pages
    objects: list[bytes] = []
    n = len(texts)
    font_id = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, text in enumerate(texts):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode() if text else b""
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def make_docx(path: Path, paragraphs: list[str]) -> Path:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(str(path))
    return path


class FakeNotion:
    """The real `notion_client.Client` with its HTTP layer replaced, so every call goes through the SDK's own endpoint methods (a method that
    does not exist in the installed SDK, such as the old `databases.query`, fails here) and the request that would be sent is recorded."""

    def __init__(self, *, database: dict[str, Any] | None = None, properties: dict[str, Any] | None = None, results: list[dict] | None = None):
        self.client = Client(auth="test-key")
        self.calls: list[dict[str, Any]] = []
        self.database = database if database is not None else {"id": "db-1", "title": [{"plain_text": "Candidates"}], "data_sources": [{"id": "ds-1", "name": "Candidates"}]}
        self.properties = properties if properties is not None else {"Name": {"type": "title"}}
        self.results = results if results is not None else []
        self.fail: dict[tuple[str, str], Exception] = {}
        self.client.request = self._request  # type: ignore[method-assign]

    def _request(self, path: str, method: str, query: Any = None, body: Any = None, form_data: Any = None, auth: Any = None) -> Any:
        self.calls.append({"method": method, "path": path, "body": body, "query": query})
        for (m, prefix), error in self.fail.items():
            if m == method and path.startswith(prefix):
                raise error
        if method == "GET" and path.startswith("databases/"):
            return self.database
        if method == "GET" and path.startswith("data_sources/"):
            return {"id": path.split("/")[1], "title": [{"plain_text": "Source"}], "properties": self.properties}
        if method == "POST" and path.endswith("/query"):
            return {"results": self.results}
        if method == "POST" and path == "pages":
            return {"id": "page-1"}
        if method == "PATCH" and path.startswith("data_sources/"):
            for name, spec in (body or {}).get("properties", {}).items():
                if "name" in spec and len(spec) == 1:  # a rename
                    self.properties[spec["name"]] = self.properties.pop(name)
                else:
                    self.properties[name] = spec
            return {"id": path.split("/")[1]}
        raise AssertionError(f"unexpected Notion call {method} {path}")

    def of(self, method: str, prefix: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["path"].startswith(prefix)]


def api_error(status: int = 400, message: str = "boom") -> Exception:
    """A Notion API error as the SDK raises it."""
    from notion_client.errors import APIResponseError

    return APIResponseError("validation_error", status, message, httpx.Headers(), "{}")


class FakeGeminiClient:
    """Stands in for `google.genai.Client`: `models.generate_content` returns queued answers (or raises queued exceptions)."""

    def __init__(self, answers: list[Any] | None = None):
        self.answers = list(answers or [])
        self.calls: list[dict[str, Any]] = []
        outer = self

        class Models:
            def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
                outer.calls.append({"model": model, "contents": contents, "config": config})
                answer = outer.answers.pop(0) if outer.answers else '{"full_name": "N/A"}'
                if isinstance(answer, Exception):
                    raise answer
                return type("Response", (), {"text": answer})()

        self.models = Models()
