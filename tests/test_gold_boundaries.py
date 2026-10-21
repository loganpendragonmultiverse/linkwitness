import json
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from linkwitness import core
from linkwitness.cli import main

NOW = "2026-10-21T00:00:00Z"
URL = "https://fixture.test/path"


def fixture(**extra):
    return {"urls": [URL], "fixtures": {URL: "body"}, "captured_at": NOW, **extra}


@pytest.mark.parametrize(
    "extra",
    [
        {"allow_private": "false"},
        {"continue_on_error": "false"},
        {"max_bytes": True},
        {"max_bytes": 50 * 1024 * 1024 + 1},
        {"timeout": float("inf")},
        {"timeout": float("nan")},
        {"timeout": 10**999},
        {"timeout": 301},
        {"timeout": False},
        {"captured_at": "2026-10-21"},
        {"captured_at": False},
        {"previous": {}},
        {"previous": {"captures": [None]}},
        {"previous": {"captures": [{"requested_url": URL, "sha256": "x"}] * 2}},
        {"previous": {"captures": [], "project": "other"}},
        {"previous": {"captures": [], "schema_version": True}},
    ],
    ids=[
        "private-string",
        "continue-string",
        "bytes-bool",
        "bytes-overflow",
        "timeout-inf",
        "timeout-nan",
        "timeout-bigint",
        "timeout-overflow",
        "timeout-bool",
        "date-only",
        "timestamp-bool",
        "previous-missing",
        "previous-nonobject",
        "duplicate-previous",
        "foreign-previous",
        "previous-bool-version",
    ],
)
def test_malformed_config_is_rejected_before_dns_or_transport(monkeypatch, extra):
    def forbidden(*args, **kwargs):
        raise AssertionError("network boundary reached")

    monkeypatch.setattr(core.socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(core, "_network_capture", forbidden)
    with pytest.raises((ValueError, TypeError)):
        core.analyze(fixture(**extra))


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        4,
        {"body": []},
        {"status": True},
        {"status": 999},
        {"headers": []},
        {"headers": {"x": 3}},
        {"redirects": [{}]},
        {"redirects": [{"status": 302, "from": URL, "to": "file:///bad"}]},
    ],
)
def test_fixture_shapes_are_validated(value):
    with pytest.raises((ValueError, TypeError)):
        core.analyze(fixture(fixtures={URL: value}))


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@host.test/",
        "https://host.test:99999/",
        "https://host.test/with space",
        "https://host.test:0/",
        17,
    ],
)
def test_explicit_urls_are_unauthenticated_and_unambiguous(url):
    with pytest.raises(ValueError):
        core.analyze({"urls": [url]})


def test_empty_and_nonglobal_dns_answers_are_blocked_without_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(core, "_network_capture", lambda *a, **k: calls.append(a))
    for addresses in [[], ["100.64.0.1"], ["224.0.0.1"], ["8.8.8.8", "127.0.0.1"]]:
        monkeypatch.setattr(
            core.socket,
            "getaddrinfo",
            lambda *a, addresses=addresses: [(0, 0, 0, "", (v, 0)) for v in addresses],
        )
        report = core.analyze({"urls": ["https://public.test/"]})
        assert report["summary"]["errors"] == 1 and calls == []


def test_snapshot_metadata_is_distinct_immutable_and_reusable(tmp_path):
    urls = ["https://one.test/", "https://two.test/"]
    data = {
        "urls": urls,
        "fixtures": dict.fromkeys(urls, "same"),
        "captured_at": NOW,
        "snapshot_dir": str(tmp_path / "snapshots"),
    }
    report = core.analyze(data)
    a, b = report["captures"]
    assert a["snapshot"] == b["snapshot"] and a["snapshot_metadata"] != b["snapshot_metadata"]
    for item in report["captures"]:
        meta = json.loads(Path(item["snapshot_metadata"]).read_text())
        assert (
            meta["requested_url"] == item["requested_url"]
            and meta["capture_source"] == "fixture"
            and meta["capture_time_source"] == "supplied"
        )
    before = {p: p.read_bytes() for p in (tmp_path / "snapshots").iterdir()}
    assert core.analyze(data)["captures"] == report["captures"]
    assert before == {p: p.read_bytes() for p in before}
    Path(a["snapshot"]).write_text("corrupt")
    assert (
        core.analyze(data)["summary"]["errors"] == 2
        and Path(a["snapshot"]).read_text() == "corrupt"
    )


def test_snapshot_symlinks_and_existing_output_fail_before_capture(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(fixture(snapshot_dir=str(tmp_path / "snapshots"))))
    dest = tmp_path / "output"
    dest.write_text("keep")
    monkeypatch.setattr(
        core,
        "_network_capture",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("transport reached")),
    )
    assert (
        main([str(source), "--output", str(dest)]) == 2
        and dest.read_text() == "keep"
        and not (tmp_path / "snapshots").exists()
    )
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        core.analyze(fixture(snapshot_dir=str(alias)))
    assert not list(target.iterdir())


def test_snapshot_existing_metadata_is_never_replaced(tmp_path):
    data = fixture(snapshot_dir=str(tmp_path / "snapshots"))
    item = core.analyze(data)["captures"][0]
    p = Path(item["snapshot_metadata"])
    p.write_text("changed")
    assert core.analyze(data)["summary"]["errors"] == 1 and p.read_text() == "changed"


def test_document_limits_symlinks_and_explicit_punctuation(tmp_path, monkeypatch):
    url = URL + "."
    assert (
        core.analyze(fixture(urls=[url], fixtures={url: "body"}))["captures"][0]["requested_url"]
        == url
    )
    doc = tmp_path / "source.md"
    doc.write_text(URL)
    alias = tmp_path / "alias.md"
    try:
        alias.symlink_to(doc)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        core.analyze(fixture(urls=[], documents=[str(alias)]))
    monkeypatch.setattr(core, "MAX_URLS", 1)
    with pytest.raises(ValueError, match="too many"):
        core.analyze(fixture(urls=[URL, URL + "/other"]))
    monkeypatch.setattr(core, "MAX_DOCUMENTS", 0)
    with pytest.raises(ValueError, match="too many"):
        core.analyze(fixture(documents=[str(doc)]))


def test_html_charset_and_canonical_tokens_and_literal_markdown():
    result = core._metadata(
        '<title>café</title><link rel="notcanonical" href="/wrong">'.encode("latin-1"),
        URL,
        "text/html; charset=iso-8859-1",
    )
    assert result["title"] == "café" and result["canonical_url"] == ""
    assert (
        core._metadata(b"<title>safe</title>", URL, "text/html; charset=unknown-charset")["title"]
        == "safe"
    )
    url = "https://fixture.test/`<img>"
    html = core.render_markdown(core.analyze(fixture(urls=[url], fixtures={url: "body"})))
    assert "``https://fixture.test/`<img>``" in html


def test_read_and_http_errors_close_responses(monkeypatch):
    class Response:
        status = 200
        closed = False

        def __init__(self):
            self.headers = {}

        def read(self, size):
            raise IncompleteRead(b"partial", 10)

        def close(self):
            self.closed = True

    response = Response()

    class Opener:
        def open(self, *a, **k):
            return response

    monkeypatch.setattr(core, "build_opener", lambda *a: Opener())
    with pytest.raises(ValueError, match="read completely"):
        core._network_capture(URL, 1, 100)
    assert response.closed
    stream = BytesIO(b"error")
    error = HTTPError(URL, 500, "fixture", {}, stream)

    class ErrorOpener:
        def open(self, *a, **k):
            raise error

    monkeypatch.setattr(core, "build_opener", lambda *a: ErrorOpener())
    with pytest.raises(HTTPError):
        core._network_capture(URL, 1, 100)
    assert stream.closed


def test_comparisons_mark_truncated_and_legacy_scope():
    first = core.analyze(fixture(max_bytes=2))
    second = core.analyze(fixture(max_bytes=2, previous=first))
    assert (
        second["changes"][0]["state"] == "unchanged"
        and not second["changes"][0]["complete_representation_compared"]
    )
    first = core.analyze(fixture())
    assert core.analyze(fixture(previous=first))["changes"][0]["complete_representation_compared"]
    legacy = {
        "captures": [
            {"requested_url": URL, "sha256": first["captures"][0]["sha256"], "final_url": URL}
        ]
    }
    assert not core.analyze(fixture(previous=legacy))["changes"][0][
        "complete_representation_compared"
    ]


def test_cli_strict_input_preserves_existing_source(tmp_path):
    source = tmp_path / "input.json"
    source.write_text('{"urls":[],"urls":[]}')
    before = source.read_bytes()
    assert main([str(source)]) == 2 and source.read_bytes() == before


def test_invalid_http_status_and_malformed_redirect_are_actionable_and_closed(monkeypatch):
    from http.client import BadStatusLine

    class Opener:
        def open(self, *a, **k):
            raise BadStatusLine("malformed fixture status")

    monkeypatch.setattr(core, "build_opener", lambda *a: Opener())
    with pytest.raises(ValueError, match="HTTP response"):
        core._network_capture(URL, 1, 100)
    fp = BytesIO(b"redirect fixture")
    with pytest.raises(ValueError):
        core._RedirectRecorder().http_error_302(
            core.Request(URL), fp, 302, "fixture", {"location": "http://["}
        )
    assert fp.closed


@pytest.mark.parametrize("include_matching_fingerprint", [False, True])
def test_failed_previous_capture_never_proves_unchanged_or_complete(include_matching_fingerprint):
    successful = core.analyze(fixture())
    old = {"requested_url": URL, "error": "previous capture failed", "truncated": False}
    if include_matching_fingerprint:
        old.update({"sha256": successful["captures"][0]["sha256"], "final_url": URL})
    report = core.analyze(fixture(previous={"captures": [old]}))
    assert report["summary"]["captured"] == 1
    assert report["changes"][0]["state"] == "changed"
    assert report["changes"][0]["complete_representation_compared"] is False
    # The same minimal legacy success record remains valid, with conservative completeness.
    legacy = {
        "captures": [
            {"requested_url": URL, "sha256": successful["captures"][0]["sha256"], "final_url": URL}
        ]
    }
    legacy_report = core.analyze(fixture(previous=legacy))
    assert legacy_report["changes"][0]["state"] == "unchanged"
    assert legacy_report["changes"][0]["complete_representation_compared"] is False
