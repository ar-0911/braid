"""Code-aware three-way merge.

Files are split into top-level entities (functions, classes, imports, ...) keyed by name, and merged
entity by entity. Two branches that add or edit *different* entities in the same file merge cleanly
even when git's line-based merge would report a conflict. Only an entity changed differently on both
sides falls back to a line merge, and only that entity can carry conflict markers. Statements that repeat
a key (reassignments, the same call twice) depend on their order, so when both sides change such a group
the whole file takes a line merge instead.

Python is parsed with `ast`. Brace languages (JS/TS, Go, Rust, Java, C/C++, C#, Swift, Kotlin, PHP)
use a column-0 heuristic, guarded by a bracket-balance check, or, when Spelunk is installed, its tree-sitter
outline (`spelunk outline`), which also splits classes into members. Anything else, or anything that fails to
parse, falls back to `git merge-file`, so the result is never worse than git's.
"""
import ast
import os
import re
import subprocess
import tempfile

PY_EXT = {".py", ".pyi"}
BRACE_EXT = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".kts",
             ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".php", ".scala", ".dart"}
SUPPORTED_EXT = PY_EXT | BRACE_EXT


class Unsupported(Exception):
    pass


class OrderDependent(Unsupported):
    """Both sides changed statements whose order matters; only a line merge is safe."""


# ---------------------------------------------------------------- splitting

def _lines(text):
    return text.splitlines(keepends=True)


def _uniq(chunks):
    """Make keys unique by numbering repeats, in order of appearance."""
    seen, out = {}, []
    for key, text in chunks:
        n = seen.get(key, 0)
        seen[key] = n + 1
        out.append((key if n == 0 else f"{key}#{n}", text))
    return out


def split_python(text):
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise Unsupported(f"python parse error: {e}")
    lines = _lines(text)
    chunks, cursor = _split_stmts(lines, tree.body, 0)
    if cursor < len(lines):
        chunks.append(("<eof>", "".join(lines[cursor:])))
    return _uniq(chunks)


def _stmt_start(node):
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1


def _split_stmts(lines, stmts, cursor):
    """Chunk consecutive statements; leading comments/blank lines belong to the statement that follows."""
    chunks = []
    for node in stmts:
        start, end = _stmt_start(node), node.end_lineno  # 0-based start, exclusive end
        if start < cursor:  # e.g. two statements on one line with ';'
            raise Unsupported("overlapping statements")
        chunks.append((_py_key(node, lines[start:end]), "".join(lines[cursor:end])))
        cursor = end
    return chunks, cursor


def nested_python(text):
    """Split a top-level class chunk into (header, member chunks) so classes merge method by method."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if len(tree.body) != 1 or not classes or not classes[0].body:
        return None
    node, lines = classes[0], _lines(text)
    first = _stmt_start(node.body[0])
    hdr_end = first
    while hdr_end > node.lineno and not lines[hdr_end - 1].strip():  # blank lines go with the first member
        hdr_end -= 1
    chunks, cursor = _split_stmts(lines, node.body, hdr_end)
    if cursor != len(lines):
        return None
    return "".join(lines[:hdr_end]), _uniq(chunks)


def _py_key(node, src_lines):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return f"def:{node.name}"
    if isinstance(node, ast.ClassDef):
        return f"class:{node.name}"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import:" + " ".join("".join(src_lines).split())
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [ast.unparse(t) for t in targets]
        return "assign:" + ",".join(names)
    if isinstance(node, ast.If):
        return "if:" + ast.unparse(node.test)
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        # keyed by what is called, so repeated calls (register(a); register(b)) form one ordered group
        return "call:" + ast.unparse(node.value.func)
    return "stmt:" + " ".join("".join(src_lines).split())


_BRACE_DECL = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:public\s+|private\s+|protected\s+|internal\s+)?"
    r"(?:static\s+|abstract\s+|final\s+|async\s+|unsafe\s+|declare\s+|open\s+|data\s+|sealed\s+)*"
    r"(function\*?|class|interface|type|enum|struct|trait|impl|mod|fn|func|const|let|var|val|object|namespace|record)"
    r"\s+(?:\([^)]*\)\s*)?([A-Za-z_$][\w$]*)")
_IMPORT = re.compile(r"^\s*(import\b|from\s+\S+\s+import\b|#include\b|use\s|require\(|using\s|package\s)")
_CLOSERS = set("}])")
_ASSIGN_OR_CALL = re.compile(r"^([A-Za-z_$][\w$.]*)\s*(\(|(?:[-+*/%&|^]|<<|>>|\?\?)?=(?!=))")


def split_brace(text):
    chunks, cur, cur_key, pending, depth = [], [], None, [], 0
    for line in _lines(text):
        s = line.rstrip("\r\n")
        if depth > 0:  # inside an open block or multi-line statement
            cur.append(line)
            depth += _depth_delta(s)
            continue
        if not s.strip() or s.lstrip().startswith(("//", "/*", "*", "@", "#!")):
            pending.append(line)  # trivia attaches to the next entity
            continue
        if not s[0].isspace() and s[0] not in _CLOSERS:
            if cur:
                chunks.append((cur_key, "".join(cur)))
            cur, cur_key, pending = pending + [line], _brace_key(s), []
        else:
            cur += pending + [line]
            pending = []
        depth += _depth_delta(s)
    if cur:
        chunks.append((cur_key, "".join(cur)))
    if pending:
        chunks.append(("<eof>", "".join(pending)))
    if any(k is None for k, _ in chunks):
        raise Unsupported("content before first entity")
    return _uniq(chunks)


_STRINGS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`[^`]*`|//.*$')


def _depth_delta(line):
    code = _STRINGS.sub("", line)
    return sum(code.count(c) for c in "{([") - sum(code.count(c) for c in "})]")


def _brace_key(line):
    if _IMPORT.match(line):
        return "import:" + " ".join(line.split())
    m = _BRACE_DECL.match(line)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    # Go methods: func (r *T) Name(
    m = re.match(r"^func\s+\(([^)]*)\)\s*([A-Za-z_]\w*)", line)
    if m:
        return f"method:{m.group(1).split()[-1].lstrip('*')}.{m.group(2)}"
    # reassignments and calls are keyed by name, so repeats form one ordered group (see _check_repeats)
    m = _ASSIGN_OR_CALL.match(line)
    if m:
        return f"{'call' if m.group(2) == '(' else 'assign'}:{m.group(1)}"
    return "line:" + " ".join(line.split())


def _balanced(text):
    return all(text.count(o) == text.count(c) for o, c in ("{}", "()", "[]"))


def splitter_for(path):
    """(split, validate, nested) for a path, or Nones when the language isn't supported."""
    ext = os.path.splitext(path)[1].lower()
    if ext in PY_EXT:
        return split_python, _py_valid, nested_python
    if ext in BRACE_EXT:
        return split_brace, _balanced, None
    return None, None, None


def _py_valid(text):
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        return False


# ---------------------------------------------------------------- merging

def line_merge(base, ours, theirs, labels=("ours", "base", "theirs")):
    """git merge-file on three strings. Returns (text, clean)."""
    with tempfile.TemporaryDirectory(prefix="braid-merge-") as d:
        paths = []
        for name, content in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = os.path.join(d, name)
            with open(p, "w", newline="") as f:
                f.write(content)
            paths.append(p)
        args = ["git", "merge-file", "-p"]
        for label in labels:
            args += ["-L", label]
        proc = subprocess.run(args + paths, capture_output=True, text=True)
        if proc.returncode < 0 or proc.returncode > 127:
            raise RuntimeError(f"git merge-file failed: {proc.stderr}")
        return proc.stdout, proc.returncode == 0


_REPEAT = re.compile(r"#\d+$")


def _groups(chunks):
    """{key without its repeat number: (chunk text, ...)} in order of appearance."""
    out = {}
    for key, text in chunks:
        out.setdefault(_REPEAT.sub("", key), []).append(text)
    return {k: tuple(v) for k, v in out.items()}


def _check_repeats(base_chunks, our_chunks, their_chunks):
    """Repeated same-key statements (X = 1; X = X + 1, or the same call twice) depend on their order, and
    numbering them X, X#1, X#2 pairs them up by position, not by meaning. If both sides changed such a group
    differently, merging it entry by entry could silently combine edits git would flag, so give up and let
    the whole file take a line merge."""
    b, o, t = _groups(base_chunks), _groups(our_chunks), _groups(their_chunks)
    for key in set(b) | set(o) | set(t):
        bg, og, tg = b.get(key, ()), o.get(key, ()), t.get(key, ())
        if max(len(bg), len(og), len(tg)) > 1 and og != bg and tg != bg and og != tg:
            raise OrderDependent(f"repeated statements {key} changed on both sides")


def merge_entities(base_chunks, our_chunks, their_chunks, labels, nested=None):
    """Three-way merge of keyed chunk lists. Returns (text, clean, conflicted_keys)."""
    _check_repeats(base_chunks, our_chunks, their_chunks)
    b, o, t = dict(base_chunks), dict(our_chunks), dict(their_chunks)
    result, conflicts = {}, []
    for key in set(b) | set(o) | set(t):
        bv, ov, tv = b.get(key), o.get(key), t.get(key)
        if ov == tv:
            merged = ov
        elif ov == bv:
            merged = tv
        elif tv == bv:
            merged = ov
        elif ov is None or tv is None:
            # one side deleted an entity the other changed: real conflict
            conflicts.append(key)
            merged, _ = line_merge(bv or "", ov or "", tv or "", labels)
        else:
            merged, clean = None, False
            if nested and bv is not None:
                parts = [nested(v) for v in (bv, ov, tv)]
                if all(parts):
                    (bh, bc, bt), (oh, oc, ot), (th, tc, tt) = (p if len(p) == 3 else (*p, "") for p in parts)
                    head, head_clean = _merge_part(bh, oh, th, labels)
                    tail, tail_clean = _merge_part(bt, ot, tt, labels)  # a closing brace, for brace languages
                    body, body_clean, _ = merge_entities(bc, oc, tc, labels)
                    merged = head + (_ensure_newline(body) if tail else body) + tail
                    clean = head_clean and body_clean and tail_clean
            if merged is None:
                merged, clean = line_merge(bv or "", ov, tv, labels)
            if not clean:
                conflicts.append(key)
        if merged is not None:
            result[key] = merged

    # Order: keep our order, then slot their new entities in after their predecessor.
    their_keys = set(t)
    order = [k for k, _ in our_chunks if k in result]
    placed = set(order)
    prev = None
    for k, _ in their_chunks:
        if k in result and k not in placed:
            idx = order.index(prev) + 1 if prev in placed else _first_non_import(order, k)
            # skip past entities only we added there, so ours come first, then theirs
            while idx < len(order) and order[idx] not in their_keys and order[idx] not in b and order[idx] != "<eof>":
                idx += 1
            order.insert(idx, k)
            placed.add(k)
        if k in placed:
            prev = k
    for k, _ in base_chunks:  # entities that only survive from base (cannot happen, kept for safety)
        if k in result and k not in placed:
            order.append(k)
            placed.add(k)
    # <eof> trivia always last
    if "<eof>" in order:
        order.remove("<eof>")
        order.append("<eof>")
    text = "".join(_ensure_newline(result[k]) if i < len(order) - 1 else result[k]
                   for i, k in enumerate(order))
    return text, not conflicts, conflicts


def _merge_part(base, ours, theirs, labels):
    if ours == theirs or theirs == base:
        return ours, True
    if ours == base:
        return theirs, True
    return line_merge(base, ours, theirs, labels)


def _first_non_import(order, key):
    if key.startswith("import:"):
        return 0
    return 0 if not order else len(order) if order[-1] != "<eof>" else len(order) - 1


def _ensure_newline(s):
    return s if s.endswith("\n") or not s else s + "\n"


def merge_text(base, ours, theirs, path, labels=("ours", "base", "theirs"), outline=None):
    """Merge three versions of `path`. Returns (text, clean, how) where how is 'structural' or 'line'.

    `outline(texts, path)`, when given, parses brace languages with a real parser (Spelunk's tree-sitter)
    instead of the column-0 heuristic; see split_outline."""
    split, valid, nested = splitter_for(path)
    if outline and split is split_brace:
        try:
            text, clean = _merge_outlined(base, ours, theirs, path, labels, outline)
            return text, clean, "structural"
        except OrderDependent:
            split = None  # the heuristic would only see less; go straight to git's line merge
        except Unsupported:
            pass  # not parsed cleanly, or the result doesn't parse: try the heuristic, then git
    if split is not None:
        try:
            text, clean, _ = merge_entities(split(base), split(ours), split(theirs), labels, nested)
            if not clean or valid(text):
                return text, clean, "structural"
        except Unsupported:
            pass
    text, clean = line_merge(base, ours, theirs, labels)
    return text, clean, "line"


# ---------------------------------------------------------------- outlines from a real parser

def _outline_key(item, src_lines):
    kind, name = item.get("kind", ""), item.get("name")
    if name is not None:
        return f"{kind}:{name}"
    text = " ".join("".join(src_lines).split())
    if "import" in kind or "include" in kind or kind in ("use_declaration", "package_clause", "package_declaration"):
        return "import:" + text
    return "stmt:" + text


def split_outline(text, items):
    """Chunks from a parser's outline: [{kind, name?, start, end, members?}] with 1-based inclusive lines.

    Returns (chunks, nested) where nested maps a class chunk's text to (header, member chunks, closing lines),
    so merge_entities can merge classes member by member. Lines between entities go with the next one."""
    lines, chunks, nested, cursor = _lines(text), [], {}, 0
    for item in items:
        start, end = int(item["start"]) - 1, int(item["end"])
        if start < cursor or end > len(lines):
            raise Unsupported("overlapping entities")  # e.g. two statements on one line
        chunk = "".join(lines[cursor:end])
        chunks.append((_outline_key(item, lines[start:end]), chunk))
        members = item.get("members")
        if members is not None:
            parts = _split_members(lines, cursor, start, end, members)
            if parts:
                nested[chunk] = parts
        cursor = end
    if cursor < len(lines):
        chunks.append(("<eof>", "".join(lines[cursor:])))
    return _uniq(chunks), nested


def _split_members(lines, cursor, start, end, members):
    """(header, member chunks, closing lines) for one class, or None when the members share its first or last
    line (`class A { m() {} }`), where splitting by line can't work."""
    if members:
        first, last = int(members[0]["start"]) - 1, int(members[-1]["end"])
        if first <= start or last >= end:
            return None
    else:  # an empty body: everything but the closing line is the header
        if end - start < 2 or not lines[end - 1].lstrip().startswith("}"):
            return None
        first = last = end - 1
    hdr_end = first
    while hdr_end > start + 1 and not lines[hdr_end - 1].strip():  # blank lines go with the first member
        hdr_end -= 1
    chunks, mcur = [], hdr_end
    for m in members:
        ms, me = int(m["start"]) - 1, int(m["end"])
        if ms < mcur:
            return None
        chunks.append((_outline_key(m, lines[ms:me]), "".join(lines[mcur:me])))
        mcur = me
    return "".join(lines[cursor:hdr_end]), _uniq(chunks), "".join(lines[last:end])


def _merge_outlined(base, ours, theirs, path, labels, outline):
    files = outline([base, ours, theirs], path)
    if not files or len(files) != 3 or not all(f.get("ok") for f in files):
        raise Unsupported("no clean outline")
    (bc, bn), (oc, on), (tc, tn) = (split_outline(t, f.get("items") or []) for t, f in zip((base, ours, theirs), files))
    nested = {**bn, **on, **tn}
    text, clean, _ = merge_entities(bc, oc, tc, labels, nested.get)
    if clean:
        check = outline([text], path)
        if not check or not check[0].get("ok"):
            raise Unsupported("merged result doesn't parse")
    return text, clean


def driver_main(base_path, ours_path, theirs_path, path, marker_size=None, outline=None):
    """Entry point for git's merge driver protocol: write result into ours_path; exit 0 clean, 1 conflict."""
    def read(p):
        with open(p, newline="") as f:
            return f.read()
    try:
        base, ours, theirs = read(base_path), read(ours_path), read(theirs_path)
    except UnicodeDecodeError:
        # binary: let git's own logic report it
        return 1
    text, clean, _ = merge_text(base, ours, theirs, path, outline=outline)
    with open(ours_path, "w", newline="") as f:
        f.write(text)
    return 0 if clean else 1
