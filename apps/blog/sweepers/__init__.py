"""Blog background sweepers — autosave flush, post-version retention, comment-moderation queue.

Phase C.4 split ``apps/blog/sweeper.py`` (587 LOC) into one module per
leader-elected sweeper. ``apps/blog/sweeper.py`` is retained as a
deprecated re-export shim so existing importers (factory + integration
tests) keep working unchanged.
"""

from __future__ import annotations

from apps.blog.sweepers._autosave import (
    autosave_sweeper,
    start_sweeper_task,
    stop_sweeper_task,
    sweep_once,
)
from apps.blog.sweepers._comment_moderation import (
    comment_moderation_sweeper,
    delete_stale_pending_comments,
    start_comment_moderation_sweeper_task,
    stop_comment_moderation_sweeper_task,
    sweep_pending_comments_once,
)
from apps.blog.sweepers._post_version import (
    post_version_sweeper,
    start_post_version_sweeper_task,
    stop_post_version_sweeper_task,
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
