# Adaptive level model

The learner has one state per skill: `(R, P, last_outlier_sign)`. Ratings use
an expanded 2.5x scale: CEFR centres are A1=1500, A2=2000, B1=2500, B2=3000,
C1=3500, and C2=4000. Level boundaries are 1750, 2250, 2750, 3250, and 3750.
The Kalman gain and step limits use this same scale, so its maximum movement is
120 rating points per accepted observation. `RATING_MODE` selects `kalman`
(the default) or `baseline`.

## Formulas

For a message with `W` English word tokens (ASCII letters with an optional
internal apostrophe, matching message validation) and evaluator confidence
`c_llm`, effective confidence is:

**3.1** `c_eff = c_llm * min(1, W / 12)`

For `E` skill-specific errors, density is `d = 100E/W`. The first matching
threshold in `[(15,1500),(10,2000),(6,2500),(3,3000),(1.5,3500),(0,4000)]`
produces `R_density`.

**3.2** `R_density = table(d)`

**3.3** `R_obs = R_llm - 0.3 * max(0, R_llm - R_density)`

The density signal is ignored below eight words and can only lower an
observation. Grammar and vocabulary density use only their matching error
types. Writing is assessed for organization and cohesion, so grammar,
vocabulary, and spelling errors do not also lower its density score. Kalman
state starts with `P0 = 625^2`; process noise is `Q=5625`.

**3.4** `R_gap = R_obs - R`

**3.5** `R_meas = 625^2 / c_eff^2`

**3.6** `K = f P / (P + R_meas)`

Here `f=0.5` for the first suspicious outlier (`|R_gap| >= 1000` and
`c_eff < 0.6`), otherwise `f=1`. A second suspicious observation in the same
direction is confirmed and uses the full factor.

**3.7** `R_new = R + clamp(K * R_gap, -120, 120)`

**3.8** `P_new = min(P0, (1-K)P + 5625)`

**3.9** `last_outlier_sign = sign(R_gap)` for suspicious observations, or zero
for normal observations. Updates with `c_eff < 0.3` are skipped.

The baseline is `delta = clamp(0.048 * w * c * (R_llm - R), -80, 80)`,
where `w=2` for the first five valid messages and `w=1` thereafter. Displayed
skill labels retain 62.5-point hysteresis across messages and are stored with
rating events. Overall ratings retain weights 0.4/0.3/0.3.

## Worked example

Starting at C1 (`R=3500`, `P=390625`), an A2 observation (`R_llm=2000`) with
14 words and confidence 0.8 has `c_eff=0.8`. With no errors, density does not
lower the observation. The successive Kalman ratings are approximately
`3380, 3260, 3140, 3020, 2900, 2780, 2673` (the first five movements are
limited by the 120-point step cap).

## Rationale

- **Kalman mode** makes early uncertain observations move the estimate more
  while naturally reducing later gains.
- **Length-aware confidence** prevents very short messages from masquerading as
  strong evidence.
- **Outlier guard** limits a single low-confidence contradiction while allowing
  repeated evidence to confirm it.
- **Error density** adds an objective, skill-specific signal without allowing
  zero errors to prove a high level.
- **Explanations** preserve the evidence behind displayed label changes and
  explicitly communicate uncertainty.

## Limitations

The evaluator remains an LLM and can misclassify levels, errors, or strengths.
The density table is heuristic, observations are not independent, and a
learner's self-assessment can be wrong. Replay is non-causal because tutor
behavior depended on the live model; small samples are not conclusive.
Ratings are learning estimates, not exam predictions or certification.

For evaluator calibration, `scripts/evaluate_cefr.py` accepts a UTF-8 JSONL
corpus with human-reviewed labels. Each row contains `text` and
`expected.grammar`, `expected.vocab`, and `expected.writing`, each set to a
CEFR label. Run it with the configured provider and evaluator model; it
reports exact accuracy and mean distance in CEFR bands. No calibration corpus
is bundled because labels should be reviewed by a qualified English teacher.

## Topic mastery and pedagogical policy

Skill ratings describe broad ability; they are complemented by
`TopicMastery(user_id, topic, mastery, uncertainty, attempts, errors)`.
Mastery starts at `0.5` and is updated only from evaluator evidence that is
validated against the learner message. A grounded error decreases mastery in
proportion to its severity, while a grounded strength increases it slightly.
Both observations reduce uncertainty.

The pedagogical policy then selects an action:

- no topic evidence: diagnostic conversation;
- high uncertainty: targeted diagnostic;
- mastery below `0.45`: micro-exercise;
- otherwise: spaced review.

The policy is intentionally deterministic and explainable. A future
contextual-bandit implementation can compare these actions using completion,
subsequent evidence, engagement, and API cost without allowing the LLM to
mutate learner state directly.
