# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker Compose deployment for LLM inference on Ascend NPU hardware. Two services:
- **vLLM** (`quay.io/ascend/vllm-ascend:main-310p-openeuler`) — serves the model on port 8000
- **Open WebUI** (`ghcr.io/open-webui/open-webui:latest`) — chat UI on port 3000

## Models

Two models are configured via Docker Compose profiles — only one can run at a time (both are 32B FP16 and saturate the NPU).

| Profile | Model | Port | Reasoning parser |
|---------|-------|------|-----------------|
| `deepseek` | `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | 8000 | `deepseek_r1` |
| `qwen3` | `Qwen/Qwen3-32B` | 8001 | `qwen3` |

Open WebUI is always running and pre-configured with both endpoints. It shows whichever model is currently loaded.

## Common Commands

```bash
# Start with DeepSeek
docker compose --profile deepseek up -d

# Start with Qwen3
docker compose --profile qwen3 up -d

# Switch models (stop current, start other)
docker compose --profile deepseek down
docker compose --profile qwen3 up -d

# Stop everything
docker compose --profile deepseek down   # or --profile qwen3
docker compose down                       # stops openwebui

# View logs
docker compose logs -f vllm-deepseek
docker compose logs -f vllm-qwen3
docker compose logs -f openwebui

# Restart a model service
docker compose --profile deepseek restart vllm-deepseek

# Check NPU status
npu-smi info
```

## Architecture

```
User → Open WebUI (port 3000) → vLLM API (http://vllm:8000/v1) → Ascend NPU
```

**Network:** Both services share the `llmnet` bridge network.

**Model:** `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` (downloaded automatically from HuggingFace on first start; cached in the `hf-cache` Docker volume at `/root/.cache/huggingface`)

**Hardware:** 2× Ascend 310P chips (`/dev/davinci2`, `/dev/davinci3`) with tensor-parallel-size=2

**Key vLLM parameters:**
- `--dtype float16`
- `--tensor-parallel-size 2`
- `--max-model-len 8192`
- `--gpu-memory-utilization 0.92`
- `--enforce-eager` with `--compilation-config '{"mode":0}'` (disables graph compilation for Ascend compatibility)
- `--reasoning-parser deepseek_r1` (required for clean output on this Ascend build — streaming thinking tokens go to `delta.reasoning`, final answer to `delta.content`)

**Driver mounts** (host paths that must exist):
- `/usr/local/dcmi`
- `/usr/local/bin/npu-smi`
- `/usr/local/Ascend/driver/lib64`
- `/usr/local/Ascend/driver/version.info`
- `/etc/ascend_install.info`

**Volumes:** `hf-cache` and `vllm-cache` are named Docker volumes for persistent caching. `openwebui-data/` is a bind mount in the project directory.

## Open WebUI Admin

- **URL:** `http://localhost:3000`
- **Admin email:** `admin@example.com`
- **Database:** `openwebui-data/webui.db` (SQLite)

### Stats Footer Function

A filter function (`stats-footer`) is installed and active in Open WebUI. It appends a generation stats line to every assistant reply:

```
---
`⚡ N.N tok/s · NNN gen · ctx NNN/8192 (N%)`
```

The function reads token usage from the Open WebUI SQLite DB. If it stops working, check:

```bash
# Verify function is active
docker exec openwebui python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
print(conn.execute(\"SELECT id, is_active, is_global FROM function WHERE id='stats-footer'\").fetchone())
conn.close()
"

# Re-enable if is_active = 0
docker exec openwebui python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
conn.execute(\"UPDATE function SET is_active = 1 WHERE id = 'stats-footer'\")
conn.commit()
conn.close()
"
```

### Reset admin password

```bash
docker exec openwebui python3 -c "
import bcrypt, sqlite3
hashed = bcrypt.hashpw(b'NEWPASSWORD', bcrypt.gensalt()).decode()
conn = sqlite3.connect('/app/backend/data/webui.db')
cur = conn.cursor()
cur.execute(\"UPDATE auth SET password = ? WHERE email = ?\", (hashed, 'admin@example.com'))
conn.commit()
print('Rows updated:', cur.rowcount)
conn.close()
"
```

## Deployment Notes

- NPU devices on this host are `/dev/davinci2` and `/dev/davinci3` (not 0/1 — update `docker-compose.yml` accordingly if re-deploying on different hardware)
- Before starting, ensure no other containers are using ports 8000 or 3000
- vLLM takes ~2 minutes to load the model; watch for `Application startup complete.` in logs before sending requests
