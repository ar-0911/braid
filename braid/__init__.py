"""braid: run many coding agents on one repo, and braid their work back together."""
import os
import sys

__version__ = "0.1.0"

# `python -m braid` (how braid starts its watcher, hooks, merge driver and MCP server) puts the current directory
# first on sys.path, and braid runs inside your repo, so a repo file named like a standard module (email.py,
# json.py) would be imported instead of Python's own. braid itself is already found by now, so drop that entry.
if sys.argv[:1] == ["-m"] and sys.path and os.path.abspath(sys.path[0] or os.curdir) == os.getcwd():
    del sys.path[0]
