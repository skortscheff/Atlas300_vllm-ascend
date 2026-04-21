# Working State Snapshot — 2026-04-21

This document captures the exact working configuration as of 2026-04-21.
Use it to restore the environment to a known-good state.

---

## Status

| Component | State |
|-----------|-------|
| vLLM image | ✅ Pinned to stable (ID `7d210d233141`, built 2026-03-19) |
| Model | ✅ `Qwen2.5-Coder-14B-Instruct` — working |
| Open WebUI | ✅ `ghcr.io/open-webui/open-webui:latest` |
| Newer vLLM image (2026-04-07) | ❌ Broken — Triton MLIRCompilationError |

---

## To Start

```bash
cd ~/Dockers/vllm-atlas
docker compose up -d
```

Wait ~2 min, then confirm:
```bash
docker compose logs -f vllm-qwen25coder | grep "Application startup complete"
```

---

## To Stop

```bash
docker compose down
```

---

## Exact Image

```
quay.io/ascend/vllm-ascend:main-310p-openeuler-stable
Docker image ID: 7d210d233141  (built 2026-03-19)
```

This tag was applied locally:
```bash
docker tag 7d210d233141 quay.io/ascend/vllm-ascend:main-310p-openeuler-stable
```

**Do not `docker pull` the vLLM image** — the upstream `main-310p-openeuler` tag now points to a broken build.

---

## Active Configuration (docker-compose.yml)

```yaml
image: quay.io/ascend/vllm-ascend:main-310p-openeuler-stable
container_name: vllm-qwen25coder
port: 8002 → 8000
host model path: ${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct
container model path: /models/Qwen2.5-Coder-14B-Instruct
served-model-name: Qwen2.5-Coder-14B-Instruct
```

vLLM flags in use:
```
--dtype float16
--tensor-parallel-size 2
--host 0.0.0.0
--port 8000
--enforce-eager
--compilation-config '{"mode":0}'
--max-model-len 32768
--max-num-batched-tokens 32768
--max-num-seqs 32
--gpu-memory-utilization 0.95
--enable-prefix-caching
--enable-chunked-prefill
```

Environment:
```
ASCEND_VISIBLE_DEVICES=0,1
OMP_NUM_THREADS=8
MALLOC_ARENA_MAX=2
```

NPU devices: `/dev/davinci0`, `/dev/davinci1`

---

## Model on Disk

```
${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct
```
Mounted into container as `/models/Qwen2.5-Coder-14B-Instruct` using an absolute host path,
so moving this repository does not affect model loading.

---

## Endpoints

| Service | URL |
|---------|-----|
| Open WebUI | `http://localhost:3000` |
| vLLM API (local) | `http://localhost:8002/v1` |
| vLLM API (LAN) | `http://<HOST_IP>:8002/v1` |
| OpenAI-compatible | No API key required |

---

## Performance Baseline

Measured 2026-04-21 via the OpenAI-compatible API (`/v1/chat/completions`), eager mode, no graph compilation:

| Metric | Value |
|--------|-------|
| Prompt tokens | 47 |
| Completion tokens | 311 |
| Total tokens | 358 |
| Total time | 28.394 s |
| Throughput | 10.95 tok/s |

API verification on the same date:

| Check | Result |
|------|--------|
| `GET /v1/models` | ✅ Returned `Qwen2.5-Coder-14B-Instruct` |
| `POST /v1/chat/completions` | ✅ Returned valid completion |

---

## What NOT to Do

- **Do not** `docker pull quay.io/ascend/vllm-ascend:main-310p-openeuler` — current upstream is broken
- **Do not** add `--swap-space` — removed from newer images, causes startup failure
- **Do not** use `--compilation-config '{"level":0}'` — deprecated; use `{"mode":0}`

---

## When a New vLLM Image Becomes Available

Check for a versioned rc/stable tag at `quay.io/ascend/vllm-ascend` before upgrading.
Test on a separate container before changing the pinned tag in `docker-compose.yml`.
