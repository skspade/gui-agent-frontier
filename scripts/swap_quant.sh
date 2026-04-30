#!/bin/bash
# DEPRECATED: kept as a thin alias for backward compatibility.
# Use scripts/swap_model.sh directly:
#   sudo bash scripts/swap_model.sh ui-venus-1.5-8b <quant>
set -euo pipefail
exec bash "$(dirname "$0")/swap_model.sh" ui-venus-1.5-8b "$@"
