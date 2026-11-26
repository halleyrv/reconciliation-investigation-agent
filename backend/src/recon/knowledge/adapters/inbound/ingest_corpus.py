"""``recon-ingest-corpus``: stores a directory of Markdown policies (one document per file,
keyed by its file name) as versioned, chunked and embedded documents."""

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from recon.knowledge.application.ingest_corpus import IngestCorpus
from recon.knowledge.domain.document import DocumentKind, InvalidDocument


def _nothing_ingested(exc: Exception) -> int:
    print(f"recon-ingest-corpus: nothing ingested: {exc}", file=sys.stderr)
    return 2


def run(argv: Sequence[str] | None, ingest: Callable[[], IngestCorpus]) -> int:
    """Exit codes: 0 the corpus is stored, 2 nothing was ingested, 3 the model or the store
    failed. Each document is stored in its own transaction, so after a 3 the documents stored
    before the failure stay; re-running skips them and stores the rest."""
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
    except (OSError, UnicodeDecodeError) as exc:
        return _nothing_ingested(exc)
    try:
        results = ingest()(texts, DocumentKind.POLICY, args.effective_from)
    except InvalidDocument as exc:  # raised before any document is stored
        return _nothing_ingested(exc)
    except OSError as exc:  # a model download, a network or a disk failure
        print(
            f"recon-ingest-corpus: ingest failed: {exc};"
            " documents stored before the failure stay, re-run to finish",
            file=sys.stderr,
        )
        return 3
    for result in results:
        print(
            f"{result.key}: version {result.version}, {'stored' if result.changed else 'unchanged'}"
        )
    return 0
