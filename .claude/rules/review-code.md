---
description: Review code changes in a git commit against FastAPI Base coding rules. Usage — /review-code commit {hash}
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

- **Router** (`apps/*/routes.py`)
- **Service** (`apps/*/services.py`)
- **Repository** (`apps/*/repositories.py`)
- **ORM Model** (`apps/*/models.py`)
- **Schema** (`apps/*/schemas.py`)
- **Exception** (`apps/*/exceptions.py`)
- **DI Container** (`apps/*/containers.py`)
- **Core Database** (`apps/core/database/sql/*.py`)
- **Core Middleware** (`apps/core/middlewares/*.py`)
- **Core Schema** (`apps/core/schemas/*.py`)
- **Core Service** (`apps/core/services/*.py`)
- **Migration** (`alembic/versions/*.py`)
- **Configuration** (`*.toml`, `*.cfg`, `*.ini`, `*.env*`)
- **Other** (tests, utils, etc.)

### 5. Review against ALL rule categories

For EACH changed file, check against the applicable rules below. Only check rules that are **relevant to the file type**.

---

#### 5.1 — Layered Architecture (01)

- [ ] **Layer dependency direction**: No upward imports (Repository -> Router FORBIDDEN)
- [ ] **Router uses `@inject`** decorator on every route function with DI
- [ ] **Router injects Service** via `Depends(Provide[{Module}Container.{service}])`, NOT manual instantiation
- [ ] **Router returns Pydantic schemas**, never ORM models
- [ ] **DI Container** declares `providers.Factory` for services and repositories
- [ ] **Service uses Repository** for data access, not raw session queries
- [ ] **Service does NOT import** Router layer
- [ ] **Repository** extends `BaseSQLAlchemyRepository`, no business logic
- [ ] **Model** inherits from project bases (`UUIDAuditBase`, etc.)
- [ ] **Module structure** follows convention (models, repos, services, routes, schemas, exceptions, containers)

#### 5.2 — Naming Conventions (02)

- [ ] **Classes**: PascalCase
- [ ] **Functions/methods**: snake_case
- [ ] **Variables**: snake_case
- [ ] **Constants**: UPPER_SNAKE_CASE
- [ ] **Component naming**: follows pattern table (`UserService`, `UserRepository`, etc.)
- [ ] **Booleans**: prefixed with `is_`, `has_`, `can_`, `should_`
- [ ] **No abbreviations**: `usr_svc` -> `user_service`
- [ ] **ALL code, comments, variables in English** — no Vietnamese

#### 5.3 — Clean Code (03)

- [ ] **Type hints** on all function parameters and return values
- [ ] **Modern Python syntax**: `str | None` not `Optional[str]`
- [ ] **Early return pattern**: no deep nesting, guard clauses at top
- [ ] **Keyword-only args** for optional parameters (after `*`)
- [ ] **Function length** <= 50 lines
- [ ] **Parameters** <= 3 positional
- [ ] **Nesting depth** <= 2 levels
- [ ] **Class length** <= 500 lines
- [ ] **Async-first**: `async/await` for all I/O operations

#### 5.4 — Database & Persistence (04)

- [ ] **No N+1 queries**: uses `.in_()` + dict for batch loading
- [ ] **Filter at DB level**, not in Python after loading all
- [ ] **Eager loading**: `selectinload()` / `joinedload()` for relationships
- [ ] **Session via `Depends(session_factory)`** — no manual session creation
- [ ] **`@Transactional`** for multi-statement writes
- [ ] **`Mapped[type]`** annotations for all columns (SQLAlchemy 2.x)
- [ ] **Indexed columns** in `WHERE`, `JOIN`, `ORDER BY`

#### 5.5 — System Design (05)

- [ ] **Async-first**: no blocking calls in async context
- [ ] **Idempotent consumers** for messaging
- [ ] **Cache keys have TTL** — no infinite cache
- [ ] **List endpoints** are paginated or bounded
- [ ] **Error handling** via `BackendError` subclasses

#### 5.6 — Decorators & Middleware (06)

- [ ] **Cross-cutting concerns** use decorators/middleware, not inline code
- [ ] **`@Transactional`** for write operations
- [ ] **Decorators NOT used** for core business logic
- [ ] **`Depends()`** for route-specific DI

#### 5.7 — Code Quality (07)

- [ ] **Logging**: `loguru`, format `{ClassName} - {method_name} - {message}`
- [ ] **No `print()` statements** in application code
- [ ] **Error codes**: defined as `StrEnum` in module `exceptions.py`
- [ ] **No hardcoded config values**: use `pydantic-settings`
- [ ] **No commented-out code**
- [ ] **No inline comments** explaining what (only comment complex WHY)
- [ ] **Google-style docstrings** on public functions

#### 5.8 — API & Schema Patterns (08)

- [ ] **Request schemas** have validation (`Field`, `field_validator`)
- [ ] **Response schemas** have NO validation — serialization only
- [ ] **`APIResponse` wrapper** for all API responses
- [ ] **NEVER return ORM models** from API endpoints
- [ ] **Pagination** for list endpoints
- [ ] **`model_validate(obj, from_attributes=True)`** for ORM -> schema

---

### 6. Generate the Review Report

Output the review as a structured report:

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
| Transaction Safety | Medium | {description or N/A} |
| Layer Violation | High | {description or N/A} |
| Security | High | {description or N/A} |
| Async Safety | Medium | {description or N/A} |
| Naming | Low | {description or N/A} |

---

## Merge Decision

- **BLOCKER violations** -> DO NOT MERGE — must fix first
- **WARNING violations** -> MERGE WITH CAUTION — should fix soon
- **INFO only** -> READY TO MERGE
```

### 7. Severity Classification

| Level | Meaning | Merge? |
|---|---|---|
| **BLOCKER** | Architecture violation, N+1 query, security risk, blocking call in async, missing type hints on public API | Must fix |
| **WARNING** | Naming convention miss, function too long, missing docstring, hardcoded message | Should fix |
| **INFO** | Style preference, comment suggestion, minor naming improvement | Can merge |

### 8. Final output

After generating the full report, clearly state the **final verdict**:

- If ANY BLOCKER exists -> state: **"BLOCKED — {N} blocker(s) must be fixed before merge"**
- If only WARNING -> state: **"MERGE WITH CAUTION — {N} warning(s) should be addressed"**
- If clean -> state: **"READY TO MERGE — All rules passed"**
