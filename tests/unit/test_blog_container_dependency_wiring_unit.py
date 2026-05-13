"""Unit test for BlogContainer DI rewiring (F-MAINT-1).

The pre-change ``BlogContainer`` imports ``UserRepository`` directly and
constructs its own ``providers.Factory(UserRepository)``. That couples
the blog module to the user module's concrete class — a layer-graph
inversion the architecture rule pages explicitly forbid.

After F-MAINT-1, ``BlogContainer.user_repository`` is declared as
``providers.Dependency()`` and ``AppContainer`` wires it from
``user.user_repository`` at composition time. The blog module's
import surface no longer mentions ``apps.user``.
"""

from __future__ import annotations

from pathlib import Path

from dependency_injector import providers

from apps.blog.containers import BlogContainer

_BLOG_CONTAINER_SOURCE: Path = Path(__file__).resolve().parents[2] / "apps" / "blog" / "containers.py"


def test_blog_container_user_repository_is_external_dependency() -> None:
    """BlogContainer must declare user_repository as Dependency, not Factory."""
    assert isinstance(BlogContainer.user_repository, providers.Dependency), (
        "BlogContainer.user_repository must be providers.Dependency() so AppContainer "
        f"can wire it from UserContainer; got {type(BlogContainer.user_repository).__name__}."
    )


def test_blog_container_module_does_not_import_user_repositories() -> None:
    """The blog DI container must not directly import the user module."""
    source = _BLOG_CONTAINER_SOURCE.read_text(encoding="utf-8")
    assert "from apps.user" not in source, (
        "apps/blog/containers.py must not import apps.user.* — it inverts the "
        "module-dependency direction. Use providers.Dependency() and let "
        "AppContainer compose the cross-container reference."
    )
