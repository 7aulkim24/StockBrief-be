"""index news_items and disclosures by ticker and published_at

Revision ID: 0006_news_disclosure_ticker_published_at_index
Revises: 0005_chat_messages_session_id_index
Create Date: 2026-07-07 00:00:00.000000

Adds composite indexes for candidate evidence summary and evidence listing
queries that filter by ticker and order/aggregate by published_at.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

revision: str = "0006_news_disclosure_ticker_published_at_index"
down_revision: str | None = "0005_chat_messages_session_id_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEWS_INDEX_NAME = "ix_news_items_ticker_published_at"
NEWS_TABLE_NAME = "news_items"
DISCLOSURES_INDEX_NAME = "ix_disclosures_ticker_published_at"
DISCLOSURES_TABLE_NAME = "disclosures"


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _create_index(table_name: str, index_name: str) -> None:
    if _index_exists(table_name, index_name):
        return

    context = op.get_context()
    if context.dialect.name == "postgresql":
        with context.autocommit_block():
            op.create_index(
                index_name,
                table_name,
                ["ticker", "published_at"],
                postgresql_concurrently=True,
            )
        return

    op.create_index(index_name, table_name, ["ticker", "published_at"])


def _drop_index(table_name: str, index_name: str) -> None:
    if not _index_exists(table_name, index_name):
        return

    context = op.get_context()
    if context.dialect.name == "postgresql":
        with context.autocommit_block():
            op.drop_index(
                index_name,
                table_name=table_name,
                postgresql_concurrently=True,
            )
        return

    op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    _create_index(NEWS_TABLE_NAME, NEWS_INDEX_NAME)
    _create_index(DISCLOSURES_TABLE_NAME, DISCLOSURES_INDEX_NAME)


def downgrade() -> None:
    _drop_index(DISCLOSURES_TABLE_NAME, DISCLOSURES_INDEX_NAME)
    _drop_index(NEWS_TABLE_NAME, NEWS_INDEX_NAME)
