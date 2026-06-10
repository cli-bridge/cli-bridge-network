"""CBN process entrypoint.

Keep this file thin. Domain logic belongs in importable packages so the CLI,
daemon, tests, and future protocol exports can share the same runtime.
"""

from cbn.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

