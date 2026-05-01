#!/bin/bash
# swap_model_remote.sh — same role as scripts/swap_model.sh, but for the
# remote Thunder instance. Writes a small wrapper script on the remote with
# the chosen llama-server args, then (re)starts it inside a fixed-name tmux
# session so successive swaps land in the same slot.
#
# Usage (run from your laptop):
#   bash scripts/thunder/swap_model_remote.sh <ssh_alias> <model> [quant]
#
# Smoke runner reaches the remote via SSH tunnel (sweep.py opens its own;
# manual: ssh -N -L 8080:localhost:8080 <ssh_alias>).
#
# Model registry mirrors scripts/swap_model.sh; remote paths live under
# ~/models on the instance instead of /home/seans/models or /mnt/data/models.
set -euo pipefail

SSH_ALIAS="${1:-}"
MODEL="${2:-}"
QUANT="${3:-Q6_K}"

MODELS="holo3-35b-a3b, qwen2.5-vl-72b-instruct"

if [[ -z "${SSH_ALIAS}" || -z "${MODEL}" ]]; then
    echo "usage: bash scripts/thunder/swap_model_remote.sh <ssh_alias> <model> [quant]" >&2
    echo "models: ${MODELS}" >&2
    exit 1
fi

case "${MODEL}" in
    holo3-35b-a3b)
        QUANT="${3:-IQ3_XXS}"
        GGUF_REL="holo3-35b-a3b/${MODEL}.i1-${QUANT}.gguf"
        MMPROJ_REL="holo3-35b-a3b/mmproj-${MODEL}-Q8_0.gguf"
        # Holo3's chat template auto-prepends a <think> block which conflicts
        # with strict response_format; mirrors the local --chat-template-kwargs
        # workaround in scripts/swap_model.sh. Single-quoted JSON survives the
        # heredoc -> file write -> remote bash parse round-trip.
        EXTRA_ARGS="--chat-template-kwargs '{\"enable_thinking\":false}'"
        ;;
    qwen2.5-vl-72b-instruct)
        QUANT="${3:-Q4_K_M}"
        GGUF_REL="qwen2.5-vl-72b-instruct/${MODEL}-${QUANT}.gguf"
        MMPROJ_REL="qwen2.5-vl-72b-instruct/mmproj-${MODEL}-Q8_0.gguf"
        # No enable_thinking quirk on Qwen2.5-VL; default --jinja handles its
        # built-in template.
        EXTRA_ARGS=""
        ;;
    *)
        echo "ERROR: unknown model '${MODEL}'" >&2
        echo "models: ${MODELS}" >&2
        exit 1
        ;;
esac

# Build the wrapper script's contents. `\$HOME` stays literal so the remote
# shell expands it; ${GGUF_REL} / ${EXTRA_ARGS} / ${MODEL} are expanded by
# the local shell now.
WRAPPER=$(cat <<EOF
#!/bin/bash
set -e
GGUF="\$HOME/models/${GGUF_REL}"
MMPROJ="\$HOME/models/${MMPROJ_REL}"
if [[ ! -f "\$GGUF" ]]; then echo "missing GGUF: \$GGUF" >&2; exit 1; fi
if [[ ! -f "\$MMPROJ" ]]; then echo "missing mmproj: \$MMPROJ" >&2; exit 1; fi
exec "\$HOME/llama.cpp/build/bin/llama-server" \\
    -m "\$GGUF" \\
    --mmproj "\$MMPROJ" \\
    --host 0.0.0.0 --port 8080 \\
    -ngl 99 -c 32768 \\
    --flash-attn on \\
    --image-min-tokens 1024 \\
    --jinja \\
    ${EXTRA_ARGS} \\
    --alias ${MODEL}
EOF
)

# Push the wrapper, kill any prior session, start a fresh one. tee captures
# stdout/stderr to a log so the health-check failure path can show context.
ssh "${SSH_ALIAS}" "cat > ~/run_llama.sh && chmod +x ~/run_llama.sh" <<< "${WRAPPER}"

ssh "${SSH_ALIAS}" bash -s <<'REMOTE'
set -e
tmux kill-session -t llamasrv 2>/dev/null || true
for _ in 1 2 3 4 5; do
    ss -ltn 2>/dev/null | grep -q ':8080 ' || break
    sleep 1
done
tmux new-session -d -s llamasrv "bash ~/run_llama.sh 2>&1 | tee /tmp/llama.log"
REMOTE

echo "waiting for /health on remote ..."
# 600s ceiling — measured 2026-04-30 sweep: Holo3 quants hit /health in
# 100-200s on A100, but Qwen2.5-VL-72B Q4_K_M (47GB GGUF + 44.5GB CUDA
# buffer) needed ~5min beyond the prior 180s cap. 600s gives margin even
# if HF disk cache is cold across instance restarts.
TIMEOUT_S=600
for i in $(seq 1 ${TIMEOUT_S}); do
    if ssh "${SSH_ALIAS}" "curl -fsS http://localhost:8080/health" >/dev/null 2>&1; then
        echo "ready after ${i}s on ${MODEL} ${QUANT}"
        exit 0
    fi
    sleep 1
done

echo "ERROR: remote llama-server did not become healthy in ${TIMEOUT_S}s" >&2
ssh "${SSH_ALIAS}" "tail -40 /tmp/llama.log" >&2 || true
exit 1
