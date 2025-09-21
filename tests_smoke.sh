#!/usr/bin/env bash
set -euo pipefail
: "${N8N_BASE:?}"; : "${N8N_USER:?}"; : "${N8N_PASS:?}"

book() {
  curl -sS -u "$N8N_USER:$N8N_PASS" -X POST \
    "$N8N_BASE/webhook/api/booking/book" -H "Content-Type: application/json" -d '{
      "name":"CI Test","phone":"+34600000000","service_id":"SVC001",
      "start_iso":"2025-09-22T09:30:00+02:00","duration_min":30,"staff_id":"any"
    }'
}

reschedule() {
  local id="$1" staff="$2"
  curl -sS -u "$N8N_USER:$N8N_PASS" -X POST \
    "$N8N_BASE/webhook/api/booking/reschedule" -H "Content-Type: application/json" -d "{
      \"booking_id\":\"$id\",\"staff_id\":\"$staff\",\"new_start_iso\":\"2025-09-22T10:30:00+02:00\"
    }"
}

find_by_phone() {
  curl -sS -u "$N8N_USER:$N8N_PASS" -X POST \
    "$N8N_BASE/webhook/api/booking/find-by-phone" -H "Content-Type: application/json" -d '{
      "phone":"+34600000000","staff_id":"ruben","days":30
    }'
}

cancel() {
  local id="$1" staff="$2"
  curl -sS -u "$N8N_USER:$N8N_PASS" -X POST \
    "$N8N_BASE/webhook/api/booking/cancel" -H "Content-Type: application/json" -d "{
      \"booking_id\":\"$id\",\"staff_id\":\"$staff\"
    }"
}

resp=$(book); echo "BOOK RESP: $resp"
booking_id=$(echo "$resp" | grep -oE '"booking_id"\s*:\s*"[^"]+"' | cut -d'"' -f4 || true)
staff_id=$(echo "$resp" | grep -oE '"staff_id"\s*:\s*"[^"]+"' | cut -d'"' -f4 || true)
if [[ -z "$booking_id" || -z "$staff_id" ]]; then
  echo "Smoke failed to create booking" >&2
  exit 1
fi

reschedule "$booking_id" "$staff_id" | tee /dev/stderr
find_by_phone | tee /dev/stderr
cancel "$booking_id" "$staff_id" | tee /dev/stderr

echo "SMOKE OK"
