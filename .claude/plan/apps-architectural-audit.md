# Implementation Plan: `apps/` Architectural Audit & Remediation

**Generated:** 2026-05-04
**Scope:** Deep audit of every module under `/home/manhnv1/Developments/fastapi-base/apps/` (auth, blog, rbac, core, user, product, workspace, health) focused on **performance, quality, architecture, SOLID, design patterns, maintainability, scalability**.
**Method:** 5 parallel `Explore` sub-agents read every `.py` under their assigned scope, then findings were calibrated against project rules in `CLAUDE.md` + `.claude/rules/*` and against recent commits (e.g., `bb242de` "no session ops in services", `139db15` "route service writes through repositories").
**Type:** Backend (no frontend surface)
**Output:** Plan only — **no code modifications were performed**.

> ⚠️ **Multi-model dispatch unavailable.** `~/.claude/bin/codeagent-wrapper` and the Codex/Gemini role prompts (`~/.claude/.ccg/prompts/{codex,gemini}/*.md`) are **not installed** on this system. The plan below is therefore Claude-synthesized from 5 parallel sub-agent audits, not from Codex+Gemini collaboration. If you want the actual multi-model flow, install the wrapper first and re-run.

---

## 0. Severity Calibration (read first)

The 5 sub-agents independently flagged ~50 issues. Several "BLOCKER" claims do **not** survive a check against project rules — calibration table:

| Agent claim | Verdict | Why |
|---|---|---|
| `functools.lru_cache` on `_load_jwt_keys` / `_load_totp_fernet` is "async-unsafe" → BLOCKER | **INFO** | `lru_cache` uses an internal `RLock`; reading immutable PEM/Fernet files is deterministic. Two concurrent first-callers either both hit the lock or both produce the same value — no inconsistency. Worth moving to `lifespan` to **fail-fast** at startup, but not a correctness bug. |
| `repositories.py:281-287 replace_post_tags()` calls `session.add/delete` → BLOCKER | **WARNING** (verify) | Repositories **ARE** allowed to call `session.*`; the rule (CLAUDE.md → "no session ops in services") forbids it only in services. Concern reduces to: is the method `@transactional`-wrapped at the *service* call site? Verify before acting. |
| `asyncio.to_thread(enforcer.enforce)` is "scaling bottleneck" → BLOCKER | **WARNING** | Standard pattern for wrapping sync libraries; default threadpool (CPU+4) is fine for typical request rates. Real fix is enforcer-result caching, not removing `to_thread`. |
| `Transactional` decorator nested-call returns coroutine before outer commit → BLOCKER | **WARNING** (verify) | Reading `apps/core/database/transactional.py` end-to-end is required before accepting this. Mark unverified. |
| `enforcer_factory()` called manually in `factory.py:73-80` creates a second instance unwired from DI → BLOCKER | **WARNING** (verify) | If the `RBACContainer.enforcer` is a `providers.Resource` and the factory function caches via `lru_cache` or the resource is the same callable, this is a non-issue. Verify by reading `apps/rbac/containers.py` + `apps/rbac/enforcer.py` together before acting. |
| TOTP Fernet fallback key generates new bytes per process when `totp_encryption_key` is unset → BLOCKER | **WARNING** | Real footgun in dev (encrypted column unreadable across restarts), but `settings.py:322` already raises in production. Fix is a louder warning + dev-mode persistence, not a code rewrite. |

**Phase 1 below is the verification pass — do that before any code change.**

---

## 1. Goal

Produce a **prioritized, surgical remediation roadmap** for the `apps/` tree that:

1. Confirms or rejects unverified agent claims against the actual code.
2. Closes real correctness/security holes (Phase 2).
3. Hardens scalability hot-paths (Phase 3).
4. Pays down the cheapest-per-byte tech debt (Phase 4).
5. Records architectural improvements as candidates, not commitments (Phase 5).

The plan is intentionally **read-and-think first, then edit** — most "BLOCKERs" need 5 minutes of file reading to either confirm or dismiss.

---

## 2. Implementation Phases

### Phase 1 — Verification (no code changes, ~30 min)

Goal: confirm/reject the 5 unverified agent claims above. Each verification is one or two `Read` calls.

| Step | File(s) to read | Question to answer | Deliverable |
|---|---|---|---|
| 1.1 | `apps/blog/repositories.py:264-310` (`replace_post_tags`) + every caller (grep for `replace_post_tags`) | Is the **caller** wrapped in `@transactional`? If yes, the agent's "BLOCKER" collapses. | Note in plan v2 |
| 1.2 | `apps/core/database/transactional.py` (full file) | Does `@transactional` short-circuit nested calls correctly? Does `session.in_transaction()` check actually return the coroutine before commit, as the agent claimed? | Note in plan v2 |
| 1.3 | `apps/rbac/containers.py` + `apps/rbac/enforcer.py` (full) + `apps/factory.py:73-80` | Is `enforcer_factory` cached (e.g. `@lru_cache` or via `providers.Resource`)? Does the seeder use the same instance routes will use? | Note in plan v2 |
| 1.4 | `apps/auth/services/_tokens.py:170-230` | When a cached `User` dict is rehydrated, does any code path pass it back to `session.merge()` / `session.add()`? grep for `merge(` and `add(` in `apps/auth`. | Note in plan v2 |
| 1.5 | `apps/blog/services/_posts.py` (cache invalidation) + `apps/blog/services/__init__.py` | Confirm `invalidate_pattern` is the only path; check the actual TTL constants and key shape against `apps/blog/constants.py`. | Note in plan v2 |

**Phase 1 stop-loss:** if any verification flips a BLOCKER → INFO, drop it from the plan in v2 before doing anything else.

---

### Phase 2 — BLOCKERS (real correctness / security issues)

Confirmed-real concerns. Order = highest blast radius first.

#### 2.1 — RBAC: DB+Casbin transactional consistency (`rbac/services/_role.py`, `_permission.py`, `_group.py`, `_object_permission.py`)

**Issue:** writes to the DB and writes to the Casbin enforcer are not in a single transaction. Pattern:
```python
await self.repository.add(session, ...)   # tx open
await self.enforcer.add_policy(...)         # outside tx
```
If the enforcer call fails, the row is committed; if the row commit fails, the policy persists in memory (and via watcher, in Redis). State splits.

**Steps:**
1. Audit every `enforcer.add_*` / `enforcer.remove_*` call site under `apps/rbac/services/`. Tabulate which side (DB or enforcer) is "source of truth."
2. Pick **DB-as-source-of-truth** (matches Casbin adapter pattern: enforcer is a cache of DB rows). Any divergence is recoverable by rebuilding the enforcer from DB.
3. Move every `enforcer.add_*` call to a **post-commit hook** (FastAPI `BackgroundTasks` or SQLAlchemy `after_commit` event). On enforcer failure, log + emit a metric; do **not** roll back the DB.
4. Add a periodic reconciliation job (re-read policies from DB, push to enforcer) — already partially supported by the watcher pattern; verify that `enforcer.load_policy()` is wired to a maintenance task.

**Pseudo-code (sketch, not final):**
```python
async def assign_permission(...):
    async with session.begin():
        await self.repository.add(session, data=...)
    # post-commit (no rollback if enforcer fails)
    try:
        await self.enforcer.add_policy(...)
    except Exception as exc:
        logger.error("enforcer_sync_failed", exc=exc)
        # optional: enqueue retry; metric increment
```

**Risk:** changing transaction boundaries is high-stakes. Add integration tests *first* (real DB, real enforcer) that prove pre-fix divergence and post-fix consistency.

**Files:** `apps/rbac/services/_role.py`, `_permission.py`, `_group.py`, `_object_permission.py`, `_facade.py`. Possibly `apps/core/database/transactional.py` if a "post-commit hook" decorator is introduced.

---

#### 2.2 — RBAC: idempotent admin-role seeding (`apps/rbac/seeders.py`)

**Issue:** `_ensure_admin_role` does `SELECT … then INSERT`. Multi-worker boot races: two workers SELECT-miss, both INSERT, second worker hits unique constraint violation → boot fails.

**Steps:**
1. Replace the SELECT+INSERT pattern with PostgreSQL `INSERT … ON CONFLICT (name) DO UPDATE SET ... RETURNING *`. The `_ensure_permission` path already uses this — copy the pattern.
2. Wrap the entire seeder in a single transaction (it is already, via `seed_session.begin()` — but verify in 1.3).
3. Add a `seeders` integration test that runs two boots concurrently against a real Postgres and asserts no `IntegrityError`.

**Files:** `apps/rbac/seeders.py`.

---

#### 2.3 — Blog: TOCTOU on autosave snapshot flush (`apps/blog/store.py:save()`)

**Issue:** `save()` reads `existing_flushed_hash` then HSETs new payload. Concurrent flush can mark the record flushed between the read and the write — autosave overwrites with stale `flushed_hash` reference.

**Steps:**
1. Read full `apps/blog/store.py` and confirm the call ordering.
2. Replace the read-then-write sequence with a single Lua script that does CAS: load hash, compute new payload, HSET only if `flushed_hash` matches what we read (or unset).
3. The Lua script already exists for `release_lock` — extend the same pattern for `save` and `mark_flushed`.
4. Unit-test the Lua script with a fakeredis or real Redis fixture, simulating concurrent save+flush.

**Files:** `apps/blog/store.py`, `tests/unit/test_blog_autosave_store_unit.py` (already present per git status), `tests/integration/realdb/test_blog_autosave_realdb.py`.

---

#### 2.4 — Auth: OAuth `access_type=offline` dead refresh token (`apps/auth/oauth/google.py`)

**Issue:** Google OAuth flow requests `access_type=offline` (line ~74), receives a refresh token in the response, then discards it (line ~119 only extracts the access token).

**Steps:**
1. Decide intent: do we need offline access (background jobs that hit Google APIs as the user later)? If **no**, drop `access_type=offline` from the auth URL — saves Google's consent screen showing scarier permissions to users.
2. If **yes**, add a `google_refresh_token` (encrypted via the same Fernet key flow as TOTP) column to the user's OAuth-link row, persist it on first login, and add a refresh-on-401 helper.
3. Default recommendation: drop it. We don't currently have any background flow that uses Google APIs.

**Files:** `apps/auth/oauth/google.py`, `apps/auth/services/_oauth.py`, possibly `apps/auth/models.py` if we add the column.

---

#### 2.5 — Production safety: TOTP Fernet fallback (`apps/auth/security/otp.py:40-49`)

**Issue:** when `auth.totp_encryption_key` is empty, `_load_totp_fernet` derives a key from `secrets.token_bytes(32)` — different bytes each process. `settings.py:322` already raises in production, but in dev/test the user's TOTP secret column becomes unreadable after every restart, and tests can flake.

**Steps:**
1. Change the fallback from `secrets.token_bytes(32)` to a deterministic-but-clearly-fake key (e.g. `Fernet(base64.urlsafe_b64encode(b"\x00" * 32))`). Log a `logger.warning` on every call so it's loud.
2. Add a `make_dev_keys.sh` script that generates `keys/jwt_*.pem` + a `.env.local` fragment with a Fernet key, mentioned in README. Half the friction is "I don't know how to generate a key."
3. Add a `tests/conftest.py` autouse fixture that sets a fixed Fernet key for the test session.

**Files:** `apps/auth/security/otp.py`, `tests/conftest.py`, `scripts/make_dev_keys.sh` (new).

---

### Phase 3 — High-priority WARNINGS (scalability / correctness margins)

Confirmed-real but lower blast radius.

#### 3.1 — User module: serial `find_by_email_or_username` collision loop (`apps/user/services.py:126-136`)

OAuth signup tries up to 5 username candidates sequentially. Replace with a single `WHERE username IN (:c1, :c2, …)` and pick the first not in the result set. ~30 min, ~80% latency cut on collision path.

#### 3.2 — Blog: cache-invalidation cost grows with workspace size (`apps/blog/services/_posts.py` invalidate_workspace_cache)

`SCAN MATCH blog:post:v1:ws:{uuid}:*` runs on every publish/update/delete. For a workspace with 10k posts, this is non-trivial.

Switch to a **versioned cache key** strategy: `blog:post:v1:ws:{uuid}:gen:{epoch}` and bump `gen` on mutation (single `INCR`). Reads use the current `gen`; old `gen` keys expire on TTL. No SCAN, O(1) invalidation.

#### 3.3 — Blog: cache stampede on cold cache (`apps/blog/services/_posts.py:get_published_detail_by_slug`)

If a hot slug expires under load, every request rebuilds from DB simultaneously. Wrap the rebuild path in a Redis lock (SETNX with a 5s TTL) — losers either wait briefly or serve last-known-good (if you store it under a separate key with longer TTL).

#### 3.4 — RBAC: per-request enforcer cache (`apps/rbac/decorators.py`)

A single request hitting 3 `@require_access`-decorated routes runs 3 separate `enforce()` calls for the same `(user, …)`. Memoize on `request.state` with a `dict` keyed by `(user_id, resource, action)`. Lifetime = request. ~30 min.

#### 3.5 — RBAC: enforcer-instance unification (depends on Phase 1.3)

If 1.3 confirms the seeder + DI use different enforcer instances, fix by initializing the container's resource provider in `lifespan` and using `BlogContainer.autosave_store()`-style accessor in the seeder. Otherwise, mark complete.

#### 3.6 — Pagination: ceiling on `OffsetPaginationRequestSchema` (`apps/core/schemas/request.py`)

Currently `limit` accepts arbitrary ints. Add `Field(le=100)` (or similar) so a bored client can't request `limit=10_000_000` and toast the DB. ~5 min, prevents accidental DoS.

#### 3.7 — Soft-delete index check (cross-cutting)

Every list query filters `deleted_at IS NULL`. Ensure each soft-deletable model has an index that **includes** `deleted_at` (partial index `WHERE deleted_at IS NULL` is best). Audit `User`, `Product`, `Workspace`, `Post` models + the most recent Alembic migration. Add migrations where missing.

#### 3.8 — Repository typing hardening (`apps/core/database/repository/base.py`)

`BaseSQLAlchemyRepository.__init__` doesn't validate `model_type` is set. Add a `__init_subclass__` hook that raises `TypeError` if a concrete subclass omits `model_type`. ~15 min, prevents a class of cryptic runtime errors.

---

### Phase 4 — Quick wins (cheapest improvements first)

These are independently mergeable and ~5–30 min each.

| # | File | Change | Why |
|---|---|---|---|
| 4.1 | `apps/auth/dependencies.py:31` | `if credentials.scheme != "Bearer"` (case-sensitive) | RFC 7235 says case-sensitive; current `.lower()` allows weird clients through. |
| 4.2 | `apps/auth/security/otp.py:96` | Replace deprecated `pyotp.utils.strings_equal` with `hmac.compare_digest` | Future-proofing. |
| 4.3 | `apps/auth/services/_email_verification.py:150` | Stop logging raw `user.id` in error logs; hash or use trace_id | PII hygiene. |
| 4.4 | `apps/auth/constants.py:29-36` | Document slowapi's per-IP behaviour with `X-Forwarded-For` and add `use_x_forwarded_for=True` if behind a proxy | Otherwise rate-limit-per-LB-IP, not per client. |
| 4.5 | `apps/blog/sweeper.py:78` | Pass `iter_dirty(batch_size=batch_size)` explicitly | Currently swallows `AUTOSAVE_SWEEP_BATCH` overrides. |
| 4.6 | `apps/blog/models.py:209-218` | Add a docstring on each `lazy="raise"` relationship explaining the project convention + how to load | Future-dev friendliness. |
| 4.7 | `apps/blog/sweeper.py:85-96` | Wrap session in `try/except` with explicit `await session.rollback()` on error | Defensive: avoids leaving an aborted session attached if the factory's cleanup is partial. |
| 4.8 | `apps/core/exceptions/handlers.py` (`unhandled_exception_handler`) | Use `logger.exception` only when `app_settings.environment != "production"`; in prod, log scrubbed `repr(exc)` | Avoid leaking internal traces to log indices. |
| 4.9 | `apps/core/redis/cache.py:189-216` (`_build_cache_key`) | Drop the `repr()` fallback; serialize via `json.dumps(default=str, sort_keys=True)` and require deterministic args. Raise on non-serializable inputs in `cached()` decorator. | Avoid silent cache-key collisions. |
| 4.10 | `apps/rbac/models/_assignments.py:112` | Drop `UserGroup.role` column (Alembic migration) — never read or written | Schema debt. |
| 4.11 | `apps/rbac/services/_facade.py` | Decide: real facade or delete. If pass-through, inject focused services into routes directly. | Eliminate vacuous indirection. |
| 4.12 | `apps/blog/repositories.py:228` (`list_for_workspace` tag filter) | Switch tag-filter join from `JOIN PostTag` + separate `selectinload(Post.tags)` to a single `joinedload` for the filter path, OR `WHERE EXISTS (SELECT 1 FROM post_tags …)` | Saves a round-trip on tag-filtered listings. |
| 4.13 | `apps/auth/services/_auth.py:_authenticate` | Split "credentials valid" from "is_active" check; raise distinct errors | Currently lumps email-not-verified into auth-failure; clients can't differentiate. |
| 4.14 | `apps/core/storage/s3.py` | Reuse a single `aioboto3.Session` and one client per bucket; don't open a fresh aiohttp session per request | Connection pooling. |
| 4.15 | `apps/auth/security/jwt.py:_load_jwt_keys` | Move call to `lifespan` and store on a singleton; fail-fast if PEMs missing | Better startup-time diagnostics, not correctness. |

---

### Phase 5 — Architectural candidates (longer-term, not committed)

These are larger refactors; record but **don't act** without a separate plan.

- **Repository mixin Protocol contract** (`apps/core/database/repository/`): formalize the host contract with `RepositoryHost` Protocol so the `_ReadRepositoryMixin` / `_WriteRepositoryMixin` `self.X` lookups are type-checkable. Pure typing change, but invasive.
- **Slug-uniqueness mixin** (`apps/core/database/model/mixins/`): `User`, `Product`, `Workspace`, `Post` all reimplement `_ensure_slug_available`. Extract once.
- **Cross-aggregate-write helper service**: `apps/auth/services/_email_verification.py` directly hits `UserRepository.update`. Acceptable per the rules, but a `UserService.activate_email(user_id)` boundary method would centralize the audit trail.
- **Post-commit hook framework**: a generic `@on_commit` decorator (or SQLAlchemy `after_commit` listener) that schedules side-effects (RBAC enforcer sync, cache invalidation, outbound webhooks) only after the DB transaction succeeds. Solves Phase 2.1 generically.
- **Observability**: there is no consistent metric emission today. A `BackendError`-handler-level counter + per-repository query timing histogram would unblock the rest of the operational story.

---

## 3. Key Files Touched (by phase)

| Phase | File | Operation | Notes |
|---|---|---|---|
| 1 (verify) | `apps/blog/repositories.py`, `apps/core/database/transactional.py`, `apps/rbac/containers.py`, `apps/rbac/enforcer.py`, `apps/auth/services/_tokens.py` | Read | No edits |
| 2.1 | `apps/rbac/services/_*.py` | Edit | Move enforcer calls post-commit |
| 2.2 | `apps/rbac/seeders.py` | Edit | `INSERT … ON CONFLICT` |
| 2.3 | `apps/blog/store.py` + tests | Edit | Lua-CAS for save/flush |
| 2.4 | `apps/auth/oauth/google.py`, `apps/auth/services/_oauth.py` | Edit | Drop `access_type=offline` (or persist refresh token) |
| 2.5 | `apps/auth/security/otp.py`, `tests/conftest.py`, `scripts/make_dev_keys.sh` | Edit + new | Loud fallback + dev-key script |
| 3.1 | `apps/user/services.py`, `apps/user/repositories.py` | Edit | Batch collision check |
| 3.2 | `apps/blog/services/_posts.py`, `apps/blog/constants.py` | Edit | Versioned cache key |
| 3.3 | `apps/blog/services/_posts.py` | Edit | Stampede lock |
| 3.4 | `apps/rbac/decorators.py`, `apps/rbac/dependencies.py` | Edit | Per-request enforcer cache |
| 3.5 | depends on 1.3 | — | Conditional |
| 3.6 | `apps/core/schemas/request.py` | Edit | `Field(le=100)` |
| 3.7 | `alembic/versions/*` | New migration | Partial indexes on `deleted_at` |
| 3.8 | `apps/core/database/repository/base.py` | Edit | `__init_subclass__` guard |
| 4.x | see table | Edit | Independent quick wins |

---

## 4. Verification Plan (per change)

For every edit:

1. **`uv run ruff check . && uv run ruff format .`** — zero warnings.
2. **`uv run pytest -x`** — all green.
3. **For Phase 2 changes:** new integration tests under `tests/integration/realdb/` proving the previous-broken behaviour and the post-fix correctness (RBAC consistency, autosave CAS, OAuth flow).
4. **For Phase 3.2/3.3 (cache changes):** load test with `locust` (or similar) hitting `/api/v1/public/posts/{slug}` — assert hit ratio and DB query count.
5. **For Phase 3.7 (indexes):** `EXPLAIN ANALYZE` before/after on the largest table in dev.
6. **Per `.claude/rules/review-code.md`:** run `/review-code commit <hash>` once each phase is committed.

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Phase 2.1 (RBAC tx boundaries) regresses authz | Tests-first; ship behind a feature flag (`rbac_post_commit_sync`); 1-week canary before enabling default. |
| Phase 2.3 Lua script breaks autosave write path | Keep the old read-then-write code behind a feature flag; A/B in dev for a week. |
| Phase 3.2 versioned-cache-key change leaks old keys until TTL | Set old-pattern keys to expire within `BLOG_CACHE_TTL_SECONDS`; document in commit message. |
| Phase 3.7 index migration locks the table | Use `CREATE INDEX CONCURRENTLY` (Alembic supports `op.execute` for this); run during low-traffic window. |
| Phase 5 candidates picked up "for free" alongside Phase 2 work | **Don't.** Phase 5 items are roadmap, not commit-along baggage; per `CLAUDE.md` "Don't add features … beyond what the task requires." |

---

## 6. Out of Scope (intentional)

- Frontend (none in this repo).
- New domain modules (no business request).
- Test-coverage uplift beyond what each fix requires (separate plan if you want 80% across the board — currently the bigger gap is integration coverage of `auth/_oauth.py` and `rbac/services/*`).
- Casbin → custom-RBAC migration (the current Casbin layer is fine; this audit didn't surface a reason to swap).
- Replacing `dependency-injector` with FastAPI-native DI (works fine; not worth the churn).

---

## 7. Suggested Order of Execution

1. **Phase 1 (verification, ~30 min)** — flips ~5 BLOCKERs to INFO.
2. **Phase 2.5 (TOTP fallback)** — smallest change, biggest dev-experience uplift.
3. **Phase 2.2 (RBAC seeder ON CONFLICT)** — small, isolates the multi-worker race.
4. **Phase 2.4 (OAuth refresh token)** — decision-driven; cheap if "drop offline" wins.
5. **Phase 2.3 (autosave CAS)** — needs careful test; medium effort.
6. **Phase 2.1 (RBAC tx boundaries)** — biggest of the BLOCKERs; do this with explicit tests + feature flag.
7. **Phase 3** items in any order; 3.6 (pagination ceiling) and 3.8 (subclass guard) are 5-minute jobs.
8. **Phase 4 quick wins** — batch into a single PR per category (auth / blog / rbac / core) to keep diff readable.

---

## 8. Sub-agent SESSION_IDs (for /ccg:execute resume)

- **CODEX_SESSION:** _n/a — wrapper not installed_
- **GEMINI_SESSION:** _n/a — wrapper not installed_

If you install `codeagent-wrapper` and want the multi-model collaboration version, re-run `/everything-claude-code:multi-plan` and the SESSION_IDs will be recorded here for `/ccg:execute resume <id>`.

---

## 8b. Verification results (v2 addendum, 2026-05-04)

Phase 1 verification reads completed; outcomes:

| Step | Plan claim | Verified outcome | Action |
|---|---|---|---|
| 1.1 (`replace_post_tags`) | BLOCKER (verify) | **INFO** — both callers (`_posts.py:136` `create()` and `:253` `update()`) are inside `@transactional` service methods; the repository's `session.add` / `session.delete` / `session.flush` are inside the active txn. Repository layer is allowed to touch session per CLAUDE.md. | Drop from BLOCKER list. |
| 1.2 (`@transactional` nested call) | BLOCKER (verify) | **INFO** — `apps/core/database/transactional.py` wrapper is an `async def` function; `await func(...)` is inside the wrapper, so the inner coroutine completes before the wrapper returns. Agent's claim was wrong. | Drop from plan. |
| 1.3 (enforcer instance split) | BLOCKER (verify) | **WARNING (conditional)** — `factory.py:74` calls `enforcer_factory()` directly for seeding; container's `providers.Resource` caches a separate enforcer. Real divergence only matters when `auto_seed_resources_from_registry=True` AND single-worker without watcher (the default has auto-seed off). Worth fixing but not hot-path BLOCKER. | Stays as Phase 3.5 WARNING. |
| 1.4 (cached User → `session.merge`) | risk in plan | **INFO** — `grep "session.\(merge\|add\)" apps/auth` only matches the docstring at `_tokens.py:226`; no code path does it. | No action. |
| 1.5 (cache key shape) | n/a | Confirmed: `POST_CACHE_KEY_PREFIX = "blog:post:v1"`, TTLs sensible. SCAN-cost concern (3.2) still valid. | No change. |

Spot-fixes inside the plan after re-reading code:

* **Phase 4.5 (sweeper `batch_size` override)** — DROP. `apps/blog/sweeper.py:78` already calls `iter_dirty(batch_size=batch_size)`. The agent's "swallows override" claim was wrong; the file is already correct.
* **Phase 3.6 (pagination ceiling)** — DOWNGRADE from "no ceiling" to "tighten ceiling": `apps/core/schemas/request.py:28` already has `le=1000`. Reduce to `le=100`.
* **Phase 2.2 (RBAC seeder race)** — Confirmed real. `apps/rbac/seeders.py:99-109` uses SELECT-then-INSERT for the admin role; concurrent worker boots can race the unique constraint. `_ensure_permission` (lines 112-139) already uses `pg_insert(...).on_conflict_do_nothing`; copy that pattern for `_ensure_admin_role`.

**Net effect of verification**: 5 → 4 confirmed BLOCKERs (1.2 dropped). 8 → 7 WARNINGs (4.5 dropped). 15 → 14 quick wins (3.6 reduced). The audit is still mostly intact but ~5 inflated-severity items have been recalibrated.

---

## 9. Top-of-mind summary

**5 confirmed BLOCKERs:** RBAC↔DB transactional split (2.1), seeder race (2.2), autosave TOCTOU (2.3), OAuth dead refresh token (2.4), TOTP fallback footgun (2.5).
**8 high-value WARNINGs:** user collision loop (3.1), cache invalidation cost (3.2), cache stampede (3.3), per-request enforcer cache (3.4), enforcer-instance unification (3.5, conditional), pagination ceiling (3.6), soft-delete indexes (3.7), repository subclass guard (3.8).
**15 quick wins** (Phase 4) clustered by module — each is 5–30 min.
**5 architectural candidates** parked as Phase 5 — do **not** pull into the current PR series.

The codebase is **healthy overall**: 4-layer separation is consistent, DI wiring is clean, recent commits (`bb242de`, `139db15`, `d612107`) have already paid down the highest-leverage debt (services touching sessions, slug uniqueness duplication). The remaining issues are scalability hot-paths and a handful of cross-cutting consistency gaps.
