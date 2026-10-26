#!/usr/bin/env bash
# Pre-kickoff setup check: is Muse Wonder reachable from here? Compares with Spark 1.3.
# Reads META_API_KEY from .env; never prints it. Cost: well under $0.01.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -f .env ] || { echo "no .env — cp .env.example .env and add META_API_KEY"; exit 1; }
set -a; . ./.env; set +a
[ -n "${META_API_KEY:-}" ] || { echo "META_API_KEY empty in .env"; exit 1; }
BASE="${META_BASE_URL:-https://api.meta.ai/v1}"

echo "== models list (free) =="
curl -s "$BASE/models" -H "Authorization: Bearer $META_API_KEY" | grep -o '"id":"[^"]*"' || echo "(no ids parsed)"

for model in muse-wonder-1.0 muse-spark-1.3; do
  echo; echo "== $model =="
  curl -s -w '\nHTTP %{http_code}\n' "$BASE/responses" \
    -H "Authorization: Bearer $META_API_KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"input\":\"Reply with OK\",\"reasoning\":{\"effort\":\"minimal\"},\"store\":false,\"max_output_tokens\":50}" \
    | cut -c1-800
done
