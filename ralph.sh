#!/usr/bin/env bash
set -euo pipefail

REPO="/home/ilya/Desktop/tg_client"
PLAN_FILE="$REPO/1plans/plan_add_user.md"
PROMPT="$REPO/1plans/promt.md"

cd "$REPO"

echo "Старт цикла Codex по задачам из $PLAN_FILE"

while grep -E '^- ' "$PLAN_FILE" | grep -vq '^- \[x\] '; do
  echo "Есть невыполненные задачи, запускаю Codex..."
  codex exec --full-auto "$PROMPT"
  echo "Итерация Codex завершена, проверяю задачи..."
  sleep 2
done

echo "Все задачи из $PLAN_FILE помечены как выполненные."