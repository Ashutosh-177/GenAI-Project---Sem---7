"""Reproduces the exact bug a real user hit: a near-empty scope brief ("Test")
caused the drafting engine to copy real facts (a building name, a city) out
of an unrelated reference document. Verifies: (1) that input is now rejected
outright, and (2) a legitimate short-but-real brief doesn't leak reference
entities into the output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generation.drafting import DraftSession, _expand_scope_of_work

print("=== Case 1: reproduce the exact reported bug ('Test' as brief) ===")
session = DraftSession()
accepted, error = session.answer("scope_of_work_brief", "Test")
print(f"Accepted: {accepted}")
print(f"Error shown to user: {error}")
assert not accepted, "BUG NOT FIXED: 'Test' was accepted as a valid scope brief"

print("\n=== Case 2: legitimate short brief should still work, no leakage ===")
brief = "annual IT helpdesk support for QCI's Delhi office"
result = _expand_scope_of_work(brief)
print(f"Brief: {brief}")
print(f"Generated: {result}")
suspicious = [term for term in ["sameer", "kolkata", "sec-v", "sec 5"] if term in result.lower()]
if suspicious:
    print(f"FAIL — leaked reference-document terms found: {suspicious}")
else:
    print("PASS — no leaked reference-document terms found")
