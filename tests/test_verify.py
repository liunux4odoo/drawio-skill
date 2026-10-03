"""Regression tests for verify_diagram.py (P0/P1/P3 scenarios)."""

from conftest import FIXTURES, run_script


def verify(fixture, *args):
    return run_script("verify_diagram", FIXTURES / fixture, *args)


def test_generated_pipeline_ok(tmp_path):
    gen = run_script("generate_diagram")
    assert gen.returncode == 0
    f = tmp_path / "pipeline.drawio"
    f.write_text(gen.stdout)
    r = verify(f)
    assert r.returncode == 0
    assert "OK: no errors." in r.stdout


def test_single_page_ok():
    r = verify("multipage.drawio")
    assert r.returncode == 0
    assert "duplicate cell id" not in r.stdout


def test_multipage_no_false_positive():
    r = verify("multipage.drawio")
    assert r.returncode == 0
    assert "duplicate cell id" not in r.stdout
    assert "overlap" not in r.stdout


def test_multipage_dup_diagram_id():
    r = verify("multipage_dup_diagramid.drawio")
    assert r.returncode == 1
    assert "duplicate <diagram> id" in r.stdout


def test_multipage_crosspage_ref():
    r = verify("multipage_crossref.drawio")
    assert r.returncode == 1
    assert "cross-page reference" in r.stdout


def test_cjk_overflow_warning():
    r = verify("cjk_overflow.drawio")
    assert r.returncode == 0
    assert "overflow" in r.stdout


def test_cjk_overflow_strict_error():
    r = verify("cjk_overflow.drawio", "--strict")
    assert r.returncode == 1


def test_edge_diagonal_lroute_ok():
    r = verify("edge_diagonal_lroute.drawio")
    assert r.returncode == 0
    assert "crosses" not in r.stdout


def test_edge_curved_warning():
    r = verify("edge_curved.drawio")
    assert r.returncode == 0
    assert "curved" in r.stdout


def test_edge_crossing_samerow():
    r = verify("edge_crossing_samerow.drawio")
    assert r.returncode == 1
    assert "crosses unrelated shape" in r.stdout


def test_edge_waypoint_detour_ok():
    r = verify("edge_waypoint_detour.drawio")
    assert r.returncode == 0


def test_waypoint_offpage_error():
    r = verify("waypoint_offpage.drawio")
    assert r.returncode == 1
    assert "outside page bounds" in r.stdout


def test_compressed_payload_dedicated_error():
    r = verify("compressed.drawio")
    assert r.returncode == 1
    assert "compressed" in r.stdout
    assert "missing root cell" not in r.stdout


def test_corner_anchor_warning():
    r = verify("edge_corner_anchor.drawio")
    assert r.returncode == 0
    assert "corner" in r.stdout


def test_identical_anchors_warning():
    r = verify("edge_identical_anchors.drawio")
    assert r.returncode == 0
    assert "identical anchors" in r.stdout


def test_missing_source_error():
    r = verify("edge_missing_source.drawio")
    assert r.returncode == 1
    assert "missing required source" in r.stdout
