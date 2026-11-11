#!/usr/bin/env bash
# Run inside a cloned checkout on an Ubuntu server with an NVIDIA A10.
# Usage: LLM_MODEL=qwen3.5:9b bash deploy/setup_a10.sh
set -Eeuo pipefail

cd "$(dirname "$0")/.."
llm_model="${LLM_MODEL:-qwen3.5:9b}"
embed_model="${EMBED_MODEL:-bge-m3}"
run_experiment="${RUN_EXPERIMENT:-1}"
export LLM_MODEL="$llm_model" EMBED_MODEL="$embed_model"
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11+ required; install it and make it available as python3.')
PY

command -v nvidia-smi >/dev/null || { echo 'NVIDIA driver missing: install a data-center driver and reboot first.' >&2; exit 1; }
gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1)"
driver="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"
echo "GPU: $gpu_name; driver: $driver"
[[ "$gpu_name" == *A10* ]] || echo 'Warning: this script is tuned for A10.' >&2

cuda_wheel="$(python3 - "$driver" <<'PY'
import sys
parts = tuple(int(x) for x in sys.argv[1].split('.')[:3])
if parts >= (580, 65, 6):
    print('cu130')
elif parts >= (560, 35, 3):
    print('cu126')
else:
    raise SystemExit('Driver is too old: use NVIDIA driver 580.65.06+ (preferred), or 560.35.03+ for CUDA 12.6.')
PY
)"
echo "PyTorch CUDA wheel: $cuda_wheel"

python3 -m venv .venv || { echo 'Install python3-venv and rerun.' >&2; exit 1; }
.venv/bin/python -m pip install --upgrade pip
if [[ "$cuda_wheel" == cu130 ]]; then
    .venv/bin/python -m pip install 'torch==2.14.0'
else
    .venv/bin/python -m pip install 'torch==2.14.0' --index-url https://download.pytorch.org/whl/cu126
fi
.venv/bin/python -m pip install -r requirements.txt

if ! command -v ollama >/dev/null; then
    echo 'Installing Ollama from its official installer (sudo required)...'
    curl -fsSL https://ollama.com/install.sh | sh
fi
sudo systemctl enable --now ollama
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_NUM_PARALLEL=1"\nEnvironment="OLLAMA_MAX_LOADED_MODELS=1"\nEnvironment="OLLAMA_CONTEXT_LENGTH=4096"\n' |
    sudo tee /etc/systemd/system/ollama.service.d/a10.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart ollama

ollama pull "$llm_model"
ollama pull "$embed_model"

mkdir -p config data/clean data/labels data/eval
if [[ -e config/config.local.yaml ]]; then
    echo 'config/config.local.yaml already exists. Keep it and set models.llm/models.embed there if needed.'
else
cat > config/config.local.yaml <<EOF
models:
  llm: "$llm_model"
  embed: "$embed_model"
ui:
  use_mock: false
EOF
fi

.venv/bin/python - <<'PY'
import os
from src.config import load_config
models = load_config()['models']
for key, env in [('llm', 'LLM_MODEL'), ('embed', 'EMBED_MODEL')]:
    if models[key] != os.environ[env]:
        raise SystemExit(f'config.local.yaml has models.{key}={models[key]!r}; expected {os.environ[env]!r}')
PY

echo 'Checking PyTorch and reranker on CUDA...'
.venv/bin/python - <<'PY'
import torch
from sentence_transformers import CrossEncoder
from src.config import load_config
assert torch.cuda.is_available(), 'PyTorch cannot see CUDA'
assert 'A10' in torch.cuda.get_device_name(0), torch.cuda.get_device_name(0)
model = CrossEncoder(load_config()['models']['reranker'], device='cuda')
device = next(model.model.parameters()).device
assert device.type == 'cuda', f'Reranker on {device}'
print('torch CUDA:', torch.version.cuda, '| reranker:', device)
PY

echo 'Checking Ollama LLM and embeddings on GPU...'
.venv/bin/python - <<'PY'
from src import llm
from src.config import load_config
cfg = load_config()['models']
reply = llm.chat(model=cfg['llm'], messages=[{'role':'user','content':'Ответь одним словом: готово'}],
                 think=False, options={'temperature': 0, 'num_ctx': 4096})
assert reply.message.content, 'Empty LLM reply'
print('LLM response:', reply.message.content[:100])
PY
ollama ps
ollama ps | grep -F "$llm_model" | grep -q '100% GPU' || { echo 'LLM is not fully on GPU' >&2; exit 1; }
ollama stop "$llm_model"
.venv/bin/python - <<'PY'
from src import llm
from src.config import load_config
vectors = llm.embed(model=load_config()['models']['embed'], input=['проверка видеокарты']).embeddings
assert vectors and vectors[0], 'Empty embedding'
print('Embedding dimension:', len(vectors[0]))
PY
ollama ps
ollama ps | grep -F "$embed_model" | grep -q '100% GPU' || { echo 'Embedding model is not fully on GPU' >&2; exit 1; }

echo 'Running project checks...'
.venv/bin/python scripts/check_env.py
if [[ ! -f data/clean/synthetic_group.jsonl && ! -f data/labels/search_gold.jsonl ]]; then
    .venv/bin/python -m scripts.make_search_experiment_chat
fi
if [[ -f data/clean/synthetic_group.jsonl ]]; then
    .venv/bin/python -m src.index.build --chat synthetic_group
fi
if [[ "$run_experiment" == 1 && -f data/labels/search_gold.jsonl ]]; then
    .venv/bin/python -m eval.search_config_experiment --gold data/labels/search_gold.jsonl \
        --out data/eval/search_config_results.json
fi

echo "Ready. App URL via SSH tunnel: http://localhost:8501"
echo "On your laptop: ssh -N -L 8501:localhost:8501 USER@SERVER"
exec .venv/bin/streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8501
