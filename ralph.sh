#!/usr/bin/env bash
set -euo pipefail

REPO="/home/ilya/Desktop/tg_client"
PLANS_DIR="$REPO/1plans"

# Если передано имя файла плана — берём его из $PLANS_DIR,
# иначе используем план по умолчанию.
if [[ $# -gt 0 ]]; then
  PLAN_FILE="$PLANS_DIR/$1"
else
  PLAN_FILE="$PLANS_DIR/plan_add_user.md"
fi

PROMPT="$PLANS_DIR/promt.md"

cd "$REPO"

START_TS=$(date +%s)

echo "Старт цикла Codex по задачам из $PLAN_FILE"

while grep -E '^- ' "$PLAN_FILE" | grep -vq '^- \[x\] '; do
  echo "Есть невыполненные задачи, запускаю Codex..."
  codex exec --full-auto "$PROMPT"
  echo "Итерация Codex завершена, проверяю задачи..."
  sleep 2
done

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

MINUTES=$((ELAPSED / 60))
SECONDS=$((ELAPSED % 60))

echo "Все задачи из $PLAN_FILE помечены как выполненные."
echo "Общее время работы: ${MINUTES} мин ${SECONDS} сек."