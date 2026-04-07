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
| `qwen3` | `Qwen/Qwen3-14B` | 8003 | ❌ Incompatible — garbled output on stable image (see Known Issues) |

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
- `--enforce-eager` with `--compilation-config '{"mode":0}'` (disables graph compilation for Ascend compatibility)

> **Note:** `--swap-space` was removed in the `main-310p-openeuler` image pulled 2026-04-07 — it is no longer a recognized argument.

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

## Performance Baseline

Measured 2026-04-07 on stable image (`main-310p-openeuler` @ 2026-03-19):

| Metric | Value |
|--------|-------|
| Model | Qwen2.5-Coder-14B-Instruct |
| Prompt tokens | 58 |
| Completion tokens | 512 |
| Total time | 47s |
| **Throughput** | **~10.9 tok/s** |

Single-request, eager mode, no graph compilation.

## Alternative Inference Frameworks (Evaluated 2026-04-07)

Evaluated for Ascend 310P (Atlas 300I Duo). Decision: **stay on vLLM-Ascend**.

| Framework | 310P Support | OpenAI API | Docker | Verdict |
|-----------|-------------|------------|--------|---------|
| **vLLM-Ascend** | Yes (experimental) | Yes | Pre-built | ✅ Current stack — best option |
| **llama.cpp CANN** | Yes (FP16/F32 only) | Yes | Must build | ❌ No pre-built image; FP16 GGUF ~28GB tight fit; no Ascend-specific kernels; unproven at 14B on 310P |
| **SGLang** | 910-series only | Yes | Pre-built | ❌ Not for 310P |
| **MindIE** | Unclear | Yes | Gated | ❌ Poor docs, requires Huawei account |
| **Xinference** | Via vLLM/llama.cpp only | Yes | Pre-built | ❌ Orchestration layer only, no added value |
| **Ollama** | No | — | — | ❌ No Ascend backend |

### llama.cpp CANN — detailed notes

- CANN version in vllm container: **8.5.1**
- Build base image needed: `ascendai/cann:8.5.1-310p-openeuler22.03-py3.10`
- No pre-built Docker image — must build from source (~30 min)
- Model must be converted to FP16 GGUF (~28GB for 14B); Q4/Q8 matmul falls back to CPU on 310P
- Context >8192 tokens pushes HBM limits with FP16
- Estimated throughput: 5–12 tok/s (no public 310P benchmark at 14B)
- Conclusion: more setup work for likely worse performance

## Known Issues / Image History

| Image pulled | Status | Notes |
|---|---|---|
| `main-310p-openeuler` @ 2026-03-19 (ID: `7d210d233141`) | ✅ Working | Last confirmed stable image |
| `main-310p-openeuler` @ 2026-04-07 (digest: `354db061...`) | ❌ Broken | Two regressions: (1) `--swap-space` argument removed with no warning; (2) Triton compiler crashes on first inference with `MLIRCompilationError: Cannot find option named 'Ascend310P3'` in `penalties.py` — affects all requests. Roll back to `7d210d233141` if this image is pulled. |
| `Qwen3-14B` model | ❌ Incompatible | Garbled/repeated words in output on the stable image. Final answers are correct but `<think>` stream is corrupted. Root cause: stable image (2026-03-19) predates Qwen3's architecture changes. Requires a newer vllm-ascend image that itself has Triton regressions — blocked until upstream fix. |

### Rolling back to a previous image

```bash
# Pin docker-compose.yml image to working version:
# image: quay.io/ascend/vllm-ascend@sha256:<digest>
# or reference by image ID directly:
docker tag 7d210d233141 quay.io/ascend/vllm-ascend:main-310p-openeuler-stable
# Then update docker-compose.yml to use :main-310p-openeuler-stable
```
