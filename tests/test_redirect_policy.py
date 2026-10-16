import socket
from email.message import Message
from io import BytesIO
from urllib.request import BaseHandler
from urllib.request import build_opener as real_build_opener
from urllib.response import addinfourl

import pytest

from linkwitness import core

NOW = "2026-10-16T00:00:00+00:00"


def mock_network(monkeypatch, routes, answers):
    requests = []
    resolutions = []

    def resolve(host, port):
        resolutions.append(host)
        if host not in answers:
            raise socket.gaierror("synthetic unresolved host")
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                0,
                "",
                (address, 0),
            )
            for address in answers[host]
        ]

    class Transport(BaseHandler):
        handler_order = 100

        def http_open(self, request):
            requests.append(request.full_url)
            code, location = routes[request.full_url]
            headers = Message()
            headers["Content-Type"] = "text/html; fixture"
            if location is not None:
                headers["Location"] = location
            response = addinfourl(
                BytesIO(b"<title>Synthetic capture</title>"), headers, request.full_url, code
            )
            response.msg = "Synthetic response"
            return response

        https_open = http_open

    monkeypatch.setattr(core.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        core, "build_opener", lambda recorder: real_build_opener(recorder, Transport())
    )
    return requests, resolutions


def test_public_redirect_to_private_is_blocked_before_transport(monkeypatch):
    start, target = "https://public.test/start", "http://127.0.0.1/private"
    requests, resolutions = mock_network(
        monkeypatch,
        {start: (302, target), target: (200, None)},
        {"public.test": ["8.8.8.8"], "127.0.0.1": ["127.0.0.1"]},
    )
    report = core.analyze({"urls": [start], "captured_at": NOW})
    assert report["summary"]["errors"] == 1
    assert "private or local" in report["captures"][0]["error"]
    assert requests == [start]
    assert resolutions == ["public.test", "127.0.0.1"]


@pytest.mark.parametrize(
    ("target", "addresses"),
    [
        ("http://10.0.0.1/private", ["10.0.0.1"]),
        ("http://[::1]/private", ["::1"]),
        ("https://[fd00::1]/private", ["fd00::1"]),
        ("http://169.254.169.254/private", ["169.254.169.254"]),
        ("https://[fe80::1]/private", ["fe80::1"]),
        ("https://mixed.test/private", ["8.8.8.8", "127.0.0.1"]),
        ("https://mixed.test/private", ["::1", "2001:4860:4860::8888"]),
    ],
)
def test_private_and_mixed_dns_redirects_never_reach_transport(monkeypatch, target, addresses):
    start = "https://public.test/start"
    host = core.urlparse(target).hostname
    requests, _ = mock_network(
        monkeypatch,
        {start: (302, target), target: (200, None)},
        {"public.test": ["8.8.8.8"], host: addresses},
    )
    report = core.analyze({"urls": [start], "captured_at": NOW})
    assert "private or local" in report["captures"][0]["error"]
    assert requests == [start]


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_relative_redirect_history_and_public_ipv6(monkeypatch, code):
    start, middle, final = (
        "https://public.test/dir/start",
        "https://public.test/next",
        "https://[2001:4860:4860::8888]/final",
    )
    requests, resolutions = mock_network(
        monkeypatch,
        {start: (code, "../next"), middle: (302, final), final: (200, None)},
        {"public.test": ["8.8.8.8"], "2001:4860:4860::8888": ["2001:4860:4860::8888"]},
    )
    item = core.analyze({"urls": [start], "captured_at": NOW, "max_redirects": 2})["captures"][0]
    if code == 308 and not hasattr(core.HTTPRedirectHandler, "http_error_308"):
        assert item["error"].startswith("HTTP Error 308")
        assert requests == [start]
        assert resolutions == ["public.test"]
        return
    assert item["title"] == "Synthetic capture"
    assert item["final_url"] == final
    assert item["redirects"] == [
        {"status": code, "from": start, "to": middle},
        {"status": 302, "from": middle, "to": final},
    ]
    assert requests == [start, middle, final]
    assert resolutions == ["public.test", "public.test", "2001:4860:4860::8888"]


def test_rechecks_same_host_dns_on_relative_redirect(monkeypatch):
    start, target = "https://public.test/start", "https://public.test/next"
    requests, resolutions = mock_network(
        monkeypatch,
        {start: (302, "/next"), target: (200, None)},
        {"public.test": ["8.8.8.8"]},
    )
    answers = iter(["8.8.8.8", "127.0.0.1"])

    def changing_dns(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (next(answers), 0))]

    monkeypatch.setattr(core.socket, "getaddrinfo", changing_dns)
    report = core.analyze({"urls": [start], "captured_at": NOW})
    assert "private or local" in report["captures"][0]["error"]
    assert requests == [start]
    assert resolutions == []


@pytest.mark.parametrize("limit", [0, 1, 3, 12])
def test_total_hop_limit_bounds_unique_targets(monkeypatch, limit):
    urls = [f"https://public.test/{i}" for i in range(limit + 2)]
    requests, resolutions = mock_network(
        monkeypatch,
        {url: (302, urls[i + 1]) for i, url in enumerate(urls[:-1])},
        {"public.test": ["8.8.8.8"]},
    )
    report = core.analyze({"urls": urls[:1], "captured_at": NOW, "max_redirects": limit})
    assert f"max_redirects={limit}" in report["captures"][0]["error"]
    assert requests == urls[: limit + 1]
    assert len(resolutions) == limit + 1


def test_repeated_url_loop_is_bounded_and_allow_private_does_not_bypass_limit(monkeypatch):
    first, second = "http://127.0.0.1/a", "http://127.0.0.1/b"
    requests, resolutions = mock_network(
        monkeypatch,
        {first: (302, second), second: (302, first)},
        {},
    )
    report = core.analyze(
        {
            "urls": [first],
            "captured_at": NOW,
            "max_redirects": 3,
            "allow_private": True,
        }
    )
    assert "hop limit" in report["captures"][0]["error"]
    assert requests == [first, second, first, second]
    assert resolutions == []


def test_allow_private_preserves_explicit_initial_and_redirect_access(monkeypatch):
    start, target = "http://127.0.0.1/start", "http://[::1]/final"
    requests, resolutions = mock_network(
        monkeypatch,
        {start: (302, target), target: (200, None)},
        {},
    )
    report = core.analyze({"urls": [start], "captured_at": NOW, "allow_private": True})
    assert report["summary"]["captured"] == 1
    assert requests == [start, target] and resolutions == []


def test_default_total_limit_is_ten_and_no_redirect_allows_zero(monkeypatch):
    urls = [f"https://public.test/{i}" for i in range(12)]
    requests, _ = mock_network(
        monkeypatch,
        {url: (302, urls[i + 1]) for i, url in enumerate(urls[:-1])},
        {"public.test": ["8.8.8.8"]},
    )
    assert "max_redirects=10" in core.analyze({"urls": urls[:1]})["captures"][0]["error"]
    assert len(requests) == 11
    requests, _ = mock_network(monkeypatch, {urls[0]: (200, None)}, {"public.test": ["8.8.8.8"]})
    assert core.analyze({"urls": urls[:1], "max_redirects": 0})["summary"]["captured"] == 1


def test_batch_continues_and_strict_stops_before_following_private_redirect(monkeypatch):
    start, target, good = (
        "https://public.test/start",
        "http://127.0.0.1/private",
        "https://public.test/good",
    )
    routes = {start: (302, target), target: (200, None), good: (200, None)}
    answers = {"public.test": ["8.8.8.8"], "127.0.0.1": ["127.0.0.1"]}
    requests, _ = mock_network(monkeypatch, routes, answers)
    report = core.analyze({"urls": [start, good], "captured_at": NOW})
    assert report["summary"]["captured"] == 1 and report["summary"]["errors"] == 1
    assert [item["state"] for item in report["changes"]] == ["error", "new"]
    assert requests == [start, good]
    requests, _ = mock_network(monkeypatch, routes, answers)
    with pytest.raises(ValueError, match="capture failed.*private or local"):
        core.analyze({"urls": [start, good], "continue_on_error": False})
    assert requests == [start]


def test_dns_failure_is_a_batch_error_and_initial_private_target_stays_blocked(monkeypatch):
    start, target = "https://public.test/start", "https://unknown.test/next"
    requests, _ = mock_network(
        monkeypatch,
        {start: (302, target)},
        {"public.test": ["8.8.8.8"], "::1": ["::1"]},
    )
    report = core.analyze({"urls": [start, "http://[::1]/"]})
    assert "cannot resolve host: unknown.test" in report["captures"][0]["error"]
    assert "private or local" in report["captures"][1]["error"]
    assert requests == [start]


def test_redirect_scheme_is_restricted_even_with_allow_private(monkeypatch):
    start = "https://public.test/start"
    requests, _ = mock_network(monkeypatch, {start: (302, "ftp://public.test/file")}, {})
    report = core.analyze({"urls": [start], "allow_private": True})
    assert "redirect URLs must use http or https" in report["captures"][0]["error"]
    assert requests == [start]


def test_rejected_redirect_closes_response(monkeypatch):
    monkeypatch.setattr(core, "_private_host", lambda url: True)
    response = BytesIO()
    with pytest.raises(ValueError, match="private or local"):
        core._RedirectRecorder().redirect_request(
            core.Request("https://public.test"), response, 302, "Synthetic", {}, "http://127.0.0.1/"
        )
    assert response.closed


@pytest.mark.parametrize("limit", [-1, True, 1.5, "3", None])
def test_invalid_hop_limits_are_rejected_before_any_request(monkeypatch, limit):
    requests, resolutions = mock_network(monkeypatch, {}, {})
    with pytest.raises((ValueError, TypeError), match="max_redirects"):
        core.analyze({"urls": ["https://public.test"], "max_redirects": limit})
    assert requests == [] and resolutions == []


def test_offline_fixtures_remain_offline_even_with_private_metadata(monkeypatch):
    requests, resolutions = mock_network(monkeypatch, {}, {})
    url = "https://fixture.test"
    report = core.analyze(
        {
            "urls": [url],
            "captured_at": NOW,
            "max_redirects": 0,
            "fixtures": {url: {"body": "offline", "final_url": "http://127.0.0.1/"}},
        }
    )
    assert report["summary"]["captured"] == 1
    assert requests == [] and resolutions == []


@pytest.mark.parametrize("strict", [False, True])
def test_hop_limit_obeys_batch_and_strict_modes(monkeypatch, strict):
    start, good = "https://public.test/start", "https://public.test/good"
    requests, _ = mock_network(
        monkeypatch,
        {start: (302, start), good: (200, None)},
        {"public.test": ["8.8.8.8", "2001:4860:4860::8888"]},
    )
    data = {"urls": [start, good], "max_redirects": 0, "continue_on_error": not strict}
    if strict:
        with pytest.raises(ValueError, match="capture failed.*hop limit"):
            core.analyze(data)
        assert requests == [start]
    else:
        report = core.analyze(data)
        assert report["summary"]["captured"] == report["summary"]["errors"] == 1
        assert requests == [start, good]
