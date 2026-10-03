"""Regression tests for render_drawio.py (P1/P3 scenarios).

No network and no cairosvg: outputs are checked as text / XML only.
"""

import re
import xml.etree.ElementTree as ET

from conftest import FIXTURES, run_script


def render(fixture, *args, out="/tmp/_kilo_test_render.svg"):
    return run_script("render_drawio", FIXTURES / fixture, "-o", out, *args)


def viewbox(svg: str) -> str:
    m = re.search(r'viewBox="([^"]*)"', svg)
    assert m, "no viewBox found"
    return m.group(1)


def test_svg_well_formed(tmp_path):
    out = tmp_path / "out.svg"
    r = render("edge_diagonal_lroute.drawio", out=out)
    assert r.returncode == 0
    ET.parse(str(out))  # raises on malformed XML


def test_shape_styles_render_non_rect(tmp_path):
    out = tmp_path / "shapes.svg"
    r = render("shape_styles.drawio", out=out)
    assert r.returncode == 0
    svg = out.read_text()
    assert svg.count("<polygon") >= 2  # hexagon + parallelogram
    assert "<ellipse" in svg  # cylinder3


def test_shape_styles_both_spellings(tmp_path):
    out = tmp_path / "shapes.svg"
    r = render("shape_styles.drawio", out=out)
    assert r.returncode == 0
    svg = out.read_text()
    assert "<rect" not in svg  # no plain-rect fallback for any shape


def test_waypoint_detour_in_viewbox(tmp_path):
    out = tmp_path / "detour.svg"
    r = render("waypoint_detour.drawio", out=out)
    assert r.returncode == 0
    svg = out.read_text()
    x0, y0, w, h = (float(v) for v in viewbox(svg).split())
    # waypoints at (-60, 400) and (960, 400) must be inside the viewport
    assert x0 <= -60 <= x0 + w
    assert x0 <= 960 <= x0 + w
    assert y0 <= 400 <= y0 + h


def test_multipage_default_merges_with_note(tmp_path):
    out = tmp_path / "mp.svg"
    r = render("multipage_render.drawio", out=out)
    assert r.returncode == 0
    assert "NOTE" in r.stdout
    assert "pages" in r.stdout
    svg = out.read_text()
    assert "P1A" in svg and "P2C" in svg  # both pages merged


def test_page_select_by_index(tmp_path):
    out = tmp_path / "mp1.svg"
    r = render("multipage_render.drawio", "--page", "1", out=out)
    assert r.returncode == 0
    svg = out.read_text()
    assert "P1A" in svg
    assert "P2C" not in svg


def test_page_select_by_name(tmp_path):
    out = tmp_path / "mp2.svg"
    r = render("multipage_render.drawio", "--page", "Second", out=out)
    assert r.returncode == 0
    svg = out.read_text()
    assert "P2C" in svg
    assert "P1A" not in svg


def test_page_select_invalid(tmp_path):
    out = tmp_path / "mpx.svg"
    r = render("multipage_render.drawio", "--page", "99", out=out)
    assert r.returncode == 1
    assert "no such page" in r.stdout


def test_generated_pipeline_render(tmp_path):
    gen = run_script("generate_diagram")
    f = tmp_path / "pipeline.drawio"
    f.write_text(gen.stdout)
    out = tmp_path / "pipeline.svg"
    r = run_script("render_drawio", f, "-o", out)
    assert r.returncode == 0
    ET.parse(str(out))
