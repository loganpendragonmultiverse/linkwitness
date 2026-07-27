import json
from pathlib import Path

import pytest

from linkwitness import core
from linkwitness.cli import main
from linkwitness.core import analyze, render_json, render_markdown

NOW = "2026-07-27T12:00:00+00:00"


def test_rich_fixture_capture_snapshot_metadata_and_redirects(tmp_path):
    url = "https://example.test/start"
    body = '<html><title> Evidence  Page </title><meta name="description" content="Proof"><link rel="canonical" href="/final"></html>'
    report = analyze(
        {
            "urls": [url],
            "captured_at": NOW,
            "snapshot_dir": str(tmp_path),
            "fixtures": {
                url: {
                    "body": body,
                    "final_url": "https://example.test/page",
                    "status": 203,
                    "headers": {
                        "Content-Type": "text/html",
                        "ETag": "abc",
                        "Last-Modified": "today",
                    },
                    "redirects": [{"status": 302, "from": url, "to": "https://example.test/page"}],
                }
            },
        }
    )
    item = report["captures"][0]
    assert item["title"] == "Evidence Page"
    assert item["description"] == "Proof"
    assert item["canonical_url"] == "https://example.test/final"
    assert item["etag"] == "abc" and item["status"] == 203
    assert Path(item["snapshot"]).read_text(encoding="utf-8") == body
    assert (
        json.loads(Path(item["snapshot_metadata"]).read_text(encoding="utf-8"))["sha256"]
        == item["sha256"]
    )
    assert item["sha256"] in render_markdown(report)
    assert '"schema_version": 2' in render_json(report)


def test_document_extraction_dedup_truncation_and_comparison(tmp_path):
    document = tmp_path / "notes.md"
    document.write_text("See https://example.test/a. and https://example.test/a", encoding="utf-8")
    report = analyze(
        {
            "documents": [str(document)],
            "captured_at": NOW,
            "max_bytes": 3,
            "fixtures": {
                "https://example.test/a": {
                    "body": "abcdef",
                    "headers": {"Content-Type": "application/octet-stream"},
                }
            },
            "previous": {
                "captures": [
                    {"requested_url": "https://example.test/a", "sha256": "old"},
                    {"requested_url": "https://old.test", "sha256": "x"},
                ]
            },
        }
    )
    assert report["summary"] == {"requested": 1, "captured": 1, "errors": 0, "changed": 1}
    assert report["captures"][0]["truncated"] is True
    assert report["captures"][0]["title"] == ""
    assert report["missing_from_current"] == ["https://old.test"]


def test_unchanged_new_and_error_states(monkeypatch):
    monkeypatch.setattr(core, "_private_host", lambda url: True)
    same = analyze(
        {
            "urls": ["https://same.test"],
            "captured_at": NOW,
            "fixtures": {"https://same.test": "same"},
        }
    )
    digest = same["captures"][0]["sha256"]
    report = analyze(
        {
            "urls": ["https://same.test", "https://new.test", "https://blocked.test"],
            "captured_at": NOW,
            "fixtures": {"https://same.test": "same", "https://new.test": "new"},
            "previous": {
                "captures": [
                    {
                        "requested_url": "https://same.test",
                        "sha256": digest,
                        "final_url": "https://same.test",
                    }
                ]
            },
        }
    )
    assert [item["state"] for item in report["changes"]] == ["unchanged", "new", "error"]
    assert report["summary"]["errors"] == 1
    with pytest.raises(ValueError, match="capture failed"):
        analyze({"urls": ["https://blocked.test"], "captured_at": NOW, "continue_on_error": False})


def test_network_capture_with_fake_opener(monkeypatch):
    class Response:
        status = 200

        def __init__(self):
            self.headers = {"Content-Type": "text/html"}

        def read(self, size):
            return b"<title>Network</title>"

        def geturl(self):
            return "https://public.test/final"

        def close(self):
            self.closed = True

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://public.test"
            assert timeout == 2.0
            return Response()

    monkeypatch.setattr(core, "_private_host", lambda url: False)
    monkeypatch.setattr(core, "build_opener", lambda recorder: Opener())
    report = analyze({"urls": ["https://public.test"], "captured_at": NOW, "timeout": 2})
    assert report["captures"][0]["title"] == "Network"


@pytest.mark.parametrize(
    "data,message",
    [
        ({}, "urls or documents"),
        ({"urls": "bad"}, "must be lists"),
        ({"urls": ["file:///tmp/a"]}, "http or https"),
        ({"documents": ["missing.txt"]}, "does not exist"),
        ({"urls": ["https://a.test"], "fixtures": []}, "fixtures must be an object"),
        ({"urls": ["https://a.test"], "max_bytes": 0}, "must be positive"),
        ({"urls": ["https://a.test"], "captured_at": "bad"}, "ISO-8601"),
    ],
)
def test_invalid_inputs(data, message):
    with pytest.raises((TypeError, ValueError), match=message):
        analyze(data)


def test_cli_output_safety(tmp_path, capsys):
    url = "https://example.test"
    source = tmp_path / "input.json"
    source.write_text(
        json.dumps({"urls": [url], "captured_at": NOW, "fixtures": {url: "<title>Page</title>"}}),
        encoding="utf-8",
    )
    assert main([str(source), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["captured"] == 1
    output = tmp_path / "report.md"
    assert main([str(source), "--output", str(output)]) == 0
    assert main([str(source), "--output", str(output)]) == 2
