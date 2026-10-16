"""Fake planner: answers with the plan in $BRAID_FAKE_PLAN, wrapped in chatter like a real model."""
import os

print("Here is the plan:\n```json\n" + os.environ["BRAID_FAKE_PLAN"] + "\n```")
