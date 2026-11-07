"""Preserve existing cases; introduce mock payment transactions and unpaid status."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("document_requests", sa.Column("payment_status", sa.String(12),
        sa.CheckConstraint("payment_status IN ('unpaid', 'paid')", name="ck_document_payment_status"),
        nullable=False, server_default="unpaid"))
    op.create_table("payment_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("document_requests.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("authority", sa.String(48), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("bank_status", sa.String(12), nullable=False),
        sa.Column("receipt", sa.String(48), unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime()),
        sa.CheckConstraint("amount > 0", name="ck_payment_positive_amount"),
        sa.CheckConstraint("status IN ('pending', 'success', 'failed')", name="ck_payment_status"),
        sa.CheckConstraint("bank_status IN ('pending', 'paid', 'cancelled')", name="ck_payment_bank_status"))
    op.create_index("ix_payment_transactions_authority", "payment_transactions", ["authority"], unique=True)
    op.create_index("ix_payment_transactions_request_id", "payment_transactions", ["request_id"])
    op.create_index("ix_payment_transactions_user_id", "payment_transactions", ["user_id"])


def downgrade():
    raise RuntimeError("Forward-only financial history migration; use a reviewed backup for rollback")
