"""seed product data and rbac policies

Revision ID: d25eb50aab99
Revises: a8e6c92843a1
Create Date: 2026-04-09 20:47:20.699781

"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d25eb50aab99"
down_revision: Union[str, Sequence[str], None] = "a8e6c92843a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Seed data — categories and 7 products from ancornerdalatfarm.com/products
# ---------------------------------------------------------------------------

CATEGORIES = [
    {
        "id": uuid.UUID("11111111-1111-1111-1111-000000000001"),
        "name": "Đà Lạt Farm",
        "slug": "da-lat-farm",
        "description": "Sản phẩm đặc trưng từ nông trại Đà Lạt.",
        "display_order": 1,
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-000000000002"),
        "name": "Trà thảo mộc",
        "slug": "tra-thao-moc",
        "description": "Các loại trà thảo mộc thuần tự nhiên.",
        "display_order": 2,
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-000000000003"),
        "name": "Gạo",
        "slug": "gao",
        "description": "Gạo đặc sản nông trại.",
        "display_order": 3,
    },
]

# Placeholder image URL used for seed products — replace with real S3 URLs later.
PLACEHOLDER_IMAGE = "https://ancornerdalatfarm.com/placeholder.jpg"

PRODUCTS = [
    {
        "id": uuid.UUID("22222222-2222-2222-2222-000000000001"),
        "name": "Đà Lạt Farm",
        "slug": "da-lat-farm",
        "category_id": CATEGORIES[0]["id"],
        "ingredients": None,
        "production": None,
        "benefits": None,
        "retail_price": 15000,
        "wholesale_price": None,
        "display_order": 1,
        "is_featured": True,
    },
    {
        "id": uuid.UUID("22222222-2222-2222-2222-000000000002"),
        "name": "Lavender Hoa Hồng",
        "slug": "lavender-hoa-hong",
        "category_id": CATEGORIES[1]["id"],
        "ingredients": (
            "Lavender, hoa hồng, bạc hà, sả chanh Pháp, hồng trà shan tuyết "
            "300-500 năm tuổi, cỏ ngọt."
        ),
        "production": (
            "Trà lavender hoa hồng được kết hợp từ 5 loại thảo mộc trồng tại "
            "khu vườn ôn đới Đà Lạt theo phương pháp thuần tự nhiên. Sản phẩm "
            "được thu hái vào ngày không mưa từ 8h sáng đến 10h sáng khi trời "
            "vừa đủ nắng, cánh hoa khô không dính sương và chưa héo do nắng "
            "ban trưa, trà sấy lạnh 40 tiếng giữ màu và chất lượng tốt nhất. "
            "Trà lavender (hoa oải hương) hiện là trà vị Âu gần như độc quyền "
            "tại Đà Lạt. Trà có mùi hương từ hoa oải hương thơm kết hợp cùng "
            "vị the mát từ bạc hà và sả chanh Pháp, kèm hậu vị đắng nhẹ của "
            "trà kết hợp cùng tinh dầu thảo dược có sẵn trong lavender, bạc "
            "hà, sả chanh. Hoa hồng có tác dụng hạn chế tinh dầu từ các loại "
            "thảo mộc và có vị ngọt nhẹ từ cánh hoa."
        ),
        "benefits": (
            "Trà lavender hoa hồng là loại trà tốt cho da, chống lão hoá cao. "
            "Đặc biệt các tinh dầu từ lavender, sả chanh và bạc hà có tác "
            "dụng an thần hỗ trợ triệu chứng mất ngủ, tốt cho hệ tim mạch, "
            "tiêu hoá, thanh nhiệt, căng thẳng, ho hen, cảm lạnh."
        ),
        "retail_price": 15000,
        "wholesale_price": None,
        "display_order": 2,
        "is_featured": True,
    },
    {
        "id": uuid.UUID("22222222-2222-2222-2222-000000000003"),
        "name": "Hương Thảo Hoa Nhài",
        "slug": "huong-thao-hoa-nhai",
        "category_id": CATEGORIES[1]["id"],
        "ingredients": None,
        "production": None,
        "benefits": None,
        "retail_price": 15000,
        "wholesale_price": None,
        "display_order": 3,
        "is_featured": False,
    },
    {
        "id": uuid.UUID("22222222-2222-2222-2222-000000000004"),
        "name": "Trà Daisy (Cúc Bạc Hà)",
        "slug": "tra-daisy-cuc-bac-ha",
        "category_id": CATEGORIES[1]["id"],
        "ingredients": None,
        "production": None,
        "benefits": None,
        "retail_price": 15000,
        "wholesale_price": None,
        "display_order": 4,
        "is_featured": False,
    },
    {
        "id": uuid.UUID("22222222-2222-2222-2222-000000000005"),
        "name": "Hoa Hồng Táo Đỏ",
        "slug": "hoa-hong-tao-do",
        "category_id": CATEGORIES[1]["id"],
        "ingredients": None,
        "production": None,
        "benefits": None,
        "retail_price": 15000,
        "wholesale_price": None,
        "display_order": 5,
        "is_featured": False,
    },
    {
        "id": uuid.UUID("22222222-2222-2222-2222-000000000006"),
        "name": "Gạo Lứt Hoa Hồng",
        "slug": "gao-lut-hoa-hong",
        "category_id": CATEGORIES[2]["id"],
        "ingredients": None,
        "production": None,
        "benefits": None,
        "retail_price": 15000,
        "wholesale_price": None,
        "display_order": 6,
        "is_featured": False,
    },
    {
        "id": uuid.UUID("22222222-2222-2222-2222-000000000007"),
        "name": "Trà Hoa Cúc Hàm Hương",
        "slug": "tra-hoa-cuc-ham-huong",
        "category_id": CATEGORIES[1]["id"],
        "ingredients": None,
        "production": None,
        "benefits": None,
        "retail_price": 15000,
        "wholesale_price": None,
        "display_order": 7,
        "is_featured": False,
    },
]

# Casbin policy rules: sub, obj, act. Only an `admin` role is granted
# write/read on product resources; the default `user` role has no implicit
# permissions and should be granted via the existing RBAC admin APIs.
CASBIN_RULES = [
    ("p", "admin", "product", "read"),
    ("p", "admin", "product", "write"),
    ("p", "admin", "product_category", "read"),
    ("p", "admin", "product_category", "write"),
]


def upgrade() -> None:
    """Insert seed data and Casbin policies."""
    bind = op.get_bind()
    meta = sa.MetaData()

    categories_table = sa.Table("product_categorys", meta, autoload_with=bind)
    products_table = sa.Table("products", meta, autoload_with=bind)
    images_table = sa.Table("product_images", meta, autoload_with=bind)
    casbin_table = sa.Table("casbin_rule", meta, autoload_with=bind)

    now = sa.func.now()

    # Categories ------------------------------------------------------------
    for category in CATEGORIES:
        bind.execute(
            sa.insert(categories_table).values(
                id=category["id"],
                name=category["name"],
                slug=category["slug"],
                description=category["description"],
                display_order=category["display_order"],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )

    # Products + images -----------------------------------------------------
    for product in PRODUCTS:
        bind.execute(
            sa.insert(products_table).values(
                id=product["id"],
                name=product["name"],
                slug=product["slug"],
                ingredients=product["ingredients"],
                production=product["production"],
                benefits=product["benefits"],
                retail_price=product["retail_price"],
                wholesale_price=product["wholesale_price"],
                category_id=product["category_id"],
                is_available=True,
                is_featured=product["is_featured"],
                display_order=product["display_order"],
                created_at=now,
                updated_at=now,
            )
        )
        bind.execute(
            sa.insert(images_table).values(
                id=uuid.uuid4(),
                product_id=product["id"],
                url=PLACEHOLDER_IMAGE,
                alt_text=product["name"],
                display_order=0,
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
        )

    # Casbin policies -------------------------------------------------------
    for ptype, sub, obj, act in CASBIN_RULES:
        bind.execute(
            sa.insert(casbin_table).values(
                ptype=ptype,
                v0=sub,
                v1=obj,
                v2=act,
            )
        )


def downgrade() -> None:
    """Remove seed data and Casbin policies."""
    bind = op.get_bind()
    meta = sa.MetaData()

    categories_table = sa.Table("product_categorys", meta, autoload_with=bind)
    products_table = sa.Table("products", meta, autoload_with=bind)
    casbin_table = sa.Table("casbin_rule", meta, autoload_with=bind)

    # Delete products first (images cascade). Categories second.
    product_ids = [p["id"] for p in PRODUCTS]
    bind.execute(sa.delete(products_table).where(products_table.c.id.in_(product_ids)))

    category_ids = [c["id"] for c in CATEGORIES]
    bind.execute(
        sa.delete(categories_table).where(categories_table.c.id.in_(category_ids))
    )

    # Remove casbin rules
    for ptype, sub, obj, act in CASBIN_RULES:
        bind.execute(
            sa.delete(casbin_table).where(
                (casbin_table.c.ptype == ptype)
                & (casbin_table.c.v0 == sub)
                & (casbin_table.c.v1 == obj)
                & (casbin_table.c.v2 == act)
            )
        )
