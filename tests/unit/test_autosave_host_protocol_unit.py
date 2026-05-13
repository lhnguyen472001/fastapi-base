"""Unit test for the _AutosaveHost Protocol (F-MAINT-2).

The pre-change ``_PostAutosaveMixin`` calls four host methods on
``self`` — ``find_or_raise``, ``_build_detail``,
``_invalidate_workspace_cache``, and ``_reload`` — which it can only
discover via comments in the module docstring. After F-MAINT-2 a
``_AutosaveHost`` Protocol declared under ``typing.TYPE_CHECKING``
formalizes that contract so static checkers can verify the host
class fulfils it.

The Protocol must NOT exist at runtime — only inside the
``TYPE_CHECKING`` block — so importing the autosave module from a
non-type-checking environment does not require the heavy
``PostDetailResponse`` symbol.
"""

from __future__ import annotations

import typing
from pathlib import Path

from apps.blog.services import _autosave


def test_autosave_host_protocol_does_not_leak_to_runtime() -> None:
    """The Protocol must live behind ``if TYPE_CHECKING:`` (no runtime symbol)."""
    assert not hasattr(_autosave, "_AutosaveHost"), (
        "_AutosaveHost must be declared under `if TYPE_CHECKING:` so it has no runtime cost; found a runtime attribute."
    )


def test_autosave_mixin_keeps_field_annotations() -> None:
    """The mixin still declares its own attribute contracts on the data fields."""
    type_hints = typing.get_type_hints(_autosave._PostAutosaveMixin)
    for name in (
        "repository",
        "content_repository",
        "post_version_repository",
        "cache",
        "autosave_store",
    ):
        assert name in type_hints, f"_PostAutosaveMixin lost annotation for {name}"


def test_autosave_module_declares_protocol_in_source() -> None:
    """The Protocol is declared in the module source under TYPE_CHECKING."""
    source = Path(_autosave.__file__).read_text(encoding="utf-8")
    assert "class _AutosaveHost" in source, "_AutosaveHost Protocol missing from apps/blog/services/_autosave.py."
    assert "Protocol" in source, "_AutosaveHost must subclass typing.Protocol."
    tc_index = source.find("if TYPE_CHECKING:")
    proto_index = source.find("class _AutosaveHost")
    assert tc_index >= 0 and proto_index > tc_index, (
        "_AutosaveHost must be declared inside the `if TYPE_CHECKING:` block so it has no runtime cost."
    )

    # Each host method that the mixin uses must be enumerated on the Protocol.
    # Delimit the Protocol body by the next top-level ``class `` definition
    # (the mixin); ``find("\nclass ")`` skips RST cross-references like
    # ``:class:`_PostAutosaveMixin``` that appear inside docstrings.
    end_index = source.find("\nclass ", proto_index + 1)
    proto_slice = source[proto_index : end_index if end_index > 0 else len(source)]
    for method_name in ("find_or_raise", "_build_detail", "_invalidate_workspace_cache", "_reload"):
        assert method_name in proto_slice, f"_AutosaveHost must declare host method '{method_name}'."
