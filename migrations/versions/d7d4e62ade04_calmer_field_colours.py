"""calmer field colours

Revision ID: d7d4e62ade04
Revises: 76fbf5b29fed
Create Date: 2026-10-06 00:35:02.228433

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7d4e62ade04'
down_revision = '76fbf5b29fed'
branch_labels = None
depends_on = None


# Field colours from the home-page redesign (blue, coral, purple, teal). Only fields that still have
# their original colour are changed, so a colour an admin picked is kept.
NEW = {"music": (212, 210), "theatre": (8, 15), "cinema": (280, 245), "dance": (142, 160)}


def upgrade():
    conn = op.get_bind()
    for key, (old, new) in NEW.items():
        conn.execute(sa.text("UPDATE field SET hue = :new WHERE key = :key AND hue = :old"),
                     {"new": new, "key": key, "old": old})


def downgrade():
    conn = op.get_bind()
    for key, (old, new) in NEW.items():
        conn.execute(sa.text("UPDATE field SET hue = :old WHERE key = :key AND hue = :new"),
                     {"new": new, "key": key, "old": old})
