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

    def test_unknown_extension_uses_line_merge(self):
        _, clean, how = merge_text("a\n", "b\n", "c\n", "notes.txt")
        self.assertFalse(clean)
        self.assertEqual(how, "line")


if __name__ == "__main__":
    unittest.main()
