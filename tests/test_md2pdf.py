"""Tests for md2pdf.py (pure Markdown → PDF via a generated Quarkdown template).

Fast tests (dry-run, argument validation, source immutability) run everywhere;
tests marked `integration` compile a real PDF with the `quarkdown` CLI and are
slow (Chromium startup).
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "quarkdown" / "references" / "md2pdf.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sample.md"


def run_md2pdf(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_missing_input_exit_1():
    r = run_md2pdf("/tmp/definitely-not-here.md")
    assert r.returncode == 1
    assert "不存在" in r.stderr


def test_invalid_numbered_exit_1():
    r = run_md2pdf(FIXTURE, "--numbered", "maybe")
    assert r.returncode == 1


def test_invalid_size_exit_1():
    r = run_md2pdf(FIXTURE, "--size", "abc")
    assert r.returncode == 1


def test_invalid_page_exit_1():
    r = run_md2pdf(FIXTURE, "--page", "X99")
    assert r.returncode == 1


def test_invalid_heading_style_exit_1():
    r = run_md2pdf(FIXTURE, "--heading-style", "1:big")
    assert r.returncode == 1


def test_output_same_as_source_rejected():
    r = run_md2pdf(FIXTURE, "-o", str(FIXTURE))
    assert r.returncode == 1


def test_dry_run_contains_key_directives():
    r = run_md2pdf(FIXTURE, "--dry-run")
    assert r.returncode == 0
    for token in (".docname", ".doclang", ".theme", ".pageformat", ".font",
                  ".paragraphstyle", ".extend", "numbered:{no}"):
        assert token in r.stdout
    assert "项目周报" in r.stdout


def test_dry_run_numbered_off_has_no_numbering():
    r = run_md2pdf(FIXTURE, "--dry-run", "--numbered", "off")
    assert ".numbering" not in r.stdout
    assert "numbered:{no}" in r.stdout


def test_dry_run_numbered_on_has_numbering():
    r = run_md2pdf(FIXTURE, "--dry-run", "--numbered", "on")
    assert ".numbering" in r.stdout
    assert "headings: 1.1.1" in r.stdout
    assert "numbered:{no}" not in r.stdout


def test_dry_run_heading_style_blocks():
    r = run_md2pdf(FIXTURE, "--dry-run", "--heading-style", "1:large,2:medium")
    assert r.returncode == 0
    assert ".depth::equals {1}" in r.stdout
    assert ".depth::equals {2}" in r.stdout
    assert "fontsize:{large}" in r.stdout
    assert "fontsize:{medium}" in r.stdout
    assert r.stdout.count(".extend {heading}") == 3
    assert "numbered:{no}" in r.stdout


def test_source_not_modified_by_dry_run():
    before = sha256(FIXTURE)
    run_md2pdf(FIXTURE, "--dry-run")
    assert sha256(FIXTURE) == before


@pytest.mark.integration
def test_integration_default_generates_pdf(tmp_path):
    out = tmp_path / "out.pdf"
    before = sha256(FIXTURE)
    r = run_md2pdf(FIXTURE, "-o", out)
    assert r.returncode == 0, r.stderr
    assert out.exists() and out.stat().st_size > 0
    assert "md2pdf: 成功" in r.stdout
    assert sha256(FIXTURE) == before


@pytest.mark.integration
def test_integration_custom_params_generates_pdf(tmp_path):
    out = tmp_path / "custom.pdf"
    r = run_md2pdf(
        FIXTURE, "--title", "自定义", "--theme", "darko", "--page", "A5",
        "--font", "Noto Sans CJK SC", "--size", "10",
        "--heading-color", "navy", "--heading-style", "1:large,2:medium",
        "-o", out,
    )
    assert r.returncode == 0, r.stderr
    assert out.exists() and out.stat().st_size > 0
