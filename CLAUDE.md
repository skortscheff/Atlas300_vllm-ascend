# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker Compose deployment for LLM inference on Ascend NPU hardware. Two services:
- **vLLM** (`quay.io/ascend/vllm-ascend:main-310p-openeuler`) — serves the model on port 8002
- **Open WebUI** (`ghcr.io/open-webui/open-webui:latest`) — chat UI on port 3000

## Models

One model is active:

| Profile | Model | Port | Status |
|---------|-------|------|--------|
| `qwen25coder` | `Qwen/Qwen2.5-Coder-14B-Instruct` | 8002 | ✅ Active |

### Starting

```bash
docker compose --profile qwen25coder up -d
```

### Open WebUI custom model entries

| UI name | DB id | Notes |
|---------|-------|-------|
| `Qwen/Qwen2.5-Coder-14B-Instruct` | `Qwen/Qwen2.5-Coder-14B-Instruct` | Default — no custom params |

## Common Commands

```bash
# Start
docker compose --profile qwen25coder up -d

# Stop everything
docker compose --profile qwen25coder down
docker compose down                          # stops openwebui

# View logs
docker compose logs -f vllm-qwen25coder
docker compose logs -f openwebui

# Check NPU status
npu-smi info
npu-smi info -l
```

## Architecture

```
User → Open WebUI (port 3000) → vLLM API (http://vllm-qwen25coder:8000/v1) → Ascend NPU
```

**Network:** Both services share the `llmnet` bridge network.

**Model:** `Qwen/Qwen2.5-Coder-14B-Instruct` — stored at `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct`, mounted into the container as `/models/Qwen2.5-Coder-14B-Instruct`

**Hardware:** 2× Atlas 300I Duo cards installed; only one is active (`/dev/davinci0`, `/dev/davinci1`). Second card fails to initialize (firmware issue).

**Key vLLM parameters:**
- `--dtype float16`
- `--tensor-parallel-size 2`
- `--max-model-len 32768`
- `--max-num-batched-tokens 32768`
- `--max-num-seqs 32`
- `--gpu-memory-utilization 0.95`
- `--swap-space 8`
- `--enforce-eager` with `--compilation-config '{"mode":0}'` (disables graph compilation for Ascend compatibility)

**Driver mounts** (host paths that must exist):
- `/usr/local/dcmi`
- `/usr/local/bin/npu-smi`
- `/usr/local/Ascend/driver/lib64`
- `/usr/local/Ascend/driver/version.info`
- `/etc/ascend_install.info`

**Volumes:** Model is a bind mount at `${MODELS_DIR}` → `/models`. `vllm-cache` is a named Docker volume. `openwebui-data/` is a bind mount in the project directory.

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

## LAN API Access

The vLLM API is OpenAI-compatible and reachable from any machine on the LAN. `ufw` is inactive on this host — no firewall rules needed.

| Profile | LAN endpoint |
|---------|-------------|
| `qwen25coder` | `http://<HOST_IP>:8002/v1` |

No API key required. See `guia-api.md` for a full usage guide (Spanish) with curl, Python, and JavaScript examples.

## Deployment Notes

- NPU devices on this host are `/dev/davinci0` and `/dev/davinci1`
- Before starting, ensure no other containers are using ports 8002 or 3000
- vLLM takes ~2 minutes to load the model; watch for `Application startup complete.` in logs before sending requests
