#!/usr/bin/env python3
"""Weekly leadership audit (spec sections 27-28).

Re-verifies every OFFICES hint against live Wikipedia infoboxes, forcing
a fresh check (bypasses the day-to-day cache). Prints a status table and
exits non-zero on any mismatch, so a scheduled workflow can raise a
[bot-alert] issue when an office changes hands.

Usage:
  python scripts/refresh_leaders.py
"""
import json
import os
import sys

# Force fresh checks regardless of LEADERSHIP_MAX_AGE_DAYS.
os.environ["LEADERSHIP_MAX_AGE_DAYS"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import post_bot as b  # noqa: E402

bad = []
print(f"{'office':8} {'holder (hint)':24} {'verified':9} actual")
for key in sorted(b.OFFICES):
    page, hint, _field = b.OFFICES[key]
    try:
        ok = b.office_verified(key)
    except Exception as ex:  # never crash the audit
        ok = False
        print(f"ERROR {key}: {ex}")
    try:
        actual = (b._leadership_cache().get(key) or {}).get("actual", "?")
    except Exception:
        actual = "?"
    print(f"{key:8} {hint:24} {'YES' if ok else 'NO!':9} {actual}")
    if not ok:
        bad.append(key)

if bad:
    print(f"\nMISMATCH: {', '.join(bad)} — update OFFICES hints in "
          f"post_bot.py after confirming via an authoritative source.")
    sys.exit(1)
print("\nAll office hints verified fresh.")
