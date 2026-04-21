# Atlas300 vLLM Ascend

A Docker Compose stack for running local LLM inference on **Huawei Ascend 310P NPU** hardware, with a chat web interface.

Getting these cards to run and actually *do* something has been proven really difficult, but with a lot of googling, chatgpt, claude and gemini i've managed to get mine to output something legible.

PLease don't mind the AI generated slop of documentation here :P it actually works.

## Stack

| Service | Image | Port |
|---------|-------|------|
| [vLLM](https://github.com/vllm-project/vllm) (Ascend fork) | `quay.io/ascend/vllm-ascend:main-310p-openeuler-stable` | 8002 |
| [Open WebUI](https://github.com/open-webui/open-webui) | `ghcr.io/open-webui/open-webui:latest` | 3000 |

## Model

| Model | Port |
|-------|------|
| `Qwen/Qwen2.5-Coder-14B-Instruct` | 8002 |

## Quickstart

```bash
docker compose up -d

# Follow logs — wait for "Application startup complete."
docker compose logs -f vllm-qwen25coder
```

- **Chat UI:** http://localhost:3000
- **vLLM API:** http://localhost:8002/v1

## Model Storage

| Path | Purpose |
|------|---------|
| `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct` | Active model (28 GB, bind-mounted directly into the container) |
| `vllm-atlas_vllm-cache` (Docker volume) | vLLM compilation cache |

The compose file uses the absolute host path `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct`
and mounts it into the container as `/models/Qwen2.5-Coder-14B-Instruct`, so moving this
repository does not break model loading.

## Hardware

| Component | Details |
|-----------|---------|
| **Cards** | 2× Atlas 300I Duo (1 active) |
| **Chips (active)** | davinci0, davinci1 (Ascend 310P3, ~44 GB each) |
| **Total VRAM (active)** | ~88 GB LPDDR4X |
| **OS** | Ubuntu 20.04.6 LTS |
| **CPU** | 2× Intel Xeon Silver 4210 @ 2.20 GHz (40 logical CPUs) |
| **RAM** | 62 GiB |
| **Ascend Driver** | 25.2.0 |
| **Ascend Firmware** | 7.7.0.6.236 |
| **CANN** | 8.5.1 |
| **vLLM** | 0.17.0 (Ascend fork) |
| **Docker Engine** | 28.1.1 |
| **Docker Compose** | v2.35.1 |

## Requirements

- Huawei Ascend 310P NPU (Atlas 300I Duo)
- Ascend drivers and firmware installed on the host
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
Browser → Open WebUI (3000) → vLLM API (8002) → Ascend NPU (davinci0 + davinci1)
```

Both services share the `llmnet` Docker bridge network. The vLLM API is OpenAI-compatible — any tool supporting the OpenAI API can point at `http://localhost:8002/v1`.

## API Access

The vLLM API is OpenAI-compatible and accessible from any machine on the LAN.

| Endpoint | URL |
|---------|-----|
| LAN | `http://<HOST_IP>:8002/v1` |

No API key required. Pass any non-empty string if the client requires one (e.g. `sk-no-key-required`).

Validated on 2026-04-21:
- `GET /v1/models` returned `Qwen2.5-Coder-14B-Instruct`
- `POST /v1/chat/completions` completed successfully at 10.95 tok/s on a 311-token generation benchmark

### Test with curl

```bash
# List available models
curl http://<HOST_IP>:8002/v1/models

# Chat completion
curl http://<HOST_IP>:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 20
  }'
```

### Python (openai SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<HOST_IP>:8002/v1",
    api_key="sk-no-key-required",
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-Coder-14B-Instruct",
    messages=[{"role": "user", "content": "Write a hello world in Python"}],
)
print(response.choices[0].message.content)
```

## Key vLLM Parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| `--dtype` | `float16` | Required for Ascend 310P compatibility |
| `--tensor-parallel-size` | `2` | Splits model across both chips |
| `--max-model-len` | `32768` | Max context window (input + output) |
| `--gpu-memory-utilization` | `0.95` | Uses 95% of NPU memory for KV cache |
| `--max-num-seqs` | `32` | Max concurrent sequences |
| `--enforce-eager` | — | Required for Ascend 310P compatibility |
| `--compilation-config` | `{"mode":0}` | Disables graph compilation (Ascend) |

## Performance Baseline

Measured 2026-04-21 against `http://127.0.0.1:8002/v1/chat/completions`:

| Metric | Value |
|--------|-------|
| Prompt tokens | 47 |
| Completion tokens | 311 |
| Total tokens | 358 |
| Total time | 28.394 s |
| Throughput | 10.95 tok/s |

## Open WebUI

- **URL:** http://localhost:3000
- **Admin:** `admin@example.com`

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

## Useful Commands

```bash
# Start
docker compose up -d

# View logs
docker compose logs -f vllm-qwen25coder
docker compose logs -f openwebui

# Stop everything
docker compose down

# Check NPU status
npu-smi info
npu-smi info -l
```
