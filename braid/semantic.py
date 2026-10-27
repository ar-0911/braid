"""Semantic conflict hints: names one side removed or renamed that the other side still uses.

Text merges can't see these. Agent A renames `load()` to `read()`; agent B adds a new call to `load()` in
another file. Both branches merge cleanly and the result is broken. Here we diff each side against its
merge base, collect the top-level names (functions, classes, methods, module constants) a side made
disappear, and look for them in the lines the other side added. Python is parsed with ast; other
languages use a declaration regex. It's a hint, not a proof, so it is reported as a 'semantic' risk.

With Spelunk installed (see spelunk.py) definitions come from its tree-sitter parsers instead, in every language
it reads, with their signatures. That adds a second kind of hint: a function whose parameters one side changed
while the other side's new code calls it.
"""
import ast
import re
from functools import lru_cache

from . import gitutil

CODE = re.compile(r"\.(py|js|jsx|mjs|cjs|ts|tsx|go|rs|java|kt|kts|c|h|cc|cpp|hpp|cs|swift|php|scala|dart|rb)$")
DECL = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:public\s+|private\s+|protected\s+|static\s+|"
    r"abstract\s+|final\s+|async\s+)*(?:def|class|function|func|fn|interface|struct|enum|trait|type|module)\s+"
    r"(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s+)?(?:function|\()", re.M)
MIN_LEN = 3


def _python_names(text):
    tree = ast.parse(text)
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if isinstance(node, ast.ClassDef):  # methods too, but not short generic ones like get or run
                names |= {n.name for n in node.body
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(n.name) >= 5}
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def defined_names(path, text):
    if not text:
        return set()
    names = None
    if path.endswith(".py"):
        try:
            names = _python_names(text)
        except SyntaxError:
            pass
    if names is None:
        names = {m.group(1) or m.group(2) for m in DECL.finditer(text)}
    return {n for n in names if len(n) >= MIN_LEN and not (n.startswith("__") and n.endswith("__"))}


def _show(rev, path, cwd):
    rc, text = gitutil.git("show", f"{rev}:{path}", cwd=cwd, check=False)
    return text if rc == 0 else ""


DEFINES = {"function", "method", "class", "struct", "enum", "trait", "interface", "type", "module", "constant"}


def _spelunk_facts(parser, rev, paths, cwd):
    """{path: facts} from Spelunk for the files it could parse at rev (files missing at rev are left out)."""
    files = {}
    for f in paths:
        rc, oid = gitutil.git("rev-parse", "--verify", "--quiet", f"{rev}:{f}", cwd=cwd, check=False)
        if rc == 0 and oid.strip():
            files[(f, oid.strip())] = _show(rev, f, cwd)
    return {k[0]: v for k, v in parser.facts(files).items() if v}


def _defs(rev, paths, cwd, parser=None):
    """{path: {name: signature}} for the files at rev; the signature is "" when only braid parsed it."""
    got = _spelunk_facts(parser, rev, paths, cwd) if parser else {}
    out = {}
    for f in paths:
        facts = got.get(f)
        if facts is None:
            out[f] = dict.fromkeys(defined_names(f, _show(rev, f, cwd)), "")
            continue
        names = {}
        for sym in facts.get("symbols", []):
            n = sym.get("name") or ""
            if sym.get("kind") not in DEFINES or len(n) < MIN_LEN or (n.startswith("__") and n.endswith("__")):
                continue
            if sym.get("parent") and len(n) < 5:  # methods too, but not short generic ones like get or run
                continue
            names.setdefault(n, sym.get("signature") or "")
        out[f] = names
    return out


def arity(signature, name):
    """(required, total) parameters from a declaration's first line, or None when it can't tell."""
    at = signature.find(name)
    start = signature.find("(", at + len(name) if at >= 0 else 0)
    if start < 0:
        return None
    depth, cur, parts = 0, "", []
    for ch in signature[start + 1:]:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                parts.append(cur)
                break
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    else:
        return None  # the parameters go on past the first line
    params = [p.strip() for p in parts if p.strip()]
    params = [p for p in params if p not in ("self", "cls", "this", "&self", "&mut self", "mut self", "/")]
    if any(p.startswith(("*", "...")) or "..." in p for p in params):
        return None  # variadic: any number of arguments may still fit
    required = sum(1 for p in params if "=" not in p and "?" not in p.split(":")[0])
    return required, len(params)


@lru_cache(maxsize=512)
def changed_signatures(mb, commit, cwd, parser=None):
    """{name: file} for functions commit kept but whose parameters it changed (needs Spelunk)."""
    if parser is None:
        return {}
    changed = [f for f in gitutil.out("diff", "--name-only", "--no-renames", mb, commit, cwd=cwd).splitlines()
               if CODE.search(f)]
    before, after = _defs(mb, changed, cwd, parser), _defs(commit, changed, cwd, parser)
    out = {}
    for f in changed:
        for n, sig in before.get(f, {}).items():
            new = after.get(f, {}).get(n)
            if not sig or not new or new == sig:
                continue
            a, b = arity(sig, n), arity(new, n)
            if a and b and (a[0] != b[0] or b[1] < a[1]):
                out[n] = f
    return out


@lru_cache(maxsize=512)
def added_calls(mb, commit, cwd, parser):
    """{file: {name, ...}} for calls in the lines commit added, from Spelunk's call sites."""
    diff = gitutil.out("diff", "-U0", "--no-renames", "--no-color", mb, commit, cwd=cwd)
    lines, cur = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") and CODE.search(line) else None
        elif cur and line.startswith("@@"):
            m = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                lines.setdefault(cur, set()).update(range(start, start + count))
    facts = _spelunk_facts(parser, commit, sorted(lines), cwd)
    out = {}
    for f, added in lines.items():
        for ref, ln in (facts.get(f) or {}).get("callSites", []):
            if ln in added:
                out.setdefault(f, set()).add(ref.rsplit(".", 1)[-1])
    return out


@lru_cache(maxsize=512)
def removed_names(mb, commit, cwd, parser=None):
    """{name: file} for names defined at mb that no longer exist anywhere commit changed."""
    changed = gitutil.out("diff", "--name-only", "--no-renames", mb, commit, cwd=cwd).splitlines()
    changed = [f for f in changed if CODE.search(f)]
    before, after = {}, set()
    defs_before, defs_after = _defs(mb, changed, cwd, parser), _defs(commit, changed, cwd, parser)
    for f in changed:
        for n in defs_before.get(f, {}):
            before.setdefault(n, f)
        after |= set(defs_after.get(f, {}))
    gone = {n: f for n, f in before.items() if n not in after}  # moved to another changed file = not removed
    declared = _declared(gone, commit, cwd)  # still declared somewhere else in the tree? then uses are fine
    return {n: f for n, f in gone.items() if n not in declared}


def _declared(names, commit, cwd):
    """The subset of names that something in commit's tree declares."""
    if not names:
        return set()
    rc, found = gitutil.git("grep", "-h", "-o", "-w", "-E",
                            r"(def|class|function|func|fn|struct|interface|type|const|let|var)\s+("
                            + "|".join(map(re.escape, names)) + ")", commit, "--", cwd=cwd, check=False)
    return {line.split()[-1].split(":")[-1] for line in found.splitlines()}


@lru_cache(maxsize=512)
def added_lines(mb, commit, cwd):
    """{file: [added line, ...]} for code files changed between mb and commit."""
    diff = gitutil.out("diff", "-U0", "--no-renames", "--no-color", mb, commit, cwd=cwd)
    out, cur = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
            if cur and not CODE.search(cur):
                cur = None
        elif cur and line.startswith("+") and not line.startswith("+++"):
            out.setdefault(cur, []).append(line[1:])
    return out


def uses(removed, added):
    """[(name, file, "removed")] where an added line uses a removed name (and doesn't define it again)."""
    if not removed:
        return []
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(removed))) + r")\b")
    hits = set()
    for f, lines in added.items():
        for line in lines:
            if line.lstrip().startswith(("#", "//", "*")):
                continue
            for m in pattern.finditer(line):
                hits.add((m.group(1), f, "removed"))
    return sorted(hits)


def hits_between(mb_r, remover, mb_u, user, cwd, parser=None):
    """What `remover` (since mb_r) breaks in the code `user` added (since mb_u): [(name, file_in_user, how)].

    how is "removed" (the name is gone) or "signature" (its parameters changed and user calls it)."""
    cwd = str(cwd)
    found = uses(removed_names(mb_r, remover, cwd, parser), added_lines(mb_u, user, cwd))
    changed = changed_signatures(mb_r, remover, cwd, parser)
    if changed:
        for f, names in added_calls(mb_u, user, cwd, parser).items():
            found += [(n, f, "signature") for n in sorted(names & set(changed))]
    return sorted(set(found))


def broken_uses(base, remover, user, cwd, parser=None):
    """Names `remover` removed or changed (relative to base) that `user` added new uses of."""
    mb_r = gitutil.out("merge-base", base, remover, cwd=cwd)
    mb_u = gitutil.out("merge-base", base, user, cwd=cwd)
    if not mb_r or not mb_u:
        return []
    return hits_between(mb_r, remover, mb_u, user, cwd, parser)


def merge_breaks(mb, ours, theirs, merged, cwd):
    """[(name, file)] where one side's new code uses a name the other side removed, and the merged commit
    still has that use and declares the name nowhere. Used by the landing queue on the real merge result."""
    cwd = str(cwd)
    hits = set(uses(removed_names(mb, theirs, cwd), added_lines(mb, ours, cwd)))
    hits |= set(uses(removed_names(mb, ours, cwd), added_lines(mb, theirs, cwd)))
    if not hits:
        return []
    declared = _declared({n for n, _ in hits}, merged, cwd)
    return sorted((n, f) for n, f in hits
                  if n not in declared and re.search(rf"\b{re.escape(n)}\b", _show(merged, f, cwd)))


def describe(hits):
    return [f"{f} calls {n}(), whose parameters changed" if how == "signature" else f"{f} uses {n}()"
            for n, f, how in hits]
