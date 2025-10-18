#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SJTU Sports CLI entrypoint."""
from sja_booking.cli import build_parser, run_cli


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        return
    run_cli(args)


if __name__ == "__main__":
    main()
