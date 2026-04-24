#!/bin/bash
# Detect the latest available Gemini Pro model name by probing.
# Caches result to ~/.gemini/cache/pro_model. Refreshes after 7 days.
#
# Usage:
#   detect-gemini-pro.sh             # print model name (cached or fresh)
#   detect-gemini-pro.sh --refresh   # force re-probe

set -euo pipefail

CACHE_FILE="${HOME}/.gemini/cache/pro_model"
CACHE_TTL_SECONDS=$((7 * 24 * 3600))

# Probe order: newest first. When Google ships a new tier, add it to the top.
CANDIDATES=(
  "gemini-3-pro-latest"
  "gemini-3-pro"
  "gemini-2.5-pro-latest"
  "gemini-2.5-pro"
)

REFRESH=0
if [[ "${1:-}" == "--refresh" ]]; then
  REFRESH=1
fi

if [[ "$REFRESH" -eq 0 && -f "$CACHE_FILE" ]]; then
  if [[ "$(uname)" == "Darwin" ]]; then
    mtime=$(stat -f %m "$CACHE_FILE")
  else
    mtime=$(stat -c %Y "$CACHE_FILE")
  fi
  now=$(date +%s)
  age=$(( now - mtime ))
  if [[ "$age" -lt "$CACHE_TTL_SECONDS" ]]; then
    cat "$CACHE_FILE"
    exit 0
  fi
fi

mkdir -p "$(dirname "$CACHE_FILE")"

probe_model() {
  local model="$1"
  local out
  out="$(BYPASS_AI_ORCH=1 gemini -m "$model" -p "ok" -o json 2>&1 || true)"
  if echo "$out" | grep -q '"session_id"'; then
    return 0
  fi
  return 1
}

for model in "${CANDIDATES[@]}"; do
  if probe_model "$model"; then
    printf '%s' "$model" >"$CACHE_FILE"
    printf '%s\n' "$model"
    exit 0
  fi
done

echo "detect-gemini-pro: no candidate model accepted" >&2
exit 1
