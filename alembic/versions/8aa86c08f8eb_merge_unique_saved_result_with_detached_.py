"""merge unique saved result with detached run heads

Revision ID: 8aa86c08f8eb
Revises: e3f6b2c1a4d8, e5e4a8b6fbd7
Create Date: 2026-09-30 19:13:43.730770

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8aa86c08f8eb'
down_revision: Union[str, Sequence[str], None] = ('e3f6b2c1a4d8', 'e5e4a8b6fbd7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
