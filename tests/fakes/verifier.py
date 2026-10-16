"""Fake resolution checker: approves, unless BRAID_FAKE_VERDICT says otherwise."""
import os

print("Both sides kept.")
print(f"VERDICT: {os.environ.get('BRAID_FAKE_VERDICT', 'approve')}")
