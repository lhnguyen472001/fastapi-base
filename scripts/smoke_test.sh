#!/usr/bin/env bash
# End-to-end API smoke test against the running compose stack.
#
# Exercises health, auth (register/verify via MailHog/login/refresh/me/logout),
# workspace create + list, blog draft create, autosave (x3) → versions
# list/detail/compare/restore, publish, and the public read path.
#
# Run after `docker compose up -d api`:
#   bash scripts/smoke_test.sh
set -u

BASE="http://localhost:8000/api/v1"
MAILHOG="http://localhost:8025"
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

STAMP=$(date +%s)
EMAIL="smoke${STAMP}@example.com"
USERNAME="smoke${STAMP}"
PASSWORD="SmokeTest!23"
WS_SLUG="smoke-ws-${STAMP}"

pass=0
fail=0
log() { printf '\033[1;36m[smoke]\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m  PASS\033[0m %s\n' "$*"; pass=$((pass+1)); }
bad() { printf '\033[1;31m  FAIL\033[0m %s\n' "$*"; fail=$((fail+1)); }

req() {
  local method="$1"; shift
  local url="$1"; shift
  curl -s -o "$BODY_FILE" -w '%{http_code}' -X "$method" "$url" "$@"
}

assert_status() {
  local got="$1" want="$2" label="$3"
  if [[ "$got" == "$want" ]]; then
    ok "$label (HTTP $got)"
  else
    bad "$label expected $want got $got"
    echo "    body: $(head -c 400 "$BODY_FILE")"
  fi
}

jget() { python3 -c "import json,sys;print(json.load(open('$BODY_FILE'))$1)"; }

# 1. Health
log "1. GET /health"
code=$(req GET "http://localhost:8000/health")
assert_status "$code" 200 "/health"

curl -s -X DELETE "${MAILHOG}/api/v1/messages" >/dev/null

# 2. Register
log "2. POST /auth/register"
code=$(req POST "${BASE}/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
assert_status "$code" 202 "auth/register"

# 3. Fetch OTP from MailHog
log "3. Fetch OTP from MailHog"
otp=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  raw=$(curl -s "${MAILHOG}/api/v2/messages?limit=1")
  otp=$(printf '%s' "$raw" | python3 -c '
import email, json, re, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
items = d.get("items") or []
if not items:
    sys.exit(0)
content = items[0].get("Content", {}) or {}
headers = content.get("Headers", {}) or {}
raw_lines = []
for k, vals in headers.items():
    for v in vals:
        raw_lines.append(f"{k}: {v}")
raw_lines.append("")
raw_lines.append(content.get("Body", ""))
msg = email.message_from_string("\n".join(raw_lines))
plain = ""
if msg.is_multipart():
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            plain = payload.decode(charset, errors="replace")
            break
if not plain:
    plain = content.get("Body", "")
m = re.search(r"verification code[^0-9]*([0-9]{4,8})", plain, re.IGNORECASE | re.DOTALL)
if not m:
    m = re.search(r"\b([0-9]{6})\b", plain)
print(m.group(1) if m else "")
')
  [[ -n "$otp" ]] && break
  sleep 1
done
if [[ -z "$otp" ]]; then bad "fetch OTP from MailHog"; exit 1; fi
ok "OTP captured: $otp"

# 4. Verify email
log "4. POST /auth/verify-email"
code=$(req POST "${BASE}/auth/verify-email" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"code\":\"$otp\"}")
assert_status "$code" 200 "auth/verify-email"

# 5. Login
log "5. POST /auth/login"
code=$(req POST "${BASE}/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
assert_status "$code" 200 "auth/login"
ACCESS=$(jget "['data']['access_token']")
REFRESH=$(jget "['data']['refresh_token']")
[[ -n "$ACCESS" && -n "$REFRESH" ]] && ok "tokens captured" || bad "tokens missing"

AUTH=(-H "Authorization: Bearer $ACCESS")

# 6. /auth/me
log "6. GET /auth/me"
code=$(req GET "${BASE}/auth/me" "${AUTH[@]}")
assert_status "$code" 200 "auth/me"

# 7. Refresh
log "7. POST /auth/refresh"
code=$(req POST "${BASE}/auth/refresh" \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}")
assert_status "$code" 200 "auth/refresh"

# 8. Workspace create
log "8. POST /workspaces"
code=$(req POST "${BASE}/workspaces" \
  "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d "{\"slug\":\"$WS_SLUG\",\"name\":\"Smoke WS\",\"description\":\"smoke\"}")
assert_status "$code" 201 "workspaces create"

# 9. Workspaces list
log "9. GET /workspaces"
code=$(req GET "${BASE}/workspaces" "${AUTH[@]}")
assert_status "$code" 200 "workspaces list"

# 10. Create draft post
log "10. POST blog post (draft)"
PAYLOAD=$(python3 -c "
import json
print(json.dumps({
  'title': 'Smoke Post ${STAMP}',
  'content_json': {'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'Initial draft body paragraph one.'}]}]}
}))")
code=$(req POST "${BASE}/workspaces/${WS_SLUG}/blog/posts" \
  "${AUTH[@]}" -H 'Content-Type: application/json' -d "$PAYLOAD")
assert_status "$code" 201 "blog post create"
POST_ID=$(jget "['data']['id']")
ok "post_id=$POST_ID"

# 11-13. Autosave three different bodies (sweeper flushes them to versions)
for i in 1 2 3; do
  log "1${i}. POST autosave v$i"
  P=$(python3 -c "
import json
print(json.dumps({'content_json':{'type':'doc','content':[
  {'type':'paragraph','content':[{'type':'text','text':'Body revision $i — line A.'}]},
  {'type':'paragraph','content':[{'type':'text','text':'Paragraph $i — line B.'}]}
]}}))")
  code=$(req PUT "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}/autosave" \
    "${AUTH[@]}" -H 'Content-Type: application/json' -d "$P")
  assert_status "$code" 200 "autosave v$i"
  sleep 3
done

# 14. Versions list
log "14. GET versions list"
sleep 3
code=$(req GET "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}/versions?limit=50&offset=0" "${AUTH[@]}")
assert_status "$code" 200 "versions list"
TOTAL=$(jget "['data']['total']")
VERSIONS=$(python3 -c "import json;d=json.load(open('$BODY_FILE'))['data'];print(' '.join(str(v['version']) for v in d['items']))")
ok "versions in DB: total=$TOTAL versions=[$VERSIONS]"
if [[ "$TOTAL" -lt 1 ]]; then bad "expected at least 1 version after autosave-flush"; fi

LOW_VER=$(python3 -c "import json;d=json.load(open('$BODY_FILE'))['data']['items'];print(min(v['version'] for v in d))")
HI_VER=$(python3 -c "import json;d=json.load(open('$BODY_FILE'))['data']['items'];print(max(v['version'] for v in d))")

# 15. Version detail
log "15. GET version detail v=$LOW_VER"
code=$(req GET "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}/versions/${LOW_VER}" "${AUTH[@]}")
assert_status "$code" 200 "version detail"
HAS_JSON=$(python3 -c "import json;d=json.load(open('$BODY_FILE'))['data'];print('1' if d.get('content_json') else '0')")
[[ "$HAS_JSON" == "1" ]] && ok "content_json decompressed" || bad "content_json missing"

# 16. Compare
if [[ "$LOW_VER" != "$HI_VER" ]]; then
  log "16. GET versions compare from=$LOW_VER to=$HI_VER"
  code=$(req GET "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}/versions/compare?from=${LOW_VER}&to=${HI_VER}" "${AUTH[@]}")
  assert_status "$code" 200 "versions compare"
  HUNKS=$(python3 -c "import json;print(len(json.load(open('$BODY_FILE'))['data']['hunks']))")
  ok "diff hunks: $HUNKS"

  log "16b. compare from==to (must be 4xx)"
  code=$(req GET "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}/versions/compare?from=${LOW_VER}&to=${LOW_VER}" "${AUTH[@]}")
  if [[ "$code" =~ ^4 ]]; then ok "compare from==to rejected (HTTP $code)"; else bad "compare from==to allowed (HTTP $code)"; fi
else
  log "16. compare skipped — only one version present"
fi

# 17. Restore
log "17. POST restore version $LOW_VER"
code=$(req POST "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}/versions/${LOW_VER}/restore" \
  "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"change_note":"smoke restore"}')
assert_status "$code" 200 "version restore"
NEW_VER=$(jget "['data']['new_version']['version']")
RESTORED=$(jget "['data']['new_version']['is_restored']")
ok "restored — new_version=$NEW_VER is_restored=$RESTORED"

# 18. Versions grew by one
log "18. versions list (post-restore)"
code=$(req GET "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}/versions?limit=50&offset=0" "${AUTH[@]}")
assert_status "$code" 200 "versions list (post-restore)"
TOTAL2=$(jget "['data']['total']")
if [[ "$TOTAL2" -gt "$TOTAL" ]]; then ok "version count grew: $TOTAL → $TOTAL2"; else bad "version count did not grow ($TOTAL → $TOTAL2)"; fi

# 19. PATCH post (publishable body)
log "19. PATCH post (publishable body)"
P=$(python3 -c "
import json
print(json.dumps({'content_json':{'type':'doc','content':[
  {'type':'paragraph','content':[{'type':'text','text':('This is the published version of the smoke test post. ' * 6).strip()}]}
]}}))")
code=$(req PATCH "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}" \
  "${AUTH[@]}" -H 'Content-Type: application/json' -d "$P")
assert_status "$code" 200 "post patch"

# 20. Publish
log "20. POST publish"
code=$(req POST "${BASE}/workspaces/${WS_SLUG}/blog/posts/${POST_ID}/publish" "${AUTH[@]}")
assert_status "$code" 200 "post publish"

# 21. Public list
log "21. GET public posts"
code=$(req GET "${BASE}/public/workspaces/${WS_SLUG}/blog/posts")
assert_status "$code" 200 "public list"
PUB_COUNT=$(jget "['data']['total']")
ok "public posts visible: $PUB_COUNT"

# 22. Logout
log "22. POST /auth/logout"
code=$(req POST "${BASE}/auth/logout" \
  "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}")
assert_status "$code" 204 "auth/logout"

echo
printf '\033[1;36m======== smoke-test summary ========\033[0m\n'
printf '  passed: \033[1;32m%d\033[0m\n' "$pass"
printf '  failed: \033[1;31m%d\033[0m\n' "$fail"
[[ "$fail" -eq 0 ]] && exit 0 || exit 1
