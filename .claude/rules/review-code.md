---
description: Review code changes in a git commit against FastAPI Base coding rules. Usage - /review-code commit {hash}
---

# Review Code — FastAPI Base

Review a git commit against ALL coding rules defined in `.claude/rules/`.

## Workflow Steps

### 1. Extract the commit hash

The user will provide: `/review-code commit {hash}`

Extract `{hash}` from the user message. If no hash is provided, ask the user to specify one.

### 2. Read ALL rule files

Before reviewing, read ALL rule files to have the full context:

```
.claude/rules/01-layered-architecture.md
.claude/rules/02-naming-conventions.md
.claude/rules/03-clean-code.md
.claude/rules/04-database-persistence.md
.claude/rules/05-system-design.md
.claude/rules/06-decorators-middleware.md
.claude/rules/07-code-quality.md
.claude/rules/08-api-schema-patterns.md
```

### 3. Get the commit diff

Run:

```bash
git show {hash} --stat
```

Then get the full diff:

```bash
git show {hash} --format="%H%n%an%n%s%n%b" --no-color
```

If the diff is very large (many files), review file by file using:

```bash
git show {hash} -- {file_path}
```

### 4. Identify changed file types

Categorize each changed file by its layer/type:

- **Route** (`apps/*/routes.py`)
- **Service** (`apps/*/services.py`)
- **Repository** (`apps/*/repositories.py`)
- **Model** (`apps/*/models.py`)
- **Schema** (`apps/*/schemas.py`)
- **Container** (`apps/*/containers.py`)
- **Exception** (`apps/*/exceptions.py`)
- **Settings** (`apps/settings.py`)
- **DB Infrastructure** (`libs/database/**`)
- **Shared Schema** (`libs/schemas/**`)
- **Shared Exception** (`libs/exceptions/**`)
- **Middleware** (`libs/middlewares/**`)
- **Migration** (`alembic/versions/*.py`)
- **Configuration** (`*.yml`, `*.toml`, `*.cfg`)
- **Other** (tests, utils, etc.)

### 5. Review against ALL rule categories

For EACH changed file, check against the applicable rules below. Only check rules that are **relevant to the file type**.

---

#### 5.1 — Layered Architecture (01)

- [ ] **Layer dependency direction**: No upward imports (Repository → Route is FORBIDDEN)
- [ ] **Routes inject Services** via `Depends(Provide[Container.service])`
- [ ] **Routes return Pydantic schemas** wrapped in `APIResponse`, never ORM models
- [ ] **Services use Repositories** for DB access, never direct SQLAlchemy queries
- [ ] **Services return Pydantic response schemas**, not ORM models
- [ ] **Repositories extend `BaseSQLAlchemyRepository`** and define `model_type`
- [ ] **Models** are SQLAlchemy declarative with `Mapped` type hints
- [ ] **Shared code** in `libs/`, module code in `apps/{module}/`

#### 5.2 — Naming Conventions (02)

- [ ] **PEP 8**: Classes `PascalCase`, functions/variables `snake_case`, constants `UPPER_SNAKE_CASE`
- [ ] **Component naming**: Service, Repository, Schema follow patterns from rule 02
- [ ] **Methods**: verb + snake_case, meaningful names, no abbreviations
- [ ] **Booleans**: prefixed with `is_`, `has_`, `can_`, `should_`
- [ ] **No redundancy**: e.g., `User.user_email` → should be `User.email`
- [ ] **ALL code, comments, variables in English** — no Vietnamese

#### 5.3 — Clean Code (03)

- [ ] **Type hints** on ALL parameters and return values
- [ ] **Constructor injection** — no global mutable state
- [ ] **Early return pattern**: guard clauses at top, no deep nesting
- [ ] **Keyword-only arguments** for service/repository methods (after `*`)
- [ ] **Function length** ≤ 50 lines (target 20–35)
- [ ] **Function parameters** ≤ 3 (else use schema/dataclass)
- [ ] **Nesting depth** ≤ 2 levels
- [ ] **Class length** ≤ 500 lines

#### 5.4 — Database & Persistence (04)

- [ ] **No N+1 queries**: uses `.in_()` + dict for batch loading
- [ ] **Filter at DB level** with `.where()`, not Python after loading all
- [ ] **Relationship loading**: `selectin` or `joinedload` for eager loading
- [ ] **SELECT FOR UPDATE** only for critical concurrent operations
- [ ] **Session lifecycle**: via `session_factory()` dependency, no manual `commit()`
- [ ] **Read/write split**: `RoutingSession` handles routing — no manual engine selection
- [ ] **SQLAlchemy 2.x style**: `select()` + `session.execute()`, not legacy `Query` API
- [ ] **No raw SQL** unless documented and justified

#### 5.5 — System Design (05)

- [ ] **Async-first**: all I/O uses `async/await`
- [ ] **No sync HTTP clients** (`requests`) in async context — use `httpx.AsyncClient`
- [ ] **Cache keys have TTL** — no infinite cache
- [ ] **Distributed locks** for scheduled jobs in multi-instance
- [ ] **List endpoints** are paginated
- [ ] **Race conditions** checked in find-or-create flows

#### 5.6 — Decorators & Middleware (06)

- [ ] **Cross-cutting concerns** (logging, audit, perf) use decorators or middleware
- [ ] **Auth** handled via FastAPI `Depends()` dependencies
- [ ] **Decorators NOT used** for core business logic

#### 5.7 — Code Quality (07)

- [ ] **Logging**: `{ClassName} - {method_name} - {message}` with `logging` module
- [ ] **No `print()` calls** — use `logging` or `loguru`
- [ ] **Error handling**: `BackendError` subclasses with module-specific error codes
- [ ] **No hardcoded config values**: use `pydantic-settings` from environment
- [ ] **Import order**: stdlib → third-party → local
- [ ] **No commented-out code**
- [ ] **Google-style docstrings** on all public functions

#### 5.8 — API & Schema Patterns (08)

- [ ] **API path convention** matches project patterns
- [ ] **Request schemas** have `Field()` validation
- [ ] **Response schemas** use `from_attributes=True` via `ResponseObjectSchema`
- [ ] **Sensitive fields** (password, tokens) NOT in response schemas
- [ ] **`model_dump(exclude_unset=True)`** for partial updates
- [ ] **`model_validate()`** to convert ORM → response schema

#### 5.9 — Alembic Migration (08)

- [ ] **Auto-generated** with descriptive message
- [ ] **Both upgrade and downgrade** functions present
- [ ] **Column types, indexes, constraints** verified after auto-generation
- [ ] **Not modified** after applying to shared environments

---

### 6. Generate the Review Report

Output the review as a structured report using this template:

```markdown
# Code Review Report

**Commit:** `{hash}`
**Author:** {author}
**Message:** {commit_message}
**Files Changed:** {count}

---

## Overall Verdict

> **{MERGE_BLOCKED / MERGE_WITH_CAUTION / READY_TO_MERGE}**
> {Summary reason}

---

## Rules Passed

| # | Rule Category | Status |
|---|---|---|
| 1 | Layered Architecture | Pass |
| 2 | Naming Conventions | Pass |
| ... | ... | ... |

## Violations Found

### [{Severity: BLOCKER / WARNING / INFO}] {Rule Category} — {Specific Rule}

**File:** `{file_path}`
**Line(s):** {line_range}
**Description:** {what is wrong}
**Rule Reference:** {rule_file} — {specific rule text}
**Suggested Fix:**
```python
# corrected code
```

(Repeat for each violation)

---

## Risk Assessment

| Risk | Level | Details |
|---|---|---|
| N+1 Query | High | {description or N/A} |
| Session Safety | Medium | {description or N/A} |
| Layer Violation | High | {description or N/A} |
| Security | High | {description or N/A} |
| Concurrency | Medium | {description or N/A} |
| Naming | Low | {description or N/A} |

---

## Merge Decision

- **BLOCKER violations** → **DO NOT MERGE** — must fix first
- **WARNING violations** → **MERGE WITH CAUTION** — should fix soon
- **INFO only** → **READY TO MERGE**
```

### 7. Severity Classification

| Level | Meaning | Merge? |
|---|---|---|
| **BLOCKER** | Architecture violation, N+1 query, security risk, session misuse, missing type hints | Must fix |
| **WARNING** | Naming convention miss, function too long, hardcoded message, missing docstring | Should fix |
| **INFO** | Style preference, minor naming improvement, optional optimization | Can merge |

### 8. Final output

After generating the full report, clearly state the **final verdict**:

- If ANY BLOCKER exists → state: **"BLOCKED — {N} blocker(s) must be fixed before merge"**
- If only WARNING → state: **"MERGE WITH CAUTION — {N} warning(s) should be addressed"**
- If clean → state: **"READY TO MERGE — All rules passed"**
