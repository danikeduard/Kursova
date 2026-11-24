"""merge heads

Revision ID: ec3d85d909a8
Revises: 20261121_seed_demo_users, 20261124_remove_theme_setting
Create Date: 2026-11-24 21:31:19.142405

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ec3d85d909a8'
down_revision = ('20261121_seed_demo_users', '20261124_remove_theme_setting')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
