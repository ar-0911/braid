"""Semantic conflict hints: names one side removed or renamed that the other side still uses.

Text merges can't see these. Agent A renames `load()` to `read()`; agent B adds a new call to `load()` in
another file. Both branches merge cleanly and the result is broken. Here we diff each side against its
merge base, collect the top-level names (functions, classes, methods, module constants) a side made
disappear, and look for them in the lines the other side added. Python is parsed with ast; other
languages use a declaration regex. It's a hint, not a proof, so it is reported as a 'semantic' risk.
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


@lru_cache(maxsize=512)
def removed_names(mb, commit, cwd):
    """{name: file} for names defined at mb that no longer exist anywhere commit changed."""
    changed = gitutil.out("diff", "--name-only", "--no-renames", mb, commit, cwd=cwd).splitlines()
    changed = [f for f in changed if CODE.search(f)]
    before, after = {}, set()
    for f in changed:
        for n in defined_names(f, _show(mb, f, cwd)):
            before.setdefault(n, f)
        after |= defined_names(f, _show(commit, f, cwd))
    gone = {n: f for n, f in before.items() if n not in after}  # moved to another changed file = not removed
    if gone:  # still declared somewhere else in the tree? then uses of it are fine
        rc, found = gitutil.git("grep", "-h", "-o", "-w", "-E",
                                r"(def|class|function|func|fn|struct|interface|type|const|let|var)\s+("
                                + "|".join(map(re.escape, gone)) + ")", commit, "--", cwd=cwd, check=False)
        for line in found.splitlines():
            gone.pop(line.split()[-1].split(":")[-1], None)
    return gone


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
    """[(name, file)] where an added line uses a removed name (and doesn't define it again)."""
    if not removed:
        return []
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(removed))) + r")\b")
    hits = set()
    for f, lines in added.items():
        for line in lines:
            if line.lstrip().startswith(("#", "//", "*")):
                continue
            for m in pattern.finditer(line):
                hits.add((m.group(1), f))
    return sorted(hits)


def broken_uses(base, remover, user, cwd):
    """Names `remover` removed (relative to base) that `user` added new uses of. [(name, file_in_user)]."""
    mb_r = gitutil.out("merge-base", base, remover, cwd=cwd)
    mb_u = gitutil.out("merge-base", base, user, cwd=cwd)
    if not mb_r or not mb_u:
        return []
    return uses(removed_names(mb_r, remover, str(cwd)), added_lines(mb_u, user, str(cwd)))


def describe(hits):
    return [f"{f} uses {n}()" for n, f in hits]
