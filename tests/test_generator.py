"""Regression tests for generate_diagram.py (determinism, verifier-clean)."""

import xml.etree.ElementTree as ET

from conftest import run_script


def test_generates_valid_xml():
    r = run_script("generate_diagram")
    assert r.returncode == 0
    ET.fromstring(r.stdout)  # raises on malformed XML


def test_deterministic_output():
    a = run_script("generate_diagram").stdout
    b = run_script("generate_diagram").stdout
    assert a == b


def test_no_agent_attribute():
    r = run_script("generate_diagram")
    assert 'agent="kilo"' not in r.stdout


def test_generated_file_passes_verifier(tmp_path):
    gen = run_script("generate_diagram")
    f = tmp_path / "gen.drawio"
    f.write_text(gen.stdout)
    v = run_script("verify_diagram", f)
    assert v.returncode == 0
