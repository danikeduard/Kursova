"""Run the configured evaluator against a manually CEFR-labeled JSONL corpus.

Each JSONL row must contain ``text`` and an ``expected`` mapping with grammar,
vocab, and writing labels. The script reports per-skill exact accuracy and
mean CEFR distance without storing learner messages in the application DB.
"""

import argparse
import json
import sys
from pathlib import Path

from app import create_app
from app.evaluator import SKILLS, evaluate_message
from app.providers import create_client
from app.rating import LEVELS
from config.llm import fallback_models, get_max_tokens, get_model, reasoning_options


def score_rows(rows: list[dict]) -> dict:
    scores = {skill: {"correct": 0, "distance": 0, "count": 0} for skill in SKILLS}
    for row in rows:
        expected = row["expected"]
        predicted = row["predicted"]
        for skill in SKILLS:
            actual_index = LEVELS.index(expected[skill])
            predicted_index = LEVELS.index(predicted[skill])
            scores[skill]["correct"] += actual_index == predicted_index
            scores[skill]["distance"] += abs(actual_index - predicted_index)
            scores[skill]["count"] += 1
    return {
        skill: {
            "exact_accuracy": values["correct"] / values["count"] if values["count"] else 0,
            "mean_level_distance": values["distance"] / values["count"] if values["count"] else 0,
            "examples": values["count"],
        }
        for skill, values in scores.items()
    }


def load_corpus(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise TypeError(f"Line {line_number}: expected a JSON object with string 'text'.")
        expected = row.get("expected")
        if not isinstance(expected, dict) or set(expected) != set(SKILLS):
            raise ValueError(f"Line {line_number}: 'expected' must contain grammar, vocab, and writing.")
        if any(level not in LEVELS for level in expected.values()):
            raise ValueError(f"Line {line_number}: labels must be one of {', '.join(LEVELS)}.")
        rows.append({"text": row["text"], "expected": expected})
    if not rows:
        raise ValueError("The labeled corpus is empty.")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="UTF-8 JSONL file with human-reviewed CEFR labels")
    args = parser.parse_args()
    try:
        rows = load_corpus(args.corpus)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    app = create_app()
    predictions = []
    with app.app_context():
        provider = app.config["LLM_PROVIDER"]
        client = create_client(app.config, provider=provider)
        for index, row in enumerate(rows, start=1):
            result = evaluate_message(
                client=client,
                model=get_model("evaluator"),
                content=row["text"],
                user_id=None,
                db=None,
                provider=provider,
                config=app.config,
                max_tokens=get_max_tokens("evaluator"),
                fallbacks=fallback_models(),
                reasoning=reasoning_options(app.config),
            )
            if result is None or result.evaluation is None:
                print(f"Evaluation failed for corpus row {index}.", file=sys.stderr)
                return 2
            row["predicted"] = {skill: result.skills[skill].level for skill in SKILLS}
            predictions.append(row)

    print(json.dumps({"rows": len(predictions), "scores": score_rows(predictions)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
