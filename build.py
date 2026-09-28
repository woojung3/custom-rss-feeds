"""Command-line entry point for the static RSS build."""

import argparse
from pathlib import Path
from rss_service.pipeline import build


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("site"))
    parser.add_argument(
        "--base-url", default="https://woojung3.github.io/custom-rss-feeds"
    )
    args = parser.parse_args()
    return 1 if build(args.output, args.base_url.rstrip("/")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
