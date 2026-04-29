#!/bin/bash
# Swap the running vision-model llama-server to a different model + quant.
# Must be run as root: sudo bash scripts/swap_model.sh <model-name> [quant]
#
# Models registered below. Default quant is Q6_K. The mmproj is always the
# f16 variant for the chosen model.
set -euo pipefail

MODEL="${1:-}"
QUANT="${2:-Q6_K}"
UNIT=/etc/systemd/system/vision-model.service

MODELS="ui-venus-1.5-8b, mai-ui-8b, ui-venus-1.5-30b-a3b, holo2-30b-a3b, bu-30b-a3b-preview, holo1.5-7b"

if [[ -z "$MODEL" ]]; then
    echo "usage: sudo bash scripts/swap_model.sh <model-name> [quant]" >&2
    echo "models: $MODELS" >&2
    exit 1
fi

case "$MODEL" in
    ui-venus-1.5-8b)
        MODEL_DIR=/home/seans/models/ui-venus-1.5-8b
        DESC="UI-Venus-1.5-8B llama.cpp server (Vulkan)"
        ;;
    mai-ui-8b)
        MODEL_DIR=/home/seans/models/mai-ui-8b
        DESC="MAI-UI-8B llama.cpp server (Vulkan)"
        ;;
    ui-venus-1.5-30b-a3b)
        MODEL_DIR=/mnt/data/models/ui-venus-1.5-30b-a3b
        DESC="UI-Venus-1.5-30B-A3B llama.cpp server (Vulkan)"
        ;;
    holo2-30b-a3b)
        MODEL_DIR=/mnt/data/models/holo2-30b-a3b
        DESC="Holo2-30B-A3B llama.cpp server (Vulkan)"
        ;;
    bu-30b-a3b-preview)
        MODEL_DIR=/mnt/data/models/bu-30b-a3b-preview
        DESC="bu-30b-a3b-preview llama.cpp server (Vulkan)"
        ;;
    holo1.5-7b)
        MODEL_DIR=/mnt/data/models/holo1.5-7b
        DESC="Holo1.5-7B llama.cpp server (Vulkan)"
        ;;
    *)
        echo "ERROR: unknown model '$MODEL'" >&2
        echo "models: $MODELS" >&2
        exit 1
        ;;
esac

ALIAS=$MODEL
GGUF="${MODEL_DIR}/${MODEL}-${QUANT}.gguf"
MMPROJ="${MODEL_DIR}/mmproj-${MODEL}-f16.gguf"

if [[ ! -f "$GGUF" ]]; then
    echo "ERROR: ${GGUF} does not exist." >&2
    echo "Available files in ${MODEL_DIR}:" >&2
    ls "${MODEL_DIR}"/*.gguf 2>&1 >&2 || true
    exit 1
fi
if [[ ! -f "$MMPROJ" ]]; then
    echo "ERROR: ${MMPROJ} does not exist." >&2
    exit 1
fi

# Rewrite the unit. Match leading whitespace so we keep the indented look.
sed -i -E "s#^Description=.*#Description=${DESC}#" "$UNIT"
sed -i -E "s#^(\s*)-m\s+\S+\.gguf#\1-m ${GGUF}#" "$UNIT"
sed -i -E "s#^(\s*)--mmproj\s+\S+\.gguf#\1--mmproj ${MMPROJ}#" "$UNIT"
sed -i -E "s#^(\s*)--alias\s+\S+#\1--alias ${ALIAS}#" "$UNIT"

systemctl daemon-reload
systemctl restart vision-model.service

for i in $(seq 1 60); do
    if curl -fsS http://localhost:8080/health > /dev/null 2>&1; then
        echo "ready after ${i}s on ${MODEL} ${QUANT}"
        break
    fi
    sleep 1
done

echo "=== unit gguf paths ==="
grep -E "(Description|gguf|alias)" "$UNIT"
