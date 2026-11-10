"""``recon-import``: an operator imports one simulator export directory."""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from recon.ingestion.adapters.outbound.simulator_files import ExportUnreadable, read_export
from recon.ingestion.application.import_export import ImportExport, ManifestMismatch


def run(argv: Sequence[str] | None, import_export: Callable[[], ImportExport]) -> int:
    """Exit codes: 0 every file completed, 1 some file was rejected, 2 nothing was imported."""
    parser = argparse.ArgumentParser(
        prog="recon-import",
        description="Import a simulator export directory (manifest.json plus one JSON per type).",
    )
    parser.add_argument("directory", type=Path, help="simulator output directory")
    args = parser.parse_args(argv)
    try:
        batches = import_export()(read_export(args.directory))
    except (ManifestMismatch, ExportUnreadable, OSError) as exc:
        print(f"recon-import: nothing imported: {exc}", file=sys.stderr)
        return 2
    for batch in batches:
        if batch.status == "completed":
            print(f"{batch.file_name}: completed, {batch.row_count} records")
        else:
            print(f"{batch.file_name}: {batch.status}")
            for error in batch.errors:
                print(f"  line {error.line_no}, {error.field}: {error.message}")
    return 0 if all(b.status == "completed" for b in batches) else 1
