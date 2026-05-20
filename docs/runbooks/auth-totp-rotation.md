# Runbook — TOTP encryption key rotation

**Scope:** Rotate `AUTH_TOTP_ENCRYPTION_KEY` (the Fernet key that
encrypts `users.totp_secret` at rest, introduced by migration
`e7a91c204f31_encrypt_totp_secrets_add_replay_counter`).

**Audience:** On-call / platform on-duty.

**Risk class:** Medium — touches every row of `users` that has 2FA
enabled. A botched rotation locks every TOTP user out of 2FA until
fixed.

---

## 1. When to rotate

Rotate when **any** of these is true:

- The current key is older than 12 months (scheduled hygiene rotation).
- The current key was exposed (a teammate posted it in Slack, a CI log
  leaked it, a contributor offboards while still holding it).
- A periodic compliance audit requires it (SOC 2, ISO 27001).

Do **not** rotate as a routine deploy step — every rotation is a
short maintenance window plus a follow-up verification pass.

## 2. Preconditions

- [ ] You have shell access to the production app environment AND the
      production database writer.
- [ ] The current `AUTH_TOTP_ENCRYPTION_KEY` is available (in the
      secret manager or env).
- [ ] You can edit the application's environment variables and roll
      the workers.
- [ ] You have run this procedure end-to-end in `staging` against a
      copy of prod data within the last 90 days.
- [ ] You have ~30 minutes of focused on-call time and a second
      engineer paged as buddy.

## 3. Procedure

### 3.1 Generate the new key

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the output in the secret manager as
`AUTH_TOTP_ENCRYPTION_KEY_NEW`. **Do not** overwrite
`AUTH_TOTP_ENCRYPTION_KEY` yet.

### 3.2 Take a database snapshot

A `users` table snapshot (or full DB snapshot) timestamped before the
rotation begins. This is the rollback artifact for §5.

### 3.3 Re-encrypt the rows

The app uses the **old** key the entire time this step runs — no
downtime. The helper is idempotent: re-running it after a crash picks
up where it left off.

```bash
OLD_KEY="$(get-secret AUTH_TOTP_ENCRYPTION_KEY)"
NEW_KEY="$(get-secret AUTH_TOTP_ENCRYPTION_KEY_NEW)"

uv run python - <<'PY'
import asyncio
import os
from apps.auth.security.otp import rotate_secret_storage
from apps.core.database.session import async_session_factory

OLD_KEY = os.environ["OLD_KEY"]
NEW_KEY = os.environ["NEW_KEY"]


async def main() -> None:
    async with async_session_factory() as session, session.begin():
        summary = await rotate_secret_storage(
            session,
            old_key=OLD_KEY,
            new_key=NEW_KEY,
        )
        print(summary)


asyncio.run(main())
PY
```

Expected output:

```
TotpRotationSummary(total_inspected=<N>, re_encrypted=<N>, already_new_key=0, undecryptable=0)
```

If `already_new_key > 0`: the rotation has been run before with the
same `NEW_KEY` — safe to continue (idempotent).

If `undecryptable > 0`: **STOP**. Some rows decrypt with neither key.
This means either the wrong `OLD_KEY` was passed OR data corruption
exists. Investigate before proceeding; capture the row IDs from the
WARNING log lines.

### 3.4 Swap the key in the app environment

In the secret manager:

1. Copy the value of `AUTH_TOTP_ENCRYPTION_KEY` to
   `AUTH_TOTP_ENCRYPTION_KEY_PREVIOUS` (rollback breadcrumb).
2. Overwrite `AUTH_TOTP_ENCRYPTION_KEY` with the value of
   `AUTH_TOTP_ENCRYPTION_KEY_NEW`.
3. Delete `AUTH_TOTP_ENCRYPTION_KEY_NEW`.

### 3.5 Roll the workers

A rolling restart of the API pods. The
`functools.lru_cache(maxsize=1)` on `_load_totp_fernet` caches the key
for the lifetime of the process, so the new key only takes effect on
restart.

**Brief 2FA outage window:** During the rolling restart, some pods
have the old key and some the new. TOTP verification fails on the
"wrong-keyed" pods because every row is now encrypted with the new
key. Mitigate by rolling fast (a single rolling step over all pods);
typically <30s of intermittent 2FA failures.

### 3.6 Verify

Within 5 minutes of the rollout finishing:

```sql
SELECT COUNT(*)
FROM users
WHERE totp_secret IS NOT NULL;
```

Then trigger a known-good 2FA login (a synthetic test user) and
confirm it succeeds. Check the application logs for any
`InvalidToken` exceptions originating from
`apps.auth.security.otp.decrypt_totp_secret`.

## 4. Cleanup

After 7 days of stable verification with no `InvalidToken` incidents:

- [ ] Delete `AUTH_TOTP_ENCRYPTION_KEY_PREVIOUS` from the secret
      manager.
- [ ] Delete the pre-rotation database snapshot taken in §3.2.
- [ ] Update the compliance log: rotation completed, date, executor.

## 5. Rollback

If verification fails OR users report 2FA failures at a rate above
baseline:

1. **Set the env variable back to the old key.** In the secret
   manager, restore `AUTH_TOTP_ENCRYPTION_KEY` from
   `AUTH_TOTP_ENCRYPTION_KEY_PREVIOUS`.
2. **Re-encrypt back to the old key.** Run `rotate_secret_storage`
   again with `old_key=NEW_KEY, new_key=OLD_KEY`:

   ```bash
   uv run python - <<'PY'
   import asyncio
   from apps.auth.security.otp import rotate_secret_storage
   from apps.core.database.session import async_session_factory
   # NOTE: keys swapped — we are rolling forward to "old" again
   OLD_KEY = "<the NEW_KEY value>"
   NEW_KEY = "<the original OLD_KEY value>"


   async def main() -> None:
       async with async_session_factory() as session, session.begin():
           summary = await rotate_secret_storage(
               session, old_key=OLD_KEY, new_key=NEW_KEY,
           )
           print(summary)


   asyncio.run(main())
   PY
   ```

3. **Roll the workers.** Same as §3.5; brief outage window.
4. **Post-mortem.** File an incident; root-cause why the new key
   didn't take.

If even the rollback fails: restore the `users` table from the
snapshot in §3.2 (this is destructive — coordinate with on-call and
notify users that any 2FA rotation since the snapshot is lost).

## 6. Escalation

| Symptom | First responder | Escalate after |
|---|---|---|
| `undecryptable > 0` during §3.3 | On-call | Immediately — do NOT swap the key |
| 2FA failure rate doubles after §3.5 | On-call | 5 minutes — start §5 rollback |
| Rollback also fails | On-call | Page the security engineer on rotation |
| Database snapshot restore needed | Platform on-duty | Pager + security |

## 7. Future work (out of scope for this runbook)

- **`MultiFernet` dual-read mode.** Today the app holds a single
  Fernet key, so the rolling-restart window has a brief 2FA outage.
  A future change can wire `cryptography.fernet.MultiFernet` so the
  app accepts both old and new ciphertexts during a configurable
  rotation window — eliminating the outage entirely. Tracked
  alongside MED-7 in `code_analysis.md`.
- **Scheduled rotation cron.** A monthly background task could call
  `rotate_secret_storage` with the latest key from the secret
  manager. Requires the dual-read mode above first.

## 8. References

- Migration: `alembic/versions/e7a91c204f31_encrypt_totp_secrets_add_replay_counter.py`
- Helper source: `apps/auth/security/otp.py` →
  `rotate_secret_storage`, `TotpRotationSummary`
- Constant: `apps/auth/constants.py` → `TOTP_ROTATION_BATCH_SIZE`
- Code-analysis report: `code_analysis.md` → MED-7
