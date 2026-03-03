# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
#!/usr/bin/env python3
"""Pre-commit hook: verify every Python file begins with the copyright header."""

import sys
from pathlib import Path

COPYRIGHT_HEADER = "# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved."

def main() -> int:
    files = sys.argv[1:]
    if not files:
        return 0

    missing = []
    for filepath in files:
        path = Path(filepath)
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if not content.startswith(COPYRIGHT_HEADER):
            missing.append(filepath)

    if missing:
        print("ERROR: Missing copyright header in the following files:")
        for f in missing:
            print(f"  {f}")
        print(f"\nAdd this as the first line of each file:")
        print(f"  {COPYRIGHT_HEADER}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
