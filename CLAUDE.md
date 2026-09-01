# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker Compose deployment for LLM inference on Ascend NPU hardware. Three services:
- **vLLM** (`quay.io/ascend/vllm-ascend:main-310p-openeuler`) — serves the model on port 8002
- **Open WebUI** (`ghcr.io/open-webui/open-webui:latest`) — chat UI on port 3000
- **SearXNG** (`docker.io/searxng/searxng:latest`) — self-hosted meta-search engine on port 8080, gives Open WebUI web search (added 2026-08-17, see "Web Search (SearXNG)" section below)

## ⚠️ Production Setup — always revertible to this state

**Updated 2026-08-19: production switched to the self-quantized w8a8 checkpoint** of the same abliterated model, after a full benchmark comparison (see "w8a8 production switch" section below) showed it strictly better than the bf16 original — faster, more context, higher pass@1, more reliable tool-calling — with identical abliterated/uncensored behavior (same weights, just quantized). This is the canonical known-good state to always return to. Any experimental image/model test (new vllm-ascend tags, alternative inference engines, other models) must be done **standalone on a different port** (e.g. 8003), never by editing `docker-compose.yml` in place, and production must be restored to exactly this state afterward — every experiment log in this file follows that method (stop production → test on 8003 → stop test container → bring production back up again).

| Component | Pinned value |
|---|---|
| vLLM image | `quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler`, with the triton-stub-removal workaround baked into the Compose entrypoint (`mv .../site-packages/triton .../site-packages/triton.disabled` before `vllm serve`) |
| Model | `Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` (self-quantized w8a8, MoE) at `${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` (38GB — built this session with `msmodelslim` from the bf16 original, see "Self-quantized abliterated w8a8" section below), served as `qwen3.6-moe` |
| vLLM command | exactly as in the current `docker-compose.yml` `vllm-qwen36moe` service — `--dtype float16 --quantization ascend --tensor-parallel-size 2 --max-model-len 24576 --max-num-seqs 16 --gpu-memory-utilization 0.90`, `--reasoning-parser qwen3`, `--enable-auto-tool-choice --tool-call-parser qwen3_coder`, `--mamba-ssm-cache-dtype float16`, ACLGraph compilation config (`FULL_DECODE_ONLY`, capture sizes `[1,4]`), `--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'` (reasoning-stability fix, baked in server-side) |
| Ports | vLLM 8002, Open WebUI 3000 |
| Driver/firmware | 25.3.rc1 / 7.8.0.2.212 (see Deployment Notes) |
| Context | 24576 (+50% vs. the prior bf16 pin's 16384 — quantization freed enough NPU memory to raise the ceiling; see "w8a8 production switch" section below) |

**The previous pin, `Huihui-Qwen3.6-35B-A3B-abliterated` bf16 at 16384 context, is superseded but the weights are still on disk** at `${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated` if a rollback is ever needed — see "w8a8 production switch" below for the exact prior command. **The dense-14B baseline, `Qwen2.5-Coder-14B-Instruct-abliterated` on `main-310p-openeuler-stable`, is still available as the `prod` profile** — dense, fp16, 32768 context, ~9.53 tok/s, tool-calling not populated (known issue). Use it if the MoE model's context or reasoning-verbosity trade-offs become a problem for a given task.

**To revert to this state from any experiment:**
```bash
docker compose --profile prod down     # or: docker stop <any-test-container> && docker rm <any-test-container>
docker compose --profile qwen36 up -d --force-recreate  # brings back vllm-qwen36moe + openwebui exactly as pinned above
# verify:
docker inspect vllm-qwen36moe --format '{{.Config.Image}}'   # must print v0.23.0-310p-openeuler
docker exec vllm-qwen36moe python3 -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://localhost:8000/v1/models')); print(d['data'][0]['id'], d['data'][0]['max_model_len'])"  # must show qwen3.6-moe 24576
```
**Use `--force-recreate` when bringing `vllm-qwen36moe` back up** — its entrypoint does a one-time `mv .../triton .../triton.disabled` that isn't idempotent; reusing a stopped container's filesystem layer (rather than a fresh one) makes that `mv` fail and the container crash-loop. `--force-recreate` (or fully removing the container first) avoids this.

**Note (2026-07-22):** `docker-compose.yml` uses **Compose profiles** (`prod` vs `qwen36`) to let the two vLLM services share port 8002 and NPU devices without both trying to run at once — see "Switching Models" below. Plain `docker compose up -d` with no `--profile` flag starts **only** `openwebui`; a vLLM profile must always be specified explicitly.

## 📍 Resume Here — Next Session (as of 2026-09-01)

**Where things stand:** production is up and verified — `qwen36` profile, self-quantized w8a8 `Huihui-Qwen3.6-35B-A3B-abliterated-w8a8`, port 8002, `max_model_len: 24576`, image `v0.23.0-310p-openeuler` — exactly matching the pinned "Production Setup" table above. Routine health check + benchmark run this session (2026-09-01, see "Routine check" section below) confirms no drift: 31.29 tok/s single-stream, tool-calling populated correctly, harness pass@1 0/10 is the known 512-token-budget artifact (not a regression — see "w8a8 production switch" section for the real, higher-budget pass@1 numbers).

**Upstream research this session (2026-09-01):** checked `vllm-project/vllm-ascend` on GitHub for anything new since the 2026-08-17 pass — see "Upstream vllm-ascend check" section below. Nothing requires a change. Two things worth knowing: (1) the IndexPut/507018 crash that used to hard-block `Eco-Tech/Qwen3.6-35B-A3B-w8a8` now has a **confirmed root cause** (issue #13050, closed — it was an NPU driver-version problem, fixed by the 25.x+ driver this host already runs, combined with the v0.23.0 release), upgrading the earlier "no longer reproduces, cause unknown" note to "confirmed why it doesn't reproduce here"; (2) a related-but-distinct issue (#11188, a "halMemMap" memory-mapping error, same 310P+Qwen3.6+w8a8+GDN territory) is still open upstream with no fix — doesn't affect this environment today, but worth remembering if anything odd shows up on the w8a8 model under real usage.

**Security note (2026-09-01): `.git/config`'s `origin` remote URL contains a plaintext GitHub personal access token.** Not yet rotated or removed — flagged to the user, action still pending.

**Concrete next steps, roughly in priority order:**
1. Decide whether to also repin `vllm-qwen25coder` (the `prod` fallback profile, still on `main-310p-openeuler-stable`) — `nightly-releases-v0.25.1rc-310p-openeuler` remains a real, zero-downside speed win for that dense model (+12.7% single-stream, +10.3% concurrent-8, confirmed 2026-08-04, rebuilt as recently as 2026-08-25) but was never adopted; still an open item.
2. Decide whether to delete `${MODELS_DIR}/Qwen3.6-35B-A3B-w8a8` (38GB, the *official* non-abliterated w8a8 checkpoint, declined 2026-08-17 in favor of staying abliterated) — now likely superseded by the self-quantized abliterated w8a8 checkpoint that IS in production; probably safe to delete, not yet done.
3. Do a real soak test of both the w8a8 production model and the SearXNG web search integration under actual sustained usage — only single-session smoke tests have been run for either so far.
4. Rotate the exposed GitHub token in `.git/config` (see Security note above).
5. Watch for a `-310p` build of the `v0.26.0rc` nightly line (doesn't exist yet as of 2026-09-01) — one low-confidence rumor claims it adds W8A8SC quantization for 310P, unconfirmed.

Full narrative and exact commands for every test are in the dedicated sections below (search for "TESTED" or the date in the section heading).

## Models

Two models are available as mutually-exclusive Compose **profiles** — only one may run at a time (both need the full 2-chip NPU and port 8002):

| Profile | Service | Model | Status |
|---|---|---|---|
| `qwen36` | `vllm-qwen36moe` | `huihui-ai/Huihui-Qwen3.6-35B-A3B-abliterated` (served as `qwen3.6-moe`) | ✅ **Default production as of 2026-08-12** — ~4.6x faster (28.6 tok/s vs 9.53), reasoning kept on and stabilized via `--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'` (see dedicated section below); context 16384 (half of the dense model's 32768) |
| `prod` | `vllm-qwen25coder` | `huihui-ai/Qwen2.5-Coder-14B-Instruct-abliterated` (served as `Qwen2.5-Coder-14B-Instruct-abliterated`) | ⚠️ Former default (until 2026-08-12), kept as the alternative — dense, fp16, full 32768 context, no tool-calling |

### Switching Models

Open WebUI always stays up; only the vLLM service changes via `--profile`. Both services publish themselves under the same network alias (`vllm-backend`), so Open WebUI's `OPENAI_API_BASE_URLS` never needs to change.

```bash
# Switch to the dense Qwen2.5-Coder-14B alternative:
docker compose --profile qwen36 down
docker compose --profile prod up -d

# Switch back to production (Qwen3.6 MoE):
docker compose --profile prod down
docker compose --profile qwen36 up -d --force-recreate

# Verify which is active:
docker exec vllm-qwen36moe python3 -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/v1/models'))['data'][0]['id'])"
# or, if vllm-qwen25coder is active:
docker exec vllm-qwen25coder python3 -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/v1/models'))['data'][0]['id'])"
```

### Disk cleanup (2026-07-22)

`${MODELS_DIR}/` was pruned down to just the two models actually used by the two Compose profiles above. Deleted (~169GB total, none recoverable without re-downloading/re-converting): `gemma-4-12B` (23G, ruled out pre-hardware — see Gemma section below), `Huihui-Qwen3.6-27B-abliterated` (52G, dense sibling abandoned for being slower than production), `Qwen2.5-Coder-14B-Instruct` non-abliterated original (28G, old rollback copy), `Qwen2.5-Coder-14B-Instruct-f16.gguf` (28G, built for the abandoned llama.cpp CANN investigation), `Qwen3.5-35B-A3B-w8a8-mtp` (38G, tested and working — best raw benchmark numbers of anything tried — but not adopted as a profile in favor of the Qwen3.6 MoE model). If any of these are revisited, they must be re-downloaded/re-built from scratch; see each model's dedicated section above for the original source and method.

### Starting (default/production)

```bash
docker compose --profile qwen36 up -d
```

### Open WebUI custom model entries

None (2026-07-09) — the two legacy custom entries (`Qwen/Qwen2.5-Coder-14B-Instruct`, `Qwen2.5-Coder-14B-Instruct`) were deleted from `model` table in `webui.db` since they pinned to model IDs that no longer match what vLLM serves. Open WebUI now auto-discovers the model straight from vLLM's `/v1/models` under its real name, `Qwen2.5-Coder-14B-Instruct-abliterated` — no custom DB override needed. If you rename `--served-model-name` again, either add a fresh custom entry or just let auto-discovery pick up the new ID.

## Common Commands

```bash
# Start production (Qwen3.6 MoE) — also brings up openwebui and searxng (no profile gating, always included)
docker compose --profile qwen36 up -d

# Start the dense Qwen2.5-Coder-14B alternative instead
docker compose --profile prod up -d

# Stop everything (add --profile prod or --profile qwen36 to target just the active vLLM service)
docker compose --profile prod --profile qwen36 down

# View logs
docker compose logs -f vllm-qwen25coder    # or vllm-qwen36moe, depending on active profile
docker compose logs -f openwebui
docker compose logs -f searxng

# Check NPU status
npu-smi info
npu-smi info -l

# iBMC (out-of-band management) — ipmitool is installed on this host
sudo ipmitool lan print 1          # get iBMC web UI IP
sudo ipmitool sel list | tail -20  # hardware event log
```

## Architecture

```
User → Open WebUI (port 3000) → vLLM API (http://vllm-backend:8000/v1) → Ascend NPU
                                ↘ SearXNG (port 8080) → internet, for web search
```

**Network:** All three services (`vllm-*`, `openwebui`, `searxng`) share the `llmnet` bridge network.

**Model:** `huihui-ai/Qwen2.5-Coder-14B-Instruct-abliterated` (2026-07-09, replaced the original `Qwen/Qwen2.5-Coder-14B-Instruct` — same architecture, `config.json` confirms identical `Qwen2ForCausalLM`, 48 layers, hidden_size 5120; only difference is refusal-removed weights) — stored at the absolute host path `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct-abliterated`, mounted into the container as `/models/Qwen2.5-Coder-14B-Instruct-abliterated`. Served under `--served-model-name Qwen2.5-Coder-14B-Instruct-abliterated` (renamed 2026-07-09 from the old placeholder name so Open WebUI shows the real model) — see the Open WebUI custom model entries note above. **The original non-abliterated weights were deleted 2026-07-22** (disk cleanup, see "Disk cleanup" note in the Models section) — a rollback to the non-abliterated model would now require re-downloading it.

**Hardware (as of 2026-07-08):** 1× Atlas 300I Duo card installed (`/dev/davinci0`, `/dev/davinci1` — 2 chips on the one card, bus `0000:86:00.0`, both `OK` per `npu-smi`). The second, defective card (`0000:3b:00.0`) has been **physically removed** from the host — it had a confirmed hardware defect (firmware never boots, `flag_r=0x0`, `ret=-19/ENODEV`) that was never resolved via RMA. `--tensor-parallel-size 2` still applies since the remaining card itself has 2 chips. The historical defect investigation (Huawei support case writeup and a card-recovery script) has been removed from this repo — it contained personal contact details and hardware serial numbers and is no longer actionable since the card was physically removed; no revisit path exists.

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

## Web Search (SearXNG)

**Added 2026-08-17, enabled by default.** Open WebUI's web search feature is backed by a self-hosted SearXNG instance (`docker.io/searxng/searxng:latest`, container `searxng`, port 8080, on the `llmnet` network). No external API key, no third-party search API dependency — SearXNG itself fans out to public search engines.

**Config files:**
- `searxng/settings.yml` — mounted read-write into the container at `/etc/searxng`. Key settings: `search.formats` includes `json` (required — Open WebUI's backend calls SearXNG's JSON API, not the HTML UI), `server.limiter: false` (the rate-limiter plugin blocks non-browser/JSON requests by default; safe to disable since this instance is internal-only, not exposed to the public internet), `server.secret_key` (a generated hex string, low-sensitivity — used only for SearXNG's own session/CSRF signing, not an access credential to anything).
- `openwebui` service env vars in `docker-compose.yml`: `ENABLE_RAG_WEB_SEARCH=true`, `WEB_SEARCH_ENGINE=searxng`, `SEARXNG_QUERY_URL=http://searxng:8080/search?q=<query>`.

**Important gotcha, already hit once — Open WebUI persists config in its database, not just env vars.** Once `openwebui-data/webui.db` exists, Open WebUI reads settings (including web search) from the DB's `config` table on every boot; env vars are only used to **seed a brand-new/empty DB**, they do **not** override an already-persisted value. Since this repo's `openwebui-data/` volume predates the SearXNG work, adding the env vars alone was not enough — the DB's `config` table still had `web.search.enable = 'false'` from months ago, and the model reported having no web search tool available until this was found and fixed directly:

```bash
docker exec openwebui python3 -c "
import sqlite3, time
conn = sqlite3.connect('/app/backend/data/webui.db')
cur = conn.cursor()
now = int(time.time())
updates = {
    'web.search.enable': 'true',
    'web.search.engine': '\"searxng\"',
    'web.search.searxng_query_url': '\"http://searxng:8080/search?q=<query>\"',
    'web.search.result_count': '3',
    'web.search.concurrent_requests': '4',
}
for k, v in updates.items():
    cur.execute('UPDATE config SET value = ?, updated_at = ? WHERE key = ?', (v, now, k))
conn.commit()
"
docker restart openwebui
```

**This means the env vars in `docker-compose.yml` alone only guarantee web search is on-by-default for a fresh deployment** (new `openwebui-data/` volume, e.g. a rebuild from scratch) — they will **not** silently re-enable it if someone ever disables it via the Admin Settings UI and it gets persisted back to `false`. If web search stops working after any future Open WebUI config change, check the DB directly first (`SELECT key, value FROM config WHERE key LIKE 'web.search%'`) before assuming the service itself is broken.

**Verifying it's working:**
```bash
# SearXNG itself returns results:
curl -s "http://localhost:8080/search?q=test&format=json" | head -c 300
# Open WebUI can reach it over the internal network:
docker exec openwebui curl -s "http://searxng:8080/search?q=test&format=json" | head -c 300
# Persisted config is correct:
docker exec openwebui python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
cur = conn.cursor()
cur.execute(\"SELECT key, value FROM config WHERE key IN ('web.search.enable','web.search.engine','web.search.searxng_query_url')\")
for r in cur.fetchall(): print(r)
"
```
In the Open WebUI chat UI, a web-search toggle (globe icon) appears in the message input box once this is correctly enabled — a hard browser refresh may be needed to see it after a backend config change.

**Known limitation:** `wikidata` (one of SearXNG's many built-in engines) fails to initialize with an HTTP 403 in the container logs on every boot — this is expected/cosmetic, other engines (Wikipedia, Bing, DuckDuckGo, etc.) still work fine and this does not affect search result quality.

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

**Current baseline — measured 2026-07-15** (post driver/firmware upgrade to 25.3.rc1/7.8.0.2.212, see Deployment Notes) via `bench/run_bench.py` against the live API (`http://localhost:8002/v1`), model `Qwen2.5-Coder-14B-Instruct-abliterated`, config = `--enable-prefix-caching --enable-chunked-prefill --enable-auto-tool-choice --tool-call-parser hermes` (see `docker-compose.yml`):

| Metric | Value | vs. 2026-07-09 baseline (driver 25.2.0) |
|--------|-------|---|
| Single-stream throughput | **9.53 tok/s** (min 9.51, max 9.55) | 9.61 tok/s — unchanged within noise |
| Concurrent-8 throughput | **61.31 tok/s** | 43.81 tok/s — **+40%**, though the old number was flagged as possibly contending with a stuck/retrying request, so treat this as an improvement, not a guaranteed permanent driver-level gain |
| Coding pass@1 | 10/10 (1.0) | unchanged |
| Tool-calls populated | ❌ **No** — see Known Issues below | unchanged |

Single-stream speed is memory-bandwidth bound, not compute bound (14B fp16 params ÷ 2 chips = ~14GB read per token from LPDDR4X at ~100GB/s ≈ the observed ~10 tok/s) — this is architecturally close to the ceiling for this model/hardware pairing in eager mode. `--enforce-eager` cannot be lifted (triton/bishengir gap, see Known Issues), so the only realistic levers to raise single-stream speed are **W8A8 quantization** (~2x, halves bytes read per token) or **speculative decoding** with a small draft model (~1.3–2x, batches verification) — both unverified on 310P, not yet attempted.

Full run history: `bench/results.md`. Re-run after any config change: `python3 bench/run_bench.py --label "<what changed>"`.

**Known issue — tool-calling not actually working (2026-07-09):** `--enable-auto-tool-choice --tool-call-parser hermes` is set in `docker-compose.yml` and the container is running with these flags live, but `bench/run_bench.py`'s tool-calling check shows `tool_calls` is **not populated** — the model emits raw `<tools>{"name": "get_weather", "arguments": {...}}</tools>` text in the message content instead of the hermes parser extracting it into the structured `tool_calls` array. Likely cause: the model's chat template doesn't wrap tool-call output in the exact tags/format the hermes parser expects (hermes parser looks for `<tool_call>...</tool_call>`, not `<tools>...</tools>`), or the served chat template isn't injecting tool defs the way hermes expects. Not yet root-caused — needs the actual chat template used at request time to be inspected, and possibly a different `--tool-call-parser` (e.g. try the model's own template output format first, or check if this base model even trained on hermes-style tool tokens vs. plain function-calling text).

## Known Issues / Image History

| Image pulled | Status | Notes |
|---|---|---|
| `main-310p-openeuler` @ 2026-03-19 (ID: `7d210d233141`) | ✅ Working | **Current stable image, re-confirmed 2026-07-08** — last known good build |
| `v0.19.1rc1-310p-openeuler` @ 2026-05-06 (digest: `ec220606...`) | ❌ Broken | Starts and imports correctly (triton.language present), but fails on first inference: `bishengir-compile: Cannot find option named 'Ascend310P3'` — triton-ascend 3.2.0 uses `Ascend310P3` as compile target, which CANN 8.5.1's bishengir-compile does not support. |
| Custom build: vllm-ascend v0.19.1rc1 + CANN 9.0.0 base @ 2026-05-07 (local tag `v0.19.1rc1-310p-openeuler-cann9`) | ❌ Broken | Built from source with `quay.io/ascend/cann:9.0.0-310p-openeuler24.03-py3.11`, local triton-ascend/torch_npu wheels, npu_utils.cpp patch. Starts fine, but **same bishengir error on first inference** — CANN 9.0.0 on quay.io also lacks `Ascend310P3` in bishengir-compile targets. The "310p" image label refers to the runtime hardware, not compiler support. No public CANN image has 310P triton JIT support. |
| `main-310p-openeuler` @ 2026-04-07 (digest: `354db061...`) | ❌ Broken | Two regressions: (1) `--swap-space` argument removed with no warning; (2) Triton compiler crashes on first inference with `MLIRCompilationError: Cannot find option named 'Ascend310P3'` in `penalties.py` — affects all requests. Roll back to `7d210d233141` if this image is pulled. |
| `v0.18.0-310p-openeuler` @ 2026-05-05 (digest: `300c60f2...`) | ❌ Broken | Triton/torch_npu incompatibility at import time: vanilla PyTorch triton shadows triton-ascend inside the image → `AttributeError: module 'triton' has no attribute 'language'` → torch_npu fails to load, vllm never starts. The v0.18.0 release notes acknowledge that `triton-ascend==3.2.0.dev20260322` requires manual installation and is not bundled correctly in the prebuilt image. |
| `v0.20.2rc1` / `v0.21.0rc1` / `v0.22.1rc1` (all `-310p-openeuler`, released 2026-06-03 to 2026-06-30) | ❌ Not viable (checked 2026-07-08, not pulled) | Checked upstream release notes for all three — none mention fixing `bishengir`/`Ascend310P3`. Confirmed via vllm-ascend maintainers (GitHub issues #7421, #7991) that **triton-ascend does not support 310P at all**; this is a permanent platform gap, not a bug being patched release-to-release. The actual fix (PR #8181, bypass triton entirely for 310P) is still unmerged as of 2026-04-13. **Do not spend time re-testing newer `-310p-openeuler` tags for this reason alone** — check whether #8181 has merged first. |
| `main-310p-openeuler` @ 2026-06-21 (ID: `4b5d312e0aba`) | ❌ Broken | Re-pulled the moving `main-310p-openeuler` tag on 2026-07-09 (PR #8181 still open/unmerged, 0 approvals — checked first). Fails at import time, not first-inference: `AttributeError: module 'triton' has no attribute 'language'` → `RuntimeError: Failed to load the backend extension: torch_npu`. Same packaging bug as `v0.18.0-310p-openeuler` (vanilla triton shadows triton-ascend), not the bishengir/Ascend310P3 gap. Rolled back to `main-310p-openeuler-stable` immediately. |
| `main-310p` (Ubuntu, no openeuler suffix, mutable) @ 2026-07-09 | ❌ Broken | Tried the non-openeuler base on the theory that the triton-shadowing bug might be openeuler-packaging-specific. **Same failure**: `AttributeError: module 'triton' has no attribute 'language'` at import. Confirms the bug is in vllm-ascend's own image build (triton bundling), not the openeuler base OS. |
| `v0.22.1rc1-310p` (Ubuntu, pinned) @ 2026-07-09 | ❌ Broken | Same pinned release as the already-rejected `v0.22.1rc1-310p-openeuler`, but Ubuntu base. **Same failure** as the two rows above (`triton.language` AttributeError). Confirms: **no currently published 310P image (openeuler or Ubuntu, `main` or `v0.22.1rc1`) works** — this is not a distro problem, and the platform gap in triton-ascend/CANN for 310P (see PR #8181 above) has not been addressed in any recent build. Stick with the pinned `main-310p-openeuler-stable` (ID `7d210d233141`) until #8181 merges. |
| `v0.23.0rc1-310p-openeuler` @ 2026-07-21 (release published 2026-07-19) | ⚠️ Broken by default, but has a **one-line workaround** — see below | Release notes explicitly claim "Ascend 310P support for Qwen3-ASR-1.7B, Qwen3.5, and Qwen3.6" (PRs #10441/#11264/#10257/#12115) — checked PR #8181 first (still open/unmerged, blocked by merge conflicts as of 2026-07-10, no change). Pulled and tested against our dense Qwen2.5-Coder-14B: same `AttributeError: module 'triton' has no attribute 'language'` at import time as every prior `main`/`v0.2x` tag. **Root cause found (2026-07-21):** `/usr/local/python3.12.13/lib/python3.12/site-packages/triton/` in this image is an empty namespace-package stub (a `backends/`+`language/` directory tree with zero actual `.py` files) — it makes `import triton` succeed (so torch's `except ImportError` guard never fires) but crashes the instant anything touches `triton.language.dtype` (torch's own `torch/_dynamo/utils.py` does this unconditionally at import time). **Fix: `mv .../site-packages/triton .../site-packages/triton.disabled` before launching `vllm serve`** (inside the container, e.g. via `--entrypoint /bin/bash -c "mv ... && exec vllm serve ..."`) — this makes `import triton` raise `ModuleNotFoundError` instead, which torch's guard *does* catch cleanly, and vllm_ascend's own `vllm.triton_utils.HAS_TRITON` correctly reports `False` and routes around it (log confirms: `Triton not installed or not compatible; certain GPU-related functions will not be available`). **Verified working end-to-end against Qwen3.5-35B-A3B-w8a8-mtp (MoE)** — see the dedicated section below. Not yet re-tested against the dense Qwen2.5-Coder-14B with this fix applied (only tried the MoE model so far) — worth doing to see if this workaround is what finally unblocks a dense-model upgrade off `main-310p-openeuler-stable`. |

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

## llama.cpp CANN Backend Retest — still a dead end, new detail on why (2026-07-22)

Retested prompted by upstream `docs/backend/CANN.md` explicitly listing `Atlas 300I Duo` / `310P` as **"Support"** (added 2024.11 per the doc's News section) — confirmed this isn't a stale claim, it predates our original May test by over a year. Retested with two changes from the original 2026-05-07 attempt: current llama.cpp `master` (`e8e6c7af`, was pinned to `632219af`) and `--no-warmup`, per that test's own "next steps."

**Model:** re-converted GGUF from `Qwen2.5-Coder-14B-Instruct-abliterated` (the original non-abliterated source dir and its GGUF were both deleted in the 2026-07-22 disk cleanup) → `~/build/llama-cpp-cann/Qwen2.5-Coder-14B-Instruct-abliterated-f16.gguf` (28GB, via `convert-model.sh`, now repointed at the abliterated model — still on disk).

**First attempt — CANN 9.0.0 base image: blocked by a driver/CANN ABI mismatch, not a kernel gap.** Built against `quay.io/ascend/cann:9.0.0-310p-openeuler24.03-py3.11` (already pulled locally). Build succeeded and correctly configured `GGML_CANN=ON`/`Ascend310P3`, but at runtime `npu-smi` itself failed inside the container: `undefined symbol: drvSetDeviceInfo` in `libdrvdsmi_host.so` — the host's driver (25.3.rc1, bind-mounted read-only) doesn't export a function CANN 9.0.0's toolkit expects. Result: `ggml_backend_cann` silently found 0 usable devices at startup (`warning: no usable GPU found`), no CANN-specific error surfaced. **This is a different failure mode than anything previously logged in this file** — not a missing kernel, not bishengir/Ascend310P3, but a driver-too-old-for-toolkit ABI gap. Confirms CANN 9.0.0 is not a drop-in swap without a driver upgrade.

**Second attempt — CANN 8.5.1 base (matches host driver, matches the original May test): got further, hit a different missing kernel.** Rebuilt against `ascendai/cann:8.5.1-310p-ubuntu22.04-py3.11` with current llama.cpp master. This time: both NPU chips correctly detected and assigned (`CANN0`/`CANN1`), model loaded, and Flash Attention was correctly auto-disabled with a clean fallback to CPU (`Flash Attention not supported, set to disabled` — this graceful-fallback behavior didn't exist in the March/`632219af` build). Then crashed on the **first real inference** (not warmup — `--no-warmup` had no effect either way) with the same class of error as May: `BinaryGetFunction failed, kernel_name=`, but this time pinpointed to a specific op: **`aclnnRoll`** (used in RoPE rotation, called from `aclnn_ops.cpp:2402`).

**Conclusion: the underlying blocker is unchanged — 310P ACLNN kernel coverage in available CANN toolkits is still incomplete for the exact ops llama.cpp's CANN backend needs, on both a 3-month-newer llama.cpp build and either available CANN version.** The specific missing op has now moved (May's warmup-time failure was never identified by name; this time it's `Roll`), consistent with kernel coverage being sparse/inconsistent across the op set rather than one specific known gap — so there's no single kernel to wait for. Upstream's "Support: 310P" listing in `CANN.md` should be read as "this device class works for some models/ops," not "every op used by every model works" — matches the same lesson already learned from vllm-ascend's `main` tags claiming 310P support while still hitting the triton-shadowing bug in practice.

**Verdict: still not viable, no material change from May.** Not worth a third retry without either (a) a llama.cpp CANN PR that specifically addresses missing 310P ACLNN kernels (Roll and whatever comes after it), or (b) a host driver upgrade paired with CANN 9.0.0+ to get past the ABI mismatch and see whether a newer CANN toolkit's kernel set happens to cover more ops (untested — the driver mismatch blocked us from ever reaching the kernel-coverage question on 9.0.0).

**Test method:** stopped the live `vllm-qwen36moe` profile to free the NPU, tested standalone on port 8003 (twice — CANN 9.0.0 then 8.5.1), removed the test container, restarted `vllm-qwen36moe` via `docker compose --profile qwen36 up -d`. **Found and fixed an unrelated operational bug in the process:** `docker compose up -d` on an existing *stopped* (not removed) container reuses its writable filesystem layer — since `vllm-qwen36moe`'s entrypoint does `mv .../triton .../triton.disabled && exec vllm serve ...` and that `mv` already ran on the container's first-ever boot, every subsequent stop/start of the *same* container instance fails at the `mv` step (already renamed) and crash-loops without ever reaching `vllm serve`. Required `docker compose --profile qwen36 up -d --force-recreate` to get a fresh container/filesystem layer. **This bug will recur on any future stop/start of this container** (host reboot, manual `docker stop`/`docker start`, `docker compose down`+`up` without `--force-recreate`) — the entrypoint command in `docker-compose.yml` should be made idempotent (e.g. `mv .../triton .../triton.disabled 2>/dev/null; exec vllm serve ...`, or check `[ -d .../triton ] && mv ...`) next time that file is touched.

**Cleanup (same day):** the 28GB re-converted GGUF and both new test images (`llama-cpp-cann:retest-2026-07-22`, `llama-cpp-cann:retest-2026-07-22-cann851`) were deleted — dead end again, same treatment as the 2026-07-22 disk cleanup above. The original `llama-cpp-cann:latest` image (from the May test) and the Dockerfile/convert-model.sh were kept, now updated to target CANN 9.0.0/8.5.1 and llama.cpp master — re-running `convert-model.sh` (source model still on disk) and `docker build` reproduces this retest if revisited.

## Alternative Inference Engine Survey (2026-07-09)

Surveyed alternatives to vllm-ascend given the permanent triton-ascend/310P gap (see Known Issues above) and the llama.cpp CANN dead-end (see above). Did not attempt any deployment yet — this is a ranked research pass only.

| Engine | 310P status | Notes |
|---|---|---|
| **Huawei MindIE** (MindIE-LLM / MindIE-Service) | ❌ Abandoned (2026-07-15) | Built and actually got the inference engine running Qwen2.5-Coder-14B on the 310P (model loaded, KV cache allocated, warmup forward pass completed) — see the (now-removed) Huawei MindIE Investigation section below for the summary. The serving daemon deterministically self-killed a few seconds after forking its tokenizer subprocess, in every attempt across two sessions; root cause never found. Abandoned by user decision, all build files/installer/wheel deleted. |
| **LMDeploy** (InternLM) via `dlinfer-ascend` backend | 🟢 Confirmed real users on 310P | Found actual GitHub issues from people running LMDeploy+dlinfer on 310P (issue #4038, CANN 8.2.rc1, Oct 2025; issue #4272, Jan 2026) — not just feature requests. `dlinfer` abstracts vendor kernels instead of using triton, avoiding our exact failure mode. `lmdeploy api_server` is OpenAI-compatible out of the box. On PyPI/GitHub, no special access needed — easiest to actually try. Reported rough edges: occasional serving hangs, multimodal input quirks. |
| vllm-ascend + CANN 9.0.0 ("Experimental" 300I Duo support per vllm-ascend wiki) | ❌ Already tried | Not a new engine. We already built this exact combo (`v0.19.1rc1-310p-openeuler-cann9` in Known Issues above) and hit the same bishengir/Ascend310P3 compile-target gap. |
| SGLang | ❌ Ruled out | Explicit "support Huawei Ascend 310P" feature request (#13917) was closed without landing. SGLang's Ascend work (ACLGraph) targets A2/A3 only. |
| TGI (Hugging Face) | ❌ Ruled out | No evidence of any Ascend/NPU backend. |

**Recommendation:** LMDeploy+dlinfer is the fastest to actually test (no access gate, real prior art on this exact chip) — worth a timeboxed trial next. MindIE has a higher ceiling (official, non-triton, native OpenAI endpoint) but needs a follow-up research pass to confirm image access and 300I Duo model coverage before attempting.

## LMDeploy + dlinfer-ascend Investigation (2026-07-09)

Attempted to actually deploy LMDeploy on the Atlas 300I Duo, following up on the survey above. **Result: confirmed dead end**, same class of problem as vllm-ascend and llama.cpp.

**Registry access:** The official prebuilt `300i-duo-latest` image lives only on an Aliyun China-region registry (`crpi-4crprmm5baj1v8iv.cn-hangzhou.personal.cr.aliyuncs.com`) — unreachable from this host (TCP connection to port 443 times out entirely, geo-blocked/no route). No Docker Hub or quay.io mirror exists.

**pip-install path:** dlinfer-ascend's README claims 300I Duo supports `pip install dlinfer-ascend` directly. False for this host: **every published wheel (0.1.0 through 0.2.7) is `manylinux2014_aarch64`-only** — there has never been an x86_64 wheel. Our host is x86_64 (Atlas 300I Duo PCIe card in an x86_64 server), so this path doesn't apply here at all; dlinfer's pip-install claim implicitly assumes an ARM/Kunpeng host pairing.

**Source build — got much further than expected:**
- Base image: `ascendai/cann:8.5.1-310p-ubuntu22.04-py3.11` (already used for the llama.cpp CANN attempt)
- Working package combo: `torch==2.8.0+cpu` + `torchvision==0.23.0+cpu` (from `download.pytorch.org/whl/cpu`) + `torch_npu==2.8.0` (per Ascend/pytorch's version matrix: torch_npu 2.8.0 ↔ CANN 8.3.RC1, close enough to our CANN 8.5.1 to work) + `dlinfer-ascend==0.2.5` built from source (`DEVICE=ascend python3 setup.py develop`) + `lmdeploy==0.11.1` + `transformers==4.46.3` (newer transformers ≥5.x restructures RoPE config and breaks lmdeploy 0.11.1's `rope_theta` access)
- `import dlinfer` succeeded cleanly with this exact combo
- torch_npu correctly detected both NPU chips (`torch.npu.device_count()` → 2) — confirms the driver/toolkit layer itself is fine on this host
- Requires `TVM_FFI_DISABLE_TORCH_C_DLPACK=1` env var — lmdeploy pulls in `xgrammar`→`tvm_ffi`→`torch_c_dlpack_ext`, which otherwise hard-crashes trying to load `libtorch_cuda.so` on a CPU-only torch build (unrelated to Ascend, just an artifact of lmdeploy assuming CUDA by default)

**Actual launch attempt:** `lmdeploy serve api_server --backend pytorch --device ascend --tp 2 /models/Qwen2.5-Coder-14B-Instruct` — reached real model construction, then hit `AttributeError: 'BaseModelAgent' object has no attribute 'build_model_ctx'` in `dlinfer/framework/lmdeploy_ext/device/ascend.py`'s `_build_model_310P` path. **This is the exact same crash reported in unresolved upstream issue #4272** (InternLM/lmdeploy) — we independently reproduced it on our own hardware with the same lmdeploy==0.11.1 + dlinfer-ascend==0.2.5 pairing. It is a genuine API mismatch between these two package versions' internal contracts, not a driver/CANN/hardware issue — confirmed by getting torch_npu device detection and `import dlinfer` working cleanly first.

**Conclusion:** LMDeploy is ruled out for now, same as vllm-ascend and llama.cpp — all three inference engines hit 310P-specific breakage. The dlinfer↔lmdeploy version pairing that avoids the `rope_theta` bug (newer transformers) doesn't exist simultaneously with the pairing that avoids the `build_model_ctx` bug (older lmdeploy) in any combination tried. Revisiting this would require either a dlinfer/lmdeploy release that fixes #4272, or trying newer dlinfer+lmdeploy pairs (0.2.6/0.2.7 + lmdeploy ≥0.12) with a correspondingly newer transformers pin — untested, no info found on whether #4272 is fixed there.

## Huawei MindIE Investigation — ABANDONED (2026-07-15)

Investigated 2026-07-13 to 2026-07-15, then **abandoned by user decision** and all related files deleted (installer `.run`, `atb_llm` wheel, install-guide PDF, `mindie-plan.md`, `~/build/mindie/` build dir, and the `mindie:3.0.0-310p` Docker image). Do not resume this investigation without re-downloading the installer/wheel from hiascend.com.

**Summary of where it got to, for context if revisited:** MindIE (Huawei's native CANN/ATB inference stack, bypasses triton entirely) was confirmed to actually run Qwen2.5-Coder-14B on the Atlas 300I Duo — model loaded across both chips, KV cache allocated, a warmup forward pass completed on NPU, engine reported ready. This ruled out the suspected blocker (no 310P custom transformer ops) since the dense-model ATB backend path doesn't need them. However, the serving daemon **deterministically self-killed its own process group** (`kill(-pid, SIGKILL)`) a few seconds after forking its tokenizer IPC subprocess, every time, in every debug run across two sessions — confirmed via strace to be a watchdog-timeout self-kill, not OOM/tini/bind/config related. Root cause of the fork failure itself was never found (leading theory: the tokenizer worker is forked *after* CANN/NPU context and threads are already live, and the forked child inherits broken post-fork state). Two persistent host-side changes were made during the investigation and were **left in place** since they're harmless/beneficial to the running vLLM stack: the model's `config.json` `torch_dtype` was changed from `bfloat16` to `float16` (vLLM already forces float16 via `--dtype` anyway), and the model directory permissions were tightened (`chmod -R go-w`).

## Huawei-internal vllm-ascend POC build for 300I Duo — TESTED (2026-07-15/16)

While researching whether the 2026-07-15 driver/firmware upgrade (see Deployment Notes) could unblock any newer vllm-ascend image, found upstream GitHub issue [vllm-project/vllm-ascend#7394](https://github.com/vllm-project/vllm-ascend/issues/7394) (RFC: "Deploy Qwen3.5 series model on 300I Duo"). The thread reveals a **Huawei-internal "POC" vllm-ascend build** (`vllm-ascend_dev-26.0.0.poc`, tag `9.0.T3.B030-20260421115402`, built 2026-04-21), tuned in the thread entirely for Qwen3.5/3.6 MoE models — distinct from the public `quay.io/ascend/vllm-ascend` images in the Known Issues table above.

**Downloaded and tested against our dense Qwen2.5-Coder-14B model (2026-07-16).** URL used: `https://mindie.obs.cn-north-4.myhuaweicloud.com/artifact/vllm/310p/9.0.T3.B030-20260421115402/vllm-ascend_dev-26.0.0.poc.300I-Duo-py311-openEuler24.03-lts-x86_64.tar.gz` (reachable, not geo-blocked, ~14.6GB, loaded fine as a proper OCI image via `docker load`, tagged `vllm-ascend:dev-26.0.0.poc.20260413-9.0.T3.B030-20260421115402-300I-Duo-py311-openEuler24.03-lts-x86_64`). Package versions inside: Python 3.11.10, `torch==2.9.0+cpu`, `torch_npu==2.9.0.post2.dev20260401`, `vllm==0.18.1.dev0`, `vllm_ascend==0.18.0rc2.dev28` — **no `triton` package installed at all** (vs. our public-image blocker where a vanilla `triton` install shadows `triton-ascend`).

**Result: non-eager ACLGraph mode genuinely works on our dense 14B model.** Launched with `--tensor-parallel-size 2 --max-model-len 16384 --additional-config '{"ascend_compilation_config": {"fuse_norm_quant": false}}' --compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY", "cudagraph_capture_sizes": [1,4]}'` (no `--enforce-eager`, no mamba-cache flag needed since this is dense not MoE) — model loaded (15.23GB/rank, matches known baseline), log showed `Triton not installed or not compatible; certain GPU-related functions will not be available` (harmless — it uses its own OOT `AscendCompiler`/torchair `npugraph_ex` backend instead), graph capture completed in 3 seconds, server started cleanly, `/v1/models` and `/v1/chat/completions` both responded correctly.

**Benchmark comparison** (`bench/run_bench.py --base-url http://localhost:8003/v1`):

| Metric | Eager baseline (25.3.rc1 driver, 2026-07-15) | POC ACLGraph non-eager (2026-07-16) |
|---|---|---|
| Single-stream | 9.53 tok/s | **11.26 tok/s (+18%)** |
| Concurrent-8 | 61.31 tok/s | 58.88 tok/s (~flat, slightly lower) |
| Coding pass@1 | 10/10 | 10/10 (unchanged) |
| Tool-calls | ❌ not populated | ❌ not populated, and errored `HTTP 400` (tool-choice flags weren't set for this test) |
| Max context | 32768 | **16384 (halved)** |

**Verdict: real but modest win, with a real cost — not adopted yet.** +18% single-stream is genuine (tight min/max range 11.24–11.27 tok/s across runs), but: (1) **max context must be halved to 16384** — the 310P attention op can't do mask compression, so this isn't a free lunch; (2) concurrent throughput doesn't improve and may be marginally worse; (3) tool-calling wasn't tested with the right flags in this pass; (4) it's an unsupported internal dev/poc snapshot with no changelog or update path — no guarantee of longevity, and the upstream thread reports real instability for MoE models (repetition loops, OOM, high TTFT) that we haven't stress-tested for our dense model beyond this one basic smoke test (single chat completion + bench suite, no long-running soak test, no restart/crash-recovery check).

**Test method:** stopped production `vllm-qwen25coder` container to free NPU devices, ran the POC image standalone on port 8003 with our model bind-mounted read-only, benchmarked, then stopped the test container and restarted production — no changes made to `docker-compose.yml` or the live stack.

**If revisiting to actually adopt this:** would need to (a) decide if losing half the context window (32768→16384) is acceptable, (b) get tool-calling working with `--enable-auto-tool-choice --tool-call-parser hermes` (or find whether this build even supports it correctly, given the OOT compiler differs from public images), (c) run a longer soak test given upstream reports of multi-turn repetition/OOM issues on MoE models, (d) evaluate whether a locally-tagged image (not pulled from a Chinese OBS bucket with no official support channel) is an acceptable long-term dependency.

## Qwen3.5-35B-A3B-w8a8 on v0.23.0rc1 — TESTED, promising but not adopted yet (2026-07-21)

Following up on the POC-image work above, downloaded and tested the exact model the #7394 thread was built around: **`Qwen3.5-35B-A3B-w8a8-mtp`** (MoE, 35B total / ~3B active per token, w8a8-quantized, with an MTP speculative-decode head), from ModelScope `Eco-Tech/Qwen3.5-35B-A3B-w8a8-mtp` → `${MODELS_DIR}/Qwen3.5-35B-A3B-w8a8-mtp` (10 safetensors shards + index/tokenizer, ~39.8GB total, all sizes verified byte-exact against the ModelScope file listing). Download initially stalled at ~1.25MB/s single-connection (would've taken ~8h); restarting with 6 parallel `curl -C -` (resumable range requests) connections got it to ~9.9MB/s aggregate, finishing in ~1h10m.

**Ran on the official `v0.23.0rc1-310p-openeuler` release, not the Huawei POC image** — using the triton-stub-removal workaround discovered while testing this release (see the Known Issues table row above: `mv .../site-packages/triton .../site-packages/triton.disabled` before `vllm serve`). Launch command:
```bash
docker run -d --name vllm-test-qwen35 --ipc host \
  -e ASCEND_VISIBLE_DEVICES=0,1 -e OMP_NUM_THREADS=8 -e MALLOC_ARENA_MAX=2 \
  --device /dev/davinci0 --device /dev/davinci1 --device /dev/davinci_manager --device /dev/devmm_svm --device /dev/hisi_hdc \
  -v /usr/local/dcmi:/usr/local/dcmi:ro -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi:ro \
  -v /usr/local/Ascend/driver/lib64:/usr/local/Ascend/driver/lib64:ro \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info:ro \
  -v /etc/ascend_install.info:/etc/ascend_install.info:ro \
  -v ${MODELS_DIR}/Qwen3.5-35B-A3B-w8a8-mtp:/models/Qwen3.5-35B-A3B-w8a8-mtp:ro \
  -p 8003:8000 --entrypoint /bin/bash \
  quay.io/ascend/vllm-ascend:v0.23.0rc1-310p-openeuler \
  -c "mv /usr/local/python3.12.13/lib/python3.12/site-packages/triton /usr/local/python3.12.13/lib/python3.12/site-packages/triton.disabled && exec vllm serve /models/Qwen3.5-35B-A3B-w8a8-mtp \
    --served-model-name qwen3.5 --trust-remote-code --tensor-parallel-size 2 \
    --dtype float16 --quantization ascend --max-model-len 16384 --max-num-seqs 16 \
    --gpu-memory-utilization 0.90 \
    --additional-config '{\"ascend_compilation_config\": {\"fuse_norm_quant\": false}}' \
    --compilation-config '{\"cudagraph_mode\": \"FULL_DECODE_ONLY\", \"cudagraph_capture_sizes\": [1,4]}' \
    --mamba-ssm-cache-dtype float16 --reasoning-parser qwen3 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder"
```
`--mamba-ssm-cache-dtype float16` is required (fixes `npu_recurrent_gated_delta_rule` error); `--reasoning-parser qwen3` separates `<think>` content into the response's `reasoning` field. Did **not** set `HCCL_OP_EXPANSION_MODE=AIV` (unsupported on 300I Duo, per thread).

**Result: it works.** Model loaded across both chips (18.85 GB/rank weights), KV cache allocated (711,856 tokens @ 16384 max-len), ACLGraph decode-graph capture completed in 3s, server reached `Application startup complete`, and `/v1/chat/completions` responded correctly to both plain and tool-calling requests.

**Benchmark comparison** (`bench/run_bench.py --base-url http://localhost:8003/v1 --model qwen3.5`, full results in `bench/results.md`):

| Metric | Dense Qwen2.5-Coder-14B (production, eager) | Qwen3.5-35B-A3B-w8a8-mtp (v0.23.0rc1, ACLGraph) |
|---|---|---|
| Single-stream | 9.53 tok/s | **29.62 tok/s (+211%)** |
| Concurrent-8 | 61.31 tok/s | 43.24 tok/s (lower — MoE/KV-cache overhead) |
| Coding pass@1 (harness default, 512 max_tokens) | 10/10 | **1/10 — misleading, see below** |
| Tool-calls populated | ❌ No (known issue) | ✅ **Yes** — correct `tool_calls` array, `finish_reason: tool_calls` |
| Max context | 32768 | 16384 (halved, same 310P attention-mask-compression limit as the POC image) |

**The 1/10 pass@1 score is a bench-harness artifact, not a real quality problem — verified by hand.** This model reasons very verbosely before answering: a manual re-test of the two failing cases (`is_prime`, `fizzbuzz`) with `max_tokens=2048` instead of the harness's default 512 produced **correct code both times** (`finish_reason: stop`, ~1350-1420 completion tokens each — almost all of it spent on chain-of-thought in the `reasoning` field before the actual code appears). At 512 tokens the model was still mid-thought when cut off (`finish_reason: length`, empty `content`), which the harness scores as a failure. **Real, practical downside this exposes:** despite ~3x higher raw single-stream tok/s, wall-clock latency per coding answer is likely *higher* than the dense 14B for simple tasks, because ~1300+ tokens of reasoning must complete before any usable output streams out. This needs a proper re-benchmark with a much larger `max_tokens` (e.g. 3000-4000) before any real throughput comparison is valid — the numbers above are speed-of-tokens-once-generating, not speed-to-useful-answer.

**Tool-calling genuinely works** (unlike production's dense model) — tested with `--tool-call-parser qwen3_coder`: a weather-lookup prompt correctly produced a populated `tool_calls` array with valid JSON arguments and `finish_reason: tool_calls`. This is a first for this whole investigation — no prior image/model/engine combination tried (see all sections above) has ever gotten tool-calling to actually populate the structured field.

**Verdict: real and significant, but not adopted as production yet.** Open items before considering a switch: (1) re-benchmark pass@1 and throughput with a token budget sized for this model's reasoning verbosity; (2) run a longer soak test — upstream thread reports of multi-turn repetition loops/OOM at long context for w8a8 MoE were **not** stress-tested here (only single-turn smoke tests); (3) decide if halved context (16384) and the added latency-per-answer from verbose reasoning are acceptable trade-offs for the tool-calling fix and raw throughput gain; (4) confirm the triton-stub-removal workaround is stable/repeatable and not fragile to image updates; (5) evaluate `v0.23.0rc1-310p-openeuler` (official, changelogged release) as a long-term dependency vs. the current pinned `main-310p-openeuler-stable`.

**Test method:** stopped production `vllm-qwen25coder`, ran standalone on port 8003, benchmarked, removed the test container, restarted production via `docker compose up -d`, verified via `docker inspect` + `curl /v1/models` that production matches the pinned "Production Setup" baseline exactly. No changes made to `docker-compose.yml`.

## Huihui-Qwen3.6-35B-A3B-abliterated on v0.23.0rc1 — TESTED, real quality-reliability risk found (2026-07-21)

Followed up the Qwen3.5 test above by trying the newer, uncensored **`huihui-ai/Huihui-Qwen3.6-35B-A3B-abliterated`** (from the [huihui-ai/qwen36-abliterated](https://huggingface.co/collections/huihui-ai/qwen36-abliterated) HF collection) — same MoE architecture family (`Qwen3_5MoeForConditionalGeneration`, confirmed via `config.json` and vLLM's `registry.py`), same 36B-total/~3B-active shape, but **unquantized bf16** (no pre-quantized w8a8 release exists for this model, unlike the Eco-Tech Qwen3.5 one). Downloaded from HuggingFace (~71.9GB, 26 safetensors shards + tokenizer, all sizes verified byte-exact) — HF's CDN was much faster than ModelScope, ~100MB/s aggregate with 6 parallel `curl -C -` connections, finished in ~10 minutes.

**Two real blockers found and worked around:**

1. **310P does not support bf16 at the hardware op level.** Launching with `--dtype bfloat16` (the checkpoint's native dtype) crashed immediately on model init: `AclNN_Parameter_Error(EZ1001): Self dtype DT_BF16 not support in current soc version`. This matches what the (now-deleted) MindIE investigation already found — 310P needs fp16. **Fix: `--dtype float16`** forces vLLM to convert weights on load; this worked cleanly.
2. Same triton-stub-removal workaround as the Qwen3.5 test was required (see Known Issues table row on `v0.23.0rc1-310p-openeuler`) — this model also has vision-tower code paths (it's `image-text-to-text` per its HF `pipeline_tag`, unused here since we only send text) that don't change the fix needed.

**Memory is genuinely tight, as anticipated for a 71.9GB bf16 model on 2×~44GB chips:** weights alone took 33.8 GiB/rank (matches ~36GB/rank ÷ overhead), leaving only ~1.6 GiB/rank for KV cache — forced `--max-model-len 4096` (vs. the dense 14B's 32768, or the w8a8 Qwen3.5's 16384). The engine's own log suggested this could be pushed slightly higher via an explicit `--kv-cache-memory` override, but 4096 was not further tuned given the other issue found below made this moot for now.

**It works and produces correct output — most of the time.** A Fibonacci-function request and a `reverse_string` request both came back correct (`finish_reason: stop`, coherent code). Single-stream throughput ~28.6-29.2 tok/s, concurrent-8 ~44 tok/s — both in the same range as the Qwen3.5 w8a8 test, i.e. a similar ~3x speed lift over the dense 14B eager baseline.

**But: a real, non-harness reasoning-termination failure was found — not just a token-budget artifact this time.** Unlike the Qwen3.5 test (where a low pass@1 was purely due to the bench harness's 512-token default being too small for verbose-but-finite reasoning), this model's `is_prime` test **failed even at `max_tokens=3500`** (`finish_reason: length`, `content` still empty). Inspecting the `reasoning` field showed the model had actually already worked out and written the correct code *inside* its own chain-of-thought early on, then kept rambling with low-information filler ("Ready. ... Output matches. Proceeds. [Output Generation] -> *Proceeds*") instead of ever transitioning out of the reasoning phase to emit a final `content` answer — burning the entire remaining token budget on repetition-like filler. This is a genuine behavioral risk (possibly an abliteration side-effect disrupting the model's normal think-token exit condition, or an inherent Qwen3.6 quirk) — **combined with the hard `--max-model-len 4096` ceiling forced by memory pressure, this means some prompts may simply never produce a usable answer on this hardware**, unlike the Qwen3.5 w8a8 test where 16384 context gave enough room to always eventually finish reasoning.

**Tool-calling not tested this pass** (launched without `--enable-auto-tool-choice --tool-call-parser qwen3_coder` to save a relaunch cycle; the Qwen3.5 test already confirmed this parser combo works for this model family, so it would likely work here too, budget permitting).

**Verdict: works, but riskier than the Qwen3.5-35B-A3B-w8a8 test above — not adopted.** The combination of (a) no available pre-quantized weights (forcing bf16→fp16 at full size), (b) the resulting hard 4096-token context ceiling, and (c) an observed real failure-to-conclude on at least one simple prompt, makes this a weaker candidate than the already-tested Qwen3.5 w8a8 model for now. If revisiting: (1) try `--kv-cache-memory` override to see how much more context can be squeezed out; (2) test whether the reasoning non-termination is reproducible/systematic or a one-off — run the same prompt multiple times; (3) check if a community w8a8 quantization of this specific model appears (would roughly halve the memory footprint like the Eco-Tech Qwen3.5 release did, freeing much more room for context); (4) the sibling **`huihui-ai/Huihui-Qwen3.6-27B-abliterated`** (dense, `Qwen3_5ForConditionalGeneration`, ~55.6GB bf16) was identified as a lower-risk candidate — proportionally similar footprint to the current working dense 14B — but not yet tested.

**Test method:** same as the Qwen3.5 test above — production stopped, tested standalone on port 8003, torn down, production restarted and verified against the pinned "Production Setup" baseline. No changes to `docker-compose.yml`.

## Huihui-Qwen3.6-27B-abliterated (dense) — TESTED, same reasoning-termination bug found; root cause and fix identified (2026-07-21)

Followed up the same day by testing the dense sibling identified above, **`huihui-ai/Huihui-Qwen3.6-27B-abliterated`** (`Qwen3_5ForConditionalGeneration`, ~55.6GB bf16, 15 safetensors shards, downloaded from HuggingFace and verified byte-exact — HF's CDN gave ~83MB/s aggregate with 6 parallel connections).

**Launched with the same recipe as the 35B MoE test** (`--dtype float16` to work around the 310P bf16-unsupported issue, triton-stub-removal workaround, `--mamba-ssm-cache-dtype float16`, `--reasoning-parser qwen3`) but with `--max-model-len 16384` instead of 4096, since dense weights (27.98 GiB/rank) leave far more room than the MoE model did — confirmed: KV cache pool of 125,922 tokens, 7.69x concurrency at 16384, vs. the MoE test's cramped 86,425 tokens at 4096.

**Speed:** ~6.2 tok/s single-stream — about **half** the dense 14B's 9.53 tok/s, consistent with the memory-bandwidth-bound scaling already documented in the Performance Baseline section (roughly 2x the parameters ≈ roughly 2x the bytes read per token ≈ roughly half the tok/s). A Fibonacci-function prompt came back correct and coherent (1318 completion tokens, 214.6s).

**The same `is_prime` prompt failed again** — `finish_reason: length` at `max_tokens=2000`, empty `content`, same rambling-without-concluding pattern as the 35B MoE test. **This confirms the bug is not specific to one model size or the MoE architecture — it reproduces identically across two different huihui-ai Qwen3.6-abliterated models** (35B-A3B MoE and 27B dense), strongly pointing to something in the abliteration process or a shared quirk of the Qwen3.6 base itself, not a fluke of one checkpoint.

**Root cause found and fix confirmed working, without needing a relaunch:** inspected the model's `chat_template.jinja` (no live inference needed) and found it supports the standard Qwen3-family `enable_thinking` toggle — when `enable_thinking` is `false`, the template inserts an **empty** `<think>\n\n</think>\n\n` block immediately after the prompt, skipping the reasoning phase entirely rather than ever entering the loop that gets stuck. Tested by resending the *same* `is_prime` request with `"chat_template_kwargs": {"enable_thinking": false}` added to the request body (an OpenAI-API-compatible extension vLLM passes through to the chat template) — **result: `finish_reason: stop`, correct code, only 91 completion tokens, 15.2s** (vs. burning 2000 tokens and failing with reasoning enabled). Confirmed via `reasoning: None` in the response that no thinking occurred at all.

**Two other untested-but-identified levers**, for prompts where disabling reasoning entirely isn't desirable: (1) `generation_config.json` ships fairly loose defaults (`temperature: 1.0, top_k: 20, top_p: 0.95`, **no repetition penalty at all**) — the observed rambling-on-filler-phrases behavior is a classic symptom of this combination, so adding `repetition_penalty` (vLLM extra param) or `frequency_penalty`/`presence_penalty` (OpenAI-standard, also passed through by vLLM) could plausibly fix it while keeping reasoning intact; (2) lowering `temperature` (e.g. to 0.2-0.3, or 0 for greedy) as a blunter version of the same idea. Neither was tested this session — `enable_thinking: false` was confirmed sufficient and cheaper to verify.

**Verdict: the reasoning-termination bug has a known, cheap, per-request fix (`enable_thinking: false`) — this meaningfully de-risks this whole model family for adoption, but soak-testing and a broader risk/reward call against the current dense 14B baseline haven't been done yet.** Before considering either Qwen3.6 model (35B-A3B MoE or 27B dense) for production: (1) re-run both models' full accuracy benchmarks with `enable_thinking: false` set by default via `--chat-template-kwargs` at server launch (or per-request) to see the *real* pass@1, not the reasoning-inflated/broken numbers gathered so far; (2) decide whether losing chain-of-thought reasoning by default is an acceptable trade for reliability, or whether the repetition-penalty alternative is worth testing as a way to keep reasoning without the failure mode; (3) the 27B dense model's ~6.2 tok/s is meaningfully slower than the current 9.53 tok/s baseline — a real regression to weigh against whatever quality gain a newer Qwen3.6 checkpoint offers over Qwen2.5-Coder-14B; (4) tool-calling untested on this model (same `qwen3_coder` parser combo from the Qwen3.5 test is the likely candidate to try).

**Test method:** same as all tests above — production stopped, tested standalone on port 8003, torn down, production restarted and verified via `docker inspect` + `curl /v1/models` against the pinned "Production Setup" baseline. No changes to `docker-compose.yml`.

## Qwen3.6 reasoning-stuck bug — real fix found via sampling params, not just `enable_thinking: false` (2026-07-22)

Follow-up session: user wants Qwen3.6 usable **with thinking kept on** (not disabled), just not getting stuck. Re-tested both models on `v0.23.0rc1-310p-openeuler` with the triton-stub-removal workaround, same recipe as before.

**Dense 27B abandoned first — too slow to be worth continued tuning.** Re-confirmed ~6.2 tok/s single-stream (vs. current production's 9.53 tok/s) and, notably, the `is_prime` prompt that failed reliably last session actually **succeeded** on a retry at default sampling (`temperature=1.0`, no repetition penalty) — 753 completion tokens, `finish_reason: stop`. This proves the bug is **probabilistic, not deterministic** (consistent with the loose default sampling already suspected), but the dense model's speed alone ruled it out as a candidate — user decision to stop testing it and focus on the 35B-A3B MoE instead (already ~4.6x faster).

**MoE model (`Huihui-Qwen3.6-35B-A3B-abliterated`, `--max-model-len 4096`, same launch recipe as before): tuned sampling genuinely fixes the bug.** Tested `temperature: 0.2` + `repetition_penalty: 1.1` (both passed per-request, no server relaunch needed) against the two prompts that had triggered problems before:

| Prompt | max_tokens | Result |
|---|---|---|
| `is_prime` | 1500 | **3/3 clean** (`finish_reason: stop`, 617-759 completion tokens) |
| `reverse_string` (no slicing/`reversed()`) | 1500 | 1/3 clean, 2/3 hit the token cap mid-reasoning |
| `reverse_string` (retest, same sampling) | 3000 | **3/3 clean** (`finish_reason: stop`, 1223-1638 completion tokens) |

**Key finding: the 1500-token "stuck" cases at the tuned sampling were a budget problem, not an infinite loop.** Given enough headroom (3000 tokens), the model always reached a real answer — reasoning tails in all 3 retries end with normal "done, outputting now" language, not endless filler. This is a **materially better result than `enable_thinking: false`**: it keeps chain-of-thought active and reliably converges, rather than skipping reasoning entirely.

**Tool-calling confirmed working with this same tuned sampling config**: `--tool-call-parser qwen3_coder`, request with `temperature: 0.2, repetition_penalty: 1.1` → `finish_reason: tool_calls`, correctly populated `tool_calls` array (`get_weather` with valid JSON args), 25s response time.

**Recommended usable config for this model, pending broader validation:**
- `temperature: 0.2`, `repetition_penalty: 1.1` per request (no server-side default needed — vLLM accepts both as OpenAI-extension body params)
- `max_tokens` generous — **3000-4000**, not the harness/API default of 512-1500 — this model's reasoning style is verbose (600-1650+ tokens observed) even when it's working correctly
- Keep `--reasoning-parser qwen3` so reasoning lands in `reasoning_content`, not mixed into `content`

**Not yet done:** broader prompt coverage beyond `is_prime`/`reverse_string` (only these two were retested this session); no soak test; no re-run of the full `bench/run_bench.py` suite with these sampling params baked in to get a real pass@1 number. The previous session's `enable_thinking: false` fix is still valid as a fallback for latency-sensitive requests where reasoning isn't needed at all — the two fixes aren't mutually exclusive, pick per-request.

**Test method:** same as all sessions above — production stopped, tested standalone on port 8003 (first the dense 27B, then swapped for the MoE model), no changes to `docker-compose.yml`. As of this note, **production is still stopped and the MoE test container (`vllm-test-qwen36-moe`) is still running** — pending user decision on next steps before restoring production.

## Qwen3.6 MoE adopted as a `docker-compose.yml` profile (2026-07-22)

User decided the MoE model (with the tuned-sampling fix above) is ready for regular use, not just ad-hoc `docker run` testing. Added it to `docker-compose.yml` as a **second Compose profile** (`qwen36`), alongside the existing production service (now explicitly profiled `prod`) — see "Switching Models" in the Models section above for the day-to-day commands. Key structural changes:

- Both `vllm-qwen25coder` (`profiles: [prod]`) and the new `vllm-qwen36moe` (`profiles: [qwen36]`) publish the same host port (`8002:8000`) and claim the same NPU devices — Compose profiles keep them mutually exclusive (only one is ever created at a time), since starting both simultaneously would conflict on both.
- Both services share the network alias `vllm-backend` (`networks.llmnet.aliases`). Open WebUI's `OPENAI_API_BASE_URLS` now points at `http://vllm-backend:8000/v1` instead of a hardcoded container name — this means switching profiles never requires touching Open WebUI's config; verified live (`docker exec openwebui curl http://vllm-backend:8000/v1/models` correctly resolved to whichever profile was active).
- **`--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'` bakes the reasoning-stability fix in server-side** — confirmed this flag exists and is honored on `v0.23.0rc1-310p-openeuler` (`vllm serve --help`'s parsed non-default args echoed it back correctly), and a live request **with zero client-side sampling params** produced `finish_reason: stop` with correct code — meaning Open WebUI users get the fix automatically, no per-request tuning needed on the client side. This is a better outcome than documented in the section above, which assumed the params had to be passed per-request.
- `vllm-qwen36moe` uses `entrypoint: [/bin/bash, -c]` + a single shell string as `command:` to apply the triton-stub-removal workaround (`mv .../triton .../triton.disabled && exec vllm serve ...`) before launch — same technique as every ad-hoc `docker run` test above, just expressed in Compose form.
- Launch config: `quay.io/ascend/vllm-ascend:v0.23.0rc1-310p-openeuler`, `--tensor-parallel-size 2 --dtype float16 --max-model-len 4096 --max-num-seqs 16 --gpu-memory-utilization 0.95`, `--reasoning-parser qwen3`, `--enable-auto-tool-choice --tool-call-parser qwen3_coder`, `--mamba-ssm-cache-dtype float16`, ACLGraph compilation config (`FULL_DECODE_ONLY`, capture sizes `[1,4]`) — same recipe validated in the standalone tests above.

**Verified end-to-end via Compose (not just ad-hoc `docker run`):** `docker compose --profile qwen36 up -d` → full startup → `/v1/chat/completions` with no client sampling params → correct `is_prime` code, `finish_reason: stop`, 656 completion tokens, 23.9s. Then `docker compose --profile qwen36 down && docker compose --profile prod up -d` → production verified back to the exact pinned baseline (`main-310p-openeuler-stable` image, `Qwen2.5-Coder-14B-Instruct-abliterated` model via `/v1/models`).

**Known trade-offs of the `qwen36` profile, unchanged from prior testing:** context was initially left at 4096 (later raised to 16384 same day — see below), and only `is_prime`/`reverse_string` have been retested with the tuned config — broader prompt coverage and a soak test are still open items (see previous section).

## Qwen3.6 MoE context window raised 4096 → 16384 (2026-07-22, same day)

The 4096 limit set during earlier testing was conservative, not a hard ceiling — the startup log for this model had already hinted at more headroom (`--kv-cache-memory` suggestions of 3.35-5.11 GiB, well above what a 4096-token pool needs). Simply changing `--max-model-len` from 4096 to 16384 in `docker-compose.yml` (no other flags touched) and recreating the container confirmed this: engine log reported **`GPU KV cache size: 119,772 tokens`, `Maximum concurrency for 16,384 tokens per request: 7.31x`** — i.e. the KV cache pool was always large enough for 16384 context with room to spare for several concurrent long requests; the earlier 4096 setting was leaving most of that pool unused.

Verified end-to-end: `/v1/models` reports `max_model_len: 16384`, and a live `is_prime` request completed normally (`finish_reason: stop`, 1453 completion tokens, ~28 tok/s, 51.8s) — no regression from the context bump.

**Update — 32768 tried same day, does NOT fit.** Tested bumping `--max-model-len` straight to 32768 (matching production) to see if the pool could go further. The KV-cache token estimate still looked fine at startup (`GPU KV cache size: 126,305 tokens`, `Maximum concurrency for 32,768 tokens per request: 3.85x`) — but the engine then **OOM'd during graph/compile workspace allocation**, a separate memory need from the KV cache pool itself: `RuntimeError: ... NPU out of memory. Tried to allocate 2.00 GiB (NPU 0; 43.24 GiB total capacity; 40.39 GiB already allocated; ...; 764.23 MiB free ...)`. So the KV-cache-size log line is **not** a reliable predictor of whether a given `--max-model-len` will actually start — larger context also needs larger ACLGraph/compile buffers that scale independently and can blow the budget even when the KV pool math looks fine. Reverted to 16384 (confirmed working again: `GPU KV cache size: 119,772 tokens`, `max_model_len: 16384` live, no regression).

**16384 is the practical ceiling for this model at the current settings.** To go further would require freeing memory elsewhere: `--enforce-eager` (drops ACLGraph, other tests showed this costs meaningful single-stream speed), a smaller `--gpu-memory-utilization` headroom trade, or — most promising — a quantized (w8a8) version of this specific checkpoint, following the same pattern as `Qwen3.5-35B-A3B-w8a8-mtp` which ran comfortably at 16384+ with much more headroom to spare (no such quantized release exists for this Qwen3.6 checkpoint as of this writing).

**Confirmed via upstream vllm-ascend docs (2026-07-22 research pass): 16384 isn't just where we happened to land — it's the officially documented safe ceiling for 310P in general.** vllm-ascend's own docs state that on 310P, auto-detected/larger context lengths can cause mask allocation to exceed NPU memory and OOM, and explicitly recommend an explicit conservative value like `--max-model-len 16384`. This is a hardware-generation constraint, not specific to this model — independently corroborated by a user report on upstream PR #7065 ("Add explanation of 310p special param: max-model-len") hitting the same OOM past 16384 even on a full dual-card (96GB combined) Atlas 300I Duo. **Decision: staying at 16384, not pursuing 32768 further.**

Other findings from that research pass, for future reference:
- The `max_cudagraph_capture_size` warning we saw at startup links to vllm-ascend issue #8240, which turned out to be an unrelated bug report (GLM-5 prefill/decode-disaggregation hang) — the linked issue in vLLM's own warning text is a generic tracker URL, not real guidance. Ignore it.
- `enable_kv_nz` and `torchair_graph_config` (310P-relevant KV-cache layout flags) are **gated to MLA-architecture models** (DeepSeek/PanguProMoE) using the torchair backend — Qwen3.6 uses standard attention on the ACLGraph/AscendCompiler backend we already run, so these would be no-ops or risk breaking things. Not applicable here.
- `moe_backend` config and EPLB (expert-parallel load balancing) shipped in v0.23.0rc1, but EPLB targets larger expert-parallel/multi-node deployments — unclear benefit for our single-node TP=2 setup where all experts are already resident. Untested, no clear recommendation either way.
- Expanding `cudagraph_capture_sizes` from `[1,4]` to include larger batch sizes (e.g. `[1,4,8,16]`, matching `--max-num-seqs 16`) could help *concurrent multi-request* throughput specifically — vLLM's own warning about this is legitimate, unlike the #8240 red herring. But each additional captured graph size costs more workspace memory, the exact resource that OOM'd at 32768. **Not attempted** — user has a single-conversation use case where this wouldn't clearly help, and it wasn't judged worth the risk/testing effort for that reason. If concurrent-user throughput becomes a priority later, test incrementally (add one size at a time, e.g. `[1,4,8]` first) rather than jumping to the full range.

**Note on the "Production Setup" pinned baseline above:** its revert commands were updated to use `--profile prod`/`--profile qwen36` instead of bare `docker compose up -d`/`down`, since profiles are now required — plain `docker compose up -d` with no profile flag only starts `openwebui`.

## Qwen3.6-35B-A3B-w8a8 download in progress — IN PROGRESS, not yet tested (2026-08-03)

Started downloading a pre-quantized w8a8 version of the Qwen3.6-35B-A3B MoE model, following up on the open item from the "Qwen3.6 MoE context window raised" section above: the currently-adopted `qwen36` profile runs bf16 weights and is capped at `--max-model-len 16384` purely by memory pressure (no pre-quantized checkpoint existed for this model at the time). Found `Eco-Tech/Qwen3.6-35B-A3B-w8a8` on ModelScope — same publisher/quantization family as the already-tested and working `Eco-Tech/Qwen3.5-35B-A3B-w8a8-mtp` (see that section above), which ran comfortably at 16384+ context with plenty of headroom to spare on this same hardware.

**Method:** a plain (non-Compose) detached container, not part of `docker-compose.yml`:
```bash
docker run -d --name modelscope-dl -v ${MODELS_DIR}:/models python:3.11-slim bash -c '
pip install --quiet modelscope hf_transfer 2>&1 | tail -5
python3 -c "
from modelscope.hub.snapshot_download import snapshot_download
snapshot_download(\"Eco-Tech/Qwen3.6-35B-A3B-w8a8\", local_dir=\"/models/Qwen3.6-35B-A3B-w8a8\", max_workers=8)
print(\"DOWNLOAD_COMPLETE\")
"
'
```
Downloads to `${MODELS_DIR}/Qwen3.6-35B-A3B-w8a8` (25 files, 10 safetensors shards @ ~2-4.3GB each). Both vLLM profiles were already stopped for unrelated reasons when this was started, so the download had the full NPU-idle host to itself — no interaction with the running stack.

**A real operational lesson learned: don't `docker stop`/restart a `snapshot_download` container mid-transfer expecting a clean resume.** The container was manually stopped and recreated (identical command) partway through, intending to force a fresh/faster connection for a slow last shard. Effect: the overall download correctly skipped the 9 already-complete shards (no wasted re-download there), but the one in-flight shard (`quant_model_weights-00010-of-00010.safetensors`, ~46% done at the time) restarted from 0% instead of resuming from its `.incomplete` file — modelscope's downloader does not appear to persist enough state across a hard container restart to resume a partial single-file download, only to skip whole already-validated files. **Lesson: leave a ModelScope snapshot_download alone once started; restarting only helps at the whole-file granularity, and costs whatever partial progress existed on the file that was mid-transfer.**

**Second, more concerning issue found independent of the restart:** after that restart, the same shard 10 **failed hash validation twice in a row** — once on the resumed-then-corrupted partial data (expected, given the above), but then *again* on a subsequent full clean re-download from 0%. Two clean-attempt failures on the same file points at something beyond our own restart — possibly a flaky network/proxy path corrupting this specific file's transfer, or a real integrity issue with this file at the ModelScope source. `modelscope_hub.download` has its own internal retry loop (observed: "Hash validation failed ... retrying (1/3)", "(2/3)") — as of end of session it was partway through attempt 2/3, download left running unattended overnight per user request.

**Next session must check this before assuming the model is ready to test:**
1. `docker ps --filter name=modelscope-dl` — still running, or exited?
2. `docker logs modelscope-dl --tail 50` — look for `DOWNLOAD_COMPLETE` (success) vs. a raised/uncaught exception after all 3 retries exhausted (failure).
3. If it failed a 3rd time: don't just re-run the whole `snapshot_download` call blind — consider fetching that one shard from HuggingFace instead (if a HF mirror of this quantization exists) or from ModelScope with `force_download`/no resume, since the repeat corruption suggests resume-state or a flaky path may be the actual culprit, not one-off bad luck.
4. Once genuinely complete: verify total size/shard count matches ModelScope's file listing (same verification method used for every other model download in this file), then proceed to the same launch recipe as `Qwen3.5-35B-A3B-w8a8-mtp` above (`--dtype float16 --quantization ascend`, triton-stub-removal workaround, `--mamba-ssm-cache-dtype float16`, `--reasoning-parser qwen3`, ACLGraph compilation config) as a starting point — standalone on port 8003, not touching `docker-compose.yml`, per the standard experiment method in this file.
5. If it works and gives meaningfully more context headroom than the current bf16 `qwen36` profile's 16384, that's the case for updating the `qwen36` profile in `docker-compose.yml` to point at this quantized checkpoint instead of the bf16 one — remember to keep the `--override-generation-config` sampling-stability fix from the "reasoning-stuck bug" section above, since that fix is specific to Qwen3.6's behavior, not the bf16 checkpoint.

## Qwen3.6-35B-A3B-w8a8 — TESTED, fatal 310P kernel gap found, NOT adopted (2026-08-04)

Followed up on the overnight download above. **Download completed successfully**: `docker logs modelscope-dl` showed `DOWNLOAD_COMPLETE`; shard 10 (the one that failed hash validation twice the night before) passed on its 3rd retry. All 25 files present, 10 safetensors shards, 38GB total. Container removed after confirming.

**Model:** official (non-abliterated) `Eco-Tech/Qwen3.6-35B-A3B-w8a8` from ModelScope — `msmodelslim`-quantized w8a8 of `Qwen/Qwen3.6-35B-A3B`, same `Qwen3_5MoeForConditionalGeneration` architecture family as the already-tested/adopted Huihui abliterated forks. No MTP speculative-decode head this time (unlike the sibling `Qwen3.5-35B-A3B-w8a8-mtp`). Note this quantization was validated by its publisher on an Atlas 800T A3, not 310P — same caveat that applied to the Qwen3.5 w8a8 test, which nonetheless worked fine on our hardware.

**Launch recipe:** same as the `Qwen3.5-35B-A3B-w8a8-mtp` test (`v0.23.0rc1-310p-openeuler`, triton-stub-removal workaround, `--dtype float16 --quantization ascend`, `--mamba-ssm-cache-dtype float16`, `--reasoning-parser qwen3`, `--tool-call-parser qwen3_coder`, `--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'`), standalone on port 8003.

**Context-ceiling testing (same methodology as every other model in this file — push `--max-model-len` until it breaks):**

| `--max-model-len` | Result |
|---|---|
| 32768 | ❌ OOM during ACLGraph decode-graph capture — `NPU out of memory. Tried to allocate 2.00 GiB ... 2.70 GiB free` (narrow miss, same failure class as the bf16 `qwen36` profile hit at this same context size) |
| 24576 | ✅ KV cache sized correctly (743,716 tokens, 30.26x concurrency), graph capture succeeded (1.18 GiB, 3s), server reached `Application startup complete`, `/v1/models` confirmed `max_model_len: 24576`. Weights: 18.85 GiB/rank (vs. bf16 Qwen3.6-35B-A3B's 33.8 GiB/rank) — quantization is working as intended memory-wise. |

**Then: fatal crash on the first real inference request.** Sent the standard `is_prime` test prompt — the entire vLLM engine died:
```
Aicpu kernel execute failed, device_id=0/1, ... kernelName=IndexPut, errorCode=0x2a
rtStreamSynchronize execution failed, reason=aicpu exception
synchronize stream failed, runtime result = 507018
RuntimeError: Worker failed with error 'ACL stream synchronize failed, error code:507018'
vllm.v1.engine.exceptions.EngineDeadError: EngineCore encountered an issue.
```
Container exited entirely (`Exited (0)`) — not a request-level error, a full engine crash requiring container restart.

**Isolated the cause: re-tested with `--enforce-eager` (dropping ACLGraph entirely) — same crash, identical `IndexPut` AICPU exception.** This rules out ACLGraph/graph-capture as the cause — it's a genuine missing/broken 310P kernel for the `IndexPut` op itself, triggered on the first real forward pass regardless of execution mode. Root cause not narrowed further (likely candidates: w8a8 dequantization's indexing step, or MoE expert gather/scatter routing — both plausible given `IndexPut`'s typical use, neither confirmed).

**Important distinction from the already-adopted `qwen36` profile:** this crash is on the **w8a8-quantized official checkpoint**, not the bf16 Huihui abliterated model currently running in production as the `qwen36` Compose profile — that model has been working fine in regular use since 2026-07-22. This is a new, hardware-specific kernel gap distinct from (a) the triton-stub bug, (b) bf16-unsupported-at-op-level, and (c) llama.cpp's `Roll` kernel gap — all already documented above. Unknown whether this is specific to this exact quantization tool/checkpoint or a more general "w8a8 quant + Qwen3.6 MoE" incompatibility on 310P — the sibling `Qwen3.5-35B-A3B-w8a8-mtp` model (different base model, same quant family/publisher) did **not** hit this error, so it's not simply "any w8a8 MoE model triggers this."

**Verdict: not viable, hard blocker — a real kernel gap, not a config/flag issue to tune around.** No further recipe variation (eager vs. graph, different context sizes) changes the outcome; the crash is deterministic on first inference. Would need either an upstream `vllm-ascend`/CANN fix for `IndexPut` on 310P, or a different quantization of this specific model that avoids whatever op path triggers it.

**Test method:** production was already stopped from the prior session (left down overnight for the download); tested standalone on port 8003 across three launches (32768 ACLGraph → OOM, 24576 ACLGraph → crash on inference, 24576 eager → same crash), each old container removed before the next launch. After confirming the blocker, removed the final test container and restored production via `docker compose --profile prod up -d`, verified via `docker inspect` + `/v1/models` against the pinned baseline (`main-310p-openeuler-stable`, `Qwen2.5-Coder-14B-Instruct-abliterated`, `max_model_len: 32768`) — no changes made to `docker-compose.yml`.

## Newer vllm-ascend release on the dense production model — TESTED, real upgrade candidate, NOT yet adopted (2026-08-04)

Finally re-tested the triton-stub-removal fix (found 2026-07-21, see Known Issues table) against the actual production dense model, per the long-standing top-priority item in this file. First checked quay.io for the newest available 310P-tagged image via the registry API (`quay.io/api/v1/repository/ascend/vllm-ascend/tag/`) rather than assuming `v0.23.0rc1` (already tested on the MoE models in July) was still current — found `nightly-releases-v0.25.1rc-310p-openeuler` as the newest 310P tag (newer than `nightly-releases-v0.24.0rc-310p-openeuler`; no numbered release past `v0.23.0rc1` exists yet, only mutable `nightly-releases-*` tags for v0.24/v0.25).

**Test 1 — exact production flags, just a newer image + the triton-stub-removal workaround.** Pulled `quay.io/ascend/vllm-ascend:nightly-releases-v0.25.1rc-310p-openeuler`, ran standalone on port 8003 with **identical flags to the current pinned production command** (`--dtype float16 --tensor-parallel-size 2 --enforce-eager --compilation-config '{"mode":0}' --max-model-len 32768 --max-num-batched-tokens 32768 --max-num-seqs 32 --gpu-memory-utilization 0.95 --enable-prefix-caching --enable-chunked-prefill --enable-auto-tool-choice --tool-call-parser hermes`), only difference being the triton-stub-removal `mv` in the entrypoint. **Result: works cleanly, full `bench/run_bench.py` comparison run:**

| Metric | Production baseline (`main-310p-openeuler-stable`, 2026-07-15) | `nightly-releases-v0.25.1rc-310p-openeuler` (2026-08-04) |
|---|---|---|
| Single-stream | 9.53 tok/s | **10.74 tok/s (+12.7%)** |
| Concurrent-8 | 61.31 tok/s | **67.62 tok/s (+10.3%)** |
| Coding pass@1 | 10/10 | 10/10 (unchanged) |
| Tool-calls | ❌ not populated | ❌ not populated — same raw `<tools>...</tools>` text, confirms this is a chat-template/model issue, not a vllm-ascend version issue |
| Max context | 32768 | 32768 (unchanged) |

**This is a genuine, no-downside win** — same context, same flags, same accuracy, just a real speed improvement from ~4 months of upstream vllm/vllm-ascend improvements, unlocked purely by the triton-stub-removal workaround this same investigation found in July.

**Test 2 — same image, non-eager ACLGraph mode** (dropping `--enforce-eager`, adding `--additional-config '{"ascend_compilation_config": {"fuse_norm_quant": false}}' --compilation-config '{"cudagraph_mode": "FULL_DECODE_ONLY", "cudagraph_capture_sizes": [1,4]}'`, same recipe as the July 2026-07-15/16 Huawei-internal POC test): **11.15 tok/s single-stream (+17%) but 65.47 tok/s concurrent-8 (worse than eager's 67.62), and requires halving `--max-model-len` to 16384** (same 310P attention-mask-compression limit documented everywhere else in this file). Coding pass@1 still 10/10, tool-calling still not populated. **Same trade-off already seen with the internal POC build in July — not worth the halved context for a marginal single-stream gain and a concurrent-throughput regression. Eager mode (Test 1) is the better candidate.**

**Verdict: `nightly-releases-v0.25.1rc-310p-openeuler` in eager mode is a real upgrade candidate for production, not yet adopted.** Open items before actually switching: (1) it's a mutable `nightly-releases-*` tag, not an immutable numbered release like the currently-pinned `main-310p-openeuler-stable` — decide whether to accept that as a rolling dependency or re-tag it locally (`docker tag ... vllm-ascend:nightly-releases-v0.25.1rc-310p-openeuler-stable` or similar) the same way the current image was pinned; (2) no soak test done — only the standard bench-harness smoke test, same caveat as every other experiment in this file; (3) if adopted, `docker-compose.yml`'s `vllm-qwen25coder` service would need its `image:` updated and the entrypoint changed to add the triton-stub-removal `mv` step (same technique already used for `vllm-qwen36moe`), and the "Production Setup" pinned-baseline section at the top of this file would need updating to match the new baseline.

**Test method:** production stopped (`docker compose --profile prod down`, which also stops `openwebui` since it has no profile — expected, not a bug), pulled the new image, tested standalone on port 8003 across two launches (eager, then ACLGraph), each verified via `bench/run_bench.py --base-url http://localhost:8003/v1`, old container removed before the next launch. After both tests, removed the final test container and restored production via `docker compose --profile prod up -d`, verified via `docker inspect` + `/v1/models` against the pinned baseline (`main-310p-openeuler-stable`, `Qwen2.5-Coder-14B-Instruct-abliterated`, `max_model_len: 32768`) — no changes made to `docker-compose.yml`.

## v0.23.0 stable released; qwen36 profile repinned from rc1 (2026-08-17)

vllm-ascend's `v0.23.0` line was promoted from release-candidate to a numbered stable release on 2026-08-16 (`quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler` / `v0.23.0-310p` on quay.io). Diffed the stable changelog against `v0.23.0rc1` (already running in production): the only post-rc1 additions (marked `†` in the release notes) are Qwen3.5/Qwen3.6 **MTP/speculative-decoding** bugfixes on 310P (`index_fill`/`GatherV2` OOB crashes, block-table overflow, Mamba-align hangs) — none of which apply to our config (no MTP/spec-decode in use).

**Tested standalone on port 8003 with production's exact `qwen36` flags** (same model, same `--max-model-len 16384`, same ACLGraph config, same `--override-generation-config` sampling fix, triton-stub-removal workaround unchanged) — `/v1/models` matched production exactly, manual `is_prime` request came back correct (`finish_reason: stop`, 950 completion tokens with a generous `max_tokens`), tool-calling confirmed working (`finish_reason: tool_calls`, correct `get_weather` args). `bench/run_bench.py` harness numbers (27.04 tok/s single-stream, 40.67 tok/s concurrent-8) are within normal run-to-run noise of the rc1 baseline; harness pass@1 was 0/10 due to the same known 512-token-budget-too-small-for-reasoning artifact already documented elsewhere in this file — not a real regression, confirmed via the manual retest above.

**Adopted:** `docker-compose.yml`'s `vllm-qwen36moe` service `image:` repinned from `v0.23.0rc1-310p-openeuler` to `v0.23.0-310p-openeuler`. Verified end-to-end via Compose: `docker compose --profile qwen36 up -d --force-recreate` → `Application startup complete` → `/v1/models` shows `qwen3.6-moe`, `max_model_len: 16384` → live `is_prime` request returns correct code, `finish_reason: stop`. No other flags changed. This is a strict improvement over the rc1 pin (immutable numbered release vs. a release-candidate tag, same or better behavior) — see "Production Setup" table above for the updated pinned value.

## Qwen3.6-35B-A3B-w8a8 retested on v0.23.0 stable — the fatal IndexPut crash is GONE, real adoption candidate (2026-08-17)

Followed up on the 2026-08-04 fatal-crash finding (`Eco-Tech/Qwen3.6-35B-A3B-w8a8` dying with AICPU `IndexPut`/error 507018 on the very first inference request, on `v0.23.0rc1-310p-openeuler`, both eager and ACLGraph modes — see that section above). Before writing this off permanently, checked upstream GitHub for the exact symptom and found it's a **known, actively-discussed bug**, not something specific to our setup:

- Issue [#11188](https://github.com/vllm-project/vllm-ascend/issues/11188) and [#13050](https://github.com/vllm-project/vllm-ascend/issues/13050) (closed) both report the identical `507018`/`IndexPut` crash on 310P with this exact model, traced to `gdn_linear_attn` (the gated-delta-net linear-attention op, `vllm_ascend/_310p/ops/fla/gdn_310.py`) — a different call site than the already-merged/open PRs for multimodal-merge IndexPut crashes (#11435, #12914), which don't apply here since we send text-only requests.
- A community user in that thread found a workaround by hand-patching `gdn_310.py`; a driver-version theory (24.x vs 25.x) was also raised. Rather than hand-patch blind, the pragmatic move was to just retest on the newly-released `v0.23.0-310p-openeuler` stable image first, since it ships a newer `torch_npu` (2.10.0.post4, vs whatever rc1 shipped) and CANN stack.

**Retested standalone on port 8003, same launch recipe as the 2026-08-04 test** (`--dtype float16 --quantization ascend --max-model-len 24576 --max-num-seqs 16 --gpu-memory-utilization 0.90`, triton-stub-removal workaround, `--mamba-ssm-cache-dtype float16`, `--reasoning-parser qwen3`, `--tool-call-parser qwen3_coder`, `--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'`), no patch applied to any vllm-ascend source file. **Result: the crash does not reproduce.** Startup succeeded (18.85 GiB/rank weights, matches prior test), and every inference request survived:

| Test | Result |
|---|---|
| First `is_prime` request (1500 max_tokens) | No crash — hit token budget mid-reasoning (`finish_reason: length`), same verbose-reasoning pattern as the bf16 model, not a kernel failure |
| `reverse_string`, `fizzbuzz` (3500 max_tokens) | Both `finish_reason: stop`, correct code |
| `is_prime` retest (5000 max_tokens) | `finish_reason: stop`, correct code, 971 completion tokens |
| Tool-calling (`get_weather`) | `finish_reason: tool_calls`, correct populated `tool_calls` array |
| Full `bench/run_bench.py` suite (throughput + 10 accuracy prompts + concurrent-8 + tools) | Container survived the entire run with zero crashes — **31.08 tok/s single-stream, 39.44 tok/s concurrent-8**, tool-calling populated via the harness too. pass@1 1/10 is the known 512-token-budget artifact, not a real failure (see manual retests above) |
| NPU memory after full bench run | ~38GB/44GB per chip used, ~6GB free per chip — meaningfully more headroom than the bf16 model typically leaves |

Container was alive and stable for the full ~20-minute test window across all of the above. The 32768-context OOM ceiling found on 2026-08-04 (a separate, memory-driven failure, not the IndexPut kernel bug) was not retested — no reason to expect the ACLGraph/compile-workspace memory math changed, so **24576 remains the practical context ceiling** for this model (vs. bf16's 16384 — a real +50% context increase).

**Root cause of why the crash disappeared is not confirmed** — plausibly the newer `torch_npu`/CANN bundled in the `v0.23.0` stable image vs. `v0.23.0rc1`, plausibly something environment/driver-related per the upstream thread's speculation. No vllm-ascend changelog entry explicitly claims an `IndexPut`/`gdn_310` fix between rc1 and stable. Treat this as "no longer reproducing under repeated testing," not "provably fixed" — worth extra vigilance (a longer soak, more varied prompts, multi-turn conversations) before fully trusting it under real usage load.

**Important distinction from the current production model:** this w8a8 checkpoint is `Eco-Tech/Qwen3.6-35B-A3B-w8a8`, the **official (non-abliterated) Qwen quantization** — not the `huihui-ai` abliterated fork currently running as the `qwen36` profile. Adopting it as production would mean trading the current model's refusal-free behavior for standard content moderation/refusals, in exchange for more context headroom (24576 vs 16384) and slightly higher single-stream throughput (31.08 vs ~27-28.6 tok/s). **This is a values/behavior trade-off, not just a technical upgrade — not adopted pending an explicit decision on whether the abliteration trade-off is worth it.** If abliteration is a hard requirement, the alternative path is watching for either (a) an abliterated fork of this specific w8a8 checkpoint, or (b) applying the same w8a8 quantization process to the currently-running `Huihui-Qwen3.6-35B-A3B-abliterated` weights directly (untested, not attempted here).

**Test method:** same as all tests in this file — production stopped, tested standalone on port 8003, torn down, production restored via `docker compose --profile qwen36 up -d --force-recreate` (using the newly-repinned stable image, see previous section) and verified against the pinned baseline. No changes made to `docker-compose.yml` model/service configuration — only the image-tag repin documented in the previous section.

## Self-quantized abliterated w8a8 of Huihui-Qwen3.6-35B-A3B-abliterated — built from scratch, TESTED, working (2026-08-19)

Followed up on the standing "no abliterated w8a8 checkpoint exists" gap (see "Qwen3.6-35B-A3B-w8a8 retested on v0.23.0 stable" above) by quantizing the currently-running abliterated bf16 model ourselves, using Huawei's own `msmodelslim` tool (`pip install msmodelslim`, version 26.1.0) rather than waiting for a community release.

**Two real bugs found and fixed along the way, both novel (not already documented in this file):**

1. **msmodelslim's `qwen3_5_moe_w8a8` config path can't load our model's native bf16 weights on 310P** — same class of `AclNN_Parameter_Error: Self dtype DT_BF16 not support` seen everywhere else in this file for inference, but hit here during calibration/quantization instead. Fix: physically converted all 26 bf16 safetensors shards to fp16 on disk first (`safetensors` + `torch`, cast via `.to(float32).to(float16)`) — just relabeling `config.json`'s `torch_dtype` field was **not** sufficient, since msmodelslim's `torch_dtype="auto"` resolution reads the actual tensor dtype from the checkpoint, not the config file. Conversion took ~20 min (67GB read+write, disk-I/O-bound, some transient slowdown from page-cache thrashing since the working set exceeds host RAM — not a bug, just slow).
2. **A genuine bug in msmodelslim's own source, not a config issue**: `msmodelslim/model/qwen3_5_moe/model_adapter.py` hardcodes `default_dtype(torch.bfloat16)` (lines 531 and 612) when constructing per-layer decoder structures for its layer-wise/on-demand loading path — independent of the actual checkpoint dtype. This crashes identically on 310P (`torch.amin` on a bf16 tensor). **Fixed by patching the installed package directly**: `sed -i 's/default_dtype(torch.bfloat16)/default_dtype(torch.float16)/g'` on that file (plus clearing the stale `.pyc` cache) — same "patch vendor source for a 310P-specific bug" pattern already used elsewhere in this repo's history (e.g. the `adeepv` W8A16 section below, the triton-stub-removal workaround). This is a report-upstream-worthy bug in msmodelslim itself, unrelated to our model.

**Quantization run, after both fixes:** `msmodelslim quant --model_type 'Qwen3.5-35B-A3B' --model_path <fp16-converted-dir> --save_path <out> --config_path .../lab_practice/qwen3_5_moe/qwen3_5_moe_w8a8.yaml --device npu:0,1 --trust_remote_code True` (note: no exact `Qwen3.6-35B-A3B` entry exists in msmodelslim's model registry — `Qwen3.5-35B-A3B` is used since it's the same architecture family and the tool auto-detects `Qwen3_5MoeForConditionalGeneration` regardless). Ran cleanly end-to-end: all 40 decoder layers + vision encoder + MTP head processed with **zero errors**, ~14s/layer, finished in ~13 minutes wall-clock. Output: **`===========SUCCESS===========`**, 38GB across 10 safetensors shards (down from 71.9GB bf16 — the expected ~2x w8a8 reduction) at `${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8`.

**Smoke-tested standalone on port 8003, same recipe as the already-tested official Eco-Tech w8a8 checkpoint** (`--dtype float16 --quantization ascend --max-model-len 24576 --max-num-seqs 16 --gpu-memory-utilization 0.90`, triton-stub-removal workaround, `--mamba-ssm-cache-dtype float16`, `--reasoning-parser qwen3`, `--tool-call-parser qwen3_coder`, `--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'`) — **passed everything, including the exact first-inference step that fatally crashed the official Eco-Tech checkpoint on the older rc1 image (`IndexPut`/507018, see that section above) — no crash here either, consistent with that bug being fixed on this `v0.23.0` stable image:**

| Test | Result |
|---|---|
| Weight load | 18.85 GiB/rank (matches Eco-Tech w8a8's footprint), `vLLM Ascend ModelSlim quantization` correctly auto-detected from `quant_model_description.json` |
| KV cache / graph capture | 753,664 tokens, 30.67x concurrency at 24576 context — graph capture completed in 3s, zero crashes |
| `is_prime` code gen (max_tokens 3000) | `finish_reason: stop`, correct code, 707 completion tokens |
| Tool-calling (`get_weather`) | `finish_reason: tool_calls`, correctly populated arguments |
| Abliteration check (SYN flood security-research question, max_tokens 2500) | `finish_reason: stop`, full detailed technical answer (2434 tokens), zero refusal/hedging language — **confirms abliteration survived quantization** |

**This closes the long-standing gap**: we now have a genuinely working abliterated + w8a8 (ascend-native msmodelslim format) checkpoint of this model, at 24576 context (+50% over the currently-running bf16 `qwen36` profile's 16384) with a real, if untested, throughput edge on top (Eco-Tech's equivalent w8a8 checkpoint measured ~31 tok/s vs. the bf16 model's ~27-31 tok/s).

**Not yet done — this is a validated candidate, not yet adopted into `docker-compose.yml`:**
1. No full `bench/run_bench.py` throughput run yet, only the manual smoke tests above.
2. No soak test — only ~15 minutes of testing across a handful of requests.
3. No side-by-side comparison of output *quality* (not just refusal-behavior) between the bf16 original and this quantized version — w8a8 quantization can subtly degrade reasoning/code quality even when it doesn't break refusal removal; unverified either way here.
4. If adopting: would need to update `docker-compose.yml`'s `vllm-qwen36moe` service to point at the new model path, bump `--max-model-len` to 24576, add `--quantization ascend`, and update the "Production Setup" pinned-baseline table at the top of this file.
5. The intermediate fp16-converted 67GB staging copy was created inside a throwaway container's writable layer and discarded when the container was removed — **not** saved to `${MODELS_DIR}`. If the quantization needs to be re-run (e.g. to try a different config/dataset), that fp16 conversion step must be redone from the original bf16 source (script/logic documented above, straightforward to reproduce, ~15-20 min).

**Test method:** production (`qwen36` profile) was stopped for the entire duration (build environment → convert weights → quantize → smoke-test), never touching `docker-compose.yml`. Standalone quantization work happened in a disposable container (`msmodelslim-quant`, based on the pinned `v0.23.0-310p-openeuler` image for its already-working `torch_npu`/CANN environment) with the abliterated model bind-mounted read-only and a host directory bind-mounted for output — removed after the quantization succeeded. The smoke-test container (`vllm-test-qwen36-w8a8`) was removed after passing all checks. Production was restarted via `docker compose --profile qwen36 up -d` and verified via `/v1/models` (`qwen3.6-moe`, `max_model_len: 16384`) to exactly match the pinned baseline before this entry was written.

## w8a8 production switch — full benchmark comparison, self-quantized model adopted (2026-08-19)

Followed up the self-quantization work above with a full head-to-head benchmark between the running bf16 production model and the new self-quantized w8a8 checkpoint, to decide which to keep. Both are the **exact same abliterated weights** (`Huihui-Qwen3.6-35B-A3B-abliterated`), just quantized differently — so this was purely a technical speed/memory/quality comparison, not a values trade-off like the earlier official-Eco-Tech-checkpoint decision.

**Method:** ran `bench/run_bench.py` (throughput + harness's 512-token accuracy/tools) against each model, plus a custom higher-budget (2500-4000 token) manual accuracy+tools script (`manual_accuracy.py`, ad-hoc, not committed to the repo) to get a fair pass@1 number — the harness's 256/512-token budgets are too small for this model family's verbose reasoning and produce a misleading 0/10 for both models regardless of real capability (already documented as a known artifact in earlier sections). Production was stopped for each test, run standalone on port 8003, then restored.

| Metric | bf16 (prior pin) | w8a8 (self-quantized) |
|---|---|---|
| Single-stream throughput | 27.84 tok/s | **31.36 tok/s (+12.6%)** |
| Concurrent-8 throughput | 40.19 tok/s | 39.85 tok/s (~flat, -0.8%) |
| Context window | 16384 | **24576 (+50%)** |
| Harness pass@1 (512-token budget) | 0/10 | 0/10 (both — known artifact, not a real score) |
| **Manual pass@1 (2500-4000 token budget)** | **6/10** | **7/10** |
| Harness tool-calling (256-token budget) | ❌ not populated (empty content, budget exhausted before tool call) | ✅ populated correctly |
| Manual tool-calling (2000-token budget) | ✅ populated correctly | ✅ populated correctly |
| Disk footprint | 71.9GB | 38GB |
| Weights loaded per rank | 33.8 GiB | 18.85 GiB |

**Key finding: the reasoning-non-termination bug (verbose chain-of-thought that runs out the token budget without concluding) is not fixed or worsened by quantization — it's an inherent, roughly-30-40%-per-task-sample property of this model family**, seen at comparable rates on both bf16 (4/10 tasks hit it) and w8a8 (3/10 tasks hit it). Notably the *specific* tasks that failed were different between the two runs (bf16 failed on `is_prime`/`flatten`/`merge_sorted`/`anagram`; w8a8 failed on `count_vowels`/`merge_sorted`/`anagram`) — confirming this is genuinely probabilistic per-request, not a fixed per-prompt failure mode. Already-known mitigations (`enable_thinking: false`, or `temperature`/`repetition_penalty` tuning — both documented in earlier sections) apply equally regardless of which quantization is running.

**Decision: switched production to the w8a8 checkpoint.** It won on every axis that differed (throughput, context, pass@1, tool-calling robustness at tight budgets) with no axis where it was meaningfully worse (concurrent-8 throughput was a statistical tie). `docker-compose.yml`'s `vllm-qwen36moe` service was updated: model path → `Huihui-Qwen3.6-35B-A3B-abliterated-w8a8`, `--max-model-len` 16384 → 24576, `--gpu-memory-utilization` 0.95 → 0.90, added `--quantization ascend`. Verified end-to-end via Compose (`docker compose --profile qwen36 up -d`) — `Application startup complete`, `/v1/models` shows `qwen3.6-moe` / `max_model_len: 24576`, live `is_prime` request returns correct code with `finish_reason: stop`.

**Not yet done:** a real soak test under sustained multi-day usage (both this session's testing and the earlier smoke tests were single-session, <1 hour of cumulative live traffic). If anything unexpected shows up under real usage, the bf16 weights are still on disk (see "Production Setup" above) for an easy rollback — just swap the model path, `--max-model-len` back to 16384, `--gpu-memory-utilization` back to 0.95, and drop `--quantization ascend`.

## Upstream vllm-ascend check + routine production health check (2026-09-01)

**Upstream research:** checked `vllm-project/vllm-ascend` on GitHub for changes since the 2026-08-17 pass (which established `v0.23.0-310p-openeuler` as the pinned baseline — see "v0.23.0 stable released" section above). Findings:

- **No numbered release newer than v0.23.0 exists.** The mutable nightly line has moved on — `nightly-releases-v0.25.1rc-310p-openeuler` was rebuilt as recently as 2026-08-25 (newer build than the one tested 2026-08-04, same tag), and a `nightly-releases-v0.26.0rc` line exists — but **no `-310p` variant of v0.26.0rc has been published** (only `-a3`/`-a5` builds). One low-confidence, uncorroborated claim suggests v0.26 may add W8A8SC quantization for 310P; nothing to test yet.
- **PR #8181 (the 310P triton bypass) is still unmerged**, blocked on merge conflicts since ~2026-07-10 — the triton-stub-removal workaround baked into `docker-compose.yml`'s entrypoint remains necessary indefinitely.
- **Issue #13050 (the AICPU `IndexPut`/507018 crash that fatally blocked `Eco-Tech/Qwen3.6-35B-A3B-w8a8` on 2026-08-04) is now closed upstream, with a confirmed root cause: an NPU driver-version problem (24.x drivers), fixed by upgrading to a 25.x+ driver combined with the v0.23.0 release.** This host already runs driver 25.3.rc1 on v0.23.0 — so the "no longer reproduces" finding from the 2026-08-17 retest (see that section above) is now understood, not just observed.
- **Issue #11188 is a separate, still-open bug** — a different symptom ("Reserve addr is invalid, should call halMemMap", a memory-mapping error) in the same 310P+Qwen3.6+w8a8+GDN territory, reported by someone who's tried driver reinstalls/firmware upgrades without resolving it. Doesn't affect this environment today (not observed here), but the underlying bug class isn't fully closed out upstream — worth remembering if anything odd surfaces on the w8a8 production model under real usage.

**Routine production health check:** verified `docker ps` shows all three services (`vllm-qwen36moe`, `openwebui`, `searxng`) up (12 days uptime at check time), and `/v1/models` reports `qwen3.6-moe` / `max_model_len: 24576` — exactly matching the pinned "Production Setup" table. Ran `bench/run_bench.py` against the live endpoint (port 8002, not a standalone test container — no need to touch production for a read-only health check):

| Metric | This check (2026-09-01) | w8a8 adoption baseline (2026-08-19) |
|---|---|---|
| Single-stream | 31.29 tok/s | 31.36 tok/s |
| Concurrent-8 | 31.41 tok/s | 39.85 tok/s |
| Tool-calls | ✅ populated | ✅ populated |
| Harness pass@1 (512-token budget) | 0/10 | 0/10 (known artifact, not a real score — see "w8a8 production switch" section for the real 7/10 manual pass@1 at a realistic token budget) |

Single-stream and tool-calling are consistent with the adoption baseline — no drift. The concurrent-8 gap (31.41 vs 39.85) was not re-verified by hand this session (e.g. repeat runs, ruling out background load from other host activity) — worth a re-check if this number matters for a near-term decision, but not treated as a regression on the strength of one run alone.

## `adeepv/Qwen3.6-27B-W8A16-Ascend310P` — surveyed, NOT tested, ruled out for now (2026-07-22)

Researched (HF page only, no download/hardware test) after the user asked to correlate it with our own Qwen3.6 work above. This is a **community weight-only int8 (W8A16) quantization** of the official (non-abliterated) `Qwen/Qwen3.6-27B`, published by a third party (`adeepv`, not Huawei/Qwen), targeting our exact chip (Ascend 310P3 / Atlas 300I Duo) via vllm-ascend.

**What it actually optimizes — memory, not speed, and it says so explicitly:** weights only go from FP16 to int8 (activations stay FP16) specifically to roughly halve weight footprint (~54GB→~27GB for the dense 27B) and free that memory for a much bigger KV cache — headline claim is **256K context, but only at TP=4** (2× Atlas 300I Duo cards / 4 chips). The author's own numbers show decode speed *slightly regresses* under quantization: ~3.8 tok/s (FP16, TP=4) → ~3.1 tok/s (W8A16, TP=4).

**Why it doesn't fit our hardware:** we removed our second (defective) card in June — see the CLAUDE.md hardware note above — so we run **1 card / 2 chips (TP=2) only**. The README's 256K-context headline is TP=4-only; for TP=2 it just says "drop `--tensor-parallel-size 2` and use a smaller `--max-model-len`" with no concrete number given. And even the TP=4 numbers (~3.1–3.8 tok/s) are far below both our current production dense-14B baseline (9.53 tok/s) and our own already-tested dense Qwen3.6-27B bf16 result (~6.2 tok/s, see section above) — a 27B model at ~3 tok/s would be a clear regression even before touching the reasoning bug.

**Correlations with our own investigation:**
- **Same reasoning-parser pattern we already found**: README says answer text lands in `reasoning_content` and to pair with `--reasoning-parser qwen3` — consistent with our `enable_thinking`/`--reasoning-parser qwen3` findings on the Huihui-Qwen3.6 models above. Doesn't confirm or deny whether *this* checkpoint has our observed reasoning-non-termination bug (untested here, and it's the non-abliterated base model, not huihui-ai's abliterated fork — the bug may be abliteration-specific, still unconfirmed).
- **A different, previously-undocumented 310P kernel bug**, orthogonal to both things we found (empty triton stub; bf16-unsupported at the op level): weight-quant (`npu_weight_quant_batchmatmul`) expects **ND `[K,N]` layout** but stock vllm-ascend's `w8a16.py` casts to FRACTAL_NZ, which 310P doesn't support (`task not supported`). The repo ships a source patch (`patches/methods_init_310.py`) overriding this — not something we've hit because we haven't tried weight-only quantization ourselves yet.
- **Also confirms `--enforce-eager` is mandatory on 310P** for this code path — but their reason (`AclmdlRICaptureEnd`, error 507903) is a *different* ACLGraph failure than what we'd expect, and notably **contradicts our own POC-image result** (see "Huawei-internal vllm-ascend POC build" section above, 2026-07-15/16) where non-eager ACLGraph decode mode genuinely worked on our dense 14B. Likely explanation: this repo targets a different vllm-ascend variant/build (`quay.io/ascend/vllm-ascend:nightly-main-310p`, with patches mounted into a `vllm_ascend/_310p/` subpackage that doesn't exist in either our pinned `main-310p-openeuler-stable` or the public `v0.23.0rc1-310p-openeuler` we already tested) — i.e. a third, distinct 310P-specific vllm-ascend code path we haven't seen before, worth a closer look on its own merits independent of this specific model.
- Uses `msmodelslim` data-free RTN int8 (ascend `ascendV1` format) — different quantization tool/format than the pre-quantized w8a8 Qwen3.5 model we already tested (Eco-Tech's release, "w8a8-mtp").

**Verdict: not worth testing on our hardware right now.** Wrong TP shape for its own headline feature (needs TP=4, we have TP=2), speed is a clear regression vs. both our current production baseline and our own already-tested bf16 Qwen3.6-27B, and the reasoning-termination risk we already found on this model family is neither confirmed nor ruled out here. The one thing worth following up independently: the `nightly-main-310p` image's dedicated `_310p` vllm-ascend subpackage — if it's a maintained, more-310P-native code path than what we've tried, it could matter for the dense-14B-upgrade question (item 1 in "Resume Here" above) separately from this quantized model.

## Gemma 4 12B Investigation (2026-07-09)

Downloaded `google/gemma-4-12B` (the "Unified" dense model, 12B params, BF16 safetensors, ~24GB, encoder-free multimodal text+image+audio) to `${MODELS_DIR}/gemma-4-12B` to evaluate as a possible alternative/addition to the Qwen2.5-Coder baseline. **Not attempted on hardware — ruled out at the software-compatibility check before even reaching the 310P/triton wall.**

- `config.json`'s `architectures` field is `Gemma4UnifiedForConditionalGeneration` — a brand-new model class.
- Checked inside the running `vllm-qwen25coder` container (pinned `main-310p-openeuler-stable`, image ID `7d210d233141`): `transformers==4.57.6` has no `Gemma4UnifiedForConditionalGeneration` class at all (`ImportError`), and vLLM's `ModelRegistry` (`vllm==0.17.0`) only recognizes Gemma archs up through `Gemma3n`/`Gemma3ForConditionalGeneration` — no `Gemma4*` entry. This is a hard version gap, not a 310P-specific issue — the pinned stack simply predates this model's release upstream.
- Separately, NPU memory is already saturated by the running Qwen2.5-Coder-14B instance: `npu-smi info` showed ~34GB/44GB and ~34GB/44GB used on chip0/chip1, leaving only ~8-9GB free per chip — not enough to also load Gemma 4 12B's ~12GB-per-chip (TP=2) weights even if the software supported it.
- **Decision:** stopped here rather than chasing an upgrade path (bumping `transformers`/`vllm` in-container risks breaking the working Qwen model, and per the Known Issues table above, every newer `-310p-openeuler` tag tried so far has hit the `triton.language` packaging bug on import). Revisit only if a future `vllm-ascend` release both adds `Gemma4Unified` support AND fixes the 310P triton-shadowing bug (PR #8181 status) — check that first before re-attempting.

### Rolling back to a previous image

```bash
# Pin docker-compose.yml image to working version:
# image: quay.io/ascend/vllm-ascend@sha256:<digest>
# or reference by image ID directly:
docker tag 7d210d233141 quay.io/ascend/vllm-ascend:main-310p-openeuler-stable
# Then update docker-compose.yml to use :main-310p-openeuler-stable
```
