"""Entry point for ``python -m tempo_cli`` and the ``tempo`` console script."""

from __future__ import annotations

import sys

from tempo_cli.cli import run


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":  # pragma: no cover
    main()
