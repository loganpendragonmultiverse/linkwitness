from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import socket
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ._io import checked_path, code_span, read_bytes, validate_json, write_new_text

PROJECT = "linkwitness"
SCHEMA_VERSION = 2
MAX_REDIRECTS = 20
MAX_URLS = 1000
MAX_DOCUMENTS = 100
MAX_CAPTURE_BYTES = 50 * 1024 * 1024
URL_PATTERN = re.compile(r"https?://[^\s<>'\"\])}]+")


def _require(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is None or value == "" or value == []:
        raise ValueError(f"{key} is required")
    return value


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title = ""
        self.description = ""
        self.canonical = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.lower() == "title":
            self.in_title = True
        elif tag.lower() == "meta" and (values.get("name") or "").lower() == "description":
            self.description = values.get("content", "") or ""
        elif tag.lower() == "link" and "canonical" in (values.get("rel", "") or "").lower().split():
            self.canonical = values.get("href", "") or ""

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False


def _redirect_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_redirects must be an integer")
    if not 0 <= value <= MAX_REDIRECTS:
        raise ValueError(f"max_redirects must be between 0 and {MAX_REDIRECTS}")
    return value


class _RedirectRecorder(HTTPRedirectHandler):
    def __init__(self, *, allow_private: bool = False, max_redirects: int = 10) -> None:
        super().__init__()
        self.chain: list[dict[str, Any]] = []
        if not isinstance(allow_private, bool):
            raise TypeError("allow_private must be boolean")
        self.allow_private = allow_private
        self.max_redirects = _redirect_limit(max_redirects)
        # urllib reads these class defaults through each handler instance.
        # The total-hop counter below bounds repeated and distinct targets.
        self.max_repeats = self.max_redirects + 1  # type: ignore[misc]
        self.max_redirections = self.max_redirects + 1  # type: ignore[misc]

    def http_error_302(self, req: Request, fp: Any, code: int, msg: str, headers: Any) -> Any:
        try:
            return super().http_error_302(req, fp, code, msg, headers)
        except (ValueError, OSError, HTTPException):
            fp.close()
            raise

    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302
    if hasattr(HTTPRedirectHandler, "http_error_308"):
        http_error_308 = http_error_302

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        try:
            target = urljoin(req.full_url, newurl)
            if len(self.chain) >= self.max_redirects:
                raise ValueError(
                    f"redirect hop limit exceeded (max_redirects={self.max_redirects})"
                )
            try:
                _url(target)
            except ValueError as exc:
                raise ValueError(
                    f"redirect URLs must use http or https and valid unauthenticated syntax: {exc}"
                ) from exc
            if not self.allow_private and _private_host(target):
                raise ValueError("private or local network targets are blocked")
            redirected = super().redirect_request(req, fp, code, msg, headers, target)
        except (ValueError, HTTPError):
            fp.close()
            raise
        if redirected is not None:
            self.chain.append({"status": code, "from": req.full_url, "to": target})
        return redirected


def _url(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise ValueError("URLs must be strings of at most 8192 characters")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("URLs cannot contain literal whitespace or control characters")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URLs must use http or https and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("authenticated URLs are outside the capture scope")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("URL port must be between 1 and 65535")
    return value


def _urls(data: dict[str, Any]) -> list[str]:
    raw_values = data.get("urls", [])
    documents = data.get("documents", [])
    if not isinstance(raw_values, list) or not isinstance(documents, list):
        raise TypeError("urls and documents must be lists")
    if len(documents) > MAX_DOCUMENTS:
        raise ValueError("too many source documents")
    unique: list[str] = []
    seen: set[str] = set()

    def add(raw: Any) -> None:
        url = _url(raw)
        if url not in seen:
            seen.add(url)
            unique.append(url)
        if len(unique) > MAX_URLS:
            raise ValueError("too many capture URLs")

    for raw in raw_values:
        add(raw)
    for document in documents:
        if not isinstance(document, str) or not document:
            raise TypeError("document paths must be nonempty strings")
        path = checked_path(Path(document))
        if not path.is_file():
            raise ValueError(f"document does not exist: {path}")
        for match in URL_PATTERN.finditer(read_bytes(path).decode("utf-8-sig")):
            # Punctuation removal applies only to prose extraction, never explicit URLs.
            add(match.group().rstrip(".,;"))
    if not unique:
        raise ValueError("urls or documents is required")
    return unique


def _private_host(url: str) -> bool:
    host = urlparse(url).hostname or ""
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host: {host}") from exc
    if not addresses:
        raise ValueError(f"cannot resolve host: {host}; no addresses returned")
    return any(
        (address := ipaddress.ip_address(value)).is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or not address.is_global
        for value in addresses
    )


def _fixture_capture(url: str, fixture: Any, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    record: dict[str, Any] = {"body": fixture} if isinstance(fixture, str) else dict(fixture)
    body = record.get("body", "").encode("utf-8")
    return body[:max_bytes], {
        "final_url": record.get("final_url", url),
        "status": record.get("status", 200),
        "headers": {
            k.lower(): v
            for k, v in record.get("headers", {"content-type": "text/html; fixture"}).items()
        },
        "redirects": record.get("redirects", []),
        "truncated": len(body) > max_bytes,
    }


def _fixtures(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("fixtures must be an object")
    for url, fixture in value.items():
        _url(url)
        if isinstance(fixture, str):
            continue
        if not isinstance(fixture, dict) or not isinstance(fixture.get("body", ""), str):
            raise TypeError("fixtures require string bodies or fixture objects")
        status = fixture.get("status", 200)
        if type(status) is not int or not 100 <= status <= 599:
            raise ValueError("fixture status must be an HTTP status integer")
        _url(fixture.get("final_url", url))
        headers = fixture.get("headers", {})
        if not isinstance(headers, dict) or any(not isinstance(v, str) for v in headers.values()):
            raise TypeError("fixture headers must be an object of strings")
        redirects = fixture.get("redirects", [])
        if not isinstance(redirects, list) or len(redirects) > MAX_REDIRECTS:
            raise ValueError("fixture redirects must be a bounded array")
        for redirect in redirects:
            if (
                not isinstance(redirect, dict)
                or type(redirect.get("status")) is not int
                or redirect["status"] not in {301, 302, 303, 307, 308}
            ):
                raise ValueError("invalid fixture redirect metadata")
            _url(redirect.get("from"))
            _url(redirect.get("to"))
    return value


def _previous(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("captures"), list):
        raise TypeError("previous capture evidence requires an explicit captures array")
    if "project" in value and value["project"] != PROJECT:
        raise ValueError("previous evidence belongs to a different project")
    if "schema_version" in value and (
        type(value["schema_version"]) is not int or value["schema_version"] not in {1, 2}
    ):
        raise ValueError("unsupported previous capture schema")
    result: dict[str, dict[str, Any]] = {}
    for item in value["captures"]:
        if not isinstance(item, dict):
            raise TypeError("previous captures must be objects")
        url = _url(item.get("requested_url"))
        if url in result:
            raise ValueError("duplicate previous requested URL")
        if "error" in item:
            if not isinstance(item["error"], str):
                raise TypeError("previous capture errors must be text")
        elif not isinstance(item.get("sha256"), str) or not item["sha256"]:
            raise ValueError("previous successful capture requires a fingerprint")
        if "final_url" in item:
            _url(item["final_url"])
        if "truncated" in item and not isinstance(item["truncated"], bool):
            raise TypeError("previous truncation must be boolean")
        result[url] = item
    return result


def _network_capture(
    url: str,
    timeout: float,
    max_bytes: int,
    *,
    allow_private: bool = False,
    max_redirects: int = 10,
) -> tuple[bytes, dict[str, Any]]:
    recorder = _RedirectRecorder(allow_private=allow_private, max_redirects=max_redirects)
    opener = build_opener(recorder)
    try:
        response = opener.open(
            Request(url, headers={"User-Agent": "LinkWitness/1.2.0"}), timeout=timeout
        )
    except HTTPError as exc:
        exc.close()
        raise
    except HTTPException as exc:
        raise ValueError("HTTP response headers could not be read") from exc
    try:
        body = response.read(max_bytes + 1)
        headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
        return body[:max_bytes], {
            "final_url": response.geturl(),
            "status": int(getattr(response, "status", 200)),
            "headers": headers,
            "redirects": recorder.chain,
            "truncated": len(body) > max_bytes,
        }
    except HTTPException as exc:
        raise ValueError("HTTP response could not be read completely") from exc
    finally:
        response.close()


def _metadata(body: bytes, final_url: str, content_type: str) -> dict[str, str]:
    if "html" not in content_type.lower():
        return {"title": "", "description": "", "canonical_url": ""}
    parser = _MetadataParser()
    message = Message()
    message["content-type"] = content_type
    charset = message.get_content_charset() or "utf-8"
    try:
        text = body.decode(charset, "replace")
    except LookupError:
        text = body.decode("utf-8", "replace")
    parser.feed(text)
    return {
        "title": re.sub(r"\s+", " ", parser.title).strip(),
        "description": re.sub(r"\s+", " ", parser.description).strip(),
        "canonical_url": urljoin(final_url, parser.canonical) if parser.canonical else "",
    }


def _snapshot(snapshot_dir: Path, item: dict[str, Any], body: bytes) -> None:
    checked_path(snapshot_dir)
    capture_id = hashlib.sha256(
        json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    body_path = snapshot_dir / f"{item['sha256']}.snapshot"
    metadata_path = snapshot_dir / f"{capture_id}.json"
    item.update(
        capture_id=capture_id, snapshot=str(body_path), snapshot_metadata=str(metadata_path)
    )
    metadata = json.dumps(item, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    # Validate both existing destinations before creating either new file.
    for path, expected in ((body_path, body), (metadata_path, metadata.encode("utf-8"))):
        checked_path(path)
        if path.exists() and read_bytes(path, len(expected)) != expected:
            raise ValueError("existing snapshot evidence differs; nothing is replaced")
    if not body_path.exists():
        if body_path.is_symlink():
            raise ValueError("snapshot symlinks are unsupported")
        with body_path.open("xb") as handle:
            handle.write(body)
    if not metadata_path.exists():
        write_new_text(metadata_path, metadata)


def _linkwitness(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise TypeError("capture input must be an object")
    validate_json(data)
    for field in ("allow_private", "continue_on_error"):
        if field in data and not isinstance(data[field], bool):
            raise TypeError(f"{field} must be boolean")
    fixtures = _fixtures(data.get("fixtures", {}))
    max_bytes = data.get("max_bytes", 5_000_000)
    timeout = data.get("timeout", 20)
    if (
        type(max_bytes) is not int
        or isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
    ):
        raise TypeError("max_bytes must be integer and timeout must be numeric")
    if (
        not 0 < max_bytes <= MAX_CAPTURE_BYTES
        or not 0 < timeout <= 300
        or not math.isfinite(timeout)
    ):
        raise ValueError("max_bytes and timeout must be positive bounded values")
    max_redirects = _redirect_limit(data.get("max_redirects", 10))
    captured_at = data.get("captured_at", datetime.now(timezone.utc).isoformat())
    try:
        if not isinstance(captured_at, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",
            captured_at,
        ):
            raise ValueError("timestamp format")
        moment = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("missing offset")
    except ValueError as exc:
        raise ValueError("captured_at must be an ISO-8601 timestamp with a UTC offset") from exc
    previous = _previous(data["previous"]) if "previous" in data else {}
    urls = _urls(data)
    snapshot_dir = None
    if "snapshot_dir" in data:
        if not isinstance(data["snapshot_dir"], str) or not data["snapshot_dir"]:
            raise TypeError("snapshot_dir must be a nonempty path string")
        snapshot_dir = checked_path(Path(data["snapshot_dir"]))
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        checked_path(snapshot_dir)
        if not snapshot_dir.is_dir():
            raise ValueError("snapshot_dir must be a directory")
    allow_private = data.get("allow_private", False)
    captures: list[dict[str, Any]] = []
    for url in urls:
        try:
            if url in fixtures:
                body, response = _fixture_capture(url, fixtures[url], max_bytes)
            else:
                if not allow_private and _private_host(url):
                    raise ValueError("private or local network targets are blocked")
                body, response = _network_capture(
                    url,
                    timeout,
                    max_bytes,
                    allow_private=allow_private,
                    max_redirects=max_redirects,
                )
            digest = hashlib.sha256(body).hexdigest()
            headers = response["headers"]
            content_type = headers.get("content-type", "")
            item = {
                "requested_url": url,
                "capture_source": "fixture" if url in fixtures else "network",
                "capture_time_source": "supplied" if "captured_at" in data else "system-utc",
                "final_url": response["final_url"],
                "redirects": response["redirects"],
                "status": response["status"],
                "captured_at": captured_at,
                "content_type": content_type,
                "etag": headers.get("etag", ""),
                "last_modified": headers.get("last-modified", ""),
                "bytes": len(body),
                "truncated": response["truncated"],
                "sha256": digest,
                **_metadata(body, response["final_url"], content_type),
            }
            if snapshot_dir:
                _snapshot(snapshot_dir, item, body)
            captures.append(item)
        except (HTTPError, URLError, OSError, ValueError) as exc:
            if not data.get("continue_on_error", True):
                raise ValueError(f"capture failed for {url}: {exc}") from exc
            captures.append({"requested_url": url, "captured_at": captured_at, "error": str(exc)})
    changes = []
    for item in captures:
        old = previous.get(item["requested_url"])
        if "error" in item:
            state = "error"
        elif old is None:
            state = "new"
        elif (
            "error" not in old
            and old.get("sha256") == item.get("sha256")
            and old.get("final_url") == item.get("final_url")
        ):
            state = "unchanged"
        else:
            state = "changed"
        changes.append(
            {
                "url": item["requested_url"],
                "state": state,
                "comparison_scope": "captured-bytes-and-final-url-only",
                "complete_representation_compared": bool(
                    old is not None
                    and "error" not in old
                    and "error" not in item
                    and not item.get("truncated", True)
                    and old.get("truncated") is False
                ),
            }
        )
    missing = sorted(set(previous) - {item["requested_url"] for item in captures})
    return {
        "captured_at": captured_at,
        "comparison_boundary": "Unchanged describes only captured bytes and final URL, not complete remote content, metadata, authorship or semantic equivalence. Failed, truncated and legacy captures are explicitly not full-representation comparisons.",
        "captures": captures,
        "changes": changes,
        "missing_from_current": missing,
        "summary": {
            "requested": len(urls),
            "captured": sum("error" not in item for item in captures),
            "errors": sum("error" in item for item in captures),
            "changed": sum(item["state"] == "changed" for item in changes),
        },
    }


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "project": PROJECT, **_linkwitness(data)}


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# LinkWitness capture report", "", f"Captured: {report['captured_at']}", ""]
    for item in report["captures"]:
        lines += [f"## {code_span(item['requested_url'])}", ""]
        if "error" in item:
            lines += [f"Error: {code_span(item['error'])}", ""]
        else:
            lines += [
                f"- Final URL: {code_span(item['final_url'])}",
                f"- Source: {item['capture_source']}",
                f"- Status: {item['status']}",
                f"- SHA-256: `{item['sha256']}`",
                f"- Redirects: {len(item['redirects'])}",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"
