#!/usr/bin/env bash
# switch.sh — switch between vLLM model profiles
# Usage: ./switch.sh [deepseek|qwen3|qwen25coder]

set -e
COMPOSE="docker compose"
DB="/app/backend/data/webui.db"

PROFILES=(deepseek qwen3 qwen25coder)
TARGET="$1"

if [[ -z "$TARGET" || ! " ${PROFILES[*]} " =~ " $TARGET " ]]; then
  echo "Usage: $0 [deepseek|qwen3|qwen25coder]"
  exit 1
fi

echo "==> Stopping all model containers..."
for p in "${PROFILES[@]}"; do
  $COMPOSE --profile "$p" down 2>/dev/null || true
done

declare -A PROFILE_PORT
PROFILE_PORT[deepseek]=8000
PROFILE_PORT[qwen3]=8001
PROFILE_PORT[qwen25coder]=8002
PORT="${PROFILE_PORT[$TARGET]}"

echo "==> Starting profile: $TARGET"
$COMPOSE --profile "$TARGET" up -d

# Toggle Qwen3-specific model entries in Open WebUI DB
if [[ "$TARGET" == "qwen3" ]]; then
  ACTIVE=1
else
  ACTIVE=0
fi

echo "==> Setting Qwen3 model visibility to: $ACTIVE"
docker exec openwebui python3 -c "
import sqlite3
conn = sqlite3.connect('$DB')
conn.execute(\"UPDATE model SET is_active = $ACTIVE WHERE id IN ('qwen3-32b', 'Qwen/Qwen3-32B')\")
conn.commit()
print('Rows updated:', conn.total_changes)
conn.close()
"

LAN_IP=$(hostname -I | awk '{print $1}')
echo "==> Done. Watch logs with: docker compose logs -f vllm-$TARGET"
echo "==> API ready at: http://$LAN_IP:$PORT/v1"
