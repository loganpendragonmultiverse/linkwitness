from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

PROJECT = "linkwitness"


def _require(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is None or value == "" or value == []:
        raise ValueError(f"{key} is required")
    return value


def _linkwitness(data: dict[str, Any]) -> dict[str, Any]:
    urls = _require(data, "urls")
    captures = []
    snapshot_dir = Path(data["snapshot_dir"]) if data.get("snapshot_dir") else None
    for url in urls:
        if not str(url).startswith(("http://", "https://")):
            raise ValueError("URLs must use http or https")
        fixture = data.get("fixtures", {}).get(url)
        response: Any = (
            None
            if fixture is not None
            else urlopen(Request(url, headers={"User-Agent": "LinkWitness/1.0"}), timeout=20)
        )
        body = fixture.encode("utf-8") if fixture is not None else response.read()
        digest = hashlib.sha256(body).hexdigest()
        title_match = re.search(b"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        item = {
            "requested_url": url,
            "final_url": url if response is None else response.geturl(),
            "status": 200 if response is None else getattr(response, "status", 200),
            "content_type": "text/html; fixture"
            if response is None
            else response.headers.get("Content-Type", ""),
            "bytes": len(body),
            "sha256": digest,
            "title": re.sub("\\s+", " ", title_match.group(1).decode("utf-8", "replace")).strip()
            if title_match
            else "",
        }
        if snapshot_dir:
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            target = snapshot_dir / f"{digest}.snapshot"
            target.write_bytes(body)
            item["snapshot"] = str(target)
        captures.append(item)
    return {"captures": captures}


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "project": PROJECT, **_linkwitness(data)}


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# {report['project'].replace('-', ' ').title()} report", ""]
    for key, value in report.items():
        if key not in {"version", "project"}:
            lines.append(f"## {key.replace('_', ' ').title()}")
            lines.append("")
            lines.append(f"```json\n{json.dumps(value, indent=2, ensure_ascii=False)}\n```")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
