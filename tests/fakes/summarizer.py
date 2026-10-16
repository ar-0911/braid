"""Fake summary model: answers the approval prompt with fixed JSON."""
import json
import sys

assert "approval summary" in sys.argv[1]
print("Sure, here it is:")
print(json.dumps({"title": "Make a() return ten", "summary": "a() now returns 10 instead of 1.",
                  "impact": "Anything calling a() gets 10.", "risk": "medium",
                  "files": {"m.py": "changes the return value of a()"}}))
