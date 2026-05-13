"""Unit tests for the strict-by-default ``model_from_dict`` helper (F-QUAL-1).

The pre-change helper silently discards unknown attributes — a footgun
when a typo in a ``data={...}`` dict drops a field unnoticed. After the
F-QUAL-1 change, strict mode raises ``TypeError`` immediately; passing
``strict=False`` opt-ins to the legacy silent-drop behavior.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from apps.core.database.model.base import UUIDAuditBase
from apps.core.database.utils import model_from_dict


class _Sample(UUIDAuditBase):
    __tablename__ = "_test_model_from_dict_sample"
    __test__ = False

    name: Mapped[str] = mapped_column()


def test_model_from_dict_accepts_known_columns() -> None:
    instance = model_from_dict(_Sample, name="hello")
    assert instance.name == "hello"


def test_model_from_dict_strict_raises_on_unknown_attribute() -> None:
    with pytest.raises(TypeError, match="unknown attribute"):
        model_from_dict(_Sample, name="hello", bogus_field="oops")


def test_model_from_dict_strict_false_drops_unknown_silently() -> None:
    instance = model_from_dict(_Sample, strict=False, name="hello", bogus_field="ignored")
    assert instance.name == "hello"
    assert not hasattr(instance, "bogus_field")
