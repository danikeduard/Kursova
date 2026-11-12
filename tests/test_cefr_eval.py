import json

import pytest

from scripts.evaluate_cefr import load_corpus, score_rows


def test_score_rows_reports_exact_accuracy_and_cefr_distance():
    rows = [
        {
            "expected": {"grammar": "A2", "vocab": "B1", "writing": "B1"},
            "predicted": {"grammar": "A2", "vocab": "B2", "writing": "A2"},
        },
        {
            "expected": {"grammar": "B1", "vocab": "B1", "writing": "B2"},
            "predicted": {"grammar": "B1", "vocab": "B1", "writing": "B2"},
        },
    ]

    scores = score_rows(rows)

    assert scores["grammar"] == {"exact_accuracy": 1.0, "mean_level_distance": 0.0, "examples": 2}
    assert scores["vocab"] == {"exact_accuracy": 0.5, "mean_level_distance": 0.5, "examples": 2}
    assert scores["writing"] == {"exact_accuracy": 0.5, "mean_level_distance": 0.5, "examples": 2}


def test_load_corpus_requires_all_expected_skill_labels(tmp_path):
    corpus = tmp_path / "labels.jsonl"
    corpus.write_text(
        json.dumps({"text": "Example text", "expected": {"grammar": "B1"}}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="grammar, vocab, and writing"):
        load_corpus(corpus)
