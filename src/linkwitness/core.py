from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROJECT = "linkwitness"
SCHEMA_VERSION = 2
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
        elif tag.lower() == "link" and "canonical" in (values.get("rel", "") or "").lower():
            self.canonical = values.get("href", "") or ""

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False


class _RedirectRecorder(HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.chain: list[dict[str, Any]] = []

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        self.chain.append(
            {"status": code, "from": req.full_url, "to": urljoin(req.full_url, newurl)}
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urls(data: dict[str, Any]) -> list[str]:
    raw_values = data.get("urls", [])
    documents = data.get("documents", [])
    if not isinstance(raw_values, list) or not isinstance(documents, list):
        raise TypeError("urls and documents must be lists")
    values = list(raw_values)
    for document in documents:
        path = Path(document)
        if not path.is_file():
            raise ValueError(f"document does not exist: {path}")
        values.extend(URL_PATTERN.findall(path.read_text(encoding="utf-8")))
    unique: list[str] = []
    for raw in values:
        url = str(raw).rstrip(".,;")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("URLs must use http or https and include a host")
        if url not in unique:
            unique.append(url)
    if not unique:
        raise ValueError("urls or documents is required")
    return unique


def _private_host(url: str) -> bool:
    host = urlparse(url).hostname or ""
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host: {host}") from exc
    return any(
        (address := ipaddress.ip_address(value)).is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        for value in addresses
    )


def _fixture_capture(url: str, fixture: Any, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    record: dict[str, Any] = {"body": fixture} if isinstance(fixture, str) else dict(fixture)
    body = str(record.get("body", "")).encode("utf-8")
    truncated = len(body) > max_bytes
    raw_headers = record.get("headers", {"content-type": "text/html; fixture"})
    if not isinstance(raw_headers, dict):
        raise TypeError("fixture headers must be an object")
    return body[:max_bytes], {
        "final_url": record.get("final_url", url),
        "status": int(record.get("status", 200)),
        "headers": {str(k).lower(): str(v) for k, v in raw_headers.items()},
        "redirects": record.get("redirects", []),
        "truncated": truncated,
    }


def _network_capture(url: str, timeout: float, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    recorder = _RedirectRecorder()
    opener = build_opener(recorder)
    response = opener.open(Request(url, headers={"User-Agent": "LinkWitness/1.1"}), timeout=timeout)
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
    finally:
        response.close()


def _metadata(body: bytes, final_url: str, content_type: str) -> dict[str, str]:
    if "html" not in content_type.lower():
        return {"title": "", "description": "", "canonical_url": ""}
    parser = _MetadataParser()
    parser.feed(body.decode("utf-8", "replace"))
    return {
        "title": re.sub(r"\s+", " ", parser.title).strip(),
        "description": re.sub(r"\s+", " ", parser.description).strip(),
        "canonical_url": urljoin(final_url, parser.canonical) if parser.canonical else "",
    }


def _snapshot(snapshot_dir: Path, item: dict[str, Any], body: bytes) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stem = item["sha256"]
    body_path = snapshot_dir / f"{stem}.snapshot"
    metadata_path = snapshot_dir / f"{stem}.json"
    body_path.write_bytes(body)
    metadata_path.write_text(
        json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    item["snapshot"] = str(body_path)
    item["snapshot_metadata"] = str(metadata_path)
    metadata_path.write_text(
        json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _linkwitness(data: dict[str, Any]) -> dict[str, Any]:
    urls = _urls(data)
    fixtures = data.get("fixtures", {})
    if not isinstance(fixtures, dict):
        raise TypeError("fixtures must be an object")
    max_bytes = int(data.get("max_bytes", 5_000_000))
    timeout = float(data.get("timeout", 20))
    if max_bytes <= 0 or timeout <= 0:
        raise ValueError("max_bytes and timeout must be positive")
    captured_at = str(data.get("captured_at", datetime.now(timezone.utc).isoformat()))
    try:
        datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("captured_at must be ISO-8601") from exc
    snapshot_dir = Path(data["snapshot_dir"]) if data.get("snapshot_dir") else None
    allow_private = bool(data.get("allow_private", False))
    captures: list[dict[str, Any]] = []
    for url in urls:
        try:
            if url in fixtures:
                body, response = _fixture_capture(url, fixtures[url], max_bytes)
            else:
                if not allow_private and _private_host(url):
                    raise ValueError("private or local network targets are blocked")
                body, response = _network_capture(url, timeout, max_bytes)
            digest = hashlib.sha256(body).hexdigest()
            headers = response["headers"]
            content_type = headers.get("content-type", "")
            item = {
                "requested_url": url,
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
    previous = {
        item["requested_url"]: item
        for item in data.get("previous", {}).get("captures", [])
        if "requested_url" in item
    }
    changes = []
    for item in captures:
        old = previous.get(item["requested_url"])
        if "error" in item:
            state = "error"
        elif old is None:
            state = "new"
        elif old.get("sha256") == item.get("sha256") and old.get("final_url") == item.get(
            "final_url"
        ):
            state = "unchanged"
        else:
            state = "changed"
        changes.append({"url": item["requested_url"], "state": state})
    missing = sorted(set(previous) - {item["requested_url"] for item in captures})
    return {
        "captured_at": captured_at,
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
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# LinkWitness capture report", "", f"Captured: {report['captured_at']}", ""]
    for item in report["captures"]:
        lines += [f"## {item['requested_url']}", ""]
        if "error" in item:
            lines += [f"Error: {item['error']}", ""]
        else:
            lines += [
                f"- Final URL: {item['final_url']}",
                f"- Status: {item['status']}",
                f"- SHA-256: `{item['sha256']}`",
                f"- Redirects: {len(item['redirects'])}",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"
