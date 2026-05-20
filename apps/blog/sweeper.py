"""Deprecated compatibility shim — re-exports :mod:`apps.blog.sweepers`.

Phase C.4 split the original sweeper module into per-aggregate files
under :mod:`apps.blog.sweepers`. This shim keeps the legacy
``from apps.blog.sweeper import …`` imports working for one release
cycle while every existing call site migrates. New code should import
from :mod:`apps.blog.sweepers` directly.
"""

from __future__ import annotations

from apps.blog.sweepers import (
    autosave_sweeper,
    comment_moderation_sweeper,
    delete_stale_pending_comments,
    post_version_sweeper,
    start_comment_moderation_sweeper_task,
    start_post_version_sweeper_task,
    start_sweeper_task,
    stop_comment_moderation_sweeper_task,
    stop_post_version_sweeper_task,
    stop_sweeper_task,
    sweep_once,
    sweep_pending_comments_once,
    sweep_post_versions_once,
    trim_post,
)

__all__ = (
    "autosave_sweeper",
    "comment_moderation_sweeper",
    "delete_stale_pending_comments",
    "post_version_sweeper",
    "start_comment_moderation_sweeper_task",
    "start_post_version_sweeper_task",
    "start_sweeper_task",
    "stop_comment_moderation_sweeper_task",
    "stop_post_version_sweeper_task",
    "stop_sweeper_task",
    "sweep_once",
    "sweep_pending_comments_once",
    "sweep_post_versions_once",
    "trim_post",
)
