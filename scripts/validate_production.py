#!/usr/bin/env python3
"""Validate that the VREYC runtime environment is safe for vreyc.com production."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PRODUCTION_SITE_URL, settings


def main() -> int:
    errors = settings.production_validation_errors()
    if errors:
        print("Production validation failed for VREYC:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Production validation passed for {PRODUCTION_SITE_URL}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
