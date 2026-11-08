"""Validate and clean the supplied destination CSV; never edit raw data."""

import argparse
import hashlib
import json
from pathlib import Path
import re

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ["_key", "Desc", "category", "district", "latitude", "longitude"]
TEXT_COLUMNS = COLUMNS[:4]


def normalize_text(value: str) -> str:
    # The source contains literal escaped line breaks as well as ordinary spaces.
    for token in (r"\r\n", r"\n", r"\r"):
        value = value.replace(token, " ")
    return " ".join(value.split())


def clean_dataset(source: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if list(source.columns) != COLUMNS:
        raise ValueError(f"Expected columns in order {COLUMNS}; got {list(source.columns)}")
    if source.empty:
        raise ValueError("Dataset has no records")
    cleaned = source.copy(deep=True)
    for column in TEXT_COLUMNS:
        if cleaned[column].isna().any():
            raise ValueError(f"Missing values in {column}")
        cleaned[column] = cleaned[column].astype(str).map(normalize_text)
        if cleaned[column].eq("").any():
            raise ValueError(f"Empty or whitespace-only values in {column}")
    # Only canonicalize the spelling variant actually observed in this dataset.
    cleaned["district"] = cleaned["district"].replace({"Gilgit−Baltistan": "Gilgit-Baltistan"})
    duplicate_ids = cleaned["_key"].str.casefold().duplicated(keep=False)
    if duplicate_ids.any():
        raise ValueError(f"Duplicate destination identifiers require review: {cleaned.loc[duplicate_ids, '_key'].tolist()}")
    for column, limit in (("latitude", 90), ("longitude", 180)):
        numeric = pd.to_numeric(cleaned[column], errors="coerce")
        valid = numeric.notna() & numeric.between(-limit, limit)
        if not valid.all():
            raise ValueError(f"Invalid {column} for: {cleaned.loc[~valid, '_key'].tolist()}")
        cleaned[column] = numeric
    # Keep attribution in Desc; exclude only parenthesized photo credits from
    # the derived recommendation input. No lowercasing or stemming is needed yet.
    descriptions = cleaned["Desc"].map(
        lambda text: normalize_text(re.sub(r"\(\s*Photo\s+Credit\s*:[^)]*\)", " ", text, flags=re.I))
    )
    cleaned["recommendation_text"] = (
        cleaned["_key"] + " " + cleaned["category"] + " "
        + cleaned["district"] + " " + descriptions
    )
    report = {
        "input_rows": len(source), "output_rows": len(cleaned), "removed_rows": 0,
        "columns": cleaned.columns.tolist(),
        "text_cells_changed": {c: int(source[c].ne(cleaned[c]).sum()) for c in TEXT_COLUMNS},
        "descriptions_with_photo_credits_excluded_from_recommendation_text": int(descriptions.ne(cleaned["Desc"]).sum()),
        "categories": cleaned["category"].value_counts().to_dict(),
        "district_values": cleaned["district"].value_counts().to_dict(),
        "coordinate_ranges": {c: {"min": float(cleaned[c].min()), "max": float(cleaned[c].max())} for c in COLUMNS[4:]},
        "notes": [
            "district contains province/territory-level labels; not verified administrative districts.",
            "Global coordinate bounds validated; locations have not been geocoded or geographically verified.",
            "Badshahi Mosque and Emperor's Mosque appear to describe the same attraction; both retained pending review.",
            "Descriptions contain editorial and potentially dated claims; no factual corrections inferred.",
            "No budgets, costs, user ratings, or supervised labels are available in this dataset.",
        ],
    }
    return cleaned, report


def preprocess(input_path: Path, output_path: Path) -> dict:
    input_path, output_path = input_path.resolve(), output_path.resolve()
    raw_dir = (ROOT / "data" / "raw").resolve()
    if output_path == input_path or output_path.is_relative_to(raw_dir):
        raise ValueError("Output must not overwrite the input or write inside data/raw")
    report_path = output_path.with_suffix(".report.json")
    if report_path == input_path:
        raise ValueError("Report path would overwrite input")
    before = hashlib.sha256(input_path.read_bytes()).hexdigest()
    source = pd.read_csv(input_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    cleaned, report = clean_dataset(source)
    report.update({"source_file": input_path.name, "source_sha256": before})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(output_path, index=False, encoding="utf-8")
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != before:
        raise RuntimeError("Raw file changed during preprocessing")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/destinations_cleaned.csv")
    args = parser.parse_args()
    if args.input is None:
        candidates = sorted((ROOT / "data/raw").glob("*.csv"))
        if len(candidates) != 1:
            parser.error("Provide --input when data/raw does not contain exactly one CSV")
        args.input = candidates[0]
    try:
        report = preprocess(args.input, args.output)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Preprocessing failed: {exc}\n")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
