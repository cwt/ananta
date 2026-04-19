#!/bin/bash

OS_NAME=$(uname -s)
case "$OS_NAME" in
  Darwin)  CPU_CORES=$(sysctl -n hw.physicalcpu);;
  Linux)   CPU_CORES=$(lscpu | awk '/^Core\(s\) per socket:/ {c=$4} /^Socket\(s\):/ {s=$2; sum += c * s} END {print sum}');;
  *)       CPU_CORES=$(python3 -c "import multiprocessing; print(multiprocessing.cpu_count())");;
esac

rm -rf */__pycache__ .pytest_cache
poetry update
poetry install
poetry run pytest tests/ -n $CPU_CORES --cov=ananta --cov-report=term-missing --cov-fail-under=85
