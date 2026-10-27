"""Fake planner: answers with the plan in $BRAID_FAKE_PLAN, wrapped in chatter like a real model.

With $BRAID_FAKE_PROMPT_LOG set, the prompt it was given is written there."""
import os
import sys

if os.environ.get("BRAID_FAKE_PROMPT_LOG"):
    with open(os.environ["BRAID_FAKE_PROMPT_LOG"], "w") as f:
        f.write(" ".join(sys.argv[1:]))
print("Here is the plan:\n```json\n" + os.environ["BRAID_FAKE_PLAN"] + "\n```")
