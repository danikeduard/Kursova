"""Expand rating values and thresholds by a factor of 2.5."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_expand_rating_scale"
down_revision = "20261112_preferred_name"
branch_labels = None
depends_on = None

FACTOR = 2.5
RATING_FIELDS = {"rating", "rating_before", "rating_after", "r_llm", "r_density", "r_obs", "density"}


def _scale_evidence(value, factor):
    if isinstance(value, dict):
        return {
            key: item * factor if key in RATING_FIELDS and isinstance(item, (int, float)) else _scale_evidence(item, factor)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scale_evidence(item, factor) for item in value]
    return value


def _scale_columns(table_name, columns, factor):
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if table_name not in tables:
        return
    table = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
    available = set(table.c.keys())
    for column in columns:
        if column in available:
            bind.execute(table.update().values({column: table.c[column] * factor}))


def _scale_level_change_json(factor):
    bind = op.get_bind()
    if "app_level_change" not in set(sa.inspect(bind).get_table_names()):
        return
    table = sa.Table("app_level_change", sa.MetaData(), autoload_with=bind)
    if "evidence" not in table.c:
        return
    for row_id, evidence in bind.execute(sa.select(table.c.id, table.c.evidence)):
        updated = _scale_evidence(evidence, factor)
        if updated != evidence:
            bind.execute(table.update().where(table.c.id == row_id).values(evidence=updated))


def upgrade():
    _scale_columns("app_skill_rating", ("rating",), FACTOR)
    _scale_columns("app_skill_rating", ("variance",), FACTOR**2)
    _scale_columns("app_rating_event", ("rating_before", "rating_after", "r_llm", "r_density", "r_obs"), FACTOR)
    _scale_columns("app_level_change", ("rating_before", "rating_after"), FACTOR)
    _scale_level_change_json(FACTOR)


def downgrade():
    _scale_columns("app_skill_rating", ("rating",), 1 / FACTOR)
    _scale_columns("app_skill_rating", ("variance",), 1 / FACTOR**2)
    _scale_columns("app_rating_event", ("rating_before", "rating_after", "r_llm", "r_density", "r_obs"), 1 / FACTOR)
    _scale_columns("app_level_change", ("rating_before", "rating_after"), 1 / FACTOR)
    _scale_level_change_json(1 / FACTOR)
