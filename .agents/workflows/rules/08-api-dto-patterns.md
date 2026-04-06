# API, DTO Patterns & Migrations

## API Path & Role Conventions

| Context | Path Prefix | Required Role |
|---|---|---|
| Admin | `/api/v1/admin/**` | `@PreAuthorize("hasRole('SUPER_ADMIN')")` |
| Organization | `/api/v1/org/**` | `@PreAuthorize("hasRole('ORG_ADMIN')")` |
| Employee/Booking | `/api/v1/booking/**` | `@PreAuthorize("hasAnyRole('ORG_ADMIN', 'ORG_USER')")` |

## DTO 3-Tier Pattern

```
Presentation DTO (@Valid annotations)       → presentation/dto/
      ↓ (DTO Adapter)
Application DTO (NO validation, prefer record) → application/dto/
      ↓ (Application Mapper)
Domain Model (pure POJO)                    → domain/model/
      ↓ (Repository Adapter)
JPA Entity (@Entity, @Table)                → infrastructure/persistence/entity/
```

## Command / Query / Context (Application Layer)

| Package | Suffix | Use For |
|---|---|---|
| `command` | `*Command` | Write-side: build data to persist, side effects |
| `query` | `*Query` | Read-side: parse, assemble, extract data |
| `context` | `*Context` | Serialize/deserialize execution context |
| Other | `*{Type}` | Distinct concerns: `*Validator`, `*Calculator` |

- Services **orchestrate** — inject Command/Query/Context
- **Not mandatory** — use separate package if logic is a distinct concern
- **Naming**: `{Feature}{PackageType}` (e.g., `BookingValidator`)

## Liquibase Migrations

- **Location:** `shared-libraries/common-db/src/main/resources/db/changelog/`
- **Naming:** `V{YYYYMMDDHHmmss}__{description}.sql`
- **MUST** include in `db.changelog-master.xml`
- ❌ NEVER sequential numbering (`001-...`)
- ❌ NEVER create at root `db/` directory

```sql
-- ✅ Good
V20260129143000__update_visitor_schema.sql

-- ❌ Bad
001-initial-schema.sql
```
