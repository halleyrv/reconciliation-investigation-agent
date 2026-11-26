"""``recon-ingest-corpus``: stores a directory of Markdown policies (one document per file,
keyed by its file name) as versioned, chunked and embedded documents."""

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from recon.knowledge.application.ingest_corpus import IngestCorpus
from recon.knowledge.domain.document import DocumentKind, InvalidDocument


def run(argv: Sequence[str] | None, ingest: Callable[[], IngestCorpus]) -> int:
    """Exit codes: 0 the corpus is stored, 2 nothing was ingested."""
    parser = argparse.ArgumentParser(prog="recon-ingest-corpus", description=__doc__)
    parser.add_argument("directory", type=Path, help="directory of policy .md files")
    parser.add_argument(
        "--effective-from",
        type=date.fromisoformat,
        default=date.today(),
        help="date a new version takes effect (YYYY-MM-DD; default: today)",
    )
    args = parser.parse_args(argv)
    files = sorted(args.directory.glob("*.md"))
    try:
        if not files:
            raise FileNotFoundError(f"no .md documents in {args.directory}")
        texts = [(path.stem, path.read_text(encoding="utf-8")) for path in files]
        results = ingest()(texts, DocumentKind.POLICY, args.effective_from)
    except (InvalidDocument, OSError, UnicodeDecodeError) as exc:
        print(f"recon-ingest-corpus: nothing ingested: {exc}", file=sys.stderr)
        return 2
    for result in results:
        print(
            f"{result.key}: version {result.version}, {'stored' if result.changed else 'unchanged'}"
        )
    return 0
