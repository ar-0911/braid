"""Fake resolver: keeps both sides of every conflict block (ours, then theirs)."""
import re
import subprocess
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "both"
files = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True).stdout.split()
block = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)
for f in files:
    if mode == "fail":
        continue
    text = open(f).read()
    if mode == "break":
        text = block.sub("raise SystemExit('broken')\n", text)
    else:
        text = block.sub(lambda m: m.group(1) + m.group(2), text)
    open(f, "w").write(text)
print("kept both sides of each conflict")
