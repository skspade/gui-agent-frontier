#!/bin/bash
# bootstrap_instance.sh — one-shot setup on a freshly-provisioned Thunder
# (or any CUDA-capable cloud) instance. Builds llama.cpp with CUDA, fetches
# the GGUFs needed for the parameter-cliff sweep, and leaves the instance
# ready for swap_model_remote.sh to start a server.
#
# Usage:
#   scp scripts/thunder/bootstrap_instance.sh thunder:~/
#   ssh thunder bash ~/bootstrap_instance.sh
#
# Idempotent: re-running skips already-built binaries and already-downloaded
# files. Safe to interrupt and resume.
set -euo pipefail

WORKDIR="${HOME}"
MODELS_DIR="${WORKDIR}/models"
LLAMA_DIR="${WORKDIR}/llama.cpp"
LLAMA_BIN="${LLAMA_DIR}/build/bin/llama-server"

echo "===== bootstrap: apt deps ====="
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
    build-essential cmake git curl ca-certificates \
    libcurl4-openssl-dev python3-pip python3-venv tmux pciutils

echo "===== bootstrap: verify CUDA ====="
if ! command -v nvcc >/dev/null 2>&1; then
    if [[ -d /usr/local/cuda/bin ]]; then
        export PATH="/usr/local/cuda/bin:${PATH}"
    else
        echo "ERROR: CUDA toolkit not found. Thunder GPU instances should ship with it — check the image type." >&2
        exit 1
    fi
fi
nvcc --version | tail -1
nvidia-smi -L || true

echo "===== bootstrap: build llama.cpp (CUDA) ====="
if [[ ! -d "${LLAMA_DIR}/.git" ]]; then
    git clone --depth 1 https://github.com/ggerganov/llama.cpp "${LLAMA_DIR}"
fi
if [[ ! -x "${LLAMA_BIN}" ]]; then
    cd "${LLAMA_DIR}"
    cmake -B build -DGGML_CUDA=ON -DLLAMA_CURL=ON >/dev/null
    cmake --build build --config Release -j "$(nproc)" --target llama-server
fi
"${LLAMA_BIN}" --version 2>&1 | head -1 || true

echo "===== bootstrap: huggingface_hub ====="
python3 -m pip install --user --break-system-packages -q -U "huggingface_hub" 2>/dev/null \
    || python3 -m pip install --user -q -U "huggingface_hub"

# Fetch a single (repo, filename) into a target path with the project's
# lowercase rename convention. Skips if the destination already exists.
fetch() {
    local repo="$1" src="$2" dst="$3"
    if [[ -f "${dst}" ]]; then
        echo "  skip $(basename "${dst}") (exists)"
        return 0
    fi
    local dst_dir
    dst_dir="$(dirname "${dst}")"
    mkdir -p "${dst_dir}"
    echo "  fetch ${repo} :: ${src} -> ${dst}"
    python3 - <<PY
from huggingface_hub import hf_hub_download
import shutil, os
path = hf_hub_download(repo_id="${repo}", filename="${src}", local_dir="${dst_dir}")
target = "${dst}"
if path != target:
    shutil.move(path, target)
PY
}

echo "===== bootstrap: download GGUFs (Holo3 ladder) ====="
# Holo3 i1-quantized weights from mradermacher/Holo3-35B-A3B-i1-GGUF; the
# mmproj lives in the *static* sibling repo (mradermacher publishes the
# vision projector once, separate from the rolling imatrix variants).
HOLO3_DIR="${MODELS_DIR}/holo3-35b-a3b"
HOLO3_I1_REPO="mradermacher/Holo3-35B-A3B-i1-GGUF"
HOLO3_STATIC_REPO="mradermacher/Holo3-35B-A3B-GGUF"
for QUANT in IQ3_XXS Q4_K_M Q6_K; do
    fetch "${HOLO3_I1_REPO}" \
          "Holo3-35B-A3B.i1-${QUANT}.gguf" \
          "${HOLO3_DIR}/holo3-35b-a3b.i1-${QUANT}.gguf"
done
fetch "${HOLO3_STATIC_REPO}" \
      "Holo3-35B-A3B.mmproj-Q8_0.gguf" \
      "${HOLO3_DIR}/mmproj-holo3-35b-a3b-Q8_0.gguf"

echo "===== bootstrap: download GGUFs (Qwen2.5-VL-72B Q4_K_M) ====="
# 70B-class rung for the parameter-cliff probe. Q4_K_M is a single 47GB file
# (no sharding); mmproj-Q8_0 is preferred over f16 for VRAM headroom.
# Skip with SKIP_72B=1 if disk-constrained.
QWEN_VL_72B_DIR="${MODELS_DIR}/qwen2.5-vl-72b-instruct"
QWEN_VL_72B_REPO="ggml-org/Qwen2.5-VL-72B-Instruct-GGUF"
if [[ "${SKIP_72B:-0}" != "1" ]]; then
    fetch "${QWEN_VL_72B_REPO}" \
          "Qwen2.5-VL-72B-Instruct-Q4_K_M.gguf" \
          "${QWEN_VL_72B_DIR}/qwen2.5-vl-72b-instruct-Q4_K_M.gguf"
    fetch "${QWEN_VL_72B_REPO}" \
          "mmproj-Qwen2.5-VL-72B-Instruct-Q8_0.gguf" \
          "${QWEN_VL_72B_DIR}/mmproj-qwen2.5-vl-72b-instruct-Q8_0.gguf"
else
    echo "  SKIP_72B=1 set, skipping Qwen2.5-VL-72B download"
fi

# UI-Venus-1.5-30B-A3B has no public GGUF (verified 2026-04-30 across
# mradermacher, bartowski, unsloth, ggml-org). To add this rung you'd need
# to download the safetensors from inclusionAI/UI-Venus-1.5-30B-A3B and run
# llama.cpp's convert_hf_to_gguf.py + llama-quantize on the instance. Not
# automated here — separate one-time workflow.

echo "===== bootstrap: complete ====="
echo "Models on disk:"
find "${MODELS_DIR}" -name '*.gguf' -printf '  %p (%s bytes)\n' 2>/dev/null | sort
echo
echo "llama-server: ${LLAMA_BIN}"
echo "Next: from your laptop, run scripts/thunder/swap_model_remote.sh <ssh_alias> holo3-35b-a3b IQ3_XXS"
echo "Or run the full sweep: .venv/bin/python scripts/thunder/sweep.py --ssh <ssh_alias> --task excalidraw_drag"
