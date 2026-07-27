import json
from pathlib import Path

import pytest

from linkwitness.cli import main
from linkwitness.core import PROJECT, analyze, render_json, render_markdown


def test_representative_sample_has_expected_result():
    data = json.loads(
        (Path(__file__).parents[1] / "examples" / "sample.json").read_text(encoding="utf-8")
    )
    report = analyze(data)
    assert report["version"] == 1
    assert report["project"] == PROJECT
    assert report["captures"][0]["title"] == "Evidence Page"
    assert f'"project": "{PROJECT}"' in render_json(report)
    assert PROJECT.replace("-", " ").title() in render_markdown(report)


def test_missing_required_input_is_rejected():
    with pytest.raises(ValueError):
        analyze({})


def test_fixture_snapshot_and_url_validation(tmp_path):
    url = "https://docs.python.org/3/"
    report = analyze(
        {
            "urls": [url],
            "fixtures": {url: "<title>Python docs</title>"},
            "snapshot_dir": str(tmp_path),
        }
    )
    snapshot = Path(report["captures"][0]["snapshot"])
    assert snapshot.read_text(encoding="utf-8") == "<title>Python docs</title>"
    with pytest.raises(ValueError, match="http or https"):
        analyze({"urls": ["file:///private/manuscript.txt"]})


def test_cli_json_and_output_safety(tmp_path, capsys):
    source = Path(__file__).parents[1] / "examples" / "sample.json"
    assert main([str(source), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["project"] == PROJECT
    output = tmp_path / "report.md"
    output.write_text("keep", encoding="utf-8")
    assert main([str(source), "--output", str(output)]) == 2
