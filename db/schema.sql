CREATE SCHEMA IF NOT EXISTS ibot;

CREATE TABLE IF NOT EXISTS ibot.learners (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ibot.conversations (
    session_id TEXT PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    history JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ibot.messages (
    id BIGSERIAL PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    text TEXT,
    word_count INTEGER NOT NULL DEFAULT 0,
    sentence_count INTEGER NOT NULL DEFAULT 0,
    avg_sentence_len DOUBLE PRECISION NOT NULL DEFAULT 0,
    ttr DOUBLE PRECISION NOT NULL DEFAULT 0,
    used_ukrainian BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ibot.skill_state (
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    skill TEXT NOT NULL CHECK (skill IN ('grammar','vocabulary','fluency','overall')),
    mu DOUBLE PRECISION NOT NULL,
    sigma2 DOUBLE PRECISION NOT NULL,
    shown_level TEXT NOT NULL,
    msgs_since_change INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (learner_id, skill)
);
CREATE TABLE IF NOT EXISTS ibot.skill_history (
    id BIGSERIAL PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    observation DOUBLE PRECISION NOT NULL,
    reliability DOUBLE PRECISION NOT NULL,
    mu_after DOUBLE PRECISION NOT NULL,
    sigma2_after DOUBLE PRECISION NOT NULL,
    message_id BIGINT REFERENCES ibot.messages(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ibot.mistakes (
    id BIGSERIAL PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    message_id BIGINT REFERENCES ibot.messages(id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    original TEXT NOT NULL,
    corrected TEXT NOT NULL,
    severity TEXT NOT NULL,
    structure_level INTEGER NOT NULL,
    weight DOUBLE PRECISION NOT NULL,
    is_typo BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ibot.mistake_weights (
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 0,
    count_total INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (learner_id, category)
);
CREATE TABLE IF NOT EXISTS ibot.vocabulary (
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    word TEXT NOT NULL,
    cefr_level TEXT NOT NULL,
    times_seen INTEGER NOT NULL DEFAULT 0,
    times_used_correct INTEGER NOT NULL DEFAULT 0,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (learner_id, word)
);
CREATE TABLE IF NOT EXISTS ibot.judge_evaluations (
    id BIGSERIAL PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    grammar INTEGER NOT NULL,
    vocabulary INTEGER NOT NULL,
    fluency INTEGER NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS ibot.llm_usage (
    id BIGSERIAL PRIMARY KEY,
    learner_id TEXT NOT NULL REFERENCES ibot.learners(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    estimated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE OR REPLACE VIEW ibot.v_cost_summary AS
SELECT learner_id, purpose, COUNT(*) AS calls,
       SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
       SUM(latency_ms) AS latency_ms
FROM ibot.llm_usage GROUP BY learner_id, purpose;
