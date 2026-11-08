r"""Inspect a real dataset without assuming destination columns or labels.

Usage (from the project root):
    .venv\Scripts\python.exe backend\inspect_dataset.py
    .venv\Scripts\python.exe backend\inspect_dataset.py data\raw\destinations.csv

With no path, inspect supported files under data/raw. This script only reads data.
Excel and Parquet support requires the appropriate optional pandas dependencies.
"""

import argparse
from pathlib import Path
import sys

import pandas as pd


RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
SUPPORTED = {".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".xls", ".parquet"}


def read_dataset(path: Path, encoding: str) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",", encoding=encoding)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl", encoding=encoding)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)  # First sheet only.
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported file extension: {suffix}")


def inspect_dataset(path: Path, encoding: str) -> None:
    frame = read_dataset(path, encoding)
    print(f"\nFile: {path.resolve()}")
    print(f"Rows: {len(frame):,}")
    print(f"Columns ({len(frame.columns)}): {frame.columns.tolist()}")
    if path.suffix.lower() in {".xlsx", ".xls"}:
        print("Scope: first worksheet only")
    print("\nColumn types and missing values (as parsed by pandas):")
    summary = pd.DataFrame({
        "dtype": frame.dtypes.astype(str),
        "missing_count": frame.isna().sum(),
        "missing_percent": frame.isna().mean().mul(100).round(2),
    })
    print(summary.to_string())
    print(f"\nRows with any missing value: {int(frame.isna().any(axis=1).sum()):,}")
    try:
        print(f"Exact duplicate rows beyond first occurrence: {int(frame.duplicated().sum()):,}")
        print(f"Rows belonging to duplicate groups: {int(frame.duplicated(keep=False).sum()):,}")
    except TypeError as exc:
        print(f"Duplicate check unavailable for nested/unhashable values: {exc}")
    print("No data was modified. Blank-looking strings may need separate review.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, help="Path to a real dataset file")
    parser.add_argument("--encoding", default="utf-8", help="Text encoding (default: utf-8)")
    args = parser.parse_args()
    paths = [args.path] if args.path else sorted(
        path for path in RAW_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED
    )
    if not paths:
        print(f"No supported dataset found in {RAW_DIR}. Supply a real dataset; none was generated.")
        return 1
    failed = False
    for path in paths:
        try:
            inspect_dataset(path, args.encoding)
        except Exception as exc:
            print(f"Could not inspect {path}: {exc}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
