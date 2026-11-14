#!/usr/bin/env python3
"""Emit descriptive data facts for scientific-analysis specification work.

The profiler intentionally does not choose cleaning, transformation, or modeling
methods. Its JSON output distinguishes a complete scan from a bounded sample so
downstream reasoning cannot silently treat sample facts as whole-file facts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable

import pandas as pd


SUPPORTED_FORMATS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".parquet": "parquet",
}


def _validate_columns(available: Iterable[str], requested: list[str] | None) -> None:
    if not requested:
        return
    available_set = set(available)
    missing = [column for column in requested if column not in available_set]
    if missing:
        raise ValueError(f"Requested columns not found: {', '.join(missing)}")


def _read_delimited(
    path: Path,
    separator: str,
    columns: list[str] | None,
    sample_rows: int,
    full_scan: bool,
) -> tuple[pd.DataFrame, bool]:
    header = pd.read_csv(path, sep=separator, nrows=0)
    _validate_columns(header.columns, columns)
    if full_scan:
        return pd.read_csv(path, sep=separator, usecols=columns), True

    frame = pd.read_csv(path, sep=separator, usecols=columns, nrows=sample_rows + 1)
    complete_file = len(frame) <= sample_rows
    return frame.iloc[:sample_rows].copy(), complete_file


def _read_parquet(
    path: Path,
    columns: list[str] | None,
    sample_rows: int,
    full_scan: bool,
) -> tuple[pd.DataFrame, bool]:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise RuntimeError(
            "Parquet profiling requires pyarrow. Install it in the selected project runtime."
        ) from exc

    parquet_file = parquet.ParquetFile(path)
    available = parquet_file.schema_arrow.names
    _validate_columns(available, columns)
    if full_scan:
        return parquet_file.read(columns=columns).to_pandas(), True

    batches: list[pd.DataFrame] = []
    rows_collected = 0
    target_rows = sample_rows + 1
    for batch in parquet_file.iter_batches(batch_size=target_rows, columns=columns):
        batch_frame = batch.to_pandas()
        batches.append(batch_frame)
        rows_collected += len(batch_frame)
        if rows_collected >= target_rows:
            break

    if batches:
        frame = pd.concat(batches, ignore_index=True).iloc[:target_rows]
    else:
        selected_columns = columns if columns is not None else available
        frame = pd.DataFrame(columns=selected_columns)
    complete_file = parquet_file.metadata.num_rows <= sample_rows
    return frame.iloc[:sample_rows].copy(), complete_file


def _number(value: Any) -> int | float | None:
    if pd.isna(value):
        return None
    if isinstance(value, int):
        return int(value)
    return float(value)


def _column_facts(series: pd.Series) -> dict[str, Any]:
    total = len(series)
    missing_count = int(series.isna().sum())
    non_null = series.dropna()
    facts: dict[str, Any] = {
        "dtype": str(series.dtype),
        "non_null_count": int(len(non_null)),
        "missing_count": missing_count,
        "missing_pct": round((missing_count / total * 100.0) if total else 0.0, 3),
        "unique_count": int(non_null.nunique(dropna=True)),
        "is_constant": bool(len(non_null) > 0 and non_null.nunique(dropna=True) <= 1),
    }

    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if len(numeric):
            quantiles = numeric.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
            facts["numeric_summary"] = {
                "min": _number(numeric.min()),
                "p01": _number(quantiles.loc[0.01]),
                "p05": _number(quantiles.loc[0.05]),
                "p25": _number(quantiles.loc[0.25]),
                "median": _number(quantiles.loc[0.5]),
                "p75": _number(quantiles.loc[0.75]),
                "p95": _number(quantiles.loc[0.95]),
                "p99": _number(quantiles.loc[0.99]),
                "max": _number(numeric.max()),
                "mean": _number(numeric.mean()),
                "std": _number(numeric.std(ddof=1)) if len(numeric) > 1 else None,
            }
    return facts


def profile_file(
    path: str | Path,
    columns: list[str] | None = None,
    sample_rows: int = 100_000,
    full_scan: bool = False,
) -> dict[str, Any]:
    """Profile a supported local data file and return JSON-serializable facts."""
    data_path = Path(path)
    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")
    if sample_rows < 1:
        raise ValueError("sample_rows must be at least 1")

    data_format = SUPPORTED_FORMATS.get(data_path.suffix.lower())
    if data_format is None:
        raise ValueError(
            f"Unsupported data format: {data_path.suffix or '<none>'}. "
            "Supported formats are CSV, TSV, and Parquet."
        )

    if data_format == "csv":
        frame, complete_file = _read_delimited(
            data_path, ",", columns, sample_rows, full_scan
        )
    elif data_format == "tsv":
        frame, complete_file = _read_delimited(
            data_path, "\t", columns, sample_rows, full_scan
        )
    else:
        frame, complete_file = _read_parquet(
            data_path, columns, sample_rows, full_scan
        )

    mode = "full" if complete_file else "sample"
    warnings: list[str] = []
    if not complete_file:
        warnings.append(
            "Profile is based on a bounded row sample; whole-file frequencies may differ."
        )
    if frame.empty:
        warnings.append("No data rows were available in the profiled scope.")

    return {
        "source": str(data_path.resolve()),
        "format": data_format,
        "profile_scope": {
            "mode": mode,
            "sample_limit": None if full_scan else sample_rows,
            "rows_profiled": int(len(frame)),
            "complete_file": complete_file,
        },
        "dimensions": {
            "rows_profiled": int(len(frame)),
            "columns_profiled": int(len(frame.columns)),
            "duplicate_rows_profiled": int(frame.duplicated().sum()),
        },
        "columns": {column: _column_facts(frame[column]) for column in frame.columns},
        "warnings": warnings,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile CSV, TSV, or Parquet data without prescribing analysis methods."
    )
    parser.add_argument("--data", required=True, type=Path, help="Input data file.")
    parser.add_argument("--columns", nargs="*", default=None, help="Columns to profile.")
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=100_000,
        help="Maximum rows for a bounded profile (default: 100000).",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Read all rows instead of a bounded sample.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = profile_file(
            args.data,
            columns=args.columns,
            sample_rows=args.sample_rows,
            full_scan=args.full_scan,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 2

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out is None:
        print(payload)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
        print(f"Profile written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
