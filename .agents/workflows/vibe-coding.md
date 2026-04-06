---
description: Vibe coding rules for KOFOS Backend - Java 21 / Spring Boot 3.x / DDD Architecture. Apply these rules for ALL coding tasks.
---

# KOFOS Backend — Vibe Coding Rules

> **Act as a Senior Java Architect.** Write code using Java 21 and Spring Boot 3. Follow SOLID principles and Clean Code. Use Constructor Injection, MapStruct for DTOs, and Records for data containers. Ensure all JPA queries avoid N+1 issues. Apply Optimistic Locking with `@Version`. For any async tasks, use Virtual Threads. Separate cross-cutting concerns using AOP and Custom Annotations. Always prioritize "Early Return" and meaningful naming without abbreviations.

## 🚨 STRICTLY FORBIDDEN — NGHIÊM CẤM

> **These rules have THE HIGHEST PRIORITY. Violating any of them is UNACCEPTABLE.**

1. **🚫 CẤM TỰ BỊA / NO GUESSING:** When the requirement, business rule, or approach is **unclear or ambiguous**, you **MUST STOP and ask the user to confirm** before proceeding. NEVER assume, invent logic, or fill in gaps on your own.

2. **🚫 CẤM CODE KHI CHƯA HIỂU / NO CODING WITHOUT UNDERSTANDING:** NEVER implement a feature or fix a bug if you **do not fully understand** what the code should do. If you are uncertain about the expected behavior, the business context, or the root cause of a bug — **STOP and ask for clarification first.**

3. **🚫 CẤM BỎ QUA CONFIRM:** NEVER skip the confirmation step. Every plan, every assumption, every ambiguous decision **MUST be confirmed by the user** before writing any code.

**If in doubt → STOP → ASK → WAIT → then proceed.**

## Rule Files

Apply ALL rules from `.agents/workflows/rules/`:

| File | Scope |
|---|---|
| `01-ddd-architecture.md` | DDD 4-layer, dependency direction, layer responsibilities |
| `02-naming-conventions.md` | Component naming, Java naming, anti-patterns |
| `03-clean-code.md` | Records, injection, early return, function/class limits |
| `04-database-persistence.md` | N+1, locking, transactions, JPQL text blocks |
| `05-system-design.md` | Messaging, Redis/cache, background jobs, virtual threads |
| `06-aop-annotations.md` | Custom annotations, @TrackAction pattern |
| `07-code-quality.md` | Logging, messages, config, comments, language |
| `08-api-dto-patterns.md` | API roles, DTO 3-tier, Command/Query/Context, Liquibase |

## Quick Reference

- **Stack:** Java 21+, Spring Boot 3.x, Lombok, MapStruct, Liquibase
- **Architecture:** DDD 4-layer — Presentation → Application → Domain → Infrastructure
- **Implementation order:** Domain → Infrastructure → Application → Presentation

## 🔴 MANDATORY WORKFLOW — BẮT BUỘC THỰC HIỆN

**NEVER write code before completing all steps below.**

### Step 1 — PLAN (Lên kế hoạch)
Before any implementation, you MUST:
1. Research the codebase to fully understand the context
2. Produce a written implementation plan that includes:
   - **Goal:** What does this change accomplish?
   - **Proposed Changes:** List every file to create/modify/delete, grouped by layer (Domain → Infrastructure → Application → Presentation)
   - **DB Migration:** Is a Liquibase migration needed? If yes, specify filename and schema changes
   - **Verification:** How will you verify the change is correct?
3. Present the plan to the user via `notify_user` and **WAIT for explicit confirmation**

### Step 2 — CONFIRM (Xác nhận)
- **DO NOT write any code** until the user explicitly says "OK", "Proceed", "Continue", or equivalent approval
- If user requests changes to the plan → update the plan and request confirmation again
- Only after confirmation, move to Step 3

### Step 3 — IMPLEMENT (Thực thi)
- Follow the confirmed plan exactly, layer by layer: Domain → Infrastructure → Application → Presentation
- **🚫 DO NOT run `mvn compile` or any build commands** — user will build manually to save system resources
- Report completed changes to user


## Pre-Commit Checklist

- [ ] Layer dependencies correct (no upward imports)
- [ ] Controllers inject Adapters, not Services
- [ ] Domain models are pure POJO (no JPA)
- [ ] Presentation DTOs have validation; Application DTOs do not
- [ ] `@Transactional` for multi-DML; no internal `@Transactional` calls
- [ ] Logging: `ClassName - methodName - message`
- [ ] All code in English
- [ ] Error messages via `MessageService`; config from env vars
- [ ] JPQL/SQL: Java 21 text blocks
- [ ] No N+1 — batch queries with `findByIdIn` + Map
- [ ] Functions ≤50 lines, ≤3 params, ≤2 nesting
- [ ] `@Version` on entities for optimistic locking
- [ ] New env vars → update `.env.*.example` + `.env.example`
- [ ] Liquibase: `V{YYYYMMDDHHmmss}__{desc}.sql`
- [ ] `record` for immutable DTOs; early return pattern
