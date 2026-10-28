"""Compare baseline, single-LLM, and full adaptive CEFR estimates.

The CSV must contain ``text,cefr_true``. Optional score columns
``llm_level`` and ``full_level`` allow recording model outputs without
calling a provider from this script.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.services.levels import LEVEL_TO_NUMBER


def baseline(text: str) -> int:
    words = len(text.split())
    return 1 if words < 5 else 2 if words < 12 else 3 if words < 22 else 4 if words < 35 else 5


def within_one(actual: list[int], predicted: list[int]) -> float:
    return sum(abs(a - p) <= 1 for a, p in zip(actual, predicted)) / len(actual)


def mae(actual: list[int], predicted: list[int]) -> float:
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)


def weighted_kappa(actual: list[int], predicted: list[int]) -> float:
    n = len(actual)
    if not n:
        return 0.0
    expected = [[0] * 6 for _ in range(6)]
    observed = [[0] * 6 for _ in range(6)]
    for a, p in zip(actual, predicted):
        observed[a - 1][p - 1] += 1
    counts_a = [sum(row) for row in observed]
    counts_p = [sum(observed[row][col] for row in range(6)) for col in range(6)]
    for row in range(6):
        for col in range(6):
            expected[row][col] = counts_a[row] * counts_p[col] / n
    weight = lambda row, col: ((row - col) / 5) ** 2
    disagreement_observed = sum(weight(row, col) * observed[row][col] for row in range(6) for col in range(6))
    disagreement_expected = sum(weight(row, col) * expected[row][col] for row in range(6) for col in range(6))
    return 1.0 - disagreement_observed / disagreement_expected if disagreement_expected else 1.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()
    rows = list(csv.DictReader(args.csv_file.open(encoding="utf-8", newline="")))
    actual = [LEVEL_TO_NUMBER[str(row["cefr_true"]).upper()] for row in rows]
    methods = {
        "baseline": [baseline(row["text"]) for row in rows],
        "single_llm": [int(row["llm_level"]) for row in rows if row.get("llm_level")],
        "full_algorithm": [int(row["full_level"]) for row in rows if row.get("full_level")],
    }
    for name, values in methods.items():
        if len(values) != len(actual):
            print(f"{name}: add a {name.replace('_', '')}_level column to evaluate")
            continue
        print(f"{name}: within_1={within_one(actual, values):.3f} "
              f"MAE={mae(actual, values):.3f} kappa={weighted_kappa(actual, values):.3f}")


if __name__ == "__main__":
    main()
