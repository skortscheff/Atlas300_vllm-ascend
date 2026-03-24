# Atlas300 vLLM Ascend

A Docker Compose stack for running local LLM inference on **Huawei Ascend 310P NPU** hardware, with a chat web interface.

Getting these cards to run and actually *do* something has been proven really difficult, but with a lot of googling, chatgpt, claude and gemini i've managed to get mine to output something legible. 

PLease don't mind the AI generated slop of documentation here :P it actually works. 

## Stack

| Service | Image | Port |
|---------|-------|------|
| [vLLM](https://github.com/vllm-project/vllm) (Ascend fork) | `quay.io/ascend/vllm-ascend:main-310p-openeuler` | 8000–8002 |
| [Open WebUI](https://github.com/open-webui/open-webui) | `ghcr.io/open-webui/open-webui:latest` | 3000 |

## Models

Three models are available as Docker Compose profiles. **Only one model can run at a time** (all are large FP16 models that saturate the NPU).

| Profile | Model | Port | Reasoning parser |
|---------|-------|------|-----------------|
| `deepseek` | `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | 8000 | `deepseek_r1` |
| `qwen3` | `Qwen/Qwen3-32B` | 8001 | `qwen3` |
| `qwen25coder` | `Qwen/Qwen2.5-Coder-14B-Instruct` | 8002 | — |

Open WebUI runs continuously and connects to whichever model is loaded.

## Quickstart

```bash
git clone https://github.com/skortscheff/Atlas300_vllm-ascend.git
cd Atlas300_vllm-ascend

# Start with Qwen2.5 Coder (recommended first-run — smallest model)
docker compose --profile qwen25coder up -d

# Follow logs — wait for "Application startup complete."
docker compose logs -f vllm-qwen25coder
```

- **Chat UI:** http://localhost:3000
- **vLLM API:** http://localhost:8002/v1

## Switching Models

Use the included `switch.sh` script — it stops the current model, starts the new one, and updates Open WebUI model visibility automatically:

```bash
./switch.sh deepseek      # DeepSeek-R1 Distill Qwen 32B
./switch.sh qwen3         # Qwen3-32B (with Qwen3-32B Fast entry in UI)
./switch.sh qwen25coder   # Qwen2.5-Coder-14B-Instruct
```

> **Note:** vLLM takes ~2 minutes to load a model. Watch for `Application startup complete.` in the logs before sending requests.

### Manual switching (without the script)

```bash
# Stop current model (example: qwen3)
docker compose --profile qwen3 down

# Start a different model
docker compose --profile deepseek up -d

# View logs
docker compose logs -f vllm-deepseek
```

## Hardware

| Chip | Device | HBM |
|------|--------|-----|
| davinci2 (chip 0) | Ascend 310P3 | ~43 GB |
| davinci3 (chip 1) | Ascend 310P3 | ~43 GB |
| **Total** | | **~87 GB** |

With a 32B float16 model (~64 GB), ~23 GB remains for KV cache across both chips.

## Environment

| Component | Details |
|-----------|---------|
| **OS** | Ubuntu 20.04.6 LTS |
| **CPU** | 2× Intel Xeon Silver 4210 @ 2.20 GHz (40 logical CPUs) |
| **RAM** | 62 GiB |
| **Ascend Driver** | 25.2.0 |
| **Docker Engine** | 28.1.1 |
| **Docker Compose** | v2.35.1 |

## Requirements

- Huawei Ascend 310P NPU (2 chips)
- Ascend drivers and card firmware installed on the host (Sorry, you'll have to look really hard for these T_T ) 
- Docker + Docker Compose

### Required host paths

```
/usr/local/dcmi
/usr/local/bin/npu-smi
/usr/local/Ascend/driver/lib64
/usr/local/Ascend/driver/version.info
/etc/ascend_install.info
```

## Architecture

```
Browser → Open WebUI (3000) → vLLM API (8000/8001/8002) → Ascend NPU (davinci2 + davinci3)
```

Both services share the `llmnet` Docker bridge network. The vLLM API is OpenAI-compatible — any tool supporting the OpenAI API can point at `http://localhost:800x/v1`.

## Key vLLM Parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| `--dtype` | `float16` | Reduces NPU memory usage |
| `--tensor-parallel-size` | `2` | Splits model across both chips |
| `--max-model-len` | `8192` | Max context window (input + output) |
| `--gpu-memory-utilization` | `0.95` | Uses 95% of NPU HBM for KV cache |
| `--enforce-eager` | — | Required for Ascend compatibility |
| `--compilation-config` | `{"mode":0}` | Disables graph compilation (Ascend) |
| `--reasoning-parser` | model-specific | Routes thinking tokens to `delta.reasoning` |

## Open WebUI

- **URL:** http://localhost:3000
- **Admin:** `admin@example.com`
- **Connections:** managed via **Admin Panel → Settings → Connections** (stored in SQLite DB — env vars are ignored once the DB is initialized)

### Custom model entries

| UI name | Profile | Notes |
|---------|---------|-------|
| `Qwen3-32B (fast)` | `qwen3` only | Injects `/no_think` as system prompt to skip reasoning chain. Visible only when qwen3 profile is active (`switch.sh` toggles this automatically). |

### Generation Stats Footer

Every assistant reply ends with:

```
---
`⚡ 11.3 tok/s · 243 gen · ctx 487/8192 (6%)`
```

Implemented as an Outlet Filter function in the Open WebUI DB. If it stops working:

```bash
# Check status
docker exec openwebui python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
print(conn.execute(\"SELECT id, is_active FROM function WHERE id='stats-footer'\").fetchone())
conn.close()
"

# Re-enable
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
conn.execute(\"UPDATE auth SET password = ? WHERE email = ?\", (hashed, 'admin@example.com'))
conn.commit()
conn.close()
"
```

## NPU Device Mapping

This setup uses `/dev/davinci2` and `/dev/davinci3`. If your system uses different device numbers, update `docker-compose.yml`:

```yaml
environment:
  ASCEND_VISIBLE_DEVICES: "2,3"
devices:
  - /dev/davinci2
  - /dev/davinci3
```

Check available devices:
```bash
ls /dev/davinci*
npu-smi info
```

## Useful Commands

```bash
# Switch models (recommended)
./switch.sh [deepseek|qwen3|qwen25coder]

# View logs
docker compose logs -f vllm-deepseek
docker compose logs -f vllm-qwen3
docker compose logs -f vllm-qwen25coder
docker compose logs -f openwebui

# Stop everything
docker compose --profile deepseek down   # or --profile qwen3 / qwen25coder
docker compose down                       # stops openwebui

# Test the API directly
curl http://localhost:8002/v1/models

# Check NPU status
npu-smi info
```
