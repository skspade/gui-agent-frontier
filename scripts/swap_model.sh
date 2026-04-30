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

MODELS="ui-venus-1.5-8b, mai-ui-8b, ui-venus-1.5-30b-a3b, holo2-30b-a3b, bu-30b-a3b-preview, holo1.5-7b, holo3-35b-a3b"

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
    holo3-35b-a3b)
        # Holo3 GGUFs from mradermacher use the .i1- imatrix prefix and a
        # Q8_0 mmproj instead of the project-default f16. Default quant
        # IQ3_XXS (13.62GB) — the only quant that fits 16GB VRAM with
        # mmproj-Q8_0 + 32K KV without OOM. Phase 15.
        MODEL_DIR=/mnt/data/models/holo3-35b-a3b
        DESC="Holo3-35B-A3B llama.cpp server (Vulkan)"
        QUANT="${2:-IQ3_XXS}"
        GGUF_OVERRIDE="${MODEL_DIR}/${MODEL}.i1-${QUANT}.gguf"
        MMPROJ_OVERRIDE="${MODEL_DIR}/mmproj-${MODEL}-Q8_0.gguf"
        ;;
    *)
        echo "ERROR: unknown model '$MODEL'" >&2
        echo "models: $MODELS" >&2
        exit 1
        ;;
esac

ALIAS=$MODEL
GGUF="${GGUF_OVERRIDE:-${MODEL_DIR}/${MODEL}-${QUANT}.gguf}"
MMPROJ="${MMPROJ_OVERRIDE:-${MODEL_DIR}/mmproj-${MODEL}-f16.gguf}"

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

# Idempotently ensure --chat-template-kwargs '{"enable_thinking":false}' is
# present after --jinja. Required for Holo3 (its template auto-prepends a
# <think> block, which conflicts with strict response_format). Harmless for
# templates that don't reference enable_thinking — a no-op kwarg.
if ! grep -q -- "--chat-template-kwargs" "$UNIT"; then
    sed -i -E "/^\s*--jinja(\s|$|\\\\)/a\\    --chat-template-kwargs '{\"enable_thinking\":false}' \\\\" "$UNIT"
fi

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
