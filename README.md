# Atlas300 vLLM Ascend

A Docker Compose stack for running local LLM inference on **Huawei Ascend 310P NPU** hardware, with a chat web interface and self-hosted web search.

Getting these cards to run and actually *do* something has been proven really difficult, but with a lot of googling, chatgpt, claude and gemini i've managed to get mine to output something legible.

PLease don't mind the AI generated slop of documentation here :P it actually works.

> Full engineering log — every experiment, dead end, and benchmark run — lives in [`CLAUDE.md`](./CLAUDE.md). This README is just the "how do I run this" summary.

## Stack

| Service | Image | Port |
|---------|-------|------|
| [vLLM](https://github.com/vllm-project/vllm) (Ascend fork) | `quay.io/ascend/vllm-ascend` (see profiles below) | 8002 |
| [Open WebUI](https://github.com/open-webui/open-webui) | `ghcr.io/open-webui/open-webui:latest` | 3000 |
| [SearXNG](https://github.com/searxng/searxng) | `docker.io/searxng/searxng:latest` | 8080 |

SearXNG is a self-hosted meta-search engine that gives Open WebUI web search with no external API key and no third-party dependency.

## Models

Two mutually-exclusive vLLM models are available as Compose **profiles** (both need the full 2-chip NPU and port 8002, so only one runs at a time):

| Profile | Model | Notes |
|---|---|---|
| `qwen36` (**default**) | `Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` — self-quantized w8a8 MoE, served as `qwen3.6-moe` | Uncensored (abliterated), ~31 tok/s, 24576 context, tool-calling works |
| `prod` | `Qwen2.5-Coder-14B-Instruct-abliterated` — dense fp16 | Uncensored (abliterated), ~9.5 tok/s, 32768 context, tool-calling not populated (known issue) |

## Quickstart

```bash
# Start production (Qwen3.6 MoE) — also brings up Open WebUI and SearXNG
docker compose --profile qwen36 up -d

# Follow logs — wait for "Application startup complete."
docker compose logs -f vllm-qwen36moe
```

- **Chat UI:** http://localhost:3000
- **vLLM API:** http://localhost:8002/v1
- **SearXNG:** http://localhost:8080

Plain `docker compose up -d` with no `--profile` flag only starts Open WebUI and SearXNG — a vLLM profile must always be specified explicitly.

### Switching models

```bash
docker compose --profile qwen36 down
docker compose --profile prod up -d
```

Open WebUI stays up across a switch; both vLLM services share a network alias so the UI never needs reconfiguring.

## Model Storage

| Path | Purpose |
|------|---------|
| `${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` | Active model, `qwen36` profile (38 GB) |
| `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct-abliterated` | Active model, `prod` profile (28 GB) |
| `vllm-atlas_vllm-cache` (Docker volume) | vLLM compilation cache |
| `openwebui-data/` | Open WebUI database (bind mount) |
| `searxng/settings.yml` | SearXNG config (bind mount) |

Models are bind-mounted directly by absolute host path, so moving this repository does not break model loading.

## Hardware

| Component | Details |
|-----------|---------|
| **Cards** | 1× Atlas 300I Duo (second card had a hardware defect, physically removed) |
| **Chips** | davinci0, davinci1 (Ascend 310P3, ~44 GB each) |
| **Total VRAM** | ~88 GB LPDDR4X |
| **OS** | Ubuntu 20.04.6 LTS |
| **CPU** | 2× Intel Xeon Silver 4210 @ 2.20 GHz (40 logical CPUs) |
| **RAM** | 62 GiB |
| **Ascend Driver** | 25.3.rc1 |
| **Ascend Firmware** | 7.8.0.2.212 |
| **CANN** | 8.5.1 |
| **vLLM (Ascend fork)** | v0.23.0 (310P-openeuler) |
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
                             ↘ SearXNG (8080) → internet, for web search
```

All three services share the `llmnet` Docker bridge network. The vLLM API is OpenAI-compatible — any tool supporting the OpenAI API can point at `http://localhost:8002/v1`.

## API Access

The vLLM API is OpenAI-compatible and accessible from any machine on the LAN.

| Endpoint | URL |
|---------|-----|
| LAN | `http://<HOST_IP>:8002/v1` |

No API key required. Pass any non-empty string if the client requires one (e.g. `sk-no-key-required`). See [`guia-api.md`](./guia-api.md) for a fuller usage guide (Spanish) with curl, Python, and JavaScript examples.

### Test with curl

```bash
# List available models
curl http://<HOST_IP>:8002/v1/models

# Chat completion
curl http://<HOST_IP>:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-moe",
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
    model="qwen3.6-moe",
    messages=[{"role": "user", "content": "Write a hello world in Python"}],
)
print(response.choices[0].message.content)
```

## Key vLLM Parameters (`qwen36` profile)

| Parameter | Value | Reason |
|-----------|-------|--------|
| `--dtype` | `float16` | Required for Ascend 310P compatibility |
| `--quantization` | `ascend` | w8a8 checkpoint, ascend-native (msmodelslim) format |
| `--tensor-parallel-size` | `2` | Splits model across both chips |
| `--max-model-len` | `24576` | Max context window (input + output); 310P's attention-mask-compression limit caps this below 32768 |
| `--gpu-memory-utilization` | `0.90` | Fraction of NPU memory used for weights + KV cache |
| `--max-num-seqs` | `16` | Max concurrent sequences |
| `--reasoning-parser` | `qwen3` | Splits `<think>` chain-of-thought into a separate `reasoning` field |
| `--enable-auto-tool-choice` / `--tool-call-parser qwen3_coder` | — | Enables structured tool-calling |
| `--override-generation-config` | `{"temperature": 0.2, "repetition_penalty": 1.1}` | Fixes a reasoning-non-termination bug in this model family (see `CLAUDE.md`) |

vLLM's own triton JIT compiler doesn't support the 310P at all — the container's entrypoint works around this by renaming the bundled (broken) `triton` package before `vllm serve` starts, so `torch` falls back to the vendor's own Ascend compiler cleanly. See `CLAUDE.md` for the full story.

## Performance Baseline

Measured 2026-08-19 against the live `qwen36` profile API, full comparison vs. the prior bf16 checkpoint in `CLAUDE.md`:

| Metric | Value |
|--------|-------|
| Single-stream throughput | 31.36 tok/s |
| Concurrent-8 throughput | 39.85 tok/s |
| Context window | 24576 tokens |
| Tool-calling | Populated correctly |

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
# Start production (Qwen3.6 MoE)
docker compose --profile qwen36 up -d

# Start the dense Qwen2.5-Coder-14B alternative instead
docker compose --profile prod up -d

# View logs
docker compose logs -f vllm-qwen36moe    # or vllm-qwen25coder, depending on active profile
docker compose logs -f openwebui
docker compose logs -f searxng

# Stop everything (add --profile prod or --profile qwen36 to target just the active vLLM service)
docker compose --profile prod --profile qwen36 down

# Check NPU status
npu-smi info
npu-smi info -l
```
