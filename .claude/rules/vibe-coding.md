---
description: Vibe coding rules for FastAPI Base — Python 3.13+ / FastAPI / SQLAlchemy 2.x / Layered Architecture. Apply these rules for ALL coding tasks.
---

# FastAPI Base — Vibe Coding Rules

> **Act as a Senior Python Architect.** Write code using Python 3.13+ and FastAPI. Follow SOLID principles and Clean Code. Use constructor injection via `dependency-injector`, Pydantic v2 for schemas, and SQLAlchemy 2.x async for ORM. Ensure all queries avoid N+1 issues. Use `StatementFilter` subclasses for composable query filtering. For any async tasks, use `asyncio` with proper structured concurrency. Separate cross-cutting concerns using decorators and middleware. Always prioritize "Early Return" and meaningful naming without abbreviations.

## STRICTLY FORBIDDEN

> **These rules have THE HIGHEST PRIORITY. Violating any of them is UNACCEPTABLE.**

1. **NO GUESSING:** When the requirement, business rule, or approach is **unclear or ambiguous**, you **MUST STOP and ask the user to confirm** before proceeding. NEVER assume, invent logic, or fill in gaps on your own.

2. **NO CODING WITHOUT UNDERSTANDING:** NEVER implement a feature or fix a bug if you **do not fully understand** what the code should do. If you are uncertain about the expected behavior, the business context, or the root cause of a bug — **STOP and ask for clarification first.**

3. **NO SKIPPING CONFIRMATION:** NEVER skip the confirmation step. Every plan, every assumption, every ambiguous decision **MUST be confirmed by the user** before writing any code.

**If in doubt -> STOP -> ASK -> WAIT -> then proceed.**

## Rule Files

Apply ALL rules from `.claude/rules/`:

| File | Scope |
|---|---|
| `01-layered-architecture.md` | 4-layer, dependency direction, layer responsibilities |
| `02-naming-conventions.md` | Component naming, PEP 8, anti-patterns |
| `03-clean-code.md` | Type hints, immutability, early return, function/class limits |
| `04-database-persistence.md` | N+1, sessions, transactions, SQLAlchemy 2.x patterns |
| `05-system-design.md` | Async patterns, caching, background jobs, concurrency |
| `06-decorators-middleware.md` | Decorators, middleware, Depends() patterns |
| `07-code-quality.md` | Logging, messages, config, comments, language |
| `08-api-schema-patterns.md` | API conventions, Pydantic schemas, pagination, Alembic |

## Quick Reference

- **Stack:** Python 3.13+, FastAPI, SQLAlchemy 2.x (async), Pydantic v2, pydantic-settings
- **Architecture:** Layered — Router -> Service -> Repository -> Model
- **Implementation order:** Model -> Repository -> Service -> Router (bottom-up)

## MANDATORY WORKFLOW

**NEVER write code before completing all steps below.**

### Step 1 — PLAN

Before any implementation, you MUST:

1. Research the codebase to fully understand the context
2. Produce a written implementation plan that includes:
   - **Goal:** What does this change accomplish?
   - **Proposed Changes:** List every file to create/modify/delete, grouped by layer (Model -> Repository -> Service -> Router)
   - **DB Migration:** Is an Alembic migration needed? If yes, specify description and schema changes
   - **Verification:** How will you verify the change is correct?
3. Present the plan to the user and **WAIT for explicit confirmation**

### Step 2 — CONFIRM

- **DO NOT write any code** until the user explicitly says "OK", "Proceed", "Continue", or equivalent approval
- If user requests changes to the plan -> update the plan and request confirmation again
- Only after confirmation, move to Step 3

### Step 3 — IMPLEMENT

- Follow the confirmed plan exactly, layer by layer: Model -> Repository -> Service -> Router
- Run `uv run ruff check .` and `uv run ruff format .` after implementation
- Report completed changes to user

## Pre-Commit Checklist

- [ ] Layer dependencies correct (no upward imports)
- [ ] Routers use `@inject` + `Depends(Provide[Container.service])` for DI
- [ ] Routers inject Services via DI container, not Repositories
- [ ] All functions have type hints
- [ ] ORM models use `Mapped[type]` annotations
- [ ] Pydantic schemas for all request/response — never return ORM models
- [ ] `@Transactional` for multi-statement writes
- [ ] Logging: `loguru`, format `{ClassName} - {method_name} - {message}`
- [ ] All code in English
- [ ] Error codes defined as `StrEnum` in module `exceptions.py`
- [ ] Config from env vars via `pydantic-settings`, never hardcoded
- [ ] No N+1 queries — batch queries with `.in_()` + dict
- [ ] Functions <= 50 lines, <= 3 positional params, <= 2 nesting levels
- [ ] Indexed columns used in `WHERE`/`JOIN`/`ORDER BY`
- [ ] New env vars -> update `.env.example`
- [ ] Alembic migration if schema changed
- [ ] `async/await` for all I/O-bound operations
- [ ] `ruff check` and `ruff format` pass cleanly
