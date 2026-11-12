"""Compute SUS scores from ten 1-5 answers."""

import argparse


def score(answers: list[int]) -> float:
    if len(answers) != 10 or any(answer < 1 or answer > 5 for answer in answers):
        raise ValueError("SUS requires exactly ten answers from 1 to 5.")
    return (sum(answer - 1 for answer in answers[::2]) + sum(5 - answer for answer in answers[1::2])) * 2.5


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("answers", nargs=10, type=int)
    args = parser.parse_args()
    print(f"SUS score: {score(args.answers):.1f}/100")


if __name__ == "__main__":
    main()
