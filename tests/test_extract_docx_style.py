"""Tests for extract_docx_style.py (docx / py-generator -> Quarkdown template).

Fast tests run everywhere (numbering decision tree unit tests + dry-run and
template generation against committed fixtures).  The compile-verification path
is exercised by running the script normally, which shells out to `quarkdown`;
those tests are marked `integration` (slow JVM startup) so the fast suite
stays quick.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "quarkdown" / "scripts" / "extract_docx_style.py"
FIXTURES = ROOT / "tests" / "fixtures"
MIXED = FIXTURES / "mixed_numbering.docx"
DEC = FIXTURES / "dec_numbering.docx"
GEN_PY = FIXTURES / "gen_docx.py"

sys.path.insert(0, str(SCRIPT.parent))
import extract_docx_style as edx  # noqa: E402


def run_extract(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


# ---- numbering decision tree (§2.2) ----------------------------------------

def d(tokens, kind):
    return {"tokens": tokens, "kind": kind}


@pytest.mark.parametrize("text,expect", [
    ("1. 总则", d([("counter", "1"), ("fix", ".")], "ok")),
    ("1、总则", d([("counter", "1"), ("fix", "、")], "ok")),
    ("1．总则", d([("counter", "1"), ("fix", "．")], "ok")),
    ("1.1 适用范围", d([("counter", "1"), ("fix", "."), ("counter", "1")], "ok")),
    ("1.1.1 细则", d([("counter", "1"), ("fix", "."), ("counter", "1"),
                      ("fix", "."), ("counter", "1")], "ok")),
    ("（一）分类", d(None, "chinese")),
    ("一、分类", d(None, "chinese")),
    ("第一章 总则", d(None, "chinese")),
    ("（1）条款", d([("fix", "（"), ("counter", "1"), ("fix", "）")], "ok")),
    ("(1) 条款", d([("fix", "("), ("counter", "1"), ("fix", ")")], "ok")),
    ("（a）款项", d([("fix", "（"), ("counter", "a"), ("fix", "）")], "ok")),
    ("（A）款项", d([("fix", "（"), ("counter", "A"), ("fix", "）")], "ok")),
    ("i. 引言", d([("counter", "i"), ("fix", ".")], "ok")),
    ("I. 引言", d([("counter", "I"), ("fix", ".")], "ok")),
    ("（i）款项", d([("fix", "（"), ("counter", "i"), ("fix", "）")], "ok")),
    ("附录", d(None, "none")),
    ("前言", d(None, "none")),
    ("ab. 自定义", d(None, "unsupported")),
    ("第一章", d(None, "chinese")),
])
def test_detect_numbering(text, expect):
    tokens, kind = edx.detect_numbering(text)
    assert {"tokens": tokens, "kind": kind} == expect


def test_build_numbering_chain_plan_a_decimal():
    per_level = {
        1: (d([("counter", "1"), ("fix", ".")], "ok")["tokens"], "ok"),
        2: (d([("counter", "1"), ("fix", "."), ("counter", "1")], "ok")["tokens"], "ok"),
        3: (d([("counter", "1"), ("fix", "."), ("counter", "1"),
               ("fix", "."), ("counter", "1")], "ok")["tokens"], "ok"),
    }
    chain, plan = edx.build_numbering_chain(per_level)
    assert plan == "A"
    assert chain == "1.1.1"


def test_build_numbering_chain_plan_b_chinese():
    per_level = {
        1: (d([("counter", "1"), ("fix", ".")], "ok")["tokens"], "ok"),
        2: (None, "chinese"),
        3: (d([("counter", "1"), ("fix", "."), ("counter", "1")], "ok")["tokens"], "ok"),
    }
    chain, plan = edx.build_numbering_chain(per_level)
    assert plan == "B"
    assert chain is None


def test_build_numbering_chain_plan_b_independent_levels():
    # level 2 does not extend level 1 (independent counters)
    per_level = {
        1: (d([("counter", "1"), ("fix", ".")], "ok")["tokens"], "ok"),
        2: (d([("counter", "1"), ("fix", ".")], "ok")["tokens"], "ok"),
    }
    chain, plan = edx.build_numbering_chain(per_level)
    assert plan == "B"
    assert chain is None


def test_build_numbering_chain_plan_b_gap():
    per_level = {
        1: (d([("counter", "1"), ("fix", ".")], "ok")["tokens"], "ok"),
        3: (d([("counter", "1"), ("fix", "."), ("counter", "1"),
               ("fix", "."), ("counter", "1")], "ok")["tokens"], "ok"),
    }
    chain, plan = edx.build_numbering_chain(per_level)
    assert plan == "B"


def test_build_numbering_chain_plan_a_mixed_types():
    per_level = {
        1: (d([("counter", "1"), ("fix", ".")], "ok")["tokens"], "ok"),
        2: (d([("counter", "1"), ("fix", "."), ("counter", "A")], "ok")["tokens"], "ok"),
        3: (d([("counter", "1"), ("fix", "."), ("counter", "A"),
               ("fix", "."), ("counter", "a")], "ok")["tokens"], "ok"),
    }
    chain, plan = edx.build_numbering_chain(per_level)
    assert plan == "A"
    assert chain == "1.A.a"


# ---- py script safety scan -------------------------------------------------

def test_safety_rejects_system_call():
    src = "import os\nos.system('rm -rf /')\n"
    assert edx.check_script_safety(src)


def test_safety_rejects_network_import():
    src = "import requests\nfrom docx import Document\n"
    findings = edx.check_script_safety(src)
    assert any("requests" in f for f in findings)


def test_safety_rejects_subprocess():
    src = "import subprocess\nsubprocess.run(['rm', '-rf', '/'])\n"
    assert edx.check_script_safety(src)


def test_safety_rejects_absolute_write():
    src = "open('/etc/x', 'w').write('x')\n"
    findings = edx.check_script_safety(src)
    assert any("写文件" in f for f in findings)


def test_safety_rejects_absolute_save():
    src = "from docx import Document\ndoc = Document()\ndoc.save('/etc/x.docx')\n"
    findings = edx.check_script_safety(src)
    assert any("save" in f and "绝对" in f for f in findings)


def test_safety_accepts_gen_fixture():
    src = Path(GEN_PY).read_text(encoding="utf-8")
    assert edx.check_script_safety(src) == []


# ---- script end-to-end (fast: dry-run / no-verify) -------------------------

def test_dry_run_mixed_plan_b():
    r = run_extract(MIXED, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "方案 B" in r.stdout
    assert "中文数字" in r.stdout


def test_dry_run_dec_plan_a():
    r = run_extract(DEC, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "方案 A" in r.stdout


def test_generate_mixed_plan_b():
    r = run_extract(MIXED, "-o", "/tmp/_t_mixed.qd", "--no-verify")
    assert r.returncode == 0, r.stderr
    out = Path("/tmp/_t_mixed.qd").read_text(encoding="utf-8")
    assert "numbered:{no}" in out
    assert "headings:" not in out
    assert ".docname {混合编号样例文档}" in out
    assert out.count(".font") >= 2
    assert "textalignment:{justify}" in out


def test_generate_dec_plan_a():
    r = run_extract(DEC, "-o", "/tmp/_t_dec.qd", "--no-verify")
    assert r.returncode == 0, r.stderr
    out = Path("/tmp/_t_dec.qd").read_text(encoding="utf-8")
    assert ".numbering" in out
    assert "    - headings: 1.1.1" in out
    assert "numbered:{no}" not in out


def test_generate_py_script_input():
    r = run_extract(GEN_PY, "-o", "/tmp/_t_gen.qd", "--no-verify")
    assert r.returncode == 0, r.stderr
    out = Path("/tmp/_t_gen.qd").read_text(encoding="utf-8")
    assert ".docname {脚本生成文档}" in out
    assert "    - headings: 1.1" in out


def test_missing_input_exit_1():
    r = run_extract("/tmp/definitely-not-here.docx")
    assert r.returncode == 1
    assert "不存在" in r.stderr


def test_risky_py_input_exit_1():
    evil = Path("/tmp/_evil_test.py")
    evil.write_text("import os\nos.system('rm -rf /')\n", encoding="utf-8")
    r = run_extract(evil, "-o", "/tmp/_t_evil.qd")
    assert r.returncode == 1
    assert "存在风险" in r.stderr


def test_bad_extension_exit_1():
    txt = Path("/tmp/_plain.txt")
    txt.write_text("hello", encoding="utf-8")
    r = run_extract(txt)
    assert r.returncode == 1
    assert "不支持的输入类型" in r.stderr


def test_bad_heading_levels_exit_1():
    r = run_extract(MIXED, "--heading-levels", "x-y", "--dry-run")
    assert r.returncode == 1


# ---- integration: quarkdown compile verification ---------------------------

@pytest.mark.integration
def test_integration_mixed_verifies():
    r = run_extract(MIXED, "-o", "/tmp/_t_mixed_it.qd")
    assert r.returncode == 0, r.stderr
    assert "通过" in r.stdout


@pytest.mark.integration
def test_integration_dec_verifies():
    r = run_extract(DEC, "-o", "/tmp/_t_dec_it.qd")
    assert r.returncode == 0, r.stderr
    assert "通过" in r.stdout
