"""backfill diary entry names

Revision ID: e2e0658fa19f
Revises: 439d171706d6
Create Date: 2026-10-10 13:46:37.000654

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2e0658fa19f'
down_revision = '439d171706d6'
branch_labels = None
depends_on = None


def upgrade():
    # Mục nhật ký ghi trước khi có cột name/serving_label: lấy tên và khẩu phần từ món tương ứng
    op.execute(
        "UPDATE diary_entries SET name = (SELECT foods.name_vi FROM foods WHERE foods.id = diary_entries.food_id) "
        "WHERE name IS NULL AND food_id IS NOT NULL"
    )
    op.execute(
        "UPDATE diary_entries SET serving_label = (SELECT foods.serving FROM foods WHERE foods.id = diary_entries.food_id) "
        "WHERE serving_label IS NULL AND food_id IS NOT NULL"
    )


def downgrade():
    pass  # Dữ liệu điền thêm, không cần hoàn tác
