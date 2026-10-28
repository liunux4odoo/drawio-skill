#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 dom-annotator 删除元素功能：apply_edits 的 delete 分支单元测试。
用法: python3 verify_delete.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from serve import apply_edits, EditError

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        print("  FAIL  %s  %s" % (name, detail))


SRC = (
    "<html><head><title>t</title></head><body>\n"
    "  <nav id=\"nav\"><a href=\"/\">首页</a></nav>\n"
    "  <h1 id=\"title\">标题</h1>\n"
    "  <div id=\"card\"><p>一段说明文字</p><img src=\"a.png\"></div>\n"
    "  <footer>脚注</footer>\n"
    "</body></html>\n"
)


def find_path(root, pred):
    """返回 (node, path) 或 None。path 是相对 root 的 child 下标序列。"""
    def walk(node, path):
        if pred(node):
            return node, path
        for i, ch in enumerate(node.children):
            r = walk(ch, path + [i])
            if r:
                return r
        return None
    return walk(root, [])


def path_of(src, tag, id_=None):
    """在 src 的树里找第一个 tag（可选 id）元素，返回 (target, node)。"""
    from serve import _Tree
    p = _Tree(src)
    p.feed(src)
    r = find_path(p.root, lambda n: n.tag == tag and (id_ is None or n.attr("id") == id_))
    if not r:
        return None, None
    node, path = r
    return {"path": path, "tag": tag, "id": id_ or ""}, node


def main():
    print("== 1. 删除普通元素（含子元素）==")
    target, node = path_of(SRC, "div", "card")
    out, changed = apply_edits(SRC, target, [{"kind": "delete"}])
    check("div#card 整块删除", "id=\"card\"" not in out and "一段说明文字" not in out
          and "src=\"a.png\"" not in out, out)
    check("前后内容保留", "id=\"title\"" in out and "footer" in out)
    check("changed 标记", changed == [{"kind": "delete"}] or changed[-1] == {"kind": "delete"},
          str(changed))

    print("== 2. 删除 void/自闭合元素 ==")
    target, node = path_of(SRC, "img")
    out, _ = apply_edits(SRC, target, [{"kind": "delete"}] * 1)
    check("img 删除", "src=\"a.png\"" not in out, out)
    check("父元素保留", "id=\"card\"" in out)

    print("== 3. 保护：html/body ==")
    target, node = path_of(SRC, "html")
    try:
        apply_edits(SRC, target, [{"kind": "delete"}])
        check("删除 html 被拒绝", False, "竟然成功了")
    except EditError as e:
        # root 的 path=[] 会被 resolve_node 先以 no-path 拒绝——这本身就是保护
        check("删除 html 被拒绝", e.reason in ("no-path", "delete-protected"), str(e))
    target, node = path_of(SRC, "body")
    try:
        apply_edits(SRC, target, [{"kind": "delete"}])
        check("删除 body 被拒绝", False, "竟然成功了")
    except EditError as e:
        check("删除 body 被拒绝", e.reason == "delete-protected", str(e))

    print("== 4. 保护：未闭合元素 ==")
    SRC2 = ("<html><body><div id=\"a\"><span>未闭合<span></div></body></html>")
    target, node = path_of(SRC2, "span")
    try:
        apply_edits(SRC2, target, [{"kind": "delete"}])
        check("未闭合 span 删除被拒绝", False, "竟然成功了")
    except EditError as e:
        check("未闭合 span 删除被拒绝", e.reason == "no-end-tag", str(e))

    print("== 5. 删除后文本内容正确 ==")
    target, node = path_of(SRC, "h1", "title")
    out, _ = apply_edits(SRC, target, [{"kind": "delete"}])
    check("h1#title 删除后不留空标签", "<h1" not in out and "标题" not in out, out)

    print()
    print("结果: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
