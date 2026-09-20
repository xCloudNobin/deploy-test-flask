#!/usr/bin/env bash
# Generate the non-sensitive build marker (VERSION) shown in the UI footer.
#
# Resolution order:
#  1. $BUILD_MARKER (explicit), e.g. BUILD_MARKER=v1.2.3 git tag builds
#  2. latest git short SHA at the checkout
#  3. current UTC date as a fallback
#
# The marker distinguishes deployed revisions. It is intentionally not
# deeply secret; database path/SECRET_KEY stay in the environment instead.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/VERSION"

if [ -n "${BUILD_MARKER:-}" ]; then
  MARKER="$BUILD_MARKER"
elif sha="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null)"; then
  MARKER="$sha"
else
  MARKER="build-$(date -u +%Y%m%d-%H%M%S)"
fi

printf '%s\n' "$MARKER" > "$OUT"
printf 'VERSION = %s\n' "$MARKER"