---
description: Review code changes in a git commit against KOFOS Backend coding rules. Usage - /review-code commit {hash}
---

# Review Code — KOFOS Backend

Review a git commit against ALL coding rules defined in `.agents/workflows/rules/`.

## Workflow Steps

// turbo-all

### 1. Extract the commit hash

The user will provide: `/review-code commit {hash}`

Extract `{hash}` from the user message. If no hash is provided, ask the user to specify one.

### 2. Read ALL rule files

Before reviewing, read ALL rule files to have the full context:

```
.agents/workflows/rules/01-ddd-architecture.md
.agents/workflows/rules/02-naming-conventions.md
.agents/workflows/rules/03-clean-code.md
.agents/workflows/rules/04-database-persistence.md
.agents/workflows/rules/05-system-design.md
.agents/workflows/rules/06-aop-annotations.md
.agents/workflows/rules/07-code-quality.md
.agents/workflows/rules/08-api-dto-patterns.md
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

- **Controller** (`*/presentation/*Controller.java`)
- **Adapter** (`*/presentation/*Adapter.java`, `*/presentation/*DtoAdapter.java`)
- **Presentation DTO** (`*/presentation/dto/*.java`)
- **Service Interface** (`*/application/*Service.java`)
- **Service Impl** (`*/application/*ServiceImpl.java`)
- **Application DTO** (`*/application/dto/*.java`)
- **Command/Query/Context** (`*/application/command/*`, `*/application/query/*`, `*/application/context/*`)
- **Application Mapper** (`*/application/mapper/*Mapper.java`)
- **Domain Model** (`*/domain/model/*.java`)
- **Domain Repository** (`*/domain/repository/*.java`)
- **Domain Service** (`*/domain/service/*.java`)
- **JPA Entity** (`*/infrastructure/persistence/entity/*.java`)
- **JPA Repository** (`*/infrastructure/persistence/*JpaRepository.java`)
- **Repository Adapter** (`*/infrastructure/persistence/*RepositoryAdapter.java`)
- **Infrastructure Mapper** (`*/infrastructure/persistence/mapper/*.java`)
- **SQL Migration** (`db/changelog/*.sql`)
- **Configuration** (`*.yml`, `*.yaml`, `*.properties`)
- **Other** (tests, utils, etc.)

### 5. Review against ALL rule categories

For EACH changed file, check against the applicable rules below. Only check rules that are **relevant to the file type**.

---

#### 5.1 — DDD Architecture (01)

- [ ] **Layer dependency direction**: No upward imports (Infrastructure → Domain OK; Application → Presentation ❌)
- [ ] **Controller injects Adapter**, NOT Service directly
- [ ] **Controller returns Presentation DTOs**, never Domain Models or JPA Entities
- [ ] **Application layer** uses Domain Repositories (interfaces), not JPA repositories
- [ ] **Application layer** does NOT import Presentation or Infrastructure
- [ ] **Domain models** are pure POJO — no JPA, no Spring annotations (Lombok OK)
- [ ] **Domain layer** only contains interfaces for Repository/Service
- [ ] **Infrastructure** implements Domain interfaces via Adapter pattern
- [ ] **Data flow** follows: PresDTO → AppDTO → Domain → Entity (and reverse)

#### 5.2 — Naming Conventions (02)

- [ ] **Controller**: `{Entity}Controller`
- [ ] **Service Interface / Impl**: `{Entity}Service` / `{Entity}ServiceImpl`
- [ ] **Adapters**: `{Entity}Adapter`, `{Entity}DtoAdapter`, `{Entity}RepositoryAdapter`
- [ ] **Mappers**: `{Entity}ApplicationMapper` (app layer), MapStruct in infra
- [ ] **Domain Model**: plain `{Entity}` (not `{Entity}Model`)
- [ ] **JPA Entity**: `{Entity}Entity`
- [ ] **Request/Response DTO**: `{Action}{Entity}Request` / `{Entity}Response`
- [ ] **Command/Query/Context**: `{Feature}Command`, `{Feature}Query`, `{Feature}Context`
- [ ] **Methods**: verb + camelCase, meaningful names, no abbreviations
- [ ] **Booleans**: prefixed with `is`, `has`, `can`, `should`
- [ ] **Constants**: `UPPER_SNAKE_CASE`
- [ ] **Enum**: singular noun, UPPER values
- [ ] **No redundancy**: e.g., `Order.orderDate` → should be `Order.createdAt`
- [ ] **ALL code, comments, variables in English** — no Vietnamese

#### 5.3 — Clean Code (03)

- [ ] **Immutability**: DTOs and data containers use `record`; Domain models use `@Data @Builder`
- [ ] **Constructor Injection only**: `@RequiredArgsConstructor` — no `@Autowired` field injection
- [ ] **Early Return pattern**: no deep nesting, guard clauses at top
- [ ] **MapStruct** for Entity ↔ DTO conversion
- [ ] **Function length** ≤ 50 lines (target 20–35)
- [ ] **Function parameters** ≤ 3 (else use DTO)
- [ ] **Nesting depth** ≤ 2 levels
- [ ] **Class length** ≤ 600 lines (target 200–500)

#### 5.4 — Database & Persistence (04)

- [ ] **No N+1 queries**: uses `findByIdIn()` + `Map` for batch loading
- [ ] **Filter at DB level**, not Java streams after loading all
- [ ] **`EXISTS (SELECT 1 ...)`** instead of `JOIN + DISTINCT` where applicable
- [ ] **`@EntityGraph`** or **`JOIN FETCH`** for lazy-loading N+1
- [ ] **Optimistic Locking**: `@Version` on entities
- [ ] **Pessimistic Locking** only for financial/inventory-critical ops
- [ ] **`@Transactional`** in Application Services, never Controllers
- [ ] **`@Transactional`** for multi-DML operations
- [ ] **No internal `@Transactional` calls** within the same class (proxy bypass)
- [ ] **JPQL/SQL** uses Java 21 text blocks `"""`
- [ ] **No string concatenation** in queries

#### 5.5 — System Design (05)

- [ ] **Idempotent consumers** for messaging
- [ ] **Dead Letter Queue (DLQ)** configured for message processing
- [ ] **Cache keys have TTL** — no infinite cache
- [ ] **ShedLock / distributed lock** for scheduled jobs
- [ ] **Virtual Threads** for I/O-bound async tasks (not default ForkJoinPool)
- [ ] **Race conditions** checked in find-or-create flows
- [ ] **List endpoints** are paginated or bounded

#### 5.6 — AOP & Annotations (06)

- [ ] **Cross-cutting concerns** (logging, audit, perf) use AOP, not inline code
- [ ] **`@TrackAction`** pattern used where appropriate
- [ ] **AOP NOT used** for core business logic

#### 5.7 — Code Quality (07)

- [ ] **Logging format**: `{ClassName} - {methodName} - {message}`
- [ ] **SLF4J** `{}` placeholders — no string concatenation in logs
- [ ] **`@Slf4j`** from Lombok
- [ ] **Error messages**: via `MessageService.getMessage()` — no hardcoded strings
- [ ] **Validation messages**: `@NotBlank(message = "{validation.xxx}")` — externalized
- [ ] **No hardcoded config values**: use `${ENV_VAR:default}` in `application.yml`
- [ ] **New env vars** → `.env.*.example` and `.env.example` updated
- [ ] **No commented-out code**
- [ ] **No inline comments** explaining what (only comment complex WHY)

#### 5.8 — API & DTO Patterns (08)

- [ ] **API path convention**: Admin `/api/v1/admin/**`, Org `/api/v1/org/**`, Booking `/api/v1/booking/**`
- [ ] **`@PreAuthorize`** matches path convention
- [ ] **DTO 3-tier**: Presentation DTO → Application DTO → Domain Model → JPA Entity
- [ ] **Presentation DTOs** have `@Valid` annotations
- [ ] **Application DTOs** do NOT have validation annotations
- [ ] **Command/Query/Context** separation in Application layer (where applicable)

#### 5.9 — Liquibase Migration (08)

- [ ] **File location**: `shared-libraries/common-db/src/main/resources/db/changelog/`
- [ ] **Naming**: `V{YYYYMMDDHHmmss}__{description}.sql`
- [ ] **Registered** in `db.changelog-master.xml`
- [ ] **No sequential numbering** like `001-xxx.sql`

---

### 6. Generate the Review Report

Output the review as a structured report using this template:

```markdown
# 🔍 Code Review Report

**Commit:** `{hash}`
**Author:** {author}
**Message:** {commit_message}
**Files Changed:** {count}

---

## 📊 Overall Verdict

> [!CAUTION/WARNING/TIP]
> **{MERGE_BLOCKED / MERGE_WITH_CAUTION / READY_TO_MERGE}**
> {Summary reason}

---

## ✅ Rules Passed

| # | Rule Category | Status |
|---|---|---|
| 1 | DDD Architecture | ✅ Pass |
| 2 | Naming Conventions | ✅ Pass |
| ... | ... | ... |

## ❌ Violations Found

### [{Severity: 🔴 BLOCKER / 🟡 WARNING / 🔵 INFO}] {Rule Category} — {Specific Rule}

**File:** `{file_path}`
**Line(s):** {line_range}
**Description:** {what is wrong}
**Rule Reference:** {rule_file} — {specific rule text}
**Suggested Fix:**
```java
// corrected code
```

(Repeat for each violation)

---

## 🛡️ Risk Assessment

| Risk | Level | Details |
|---|---|---|
| N+1 Query | 🔴 High | {description or N/A} |
| Transaction Safety | 🟡 Medium | {description or N/A} |
| Layer Violation | 🔴 High | {description or N/A} |
| Security | 🔴 High | {description or N/A} |
| Concurrency | 🟡 Medium | {description or N/A} |
| Naming | 🔵 Low | {description or N/A} |

---

## 📝 Merge Decision

- **🔴 BLOCKER violations** → ❌ **DO NOT MERGE** — must fix first
- **🟡 WARNING violations** → ⚠️ **MERGE WITH CAUTION** — should fix soon
- **🔵 INFO only** → ✅ **READY TO MERGE**
```

### 7. Severity Classification

Use these severity levels:

| Level | Meaning | Merge? |
|---|---|---|
| 🔴 **BLOCKER** | Architecture violation, N+1 query, security risk, transaction bug, `@Autowired` field injection | ❌ Must fix |
| 🟡 **WARNING** | Naming convention miss, function too long, missing `@Version`, hardcoded message | ⚠️ Should fix |
| 🔵 **INFO** | Style preference, comment suggestion, minor naming improvement | ✅ Can merge |

### 8. Final output

After generating the full report, clearly state the **final verdict**:

- If ANY 🔴 BLOCKER exists → state: **"❌ BLOCKED — {N} blocker(s) must be fixed before merge"**
- If only 🟡 WARNING → state: **"⚠️ MERGE WITH CAUTION — {N} warning(s) should be addressed"**
- If clean → state: **"✅ READY TO MERGE — All rules passed"**
