# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker Compose deployment for LLM inference on Ascend NPU hardware. Two services:
- **vLLM** (`quay.io/ascend/vllm-ascend:main-310p-openeuler`) — serves the model on port 8002
- **Open WebUI** (`ghcr.io/open-webui/open-webui:latest`) — chat UI on port 3000

## Models

One model is active:

| Model | Port | Status |
|-------|------|--------|
| `Qwen/Qwen2.5-Coder-14B-Instruct` | 8002 | ✅ Active |

### Starting

```bash
docker compose up -d
```

### Open WebUI custom model entries

| UI name | DB id | Notes |
|---------|-------|-------|
| `Qwen/Qwen2.5-Coder-14B-Instruct` | `Qwen/Qwen2.5-Coder-14B-Instruct` | Default — no custom params |

## Common Commands

```bash
# Start
docker compose up -d

# Stop everything
docker compose down

# View logs
docker compose logs -f vllm-qwen25coder
docker compose logs -f openwebui

# Check NPU status
npu-smi info
npu-smi info -l

# iBMC (out-of-band management) — ipmitool is installed on this host
sudo ipmitool lan print 1          # get iBMC web UI IP
sudo ipmitool sel list | tail -20  # hardware event log
```

## Architecture

```
User → Open WebUI (port 3000) → vLLM API (http://vllm-qwen25coder:8000/v1) → Ascend NPU
```

**Network:** Both services share the `llmnet` bridge network.

**Model:** `Qwen/Qwen2.5-Coder-14B-Instruct` — stored at the absolute host path `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct`, mounted into the container as `/models/Qwen2.5-Coder-14B-Instruct`

**Hardware (as of 2026-07-08):** 1× Atlas 300I Duo card installed (`/dev/davinci0`, `/dev/davinci1` — 2 chips on the one card, bus `0000:86:00.0`, both `OK` per `npu-smi`). The second, defective card (`0000:3b:00.0`) has been **physically removed** from the host — it had a confirmed hardware defect (firmware never boots, `flag_r=0x0`, `ret=-19/ENODEV`) that was never resolved via RMA. `--tensor-parallel-size 2` still applies since the remaining card itself has 2 chips. See `huawei-support-case.md` and `recover-card.sh` for the historical defect investigation (kept for reference, no longer actionable).

**IOMMU investigation (2026-05-08, historical, ruled out before the card was removed):** IOMMU was not the cause of the second card's failure. Kernel cmdline has `intel_iommu=on iommu=pt` (passthrough mode). Both IOMMU groups for the NPU cards were type `identity` (no address translation). No IOMMU faults in dmesg. The probe failure (`flag_r=0x0`) occurred at MMIO register read level — before any DMA was attempted.

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

| Endpoint | URL |
|---------|-----|
| LAN | `http://<HOST_IP>:8002/v1` |

No API key required. See `guia-api.md` for a full usage guide (Spanish) with curl, Python, and JavaScript examples.

## Deployment Notes

- NPU devices on this host are `/dev/davinci0` and `/dev/davinci1`
- Before starting, ensure no other containers are using ports 8002 or 3000
- vLLM takes ~2 minutes to load the model; watch for `Application startup complete.` in logs before sending requests

## Performance Baseline

Measured 2026-04-21 on stable image (`main-310p-openeuler-stable`) via the OpenAI-compatible API:

| Metric | Value |
|--------|-------|
| Model | Qwen2.5-Coder-14B-Instruct |
| Prompt tokens | 47 |
| Completion tokens | 311 |
| Total time | 28.394s |
| **Throughput** | **10.95 tok/s** |

Single-request, eager mode, no graph compilation.

## Known Issues / Image History

| Image pulled | Status | Notes |
|---|---|---|
| `main-310p-openeuler` @ 2026-03-19 (ID: `7d210d233141`) | ✅ Working | **Current stable image, re-confirmed 2026-07-08** — last known good build |
| `v0.19.1rc1-310p-openeuler` @ 2026-05-06 (digest: `ec220606...`) | ❌ Broken | Starts and imports correctly (triton.language present), but fails on first inference: `bishengir-compile: Cannot find option named 'Ascend310P3'` — triton-ascend 3.2.0 uses `Ascend310P3` as compile target, which CANN 8.5.1's bishengir-compile does not support. |
| Custom build: vllm-ascend v0.19.1rc1 + CANN 9.0.0 base @ 2026-05-07 (local tag `v0.19.1rc1-310p-openeuler-cann9`) | ❌ Broken | Built from source with `quay.io/ascend/cann:9.0.0-310p-openeuler24.03-py3.11`, local triton-ascend/torch_npu wheels, npu_utils.cpp patch. Starts fine, but **same bishengir error on first inference** — CANN 9.0.0 on quay.io also lacks `Ascend310P3` in bishengir-compile targets. The "310p" image label refers to the runtime hardware, not compiler support. No public CANN image has 310P triton JIT support. |
| `main-310p-openeuler` @ 2026-04-07 (digest: `354db061...`) | ❌ Broken | Two regressions: (1) `--swap-space` argument removed with no warning; (2) Triton compiler crashes on first inference with `MLIRCompilationError: Cannot find option named 'Ascend310P3'` in `penalties.py` — affects all requests. Roll back to `7d210d233141` if this image is pulled. |
| `v0.18.0-310p-openeuler` @ 2026-05-05 (digest: `300c60f2...`) | ❌ Broken | Triton/torch_npu incompatibility at import time: vanilla PyTorch triton shadows triton-ascend inside the image → `AttributeError: module 'triton' has no attribute 'language'` → torch_npu fails to load, vllm never starts. The v0.18.0 release notes acknowledge that `triton-ascend==3.2.0.dev20260322` requires manual installation and is not bundled correctly in the prebuilt image. |
| `v0.20.2rc1` / `v0.21.0rc1` / `v0.22.1rc1` (all `-310p-openeuler`, released 2026-06-03 to 2026-06-30) | ❌ Not viable (checked 2026-07-08, not pulled) | Checked upstream release notes for all three — none mention fixing `bishengir`/`Ascend310P3`. Confirmed via vllm-ascend maintainers (GitHub issues #7421, #7991) that **triton-ascend does not support 310P at all**; this is a permanent platform gap, not a bug being patched release-to-release. The actual fix (PR #8181, bypass triton entirely for 310P) is still unmerged as of 2026-04-13. **Do not spend time re-testing newer `-310p-openeuler` tags for this reason alone** — check whether #8181 has merged first. |

**Model compatibility note (2026-07-08):** vllm-ascend docs describe a separate 310P path for **Qwen3 dense models via W8A8SC quantization + ACLGraph**, which avoids triton entirely (different from the fp16/eager path used here). Untested — would require re-quantizing weights, not just swapping the image. Qwen2.5-Coder-32B-Instruct is believed **architecturally safe** to try next (same dense Llama/Qwen2-style blocks as the working 14B) but would need reduced `--max-model-len` (~8K–16K) to fit ~64GB of fp16 weights in the ~88GB total HBM. MoE models (DeepSeek-Coder-V2-Lite, Qwen3-Coder) and Qwen3 in general are considered risky — 310P MoE support is explicitly incomplete upstream (RFC #9044), and Qwen3's QK-norm caused garbled `<think>` output in our 2026-04-07 test.

## llama.cpp CANN Backend Investigation (2026-05-07)

Attempted to use llama.cpp as an alternative inference engine to bypass the vllm/triton/bishengir limitation.

**Build:** [~/build/llama-cpp-cann/Dockerfile](../../../build/llama-cpp-cann/Dockerfile)
- Base: `ascendai/cann:8.5.1-310p-ubuntu22.04-py3.11`
- llama.cpp pinned to commit `632219af` (2026-03-31) — master requires `aclnn_recurrent_gated_delta_rule.h` absent in CANN 8.5.1
- SOC type: `-DSOC_TYPE=Ascend310P3`

**Model:** `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct-f16.gguf` (28GB, converted from safetensors)

**Results:**

| Stage | Result |
|---|---|
| CANN init | ✅ Both chips detected: `CANN0 = 13,126 MiB`, `CANN1 = 13,561 MiB` |
| Layer offload | ✅ 49/49 layers offloaded across both NPU chips via `--split-mode layer` |
| KV cache | ✅ `CANN0: 3200 MiB`, `CANN1: 2944 MiB` |
| Warmup inference | ❌ `BinaryGetFunction failed, kernel_name=` — a required ACLNN kernel binary does not exist for Ascend310P3 in CANN 8.5.1 |

**Root cause:** llama.cpp's CANN backend calls an ACLNN op during warmup that has no compiled binary for the 310P chip in CANN 8.5.1. Same class of problem as the triton/bishengir issue: 310P kernel support in available CANN versions is incomplete. The `graph splits = 99` across two devices during scheduling suggests the split-layer mode may also be hitting unimplemented inter-device ops.

**What worked on the way:** CANN 8.5.1 driver API is compatible (unlike 8.2.rc2 which gave `drvRet=87`). Layer offload to both chips is successful. The blocker is a missing kernel binary at the ACLNN level, not a driver or build issue.

**Next steps if revisiting:**
- Try with `--no-warmup` flag to see if only warmup triggers the bad op (first real request might work)
- Try a single-device config (`--split-mode none --main-gpu 0`) to eliminate inter-device ops
- Watch for llama.cpp CANN PRs adding 310P kernel support, or try with CANN 8.5.2/9.0.0 (`ascendai/cann:8.5.2-310p-ubuntu22.04-py3.11` is available)

### Rolling back to a previous image

```bash
# Pin docker-compose.yml image to working version:
# image: quay.io/ascend/vllm-ascend@sha256:<digest>
# or reference by image ID directly:
docker tag 7d210d233141 quay.io/ascend/vllm-ascend:main-310p-openeuler-stable
# Then update docker-compose.yml to use :main-310p-openeuler-stable
```
