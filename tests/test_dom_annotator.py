"""dom-annotator 技能的 serve.apply_edits 单元测试。

覆盖文本 / 样式 / 属性 / 删除四种修改路径，以及此前修掉的边界情况：
属性名与 data-* 前缀碰撞、无引号 / 布尔属性、!important 值等。
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "dom-annotator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from serve import _Tree, EditError, apply_edits  # noqa: E402

SRC = "<html><body><h1 id=\"title\">标题</h1><p id=\"p1\">一段 <b>加粗</b> 文字</p></body></html>\n"


def find_path(src, tag, id_=None):
    p = _Tree(src)
    p.feed(src)

    def walk(node, path):
        if node.tag == tag and (id_ is None or node.attr("id") == id_):
            return node, path
        for i, ch in enumerate(node.children):
            r = walk(ch, path + [i])
            if r:
                return r
        return None

    return walk(p.root, [])


def target(src, tag, id_=None):
    node, path = find_path(src, tag, id_)
    assert node is not None, "fixture: element %s#%s not found" % (tag, id_ or "")
    return {"path": path, "tag": tag, "id": id_ or ""}


# ---------- text ----------

def test_text_edit_leaf():
    out, changed = apply_edits(SRC, target(SRC, "h1"), [{"kind": "text", "value": "新标题"}])
    assert "新标题" in out
    assert '<h1 id="title">标题</h1>' not in out
    assert changed == [{"kind": "text"}]


def test_text_edit_escapes_html():
    out, _ = apply_edits(SRC, target(SRC, "h1"), [{"kind": "text", "value": "A & B <x>"}])
    assert "A &amp; B &lt;x&gt;" in out


def test_text_edit_rejected_with_children():
    with pytest.raises(EditError) as ei:
        apply_edits(SRC, target(SRC, "p"), [{"kind": "text", "value": "x"}])
    assert ei.value.reason == "text-not-editable"


def test_text_edit_crlf_and_entities():
    src = "<html>\r\n<body>\r\n<h1 id=\"t\">A &amp; B</h1>\r\n</body>\r\n</html>\r\n"
    out, _ = apply_edits(src, target(src, "h1"), [{"kind": "text", "value": "X & Y"}])
    assert "X &amp; Y" in out
    assert "A &amp; B" not in out


# ---------- style ----------

def test_style_add_and_update():
    out, changed = apply_edits(SRC, target(SRC, "p"),
                               [{"kind": "style", "property": "color", "value": "red"}])
    assert 'style="color: red"' in out
    assert changed[-1] == {"kind": "style", "property": "color"}

    src2 = '<html><body><p id="p1" style="color: blue">x</p></body></html>'
    out, _ = apply_edits(src2, target(src2, "p"),
                         [{"kind": "style", "property": "color", "value": "red"}])
    assert 'style="color: red"' in out
    assert "blue" not in out


def test_style_whitelist_covers_manual_panel_props():
    # 手动面板暴露的斜体 / 下划线（回归：此前被 STYLE_ALLOW 拒绝）
    for prop, value in (("font-style", "italic"), ("text-decoration", "underline")):
        out, _ = apply_edits(SRC, target(SRC, "p"),
                             [{"kind": "style", "property": prop, "value": value}])
        assert prop in out and value in out


def test_style_rejects_unknown_prop():
    with pytest.raises(EditError) as ei:
        apply_edits(SRC, target(SRC, "p"),
                    [{"kind": "style", "property": "position", "value": "absolute"}])
    assert ei.value.reason == "style-not-allowed"


def test_style_strips_trailing_important():
    out, _ = apply_edits(SRC, target(SRC, "p"),
                         [{"kind": "style", "property": "color",
                           "value": "red !important", "important": True}])
    assert out.count("!important") == 1
    assert "color: red !important" in out


def test_style_important_flag():
    out, _ = apply_edits(SRC, target(SRC, "p"),
                         [{"kind": "style", "property": "color",
                           "value": "red", "important": True}])
    assert "color: red !important" in out


def test_style_rejects_bad_value():
    with pytest.raises(EditError) as ei:
        apply_edits(SRC, target(SRC, "p"),
                    [{"kind": "style", "property": "color", "value": "red; x: 1"}])
    assert ei.value.reason == "bad-value"


# ---------- attributes ----------

def test_attr_replace_quoted():
    src = '<html><body><a id="a" href="/old">x</a></body></html>'
    out, changed = apply_edits(src, target(src, "a"),
                               [{"kind": "attr", "name": "href", "value": "/new"}])
    assert 'href="/new"' in out
    assert 'href="/old"' not in out
    assert out.count('href=') == 1
    assert changed[-1] == {"kind": "attr", "name": "href"}


def test_attr_replace_unquoted():
    # 无引号属性原位替换，保留无引号写法，且不产生重复属性
    src = "<html><body><a href=/page>link</a></body></html>"
    out, _ = apply_edits(src, target(src, "a"),
                         [{"kind": "attr", "name": "href", "value": "/new"}])
    assert out == "<html><body><a href=/new>link</a></body></html>"
    assert out.count('href=') == 1


def test_attr_valueless_boolean():
    src = '<html><body><input type="checkbox" checked></body></html>'
    out, _ = apply_edits(src, target(src, "input"),
                         [{"kind": "attr", "name": "checked", "value": "checked"}])
    assert out == '<html><body><input type="checkbox" checked="checked"></body></html>'


def test_attr_valueless_boolean_multiple():
    src = '<html><body><button disabled hidden>go</button></body></html>'
    out, _ = apply_edits(src, target(src, "button"), [
        {"kind": "attr", "name": "disabled", "value": "disabled"},
        {"kind": "attr", "name": "hidden", "value": "hidden"},
    ])
    assert 'disabled="disabled"' in out and 'hidden="hidden"' in out


def test_attr_name_not_colliding_with_data_attr():
    # 回归：id 不能误改 data-id
    src = '<html><body><div data-id="keepme" id="realid">x</div></body></html>'
    out, _ = apply_edits(src, target(src, "div"),
                         [{"kind": "attr", "name": "id", "value": "newid"}])
    assert 'id="newid"' in out
    assert 'data-id="keepme"' in out


def test_attr_src_not_colliding_with_srcset():
    src = '<html><body><img srcset="/a.png 1x" src="/b.png" data-src="k"></body></html>'
    out, _ = apply_edits(src, target(src, "img"),
                         [{"kind": "attr", "name": "src", "value": "/c.png"}])
    assert 'src="/c.png"' in out
    assert 'srcset="/a.png 1x"' in out
    assert 'data-src="k"' in out


def test_attr_uppercase_name():
    src = '<html><body><div ID="a">x</div></body></html>'
    out, _ = apply_edits(src, target(src, "div"),
                         [{"kind": "attr", "name": "id", "value": "b"}])
    assert 'ID="b"' in out


def test_attr_insert_new():
    out, _ = apply_edits(SRC, target(SRC, "h1"),
                         [{"kind": "attr", "name": "data-testid", "value": "hero"}])
    assert 'data-testid="hero"' in out


def test_attr_rejects_bad_name():
    with pytest.raises(EditError) as ei:
        apply_edits(SRC, target(SRC, "h1"), [{"kind": "attr", "name": "x y", "value": "1"}])
    assert ei.value.reason == "bad-attr"


# ---------- delete ----------

def test_delete_element_with_children():
    src = '<html><body><div id="card"><p>正文</p><img src="a.png"></div></body></html>'
    out, changed = apply_edits(src, target(src, "div"), [{"kind": "delete"}])
    assert "id=\"card\"" not in out and "正文" not in out and "a.png" not in out
    assert "<div" not in out
    assert changed == [{"kind": "delete"}]


def test_delete_void_and_selfclosing():
    src = '<html><body><p>a<br>b<img src="i.png"></p></body></html>'
    out, _ = apply_edits(src, target(src, "br"), [{"kind": "delete"}])
    assert "<br" not in out
    out, _ = apply_edits(src, target(src, "img"), [{"kind": "delete"}])
    assert "i.png" not in out


def test_delete_protected_root():
    for tag in ("html", "body"):
        with pytest.raises(EditError) as ei:
            apply_edits(SRC, target(SRC, tag), [{"kind": "delete"}])
        assert ei.value.reason in ("no-path", "delete-protected")


def test_delete_rejects_unclosed():
    src = '<html><body><div id="a"><span>未闭合<span></div></body></html>'
    with pytest.raises(EditError) as ei:
        apply_edits(src, target(src, "span"), [{"kind": "delete"}])
    assert ei.value.reason == "no-end-tag"


# ---------- misc ----------

def test_path_mismatch():
    with pytest.raises(EditError) as ei:
        apply_edits(SRC, {"path": [0], "tag": "div", "id": ""}, [{"kind": "delete"}])
    assert ei.value.reason == "path-mismatch"


def test_bad_edit_kind():
    with pytest.raises(EditError) as ei:
        apply_edits(SRC, target(SRC, "h1"), [{"kind": "unknown"}])
    assert ei.value.reason == "bad-edit"
