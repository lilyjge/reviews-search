from __future__ import annotations

import sys
from pathlib import Path

# QuackIR lives in vendor/ until published to PyPI
_VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "quackir"
if _VENDOR.exists() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from quackir import IndexType  # noqa: E402
from quackir.index import DuckDBIndexer  # noqa: E402

from reviews_search.config import CORPUS_TABLE


def build_fts_index(db_path: Path, corpus_jsonl: Path | None = None) -> int:
    """
    (Re)build the QuackIR sparse FTS index in the shared DuckDB file.
    If corpus_jsonl is provided, load from file; otherwise caller must have
  populated the reviews table and exported JSONL separately.
    """
    if corpus_jsonl is None:
        raise ValueError("corpus_jsonl path is required")

    indexer = DuckDBIndexer(db_path=str(db_path))
    indexer.init_table(CORPUS_TABLE, IndexType.SPARSE)
    indexer.load_table(CORPUS_TABLE, str(corpus_jsonl), IndexType.SPARSE)
    indexer.fts_index(CORPUS_TABLE)
    count = indexer.get_num_rows(CORPUS_TABLE)
    indexer.close()
    return count
