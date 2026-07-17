"""Punto de entrada de la interfaz de línea de comandos de Nox."""

import argparse

from nox_agent import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nox",
        description="Nox Agent",
    )
    parser.add_argument(
        "--version",
        "--v",
        action="version",
        version=f"Nox {__version__}",
        help="Muestra la versión instalada y termina.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
