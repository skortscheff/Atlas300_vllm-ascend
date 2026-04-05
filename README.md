# Atlas300 vLLM Ascend

A Docker Compose stack for running local LLM inference on **Huawei Ascend 310P NPU** hardware, with a chat web interface.

Getting these cards to run and actually *do* something has been proven really difficult, but with a lot of googling, chatgpt, claude and gemini i've managed to get mine to output something legible.

PLease don't mind the AI generated slop of documentation here :P it actually works.

## Stack

| Service | Image | Port |
|---------|-------|------|
| [vLLM](https://github.com/vllm-project/vllm) (Ascend fork) | `quay.io/ascend/vllm-ascend:main-310p-openeuler` | 8002 |
| [Open WebUI](https://github.com/open-webui/open-webui) | `ghcr.io/open-webui/open-webui:latest` | 3000 |

## Model

| Profile | Model | Port |
|---------|-------|------|
| `qwen25coder` | `Qwen/Qwen2.5-Coder-14B-Instruct` | 8002 |

## Quickstart

```bash
docker compose --profile qwen25coder up -d

# Follow logs — wait for "Application startup complete."
docker compose logs -f vllm-qwen25coder
```

- **Chat UI:** http://localhost:3000
- **vLLM API:** http://localhost:8002/v1

## Model Storage

| Path | Purpose |
|------|---------|
| `${MODELS_DIR}/hf-cache` | HuggingFace cache (mounted as `/root/.cache/huggingface` in container) |
| `${MODELS_DIR}` | Also mounted as `/models` |

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

| Profile | LAN endpoint |
|---------|-------------|
| `qwen25coder` | `http://<HOST_IP>:8002/v1` |

No API key required. Pass any non-empty string if the client requires one (e.g. `sk-no-key-required`).

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
| `--enforce-eager` | — | Required for Ascend 310P compatibility |
| `--compilation-config` | `{"mode":0}` | Disables graph compilation (Ascend) |

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
docker compose --profile qwen25coder up -d

# View logs
docker compose logs -f vllm-qwen25coder
docker compose logs -f openwebui

# Stop everything
docker compose --profile qwen25coder down
docker compose down   # stops openwebui

# Check NPU status
npu-smi info
npu-smi info -l
```
