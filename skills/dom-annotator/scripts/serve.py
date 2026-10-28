#!/usr/bin/env python3
"""dom-annotator 本地启动器 —— 一条命令把目录装进标注页。

用法::

    python3 serve.py [--dir DIR] [--entry index.html] [--port 0] [--open|--no-open]

它做三件事：

1. 把本 skill 的 ``annotator.html`` 挂到 ``/__da__/``
2. 把目标目录挂到 ``/``（相对 / 绝对路径都按生产环境解析，
   ``type="module"`` 脚本和页面里的 ``fetch()`` 也能正常工作）
3. 提供 ``/__da__/info``、``/__da__/events``(SSE 文件变化)、
   ``/__da__/save``(POST 写回 ``.dom-annotator/annotations.json``)

只监听 127.0.0.1，不对外暴露；不写任何文件到目标目录，除非收到保存请求。

退出：Ctrl-C（agent 侧用终止进程即可）。
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SKIP_DIRS = {".git", ".svn", "node_modules", "__pycache__", ".idea", ".dom-annotator"}
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ANNOTATOR = os.path.join(SKILL_DIR, "annotator.html")

MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".md": "text/markdown; charset=utf-8",
    ".woff2": "font/woff2",
    ".wasm": "application/wasm",
}

ROOT = "."
ENTRY = "index.html"
WATCHING = True
WRITE_MODE = "inline"  # inline | suggest

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
STYLE_ALLOW = {
    "color", "background-color", "background", "border-color",
    "font-size", "font-weight", "font-style", "font-family", "line-height",
    "text-decoration", "text-decoration-line", "text-decoration-style",
    "text-decoration-color", "text-decoration-thickness",
    "width", "height", "max-width", "min-width", "max-height", "min-height",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "border-radius", "border-width", "border-style", "border",
    "gap", "display", "visibility", "opacity", "text-align", "letter-spacing",
}

# 请求体大小上限（防误提交超大 JSON）
MAX_BODY = 5 * 1024 * 1024

# 与 html.parser 的 attrfind_tolerant 语义对齐的属性名 / 无引号值 token
_ATTR_NAME_RE = re.compile(r"[^\s\"'\u0060=<>/]+")
_ATTR_VALUE_RE = re.compile(r"[^\s\"'\u0060=<>]+")

# 源文件改写串行化（读-改-写原子化），避免并发 apply 互相覆盖
APPLY_LOCK = threading.Lock()

# SSE 文件监听：单个后台线程统一扫描，所有连接经 Condition 广播变化
_sse_cond = threading.Condition()
_sse_gen = 0
_sse_running = False


class EditError(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


class Node:
    __slots__ = ("tag", "start", "close", "self_closing", "attrs", "attr_spans",
                 "children", "parent", "runs", "end")

    def __init__(self, tag, start, close, self_closing, attrs, attr_spans, parent):
        self.tag = tag
        self.start = start
        self.close = close
        self.self_closing = self_closing
        self.attrs = attrs
        self.attr_spans = attr_spans
        self.children = []
        self.parent = parent
        self.runs = []          # 直接文本片段 [(start, end, raw)]
        self.end = None         # 结束标签 '>' 之后的位置；无显式结束标签则为 None

    def attr(self, name, default=""):
        return self.attrs.get(name, default)

    def insert_pos(self):
        return self.close - 1 if self.self_closing else self.close

    def delete_span(self):
        """删除整个元素需要的源区间 [start, end)；无法安全删除时抛 EditError。"""
        if self.tag in ("html", "body"):
            raise EditError("delete-protected", "不能直接删除 <html>/<body> 根元素")
        if self.self_closing or self.tag in VOID_TAGS:
            return self.start, self.close + 1
        if self.end is None:
            raise EditError("no-end-tag",
                            "源文件里该元素没有显式结束标签（未闭合），无法安全删除整块内容")
        return self.start, self.end

    def text_span(self):
        """元素只含文本时返回合并后的区间，否则 None。"""
        if self.children or not self.runs:
            return None
        runs = sorted(self.runs)
        start, end = runs[0][0], runs[0][1]
        for s, e, _ in runs[1:]:
            if s != end:
                return None
            end = e
        return start, end


class _Tree(HTMLParser):
    def __init__(self, src: str):
        super().__init__(convert_charrefs=False)
        self.src = src
        self.offsets = [0]
        for line in src.split("\n"):
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.root = None
        self.stack = []

    def _pos(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def _tag_close(self, start):
        i, quote = start, None
        while i < len(self.src):
            ch = self.src[i]
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == ">":
                return i
            i += 1
        return len(self.src) - 1

    def _attr_spans(self, start, close, attrs):
        """定位起始标签内各属性的值区间。

        支持带引号 / 无引号 / 无值（布尔）三种属性写法；属性名按 HTMLParser
        规则转为小写，并以属性名 token 为单位匹配，避免 ``id`` 误中
        ``data-id``、``src`` 误中 ``srcset`` 之类的前缀/后缀碰撞。
        布尔属性（无 ``=``）的区间覆盖整个属性名，替换后得到 ``name="value"``。
        """
        frag = self.src[start:close + 1]
        spans = {}
        n = len(frag)
        i = 0
        # 跳过起始标签名（第一个 token）
        m = _ATTR_NAME_RE.match(frag, 1)
        if m:
            i = 1 + m.end()
        while i < n:
            ch = frag[i]
            if ch.isspace() or ch in "/>":
                i += 1
                continue
            m = _ATTR_NAME_RE.match(frag, i)
            if not m:
                i += 1
                continue
            raw = m.group(0)
            name = raw.lower()
            name_end = i + len(raw)
            if name not in spans:
                j = name_end
                while j < n and frag[j].isspace():
                    j += 1
                if j < n and frag[j] == "=":
                    j += 1
                    while j < n and frag[j].isspace():
                        j += 1
                    if j < n and frag[j] in "\"'":
                        q = frag[j]
                        end = frag.find(q, j + 1)
                        if end == -1:
                            end = n - 1
                        spans[name] = (start + j + 1, start + end)
                        i = end + 1
                        continue
                    if j < n:
                        vm = _ATTR_VALUE_RE.match(frag, j)
                        if vm:
                            spans[name] = (start + j, start + vm.end())
                            i = vm.end()
                            continue
                        # 空值 ``name=``：区间覆盖 ``name=``，标记 bare，替换为 name="value"
                        spans[name] = (start + i, start + j, True)
                        i = j
                        continue
                else:
                    # 无值布尔属性：区间 = 属性名 token，第三位标记 bare
                    spans[name] = (start + i, start + name_end, True)
            i = max(name_end, i + 1)
        return spans

    def _open(self, tag, attrs, self_closing):
        start = self._pos()
        close = self._tag_close(start)
        amap = {}
        for k, v in attrs:
            if k not in amap:
                amap[k] = v if v is not None else ""
        node = Node(tag, start, close, self_closing, amap,
                    self._attr_spans(start, close, amap),
                    self.stack[-1] if self.stack else None)
        if node.parent is not None:
            node.parent.children.append(node)
        elif self.root is None:
            self.root = node
        if not self_closing and tag not in VOID_TAGS:
            self.stack.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, True)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                node = self.stack[i]
                start = self._pos()
                end = self._tag_close(start)
                node.end = end + 1
                del self.stack[i:]
                return

    def _record_text(self, length):
        if not self.stack:
            return
        node = self.stack[-1]
        start = self._pos()
        node.runs.append((start, start + length, self.src[start:start + length]))

    def handle_data(self, data):
        self._record_text(len(data))

    def handle_entityref(self, name):
        self._record_text(len(name) + 2)

    def handle_charref(self, name):
        self._record_text(len(name) + 3)


def escape_attr(value: str) -> str:
    return (value.replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def parse_style(raw: str):
    out = []
    for part in (raw or "").split(";"):
        if ":" not in part:
            continue
        prop, _, val = part.partition(":")
        prop = prop.strip()
        val = val.strip()
        if not prop or not val:
            continue
        important = val.endswith("!important")
        if important:
            val = val[: -len("!important")].strip()
        out.append([prop.lower(), val, important])
    return out


def serialize_style(pairs) -> str:
    return "; ".join("%s: %s%s" % (p, v, " !important" if imp else "") for p, v, imp in pairs)


def set_style(pairs, prop, value, important):
    prop = prop.strip().lower()
    if prop not in STYLE_ALLOW:
        raise EditError("style-not-allowed", "不支持的样式属性：%s" % prop)
    value = str(value).strip()
    if value.lower().endswith("!important"):
        value = value[:-len("!important")].strip()
        important = True
    if any(ch in value for ch in ";}{"):
        raise EditError("bad-value", "样式值非法：%r" % value)
    for item in pairs:
        if item[0] == prop:
            item[1] = value
            item[2] = important
            return
    pairs.append([prop, value, important])


def resolve_node(root, target):
    if root is None:
        raise EditError("empty-source", "源文件没有可解析的 HTML 结构")
    path = target.get("path")
    if not isinstance(path, list) or not path:
        raise EditError("no-path", "缺少元素路径")
    node = root
    if node.tag != "html":
        # 源文件片段（没有 <html>），浏览器会补全，路径必然错位
        raise EditError("fragment-source", "源文件不是完整 HTML（缺少 <html>），暂不支持直接写入")
    for idx in path:
        if not isinstance(idx, int) or idx < 0 or idx >= len(node.children):
            raise EditError("path-mismatch", "元素路径在源文件中不存在")
        node = node.children[idx]
    if target.get("tag") and node.tag != target["tag"]:
        raise EditError("path-mismatch",
                        "路径对应的标签不一致（源=%s，页面=%s）" % (node.tag, target["tag"]))
    if target.get("id") and node.attr("id") != target["id"]:
        raise EditError("path-mismatch", "路径对应的 id 不一致")
    return node


def apply_edits(src: str, target: dict, edits: list):
    parser = _Tree(src)
    parser.feed(src)
    node = resolve_node(parser.root, target)

    ops = []
    insert_attrs = []
    style_pairs = None
    changed = []

    for edit in edits:
        kind = edit.get("kind")
        if kind == "text":
            span = node.text_span()
            if span is None:
                raise EditError("text-not-editable",
                                "该元素含子元素或文本被实体/注释打断，无法安全替换文本")
            ops.append((span[0], span[1], html.escape(str(edit.get("value", "")), quote=False)))
            changed.append({"kind": "text"})
        elif kind == "style":
            if style_pairs is None:
                style_pairs = parse_style(node.attr("style"))
            set_style(style_pairs, str(edit.get("property", "")),
                      str(edit.get("value", "")), bool(edit.get("important")))
            changed.append({"kind": "style", "property": edit.get("property")})
        elif kind == "attr":
            name = str(edit.get("name", "")).strip().lower()
            if not re.fullmatch(r"[a-z][a-z0-9:-]*", name):
                raise EditError("bad-attr", "属性名非法：%s" % name)
            value = str(edit.get("value", ""))
            span = node.attr_spans.get(name)
            if span:
                if len(span) == 3:
                    # 无值/空值布尔属性：区间覆盖属性名（或 name=），
                    # 直接写成 name="value"，避免产生重复属性
                    ops.append((span[0], span[1], '%s="%s"' % (name, escape_attr(value))))
                else:
                    ops.append((span[0], span[1], escape_attr(value)))
            else:
                insert_attrs.append((name, value))
            changed.append({"kind": "attr", "name": name})
        elif kind == "delete":
            dstart, dend = node.delete_span()
            ops.append((dstart, dend, ""))
            changed.append({"kind": "delete"})
        else:
            raise EditError("bad-edit", "未知的修改类型：%r" % kind)

    if style_pairs is not None:
        value = serialize_style(style_pairs)
        span = node.attr_spans.get("style")
        if span:
            ops.append((span[0], span[1], escape_attr(value)))
        else:
            insert_attrs.insert(0, ("style", value))

    if insert_attrs:
        ins = "".join(' %s="%s"' % (n, escape_attr(v)) for n, v in insert_attrs)
        pos = node.insert_pos()
        ops.append((pos, pos, ins))

    if not ops:
        raise EditError("no-op", "没有可执行的修改")

    ops.sort(key=lambda op: (op[0], op[1]), reverse=True)
    out = src
    for start, end, repl in ops:
        out = out[:start] + repl + out[end:]
    return out, changed


def backup_file(rel: str, full: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak_dir = os.path.join(ROOT, ".dom-annotator", "backup")
    os.makedirs(bak_dir, exist_ok=True)
    name = rel.replace("/", "__") + "." + stamp
    dst = os.path.join(bak_dir, name + os.path.splitext(full)[1])
    shutil.copy2(full, dst)
    files = sorted(f for f in os.listdir(bak_dir) if f.startswith(rel.replace("/", "__")))
    for old in files[:-50]:
        try:
            os.remove(os.path.join(bak_dir, old))
        except OSError:
            pass
    return os.path.relpath(dst, ROOT)


def list_html(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for fn in filenames:
            if fn.lower().endswith((".html", ".htm", ".xhtml")):
                rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
                # 排除标注页自身（按文件名，兼容拷贝副本）：把 skill 目录或含
                # annotator.html 的目录当目标目录时，避免入口/站内链接加载出
                # 「annotator 嵌套 annotator」
                if os.path.basename(fn).lower() == "annotator.html":
                    continue
                out.append(rel)
    out.sort(key=lambda p: (0 if os.path.basename(p).lower().startswith("index.") else 1, p))
    return out


def scan(root: str) -> dict[str, tuple[int, int]]:
    sig = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
                sig[os.path.relpath(p, root)] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
    return sig


class Handler(BaseHTTPRequestHandler):
    server_version = "dom-annotator/0.3"

    # ---- helpers -------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return True
        name = host.split(":", 1)[0].strip().lower().strip("[]")
        return name in ("127.0.0.1", "localhost", "::1")

    def log_message(self, fmt, *args):  # 静默，避免污染 agent 的终端
        if os.environ.get("DA_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- routes --------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            self._error(403, "forbidden host")
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path in ("/__da__", "/__da__/"):
            self._serve_tool()
            return
        if path == "/__da__/annotator.html":
            self._serve_tool()
            return
        if path == "/__da__/info":
            self._json({
                "ok": True,
                "root": os.path.abspath(ROOT),
                "name": os.path.basename(os.path.abspath(ROOT)),
                "entry": ENTRY,
                "entries": list_html(ROOT),
                "writeMode": WRITE_MODE,
                "version": "0.6",
            })
            return
        if path == "/__da__/files":
            self._list_files(urllib.parse.parse_qs(parsed.query))
            return
        if path == "/__da__/events":
            self._serve_events()
            return

        self._serve_static(path)

    def do_POST(self):
        if not self._host_ok():
            self._error(403, "forbidden host")
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/__da__/apply":
            self._apply_edits()
            return
        if parsed.path != "/__da__/save":
            self._error(404, "not found")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._error(413, "payload too large")
            return
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._error(400, "invalid json: %s" % exc)
            return
        if not isinstance(data, dict) or data.get("schemaVersion") != "dom-feedback-1":
            self._error(400, "expected dom-feedback-1 payload")
            return

        out_dir = os.path.join(ROOT, ".dom-annotator")
        try:
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "annotations.json")
            tmp = out_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, out_path)
        except OSError as exc:
            self._error(500, "write failed: %s" % exc)
            return

        self._json({
            "ok": True,
            "path": os.path.relpath(out_path, ROOT),
            "absolute": out_path,
            "annotations": len(data.get("annotations") or []),
        })

    # ---- handlers ------------------------------------------------
    def _serve_tool(self) -> None:
        try:
            with open(ANNOTATOR, "rb") as fh:
                body = fh.read()
        except OSError as exc:
            self._error(500, "annotator.html missing: %s" % exc)
            return
        self._send(200, body, MIME_OVERRIDES[".html"])

    def _serve_static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        rel = os.path.normpath(rel)
        if rel.startswith("..") or os.path.isabs(rel):
            self._error(403, "forbidden")
            return
        full = os.path.join(ROOT, rel)
        # 目标目录里若恰好有 annotator.html（把 skill 目录当目标目录，或目录里
        # 拷贝了标注页副本），静态服务不暴露它，避免 iframe/站内链接加载出嵌套标注页
        if os.path.basename(full).lower() == "annotator.html":
            self._error(404, "not found: %s" % rel)
            return
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            self._error(404, "not found: %s" % rel)
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME_OVERRIDES.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
        try:
            with open(full, "rb") as fh:
                body = fh.read()
        except OSError as exc:
            self._error(500, str(exc))
            return
        self._send(200, body, ctype)

    def _list_files(self, query) -> None:
        kind = (query.get("type") or ["image"])[0]
        if kind == "image":
            exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".ico", ".bmp"}
        else:
            exts = {".html", ".htm", ".xhtml"}
        out = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in exts:
                    out.append(os.path.relpath(os.path.join(dirpath, fn), ROOT).replace(os.sep, "/"))
        out.sort()
        self._json({"ok": True, "type": kind, "files": out[:500]})

    def _apply_edits(self) -> None:
        if WRITE_MODE != "inline":
            self._json({"ok": False, "reason": "write-disabled",
                        "error": "服务以 --write-mode=suggest 启动，未开启直接写入"}, 409)
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._error(413, "payload too large")
            return
        raw = self.rfile.read(length) if length else b""
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._error(400, "invalid json: %s" % exc)
            return

        rel = os.path.normpath(str(req.get("page") or "").lstrip("/"))
        if not rel or rel.startswith("..") or os.path.isabs(rel):
            self._error(400, "bad page path")
            return
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            self._error(404, "page not found: %s" % rel)
            return
        if os.path.splitext(full)[1].lower() not in (".html", ".htm", ".xhtml"):
            self._error(400, "not an html file")
            return

        with APPLY_LOCK:
            try:
                with open(full, encoding="utf-8") as fh:
                    src = fh.read()
            except UnicodeDecodeError:
                self._error(422, "source is not valid utf-8")
                return
            except OSError as exc:
                self._error(500, str(exc))
                return

            try:
                new_src, changed = apply_edits(src, req.get("target") or {}, req.get("edits") or [])
            except EditError as exc:
                self._json({"ok": False, "reason": exc.reason, "error": exc.message}, 422)
                return

            if new_src == src:
                self._json({"ok": True, "changed": [], "backup": "", "note": "源文件无需改动"})
                return

            try:
                bak = backup_file(rel.replace(os.sep, "/"), full)
                tmp = full + ".da-tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(new_src)
                os.replace(tmp, full)
            except OSError as exc:
                self._error(500, "write failed: %s" % exc)
                return

        self._json({
            "ok": True,
            "page": rel.replace(os.sep, "/"),
            "backup": bak,
            "changed": changed,
            "bytes": len(new_src),
        })

    def _serve_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        try:
            self.wfile.write(b"retry: 1500\n\n")
            self.wfile.flush()
        except OSError:
            return

        # 每个连接不各自扫描目录：由共享的 _sse_watcher_loop 统一扫描并广播
        start_sse_watcher()
        with _sse_cond:
            seen = _sse_gen
        last_beat = time.time()
        try:
            while WATCHING:
                with _sse_cond:
                    gen = _sse_gen
                    _sse_cond.wait(timeout=0.7)
                if gen != seen:
                    seen = gen
                    self.wfile.write(b"data: change\n\n")
                    self.wfile.flush()
                    last_beat = time.time()
                elif time.time() - last_beat > 15:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_beat = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def start_sse_watcher() -> None:
    """启动共享文件监听线程：每个进程只扫一遍目录，SSE 连接共享其结果。"""
    global _sse_running
    with _sse_cond:
        if _sse_running:
            return
        _sse_running = True
        threading.Thread(target=_sse_watcher_loop, daemon=True,
                         name="da-sse-watcher").start()


def stop_sse_watcher() -> None:
    global _sse_running
    with _sse_cond:
        _sse_running = False


def _sse_watcher_loop() -> None:
    global _sse_gen
    last = None
    while True:
        with _sse_cond:
            if not _sse_running:
                return
        cur = scan(ROOT)
        with _sse_cond:
            if cur != last:
                last = cur
                _sse_gen += 1
                _sse_cond.notify_all()
        time.sleep(0.7)


def pick_port(preferred: int) -> int:
    if preferred:
        return preferred
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    global ROOT, ENTRY, WATCHING, WRITE_MODE

    ap = argparse.ArgumentParser(description="dom-annotator 本地启动器")
    ap.add_argument("--dir", default=".", help="要标注的站点根目录（默认当前目录）")
    ap.add_argument("--entry", default="", help="入口 HTML（默认 index.html 或首个 html）")
    ap.add_argument("--port", type=int, default=0, help="端口（0 = 自动选）")
    ap.add_argument("--write-mode", choices=("inline", "suggest"), default="inline",
                    help="inline=页面可直接改写源文件；suggest=只收集建议")
    ap.add_argument("--open", dest="open_browser", action="store_true", default=True,
                    help="自动打开浏览器（默认开）")
    ap.add_argument("--no-open", dest="open_browser", action="store_false")
    args = ap.parse_args()

    WRITE_MODE = args.write_mode

    ROOT = os.path.abspath(args.dir)
    if not os.path.isdir(ROOT):
        sys.stderr.write("目录不存在：%s\n" % ROOT)
        return 2
    if not os.path.isfile(ANNOTATOR):
        sys.stderr.write("找不到 annotator.html：%s\n" % ANNOTATOR)
        return 2

    pages = list_html(ROOT)
    if args.entry:
        ENTRY = args.entry.lstrip("/").replace(os.sep, "/")
    elif pages:
        ENTRY = pages[0]
    else:
        ENTRY = ""

    port = pick_port(args.port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/__da__/" % port

    print("dom-annotator 已启动")
    print("  目录：%s" % ROOT)
    print("  入口：%s" % (ENTRY or "(未找到 html)"))
    print("  页面：%s" % url)
    print("  停止：Ctrl-C")
    sys.stdout.flush()

    if args.open_browser:
        threading.Thread(target=lambda: (time.sleep(0.4), webbrowser.open(url)), daemon=True).start()

    try:
        httpd.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        WATCHING = False
        stop_sse_watcher()
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
