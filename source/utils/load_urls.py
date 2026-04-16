import argparse
from pathlib import Path

def _load_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []

    if args.urls:
        urls.extend(args.urls)

    if args.urls_file:
        urls.extend(Path(args.urls_file).read_text(encoding="utf-8").splitlines())

    return [url.strip() for url in urls if url and url.strip()]