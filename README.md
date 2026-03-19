# Atlas300 vLLM Ascend

A Docker Compose stack for running a local LLM inference server on **Huawei Ascend 310P NPU** hardware, with a chat web interface.

## Stack

| Service | Image | Port |
|---------|-------|------|
| [vLLM](https://github.com/vllm-project/vllm) (Ascend fork) | `quay.io/ascend/vllm-ascend:v0.9.2rc1-310p-openeuler` | 8000 |
| [Open WebUI](https://github.com/open-webui/open-webui) | `ghcr.io/open-webui/open-webui:latest` | 3000 |

**Model:** DeepSeek-R1 distilled Llama 8B (`ds_r1_llama8b`)

## Requirements

- Huawei Ascend 310P NPU (2 chips)
- Ascend drivers installed on the host
- Docker + Docker Compose
- Model weights in `${MODELS_DIR}/ds_r1_llama8b`

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
| `--max-model-len` | `4096` | Max context window (input + output) |
| `--gpu-memory-utilization` | `0.92` | Uses 92% of NPU memory for KV cache |
| `--enforce-eager` | — | Required for Ascend compatibility |
| `--compilation-config` | `{"level":0}` | Disables graph compilation (Ascend) |

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
