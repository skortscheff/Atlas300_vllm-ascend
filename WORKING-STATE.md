# Working State Snapshot — 2026-09-01

This document captures the exact production configuration as of 2026-09-01.
Use it to restore the environment to a known-good state. Full narrative and
every experiment that led here is in `CLAUDE.md` — this is just the fast
"how do I get back to known-good" reference.

---

## Status

| Component | State |
|-----------|-------|
| vLLM image | ✅ `quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler` (numbered stable release) |
| Model | ✅ `Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` — self-quantized w8a8 MoE, served as `qwen3.6-moe` |
| Open WebUI | ✅ `ghcr.io/open-webui/open-webui:latest` |
| SearXNG (web search) | ✅ `docker.io/searxng/searxng:latest`, enabled by default |
| Dense fallback (`prod` profile) | ✅ Still available — `Qwen2.5-Coder-14B-Instruct-abliterated` on `main-310p-openeuler-stable` |

---

## To Start

```bash
docker compose --profile qwen36 up -d
```

Wait ~2 min, then confirm:
```bash
docker compose logs -f vllm-qwen36moe | grep "Application startup complete"
```

**Use `--force-recreate` if the container was previously stopped (not removed)** — its entrypoint does a one-time, non-idempotent `mv .../triton .../triton.disabled` that fails on a reused filesystem layer:
```bash
docker compose --profile qwen36 up -d --force-recreate
```

---

## To Stop

```bash
docker compose --profile qwen36 down
```

---

## Exact Image

```
quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler
```

vLLM's own triton JIT compiler does not support 310P at all (upstream PR #8181, unmerged) —
the container's entrypoint works around this by renaming the bundled (broken) `triton` package
before `vllm serve` starts:
```
mv /usr/local/python3.12.13/lib/python3.12/site-packages/triton \
   /usr/local/python3.12.13/lib/python3.12/site-packages/triton.disabled
```
This is baked into `docker-compose.yml`'s `vllm-qwen36moe` entrypoint — no manual step needed.

---

## Active Configuration (docker-compose.yml, `qwen36` profile)

```yaml
image: quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler
container_name: vllm-qwen36moe
port: 8002 → 8000
host model path: ${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8
container model path: /models/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8
served-model-name: qwen3.6-moe
```

vLLM flags in use:
```
--trust-remote-code
--tensor-parallel-size 2
--dtype float16
--quantization ascend
--max-model-len 24576
--max-num-seqs 16
--gpu-memory-utilization 0.90
--additional-config '{"ascend_compilation_config": {"fuse_norm_quant": false}}'
--compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY", "cudagraph_capture_sizes": [1,4]}'
--mamba-ssm-cache-dtype float16
--reasoning-parser qwen3
--enable-auto-tool-choice
--tool-call-parser qwen3_coder
--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'
--host 0.0.0.0
--port 8000
```

Environment:
```
ASCEND_VISIBLE_DEVICES=0,1
OMP_NUM_THREADS=8
MALLOC_ARENA_MAX=2
```

NPU devices: `/dev/davinci0`, `/dev/davinci1` (single Atlas 300I Duo card — the second card had
a confirmed hardware defect and was physically removed; see CLAUDE.md's "Architecture" section).

---

## Model on Disk

```
${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8
```
38GB, self-quantized (w8a8, `msmodelslim`) from the bf16 `Huihui-Qwen3.6-35B-A3B-abliterated`
original — same abliterated weights, just quantized. Mounted into the container as
`/models/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` using an absolute host path, so moving this
repository does not affect model loading. The bf16 original is still on disk at
`${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated` as a rollback path.

---

## Endpoints

| Service | URL |
|---------|-----|
| Open WebUI | `http://localhost:3000` |
| vLLM API (local) | `http://localhost:8002/v1` |
| vLLM API (LAN) | `http://<HOST_IP>:8002/v1` |
| SearXNG | `http://localhost:8080` |
| OpenAI-compatible | No API key required |

---

## Performance Baseline

Measured 2026-08-19 via the OpenAI-compatible API (`/v1/chat/completions`), full comparison
against the prior bf16 checkpoint in `CLAUDE.md`'s "w8a8 production switch" section:

| Metric | Value |
|--------|-------|
| Single-stream throughput | 31.36 tok/s |
| Concurrent-8 throughput | 39.85 tok/s |
| Context window | 24576 tokens |
| Manual pass@1 (realistic token budget) | 7/10 |
| Tool-calling | Populated correctly (`finish_reason: tool_calls`) |

Re-verified with no drift on 2026-09-01 (`bench/run_bench.py`): 31.29 tok/s single-stream,
tool-calling still populated correctly.

---

## What NOT to Do

- **Do not** `docker pull` and blindly retag `v0.23.0-310p-openeuler` — verify against `CLAUDE.md`'s
  Known Issues table first; several `-310p-openeuler` tags have shipped broken (triton-shadowing,
  bishengir/Ascend310P3 gaps).
- **Do not** push `--max-model-len` past 24576 for this model — 310P's attention-mask-compression
  limit and ACLGraph compile-workspace memory both cap out here (confirmed via OOM testing, see
  CLAUDE.md).
- **Do not** reuse a stopped (not removed) `vllm-qwen36moe` container — its triton-rename entrypoint
  step isn't idempotent and will crash-loop; always `--force-recreate` after any stop/start cycle.
- **Do not** assume env vars alone control Open WebUI's web-search setting — it persists config in
  its SQLite DB after first boot; env vars only seed a brand-new DB (see CLAUDE.md's "Web Search
  (SearXNG)" section).

---

## When a New vLLM Image Becomes Available

Check `CLAUDE.md`'s "Known Issues / Image History" table and the latest "Upstream vllm-ascend
check" section before upgrading — 310P support has regressed on several past tags. Always test a
new tag standalone on a different port (e.g. 8003), never by editing `docker-compose.yml` in
place, and restore production exactly before considering the task done.
