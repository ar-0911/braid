import json
import os
import shutil
import subprocess
import unittest

import helpers  # noqa: F401  (sets sys.path)
from braid.structmerge import merge_text

PY_BASE = "import os\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n"


class PythonMerge(unittest.TestCase):
    def test_both_append_functions_and_imports(self):
        ours = PY_BASE.replace("import os\n", "import os\nimport sys\n") + "\n\ndef login():\n    return 'in'\n"
        theirs = PY_BASE.replace("import os\n", "import os\nimport json\n") + "\n\ndef export():\n    return 'csv'\n"
        text, clean, how = merge_text(PY_BASE, ours, theirs, "m.py")
        self.assertTrue(clean)
        self.assertEqual(how, "structural")
        self.assertEqual(text, "import os\nimport sys\nimport json\n\n\ndef a():\n    return 1\n\n\ndef b():\n"
                               "    return 2\n\n\ndef login():\n    return 'in'\n\n\ndef export():\n"
                               "    return 'csv'\n")

    def test_edits_to_different_functions(self):
        text, clean, _ = merge_text(PY_BASE, PY_BASE.replace("return 1", "return 10"),
                                    PY_BASE.replace("return 2", "return 20"), "m.py")
        self.assertTrue(clean)
        self.assertIn("return 10", text)
        self.assertIn("return 20", text)

    def test_same_function_changed_both_ways_conflicts_only_there(self):
        text, clean, _ = merge_text(PY_BASE, PY_BASE.replace("return 1", "return 10"),
                                    PY_BASE.replace("return 1", "return 100") + "\n\ndef c():\n    return 3\n",
                                    "m.py")
        self.assertFalse(clean)
        self.assertIn("<<<<<<< ours\n    return 10\n=======\n    return 100\n>>>>>>> theirs", text)
        self.assertIn("def c():", text)  # the clean part still merged

    def test_one_side_deletes_function_other_unchanged(self):
        ours = PY_BASE.replace("\n\ndef b():\n    return 2\n", "")
        text, clean, _ = merge_text(PY_BASE, ours, PY_BASE.replace("return 1", "return 5"), "m.py")
        self.assertTrue(clean)
        self.assertNotIn("def b", text)
        self.assertIn("return 5", text)

    def test_delete_vs_modify_conflicts(self):
        ours = PY_BASE.replace("\n\ndef b():\n    return 2\n", "")
        _, clean, _ = merge_text(PY_BASE, ours, PY_BASE.replace("return 2", "return 9"), "m.py")
        self.assertFalse(clean)

    def test_class_and_decorators(self):
        base = "class A:\n    x = 1\n\n\n@dec\ndef f():\n    pass\n"
        ours = base.replace("x = 1", "x = 2")
        theirs = base.replace("    pass", "    return 1")
        text, clean, _ = merge_text(base, ours, theirs, "m.py")
        self.assertTrue(clean)
        self.assertEqual(text, "class A:\n    x = 2\n\n\n@dec\ndef f():\n    return 1\n")

    def test_both_add_methods_to_same_class(self):
        # the exact case two real agents hit: both added a test method to the same TestCase
        base = "import unittest\n\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
        ours = base.replace("from calc import add", "from calc import add, subtract") + "\n    def test_sub(self):\n        self.assertEqual(subtract(5, 3), 2)\n"
        theirs = base + "\n    def test_mul(self):\n        self.assertEqual(1, 1)\n"
        text, clean, _ = merge_text(base, ours, theirs, "t.py")
        self.assertTrue(clean, text)
        self.assertLess(text.index("def test_add"), text.index("def test_sub"))
        self.assertLess(text.index("def test_sub"), text.index("def test_mul"))
        self.assertIn("from calc import add, subtract", text)

    def test_same_method_changed_both_ways_still_conflicts(self):
        base = "class A:\n    def f(self):\n        return 1\n\n    def g(self):\n        return 2\n"
        text, clean, _ = merge_text(base, base.replace("return 1", "return 10"),
                                    base.replace("return 1", "return 100").replace("return 2", "return 20"), "a.py")
        self.assertFalse(clean)
        self.assertIn("return 20", text)

    def test_repeated_assignment_changed_on_both_sides_conflicts(self):
        # order-dependent: entry-by-entry merging would keep both and report clean; git flags it
        base = "X = 1\nX = X + 1\n"
        text, clean, how = merge_text(base, base + "X = X * 10\n", "X = 1\nX = X + 5\n", "m.py")
        self.assertFalse(clean)
        self.assertEqual(how, "line")
        self.assertIn("<<<<<<<", text)

    def test_repeated_calls_changed_on_both_sides_conflict(self):
        base = "setup()\nregister('a')\nregister('b')\n"
        ours = base.replace("register('b')", "register('b', fast=True)")
        theirs = base + "register('c')\n"
        _, clean, _ = merge_text(base, ours, theirs, "m.py")
        self.assertFalse(clean)

    def test_repeated_group_changed_on_one_side_still_merges_structurally(self):
        base = "X = 1\nX = X + 1\n\n\ndef a():\n    return 1\n"
        ours = base.replace("X = X + 1", "X = X + 5")
        theirs = base.replace("return 1", "return 2")
        text, clean, how = merge_text(base, ours, theirs, "m.py")
        self.assertTrue(clean)
        self.assertEqual(how, "structural")
        self.assertEqual(text, "X = 1\nX = X + 5\n\n\ndef a():\n    return 2\n")

    def test_same_change_to_repeated_group_on_both_sides_is_clean(self):
        base = "X = 1\nX = X + 1\n"
        ours = theirs = base + "X = X * 10\n"
        text, clean, _ = merge_text(base, ours, theirs, "m.py")
        self.assertTrue(clean)
        self.assertEqual(text, ours)

    def test_repeated_class_attribute_changed_on_both_sides_conflicts(self):
        base = "class A:\n    x = 1\n    x = x + 1\n"
        _, clean, _ = merge_text(base, base + "    x = x * 10\n", base.replace("x + 1", "x + 5"), "m.py")
        self.assertFalse(clean)

    def test_syntax_error_falls_back_to_line_merge(self):
        bad = "def (:\n"
        _, _, how = merge_text(bad, bad + "x\n", bad, "m.py")
        self.assertEqual(how, "line")


class BraceMerge(unittest.TestCase):
    BASE = "import a from 'a';\n\nfunction f() {\n  return 1;\n}\n"

    def test_ts_both_add(self):
        ours = self.BASE + "\nfunction g() {\n  return 2;\n}\n"
        theirs = (self.BASE.replace("import a from 'a';", "import a from 'a';\nimport b from 'b';")
                  + "\nexport const h = () => {\n  return 3;\n};\n")
        text, clean, how = merge_text(self.BASE, ours, theirs, "x.ts")
        self.assertTrue(clean)
        self.assertEqual(how, "structural")
        self.assertEqual(text.count("import"), 2)
        self.assertLess(text.index("function g"), text.index("export const h"))

    def test_go_methods(self):
        base = "package x\n\nfunc (s *S) A() int {\n\treturn 1\n}\n\nfunc (s *S) B() int {\n\treturn 2\n}\n"
        text, clean, _ = merge_text(base, base.replace("return 1", "return 10"),
                                    base.replace("return 2", "return 20"), "x.go")
        self.assertTrue(clean)
        self.assertIn("return 10", text)
        self.assertIn("return 20", text)

    def test_repeated_assignment_changed_on_both_sides_conflicts(self):
        base = "X = 1;\nX = X + 1;\n"
        _, clean, how = merge_text(base, base + "X = X * 10;\n", "X = 1;\nX = X + 5;\n", "m.js")
        self.assertFalse(clean)
        self.assertEqual(how, "line")

    def test_repeated_calls_changed_on_both_sides_conflict(self):
        base = "app.use(a);\napp.use(b);\n"
        _, clean, _ = merge_text(base, base.replace("use(b)", "use(b, opts)"), base + "app.use(c);\n", "m.js")
        self.assertFalse(clean)

    def test_unknown_extension_uses_line_merge(self):
        _, clean, how = merge_text("a\n", "b\n", "c\n", "notes.txt")
        self.assertFalse(clean)
        self.assertEqual(how, "line")


def cls(start, end, *members, name="Store"):
    return {"kind": "class_declaration", "name": name, "start": start, "end": end,
            "members": [{"kind": "method_definition", "name": n, "start": a, "end": b} for n, a, b in members]}


def fake_outline(table, calls=None):
    """An outline function like Spelunk's, from hand-written outlines; unknown texts (merge results) parse fine."""
    def outline(texts, path):
        if calls is not None:
            calls.append(len(texts))
        return [{"path": path, "ok": True, "items": table.get(t, [])} for t in texts]
    return outline


class OutlineMerge(unittest.TestCase):
    """Brace languages split by a real parser's outline (Spelunk's tree-sitter) instead of the heuristic."""
    BASE = "class Store {\n  save(x) {\n    return x;\n  }\n}\n"
    OURS = "class Store {\n  save(x) {\n    return x;\n  }\n\n  load() {\n    return 1;\n  }\n}\n"
    THEIRS = "class Store {\n  save(x) {\n    return x;\n  }\n\n  remove() {\n    return 2;\n  }\n}\n"
    TABLE = {BASE: [cls(1, 5, ("save", 2, 4))],
             OURS: [cls(1, 9, ("save", 2, 4), ("load", 6, 8))],
             THEIRS: [cls(1, 9, ("save", 2, 4), ("remove", 6, 8))]}

    def test_two_methods_added_to_same_js_class_merge_cleanly(self):
        calls = []
        text, clean, how = merge_text(self.BASE, self.OURS, self.THEIRS, "store.js",
                                      outline=fake_outline(self.TABLE, calls))
        self.assertTrue(clean, text)
        self.assertEqual(how, "structural")
        self.assertEqual(text, "class Store {\n  save(x) {\n    return x;\n  }\n\n  load() {\n    return 1;\n  }\n"
                               "\n  remove() {\n    return 2;\n  }\n}\n")
        self.assertEqual(calls, [3, 1])  # one call for the three versions, one to check the result parses

    def test_without_spelunk_the_heuristic_still_conflicts(self):
        _, clean, _ = merge_text(self.BASE, self.OURS, self.THEIRS, "store.js")
        self.assertFalse(clean)

    def test_same_method_changed_both_ways_conflicts_only_there(self):
        ours = self.OURS.replace("return x;", "return x + 1;")
        theirs = self.THEIRS.replace("return x;", "return x * 2;")
        table = {**self.TABLE, ours: self.TABLE[self.OURS], theirs: self.TABLE[self.THEIRS]}
        text, clean, _ = merge_text(self.BASE, ours, theirs, "store.js", outline=fake_outline(table))
        self.assertFalse(clean)
        self.assertIn("<<<<<<< ours\n    return x + 1;\n=======\n    return x * 2;\n>>>>>>> theirs", text)
        self.assertIn("load()", text)
        self.assertIn("remove()", text)

    def test_empty_class_gets_methods_from_both_sides(self):
        base = "class Store {\n}\n"
        ours = "class Store {\n  load() {}\n}\n"
        theirs = "class Store {\n  remove() {}\n}\n"
        table = {base: [cls(1, 2)], ours: [cls(1, 3, ("load", 2, 2))], theirs: [cls(1, 3, ("remove", 2, 2))]}
        text, clean, _ = merge_text(base, ours, theirs, "store.ts", outline=fake_outline(table))
        self.assertTrue(clean, text)
        self.assertEqual(text, "class Store {\n  load() {}\n  remove() {}\n}\n")

    def test_outline_failure_falls_back(self):
        for outline in (lambda texts, path: None,
                        lambda texts, path: [{"ok": False, "items": []}] * len(texts)):
            _, clean, _ = merge_text(self.BASE, self.OURS, self.THEIRS, "store.js", outline=outline)
            self.assertFalse(clean)  # the heuristic's answer, as without Spelunk

    def test_result_that_does_not_parse_falls_back(self):
        def outline(texts, path):
            return [{"ok": len(texts) == 3, "items": self.TABLE.get(t, [])} for t in texts]
        _, clean, how = merge_text(self.BASE, self.OURS, self.THEIRS, "store.js", outline=outline)
        self.assertFalse(clean)

    def test_python_keeps_using_ast(self):
        calls = []
        merge_text(PY_BASE, PY_BASE + "x = 1\n", PY_BASE + "y = 2\n", "m.py", outline=fake_outline({}, calls))
        self.assertEqual(calls, [])


SPELUNK = os.environ.get("BRAID_TEST_SPELUNK") or shutil.which("spelunk")


@unittest.skipUnless(SPELUNK, "needs Spelunk (set BRAID_TEST_SPELUNK to its command)")
class RealSpelunkOutline(unittest.TestCase):
    """The same merges with the real `spelunk outline`, when it is installed."""

    def outline(self, texts, path):
        req = json.dumps({"files": [{"path": path, "text": t} for t in texts]})
        out = subprocess.run([*SPELUNK.split(), "outline"], input=req, capture_output=True, text=True, check=True)
        return json.loads(out.stdout)["files"]

    def test_js_class_methods_from_both_sides(self):
        base = "import a from 'a';\n\nexport class Store extends Base {\n  count = 0;\n\n  save(x) {\n    return x;\n  }\n}\n"
        ours = base.replace("    return x;\n  }\n", "    return x;\n  }\n\n  load() {\n    return 1;\n  }\n")
        theirs = base.replace("    return x;\n  }\n", "    return x;\n  }\n\n  /** Removes. */\n  remove() {\n    return 2;\n  }\n")
        text, clean, how = merge_text(base, ours, theirs, "src/store.js", outline=self.outline)
        self.assertTrue(clean, text)
        self.assertLess(text.index("load()"), text.index("/** Removes. */"))
        self.assertLess(text.index("remove()"), text.rindex("}"))

    def test_ts_and_java_and_rust(self):
        cases = {
            "a.ts": ("export class C {\n  a(): void {}\n}\n", "  b(): void {}\n", "  @dec()\n  c(): void {}\n"),
            "A.java": ("class A {\n  void a() {}\n}\n", "  void b() {}\n", "  @Override\n  public String toString() { return \"\"; }\n"),
            "s.rs": ("impl S {\n    fn a(&self) {}\n}\n", "    fn b(&self) {}\n", "    fn c(&self) {}\n"),
        }
        for path, (base, add_o, add_t) in cases.items():
            at = base.index("\n", base.index("\n") + 1) + 1  # after the first member
            text, clean, how = merge_text(base, base[:at] + add_o + base[at:], base[:at] + add_t + base[at:], path,
                                          outline=self.outline)
            self.assertTrue(clean, (path, text))
            self.assertIn(add_o, text)
            self.assertIn(add_t, text)

    def test_repeated_calls_changed_on_both_sides_conflict(self):
        base = "register('a');\nregister('b');\n"
        _, clean, _ = merge_text(base, base.replace("'b'", "'b', true"), base + "register('c');\n", "r.js",
                                 outline=self.outline)
        self.assertFalse(clean)


if __name__ == "__main__":
    unittest.main()
