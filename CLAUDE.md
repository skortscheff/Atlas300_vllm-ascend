# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker Compose deployment for LLM inference on Ascend NPU hardware. Two services:
- **vLLM** (`quay.io/ascend/vllm-ascend:v0.9.2rc1-310p-openeuler`) — serves the model on port 8000
- **Open WebUI** (`ghcr.io/open-webui/open-webui:latest`) — chat UI on port 3000

## Common Commands

```bash
# Start stack
docker compose up -d

# Stop stack
docker compose down

# View logs
docker compose logs -f vllm
docker compose logs -f openwebui

# Restart a single service
docker compose restart vllm

# Check NPU status
npu-smi info
```

## Architecture

```
User → Open WebUI (port 3000) → vLLM API (http://vllm:8000/v1) → Ascend NPU
```

**Network:** Both services share the `llmnet` bridge network.

**Model:** `${MODELS_DIR}/ds_r1_llama8b` (mounted read-only into container at `/models`)

**Hardware:** 2× Ascend 310P chips (`/dev/davinci2`, `/dev/davinci3`) with tensor-parallel-size=2

**Key vLLM parameters:**
- `--dtype float16`
- `--tensor-parallel-size 2`
- `--max-model-len 4096`
- `--gpu-memory-utilization 0.92`
- `--enforce-eager` with `--compilation-config '{"level":0}'` (disables graph compilation for Ascend compatibility)

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
