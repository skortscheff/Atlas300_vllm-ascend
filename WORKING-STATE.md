# Working State Snapshot — 2026-09-02

This document captures the exact production configuration as of 2026-09-02.
Use it to restore the environment to a known-good state. `CLAUDE.md` is the
fuller operational reference (why the non-obvious flags exist, model
inventory, open items) — this is just the fast "how do I get back to
known-good" summary.

---

## Status

| Component | State |
|-----------|-------|
| vLLM image | ✅ `quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler` (numbered stable release) |
| Model | ✅ `Huihui-Qwen3.8-27B-abliterated` — bf16 (cast to fp16), hybrid linear+full-attention, served as `qwen3.8-27b` |
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
host model path: ${MODELS_DIR}/Huihui-Qwen3.8-27B-abliterated
container model path: /models/Huihui-Qwen3.8-27B-abliterated
served-model-name: qwen3.8-27b
```

vLLM flags in use:
```
--trust-remote-code
--tensor-parallel-size 2
--dtype float16
--enforce-eager
--max-model-len 16384
--max-num-seqs 16
--gpu-memory-utilization 0.90
--enable-prefix-caching
--enable-chunked-prefill
--max-num-batched-tokens 16384
--mamba-ssm-cache-dtype float16
--reasoning-parser qwen3
--enable-auto-tool-choice
--tool-call-parser qwen3_coder
--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'
--host 0.0.0.0
--port 8000
```

**`--enforce-eager` is mandatory, not optional** — this model's architecture (hybrid linear+full
attention, `Qwen3_5ForConditionalGeneration`) crashes ACLGraph (non-eager) mode with
`AclmdlRICaptureEnd`/error 507903 on 310P. `--gpu-memory-utilization` and `--max-num-seqs` were
both tuned experimentally and found to have no measurable effect at this context size — left at
conservative values rather than pushed further. `--override-generation-config` is required: this
model's own `generation_config.json` ships loose defaults (`temperature: 1.0`, no repetition
penalty) that produced a real accuracy failure in testing; the override fixed it to a clean
10/10 pass@1.

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
${MODELS_DIR}/Huihui-Qwen3.8-27B-abliterated
```
52GB, bf16 (`huihui-ai`'s abliterated fork of Qwen3.8-27B), cast to fp16 on load since 310P does
not support bf16 at the hardware op level. Mounted into the container as
`/models/Huihui-Qwen3.8-27B-abliterated` using an absolute host path, so moving this repository
does not affect model loading. The prior production model, the self-quantized w8a8
`Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` (38GB, ~31 tok/s single-stream), is still on disk at
`${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` as a rollback path if throughput matters
more than accuracy for a given use case (see `CLAUDE.md`'s "Models on disk" table). A 2026-09-02
disk cleanup removed several declined/superseded checkpoints and ~240GB of dead Docker images —
see `CLAUDE.md`'s "Housekeeping" section for what's left to do (one pending `sudo rm`).

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

Measured 2026-09-01 via the OpenAI-compatible API (`/v1/chat/completions`) — see `CLAUDE.md`'s
"Performance Baseline" section:

| Metric | Value |
|--------|-------|
| Single-stream throughput | 5.82 tok/s |
| Concurrent-8 throughput | 31.63 tok/s |
| Context window | 16384 tokens |
| Coding pass@1 | 10/10 |
| Tool-calling | Populated correctly (`finish_reason: tool_calls`) |

This is a deliberate accuracy-over-throughput trade — the prior w8a8 Qwen3.6 MoE model measured
31.36 tok/s single-stream at 24576 context (7/10 manual pass@1). Adopted anyway per an explicit
user decision to prioritize coding accuracy for this model; see `CLAUDE.md` for the full
tuning-pass narrative (what knobs were tried, what mattered and what didn't).

---

## What NOT to Do

- **Do not** `docker pull` and blindly retag `v0.23.0-310p-openeuler` — several `-310p-openeuler`
  tags have shipped broken in the past (triton-shadowing, bishengir/Ascend310P3 gaps). Test any new
  tag standalone on a different port first (see CLAUDE.md's "Production Setup" section).
- **Note:** `--max-model-len 16384` is a deliberate choice for headroom, not a hard ceiling for this
  model — 32768 was already proven feasible in testing (this model uses `--enforce-eager`, so it
  doesn't hit the ACLGraph compile-workspace OOM that caps other models on this hardware). Raise it
  if more context is needed; re-verify KV cache sizing in the startup logs after doing so.
- **Do not** reuse a stopped (not removed) `vllm-qwen36moe` container — its triton-rename entrypoint
  step isn't idempotent and will crash-loop; always `--force-recreate` after any stop/start cycle.
- **Do not** assume env vars alone control Open WebUI's web-search setting — it persists config in
  its SQLite DB after first boot; env vars only seed a brand-new DB (see CLAUDE.md's "Web Search
  (SearXNG)" section).

---

## When a New vLLM Image Becomes Available

310P support has regressed on several past tags (triton-shadowing bugs, missing bishengir compile
targets) — never assume a newer tag is safe. Always test a new tag standalone on a different port
(e.g. 8003), never by editing `docker-compose.yml` in place, and restore production exactly before
considering the task done. See `CLAUDE.md`'s "Production Setup" section for the required
triton-stub-removal workaround and other platform facts that any new image still needs.
