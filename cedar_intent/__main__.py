"""Module entrypoint for ``python -m cedar_intent``."""

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
