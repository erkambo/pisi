#!/usr/bin/env bash
# Launch the desktop companion.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec python3 -m companion
