"""Unit tests for :func:`apps.blog.utils.diff_versions` (US4 / Phase 6).

The diff helper is pure-Python with no I/O so these tests run without
any fixtures. They cover:

* Title-only changes — every body line is ``context`` and
  ``title_changed`` flips.
* Pure insertion — only ``added`` hunks for the new lines, with
  surrounding ``context`` for unchanged ones.
* Symmetry — swapping ``from`` and ``to`` swaps every ``added`` and
  ``removed`` op.
* Size cap — combined input over ``max_bytes`` raises
  :class:`PostVersionDiffTooLargeError`.
"""

from __future__ import annotations

import uuid

import pytest

from apps.blog.constants import POST_VERSION_DIFF_MAX_BYTES
from apps.blog.exceptions import PostVersionDiffTooLargeError
from apps.blog.schemas import CompareVersionsResult
from apps.blog.utils import diff_versions

pytestmark = pytest.mark.unit


_POST_ID = uuid.UUID("00000000-0000-0000-0000-00000000abcd")


def _diff(
    *,
    from_title: str = "Title A",
    from_text: str = "",
    to_title: str = "Title A",
    to_text: str = "",
    max_bytes: int = POST_VERSION_DIFF_MAX_BYTES,
) -> CompareVersionsResult:
    return diff_versions(
        post_id=_POST_ID,
        from_version=1,
        from_title=from_title,
        from_text=from_text,
        to_version=2,
        to_title=to_title,
        to_text=to_text,
        max_bytes=max_bytes,
    )


def test_title_only_change_marks_title_changed_and_body_all_context() -> None:
    body = "alpha\nbeta\ngamma"
    result = _diff(
        from_title="Old title",
        to_title="New title",
        from_text=body,
        to_text=body,
    )
    assert result.title_changed is True
    assert result.from_title == "Old title"
    assert result.to_title == "New title"
    ops = [h.op for h in result.hunks]
    assert ops == ["context", "context", "context"]
    assert [h.line for h in result.hunks] == ["alpha", "beta", "gamma"]
    assert [(h.from_line_no, h.to_line_no) for h in result.hunks] == [(1, 1), (2, 2), (3, 3)]


def test_pure_insertion_emits_added_hunks_for_new_lines() -> None:
    from_text = "alpha\nbeta"
    to_text = "alpha\nbeta\ngamma\ndelta"
    result = _diff(from_text=from_text, to_text=to_text)
    assert result.title_changed is False
    op_line_pairs = [(h.op, h.line) for h in result.hunks]
    assert ("context", "alpha") in op_line_pairs
    assert ("context", "beta") in op_line_pairs
    assert ("added", "gamma") in op_line_pairs
    assert ("added", "delta") in op_line_pairs
    added = [h for h in result.hunks if h.op == "added"]
    assert all(h.from_line_no is None for h in added)
    assert [h.to_line_no for h in added] == [3, 4]


def test_swapping_from_and_to_swaps_added_and_removed() -> None:
    a = "alpha\nbeta\ngamma"
    b = "alpha\nbeta\ngamma\ndelta"
    forward = _diff(from_text=a, to_text=b)
    reverse = _diff(from_text=b, to_text=a)
    forward_counts = {op: sum(1 for h in forward.hunks if h.op == op) for op in ("added", "removed", "context")}
    reverse_counts = {op: sum(1 for h in reverse.hunks if h.op == op) for op in ("added", "removed", "context")}
    assert forward_counts["added"] == reverse_counts["removed"]
    assert forward_counts["removed"] == reverse_counts["added"]
    assert forward_counts["context"] == reverse_counts["context"]


def test_replace_emits_removed_then_added() -> None:
    """A modified-in-place line surfaces as remove(old) + add(new), in that order."""
    from_text = "alpha\nbeta\ngamma"
    to_text = "alpha\nBETA\ngamma"
    result = _diff(from_text=from_text, to_text=to_text)
    ops = [(h.op, h.line) for h in result.hunks]
    assert ops == [
        ("context", "alpha"),
        ("removed", "beta"),
        ("added", "BETA"),
        ("context", "gamma"),
    ]


def test_oversized_input_raises_diff_too_large() -> None:
    """The byte cap is enforced on the sum of the two encoded payloads."""
    huge_a = "x" * 100
    huge_b = "y" * 200
    with pytest.raises(PostVersionDiffTooLargeError):
        _diff(from_text=huge_a, to_text=huge_b, max_bytes=200)


def test_just_under_cap_is_accepted() -> None:
    """Sanity boundary: combined exactly equal to cap is OK."""
    huge_a = "x" * 100
    huge_b = "y" * 100
    result = _diff(from_text=huge_a, to_text=huge_b, max_bytes=200)
    assert result.hunks
