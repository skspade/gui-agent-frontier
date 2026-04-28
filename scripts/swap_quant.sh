#!/bin/bash
# Swap the running ui-venus llama-server to a different LLM quantization.
# Must be run as root: sudo bash scripts/swap_quant.sh <Q4_K_M|Q5_K_M|Q6_K|f16>
#
# The mmproj (vision encoder) only exists in f16 - this script always restores
# the mmproj line to f16 to recover from a previous bad swap.
set -euo pipefail

TARGET="${1:-Q6_K}"
UNIT=/etc/systemd/system/ui-venus.service
MODEL_DIR=/home/seans/models/ui-venus-1.5-8b

LLM_PATH="${MODEL_DIR}/ui-venus-1.5-8b-${TARGET}.gguf"
if [[ ! -f "$LLM_PATH" ]]; then
    echo "ERROR: ${LLM_PATH} does not exist." >&2
    echo "Available quants:" >&2
    ls "${MODEL_DIR}"/*.gguf 2>&1 >&2
    exit 1
fi

# Always restore mmproj to f16 (only f16 exists for the vision encoder).
sed -i -E "s#/mmproj-ui-venus-1\.5-8b-(Q4_K_M|Q5_K_M|Q6_K|f16)\.gguf#/mmproj-ui-venus-1.5-8b-f16.gguf#" "$UNIT"

# Swap the LLM filename. The leading slash anchors against the directory
# separator so the mmproj line (which has '-' before 'ui-venus') doesn't match.
sed -i -E "s#/ui-venus-1\.5-8b-(Q4_K_M|Q5_K_M|Q6_K|f16)\.gguf#/ui-venus-1.5-8b-${TARGET}.gguf#" "$UNIT"

systemctl daemon-reload
systemctl restart ui-venus.service

# Wait for /health to come back instead of fixed sleep.
for i in $(seq 1 30); do
    if curl -fsS http://localhost:8080/health > /dev/null 2>&1; then
        echo "ready after ${i}s on $TARGET"
        break
    fi
    sleep 1
done

echo "=== unit gguf paths ==="
grep -E "gguf" "$UNIT"
