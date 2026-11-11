#!/usr/bin/env bash
# Run in tmux: bash deploy/run_experiment.sh
set -Eeuo pipefail
cd "$(dirname "$0")/.."
run_dir="data/eval/run-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$run_dir"
cp data/labels/search_gold.jsonl "$run_dir/search_gold.jsonl"
cp config/config.yaml "$run_dir/config.yaml"
git rev-parse HEAD > "$run_dir/commit.txt"
nvidia-smi > "$run_dir/gpu.txt"
.venv/bin/python -m pip freeze > "$run_dir/packages.txt"
echo "Results directory: $run_dir"
echo "Watch: tail -f $run_dir/run.log"
trap 'tar -czf "$run_dir.tar.gz" "$run_dir"; echo "Archive: $run_dir.tar.gz"' EXIT
.venv/bin/python -u -m eval.search_config_experiment \
    --gold "$run_dir/search_gold.jsonl" --out "$run_dir/results.json" 2>&1 | tee "$run_dir/run.log"
