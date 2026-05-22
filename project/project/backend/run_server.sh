#!/usr/bin/env bash
# Запускает backend-сервер. Создаёт venv при первом запуске.
#
# Использование:
#   ./run_server.sh          # 0.0.0.0:8000
#   PORT=9000 ./run_server.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

if [ ! -d "$VENV_DIR" ]; then
    echo "[run_server] Создаю venv в $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
else
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
fi

echo "[run_server] Проверяю зависимости..."
pip install -r requirements.txt

echo "[run_server] Запуск uvicorn на $HOST:$PORT"
# --workers 1: ML-модели держим в одной памяти; реплики с отдельной
# копией моделей = +2-4 ГБ RAM на каждую. Для дипломного проекта хватит.
exec uvicorn main:app --host "$HOST" --port "$PORT" --workers 1
