# Atlas300 vLLM Ascend

A Docker Compose stack for running a local LLM inference server on **Huawei Ascend 310P NPU** hardware, with a chat web interface.

## Stack

| Service | Image | Port |
|---------|-------|------|
| [vLLM](https://github.com/vllm-project/vllm) (Ascend fork) | `quay.io/ascend/vllm-ascend:main-310p-openeuler` | 8000 |
| [Open WebUI](https://github.com/open-webui/open-webui) | `ghcr.io/open-webui/open-webui:latest` | 3000 |

**Model:** DeepSeek-R1 Distill Qwen 32B (`ds_r1_qwen32b`)

## Hardware

| Chip | Device | Total HBM | Notes |
|------|--------|-----------|-------|
| 0 | davinci2 | ~43 GB | — |
| 1 | davinci3 | ~43 GB | — |
| **Total** | | **~87 GB** | ~23 GB available for KV cache with 32B float16 |

## Model Selection

The 32B model was chosen based on the available HBM:

| Model | VRAM (float16) | Fits? | Notes |
|-------|---------------|-------|-------|
| DeepSeek-R1 Distill Qwen **32B** | ~64 GB | ✅ | **Current — comfortable fit, no quantization needed** |
| DeepSeek-R1 Distill Llama 70B | ~140 GB | ⚠️ | W8A8 quantization required (needs vllm-ascend ≥ v0.15.0) |
| DeepSeek-R1 Distill Llama 8B | ~16 GB | ✅ | Previous model — underutilized VRAM |

## Environment

### Host System

| Component | Details |
|-----------|---------|
| **OS** | Ubuntu 20.04.6 LTS (Focal Fossa) |
| **CPU** | 2× Intel Xeon Silver 4210 @ 2.20 GHz (2 sockets × 10 cores × 2 threads = 40 logical CPUs) |
| **RAM** | 62 GiB |
| **Swap** | 4 GiB |
| **Disk** | 879 GB (`/dev/sda2`), ~428 GB free |

### NPU Hardware

| Chip | Model | HBM Total | Bus ID |
|------|-------|-----------|--------|
| davinci2 (chip 0) | Huawei Ascend 310P3 | 44,280 MB (~43 GB) | 0000:86:00.0 |
| davinci3 (chip 1) | Huawei Ascend 310P3 | 43,693 MB (~43 GB) | 0000:86:00.0 |
| **Total** | | **~87 GB HBM** | |

> With DeepSeek-R1-Distill-Qwen-32B in float16 (~64 GB model weights), roughly 23 GB remains available for KV cache across both chips.

### Software Versions

| Software | Version |
|----------|---------|
| **Ascend Driver / npu-smi** | 25.2.0 |
| **Ascend HAL** | 7.35.23 |
| **Docker Engine** | 28.1.1 |
| **Docker Compose** | v2.35.1 |
| **vLLM image** | `quay.io/ascend/vllm-ascend:main-310p-openeuler` |
| **Open WebUI image** | `ghcr.io/open-webui/open-webui:latest` |

---

## Requirements

- Huawei Ascend 310P NPU (2 chips)
- Ascend drivers installed on the host
- Docker + Docker Compose
### Required host paths

```
/usr/local/dcmi
/usr/local/bin/npu-smi
/usr/local/Ascend/driver/lib64
/usr/local/Ascend/driver/version.info
/etc/ascend_install.info
```

## Quickstart

```bash
# Clone
git clone https://github.com/skortscheff/Atlas300_vllm-ascend.git
cd Atlas300_vllm-ascend

# Start
docker compose up -d

# Follow vLLM logs (takes ~2 min to load model)
docker compose logs -f vllm
```

Once you see `Application startup complete.` in the logs, the stack is ready.

- **Chat UI:** http://localhost:3000
- **vLLM API:** http://localhost:8000/v1

## Architecture

```
Browser → Open WebUI (3000) → vLLM API (http://vllm:8000/v1) → Ascend NPU (davinci2 + davinci3)
```

Both services communicate over an internal Docker bridge network (`llmnet`). The vLLM API is OpenAI-compatible, so any tool that supports the OpenAI API can point at `http://localhost:8000/v1`.

## Key vLLM Parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| `--dtype` | `float16` | Reduces NPU memory usage |
| `--tensor-parallel-size` | `2` | Splits model across both chips |
| `--max-model-len` | `8192` | Max context window (input + output) |
| `--gpu-memory-utilization` | `0.92` | Uses 92% of NPU memory for KV cache |
| `--enforce-eager` | — | Required for Ascend compatibility |
| `--compilation-config` | `{"mode":0}` | Disables graph compilation (Ascend; `mode` key replaces deprecated `level`) |
| `--reasoning-parser` | `deepseek_r1` | Parses DeepSeek-R1 `<think>` blocks — clean answer in `content`, reasoning in `reasoning_content` |
| `--max-thinking-tokens` | `2048` | Caps chain-of-thought length — prevents the model over-thinking simple questions |

## NPU Device Mapping

This setup uses `/dev/davinci2` and `/dev/davinci3`. If your system uses different device numbers, update `docker-compose.yml`:

```yaml
environment:
  ASCEND_VISIBLE_DEVICES: "2,3"   # adjust to your chip indices
devices:
  - /dev/davinci2
  - /dev/davinci3
```

Check available devices with:
```bash
ls /dev/davinci*
npu-smi info
```

## Useful Commands

```bash
# Stop the stack
docker compose down

# Restart a service
docker compose restart vllm

# Test the API
curl http://localhost:8000/v1/models

# Reset Open WebUI admin password
docker exec openwebui python3 -c "
import bcrypt, sqlite3
hashed = bcrypt.hashpw(b'NEWPASSWORD', bcrypt.gensalt()).decode()
conn = sqlite3.connect('/app/backend/data/webui.db')
cur = conn.cursor()
cur.execute(\"UPDATE auth SET password = ? WHERE email = ?\", (hashed, 'your@email.com'))
conn.commit()
conn.close()
"
```
