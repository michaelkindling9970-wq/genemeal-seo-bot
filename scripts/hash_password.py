#!/usr/bin/env python3
"""Hash a password from an environment variable and print only the hash.

Usage:
    python scripts/hash_password.py ENV_VAR_NAME

Reads the password from the named environment variable and writes a
PBKDF2-SHA256 hash to stdout. The plaintext is never printed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seo_bot.auth import hash_console_password  # noqa: E402

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: python scripts/hash_password.py ENV_VAR_NAME", file=sys.stderr)
        return 2
    name = args[0]
    if not _ENV_NAME.match(name):
        print("Invalid environment variable name.", file=sys.stderr)
        return 2
    import os

    password = os.environ.get(name)
    if not password:
        print(f"Environment variable {name} is missing or empty.", file=sys.stderr)
        return 1
    print(hash_console_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
