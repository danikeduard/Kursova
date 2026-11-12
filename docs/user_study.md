# Evaluation and user-study protocol

LinguaPath should be evaluated as an adaptive learning prototype, not as a
CEFR certification tool. The following protocol keeps the comparison
reproducible and separates product usability from model quality.

## Rating-model replay

1. Export anonymized `RatingEvent` rows from a staging database.
2. Run `python scripts/replay_models.py`.
3. Compare baseline, Kalman, no-density, and no-outlier variants by:
   - mean absolute rating movement;
   - number of CEFR label changes;
   - messages needed to approach the final estimate;
   - disagreement with the learner's self-assessed starting level.
4. Report sample size and the non-causal limitation: the live tutor influenced
   the messages that were later replayed.

## Small usability study

Recruit at least 8 participants across A2-B2 self-assessed levels. Ask each
participant to complete the same three tasks:

1. have a free conversation;
2. complete a recommended weak-topic exercise;
3. inspect the progress dashboard and explain why the system selected the next
   activity.

Collect:

- completion rate and time per task;
- helpful/not-helpful message feedback;
- perceived adaptation on a 1-5 scale;
- ten System Usability Scale answers;
- optional free-text comments.

Do not collect names or unrelated personal data. Store participant IDs
separately from chat exports. Obtain consent before recording responses and
provide account deletion after the session.

## Reporting

Report median and interquartile range for task time, mean SUS score with the
sample size, and the distribution of perceived adaptation. Do not claim that
rating movement proves language acquisition; use a delayed writing sample or
teacher assessment for any learning-effect claim.

SUS can be calculated locally with:

```powershell
python scripts/sus_score.py 4 2 4 2 5 2 4 1 4 2
```
