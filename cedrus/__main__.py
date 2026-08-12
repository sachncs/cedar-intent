"""Module entrypoint for ``python -m cedrus``.

Routes the module-invocation form of the CLI through the standard
:func:`cedrus.cli.main` entry point. Kept as a separate module so the
package can be both imported (``import cedrus``) and executed
(``python -m cedrus``) without pulling CLI argparse into casual
importers.

See Also:
    :mod:`cedrus.cli`: Argument parsing and subcommand dispatch.
"""

from __future__ import annotations

from cedrus.cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())