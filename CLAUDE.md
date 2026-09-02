# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Baseline date: 2026-09-02.** Prior investigation history (months of model/image testing) has been dropped from this file — treat the state described here as the starting point. Git history still has the old file if any of that context is ever needed.

## What This Is

A Docker Compose deployment for LLM inference on Ascend NPU hardware. Three services:
- **vLLM** (`quay.io/ascend/vllm-ascend`) — serves the model on port 8002
- **Open WebUI** (`ghcr.io/open-webui/open-webui:latest`) — chat UI on port 3000
- **SearXNG** (`docker.io/searxng/searxng:latest`) — self-hosted meta-search engine on port 8080, gives Open WebUI web search

## ⚠️ Production Setup — always revertible to this state

| Component | Pinned value |
|---|---|
| vLLM image | `quay.io/ascend/vllm-ascend:v0.23.0-310p-openeuler`, with the triton-stub-removal workaround baked into the Compose entrypoint (`mv .../site-packages/triton .../site-packages/triton.disabled` before `vllm serve`) |
| Model | `Huihui-Qwen3.8-27B-abliterated` (bf16 cast to float16 at load) at `${MODELS_DIR}/Huihui-Qwen3.8-27B-abliterated` (52GB), served as `qwen3.8-27b` |
| vLLM command | see `vllm-qwen36moe` service in `docker-compose.yml` — `--dtype float16 --enforce-eager --tensor-parallel-size 2 --max-model-len 16384 --max-num-seqs 16 --gpu-memory-utilization 0.90`, `--enable-prefix-caching --enable-chunked-prefill --max-num-batched-tokens 16384`, `--mamba-ssm-cache-dtype float16`, `--reasoning-parser qwen3`, `--enable-auto-tool-choice --tool-call-parser qwen3_coder`, `--override-generation-config '{"temperature": 0.2, "repetition_penalty": 1.1}'` |
| Ports | vLLM 8002, Open WebUI 3000, SearXNG 8080 |
| Driver/firmware | 25.3.rc1 / 7.8.0.2.212 |
| Context | 16384, deliberately capped below what's technically feasible (32768 works fine in `--enforce-eager` mode) to leave memory headroom |

**Deliberate accuracy-over-throughput trade:** single-stream speed is ~5.9 tok/s — slow relative to what a quantized MoE model can do on this hardware — because this architecture requires `--enforce-eager` (ACLGraph crashes on it, error 507903) and is dense-ish rather than MoE. Chosen for a clean 10/10 pass@1 on the standard coding benchmark, with zero mitigation needed beyond the sampling override.

**Facts about this deployment worth knowing before changing anything:**
- **310P does not support bf16 at the hardware op level** — always load with `--dtype float16`, even for a checkpoint whose native weights are bf16.
- **This vLLM image's bundled `triton` package is a broken empty stub** — `import triton` succeeds but crashes the instant anything touches it, breaking vLLM at import time. The fix is renaming it out of the way before `vllm serve` runs (already baked into the `vllm-qwen36moe` entrypoint in `docker-compose.yml`). Any new/updated image needs this same workaround.
- **`--enforce-eager` is mandatory for this model's architecture** (hybrid linear+full-attention) — ACLGraph graph-capture crashes with `AclmdlRICaptureEnd`/error 507903 regardless of quantization.
- **`--override-generation-config` with `temperature: 0.2, repetition_penalty: 1.1` is required, not optional** — this model family's shipped defaults (`temperature: 1.0`, no repetition penalty) allow a reasoning-non-termination failure mode (verbose chain-of-thought that never concludes, burning the token budget). The override fixes it cleanly.
- **310P's practical `--max-model-len` ceiling is architecture/memory dependent, not just a KV-cache-size calculation** — larger context also needs larger ACLGraph/compile-workspace memory that can OOM even when the KV-cache pool math looks fine. Push incrementally and verify, don't just trust the startup log's KV-cache-size line.

**To revert to this state from any experiment:**
```bash
docker compose --profile prod down     # or: docker stop <any-test-container> && docker rm <any-test-container>
docker compose --profile qwen36 up -d --force-recreate  # brings back vllm-qwen36moe + openwebui + searxng exactly as pinned above
# verify:
docker inspect vllm-qwen36moe --format '{{.Config.Image}}'   # must print v0.23.0-310p-openeuler
docker exec vllm-qwen36moe python3 -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://localhost:8000/v1/models')); print(d['data'][0]['id'], d['data'][0]['max_model_len'])"  # must show qwen3.8-27b 16384
```
**Use `--force-recreate` when bringing `vllm-qwen36moe` back up** — its entrypoint does a one-time `mv .../triton .../triton.disabled` that isn't idempotent; reusing a stopped container's filesystem layer makes that `mv` fail and the container crash-loop.

**Any experimental image/model test (new vllm-ascend tags, alternative inference engines, other models) must be done standalone on a different port (e.g. 8003), never by editing `docker-compose.yml` in place**, and production must be restored to exactly this state afterward.

**Note:** `docker-compose.yml` uses Compose profiles (`prod` vs `qwen36`) to let two vLLM services share port 8002 and NPU devices without both trying to run at once. Plain `docker compose up -d` with no `--profile` flag starts **only** `openwebui` and `searxng` — a vLLM profile must always be specified explicitly.

## Models on disk

| Path | Size | Role |
|---|---|---|
| `${MODELS_DIR}/Huihui-Qwen3.8-27B-abliterated` | 52GB | **Current production** (`qwen36` profile — profile name kept from a prior model generation, not renamed) |
| `${MODELS_DIR}/Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` | 38GB | Prior production pin (abliterated, self-quantized w8a8 MoE), kept as a documented rollback if the current model's ~5.9 tok/s proves too slow — ~31 tok/s single-stream, probabilistic 6-7/10 pass@1 (reasoning-non-termination bug ~30-40% of tasks) |
| `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct-abliterated` | 28GB | Dense fp16 baseline, still used by the `prod` profile fallback — 32768 context, ~9.5-10.7 tok/s, tool-calling not populated |
| `${MODELS_DIR}/Qwen3.6-35B-A3B-w8a8` | 38GB* | Official (non-abliterated) w8a8 quant — declined, not wired into any profile |

\* Pending deletion — see Housekeeping below.

### Switching profiles

Open WebUI and SearXNG always stay up; only the vLLM service changes via `--profile`. Both vLLM services publish themselves under the same network alias (`vllm-backend`), so Open WebUI's `OPENAI_API_BASE_URLS` never needs to change.

```bash
# Switch to the dense Qwen2.5-Coder-14B alternative:
docker compose --profile qwen36 down
docker compose --profile prod up -d

# Switch back to production (Qwen3.8-27B):
docker compose --profile prod down
docker compose --profile qwen36 up -d --force-recreate

# Verify which is active:
docker exec vllm-qwen36moe python3 -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/v1/models'))['data'][0]['id'])"
# or, if vllm-qwen25coder is active:
docker exec vllm-qwen25coder python3 -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/v1/models'))['data'][0]['id'])"
```

## Common Commands

```bash
# Start production (Qwen3.8-27B) — also brings up openwebui and searxng
docker compose --profile qwen36 up -d

# Start the dense Qwen2.5-Coder-14B alternative instead
docker compose --profile prod up -d

# Stop everything (add --profile prod or --profile qwen36 to target just the active vLLM service)
docker compose --profile prod --profile qwen36 down

# View logs
docker compose logs -f vllm-qwen36moe    # or vllm-qwen25coder, depending on active profile
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

**Hardware:** 1× Atlas 300I Duo card (`/dev/davinci0`, `/dev/davinci1` — 2 chips on one card, bus `0000:86:00.0`, both `OK` per `npu-smi`). `--tensor-parallel-size 2` matches the 2 chips.

**Driver mounts** (host paths that must exist):
- `/usr/local/dcmi`
- `/usr/local/bin/npu-smi`
- `/usr/local/Ascend/driver/lib64`
- `/usr/local/Ascend/driver/version.info`
- `/etc/ascend_install.info`

**Volumes:** Models are bind mounts at `${MODELS_DIR}` → `/models`. `vllm-cache` is a named Docker volume. `openwebui-data/` and `searxng/` are bind mounts in the project directory.

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

Open WebUI's web search feature is backed by a self-hosted SearXNG instance (container `searxng`, port 8080, on the `llmnet` network). No external API key, no third-party search API dependency.

**Config files:**
- `searxng/settings.yml` — mounted read-write into the container at `/etc/searxng`. Key settings: `search.formats` includes `json` (required — Open WebUI's backend calls SearXNG's JSON API, not the HTML UI), `server.limiter: false` (safe since this instance is internal-only), `server.secret_key` (low-sensitivity, used only for SearXNG's own session/CSRF signing).
- `openwebui` service env vars in `docker-compose.yml`: `ENABLE_RAG_WEB_SEARCH=true`, `WEB_SEARCH_ENGINE=searxng`, `SEARXNG_QUERY_URL=http://searxng:8080/search?q=<query>`.

**Important gotcha: Open WebUI persists config in its database, not just env vars.** Once `openwebui-data/webui.db` exists, Open WebUI reads settings from the DB's `config` table on every boot; env vars only seed a brand-new/empty DB, they do **not** override an already-persisted value. If web search stops working after any future Open WebUI config change, check the DB directly first:

```bash
docker exec openwebui python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
cur = conn.cursor()
cur.execute(\"SELECT key, value FROM config WHERE key LIKE 'web.search%'\")
for r in cur.fetchall(): print(r)
"
```

To force it on directly:
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

**Verifying it's working:**
```bash
curl -s "http://localhost:8080/search?q=test&format=json" | head -c 300
docker exec openwebui curl -s "http://searxng:8080/search?q=test&format=json" | head -c 300
```
A web-search toggle (globe icon) appears in the Open WebUI chat input box once correctly enabled — a hard browser refresh may be needed after a backend config change.

**Known limitation:** `wikidata` (one of SearXNG's built-in engines) fails to initialize with an HTTP 403 in the container logs on every boot — expected/cosmetic, other engines still work fine.

## LAN API Access

The vLLM API is OpenAI-compatible and reachable from any machine on the LAN. `ufw` is inactive on this host — no firewall rules needed.

| Endpoint | URL |
|---------|-----|
| LAN | `http://<HOST_IP>:8002/v1` |

No API key required. See `guia-api.md` for a full usage guide (Spanish) with curl, Python, and JavaScript examples.

## Deployment Notes

- NPU devices on this host are `/dev/davinci0` and `/dev/davinci1`
- Before starting, ensure no other containers are using ports 8002, 3000, or 8080
- vLLM takes a couple of minutes to load the model; watch for `Application startup complete.` in logs before sending requests

## Performance Baseline (production, 2026-09-01)

Via `bench/run_bench.py` against the live API, model `qwen3.8-27b`:

| Metric | Value |
|--------|-------|
| Single-stream throughput | ~5.9 tok/s |
| Concurrent-8 throughput | ~29.6-31.6 tok/s |
| Coding pass@1 | 10/10 (1.0), with the sampling override in place |
| Tool-calls populated | ✅ Yes |

Re-run after any config change: `python3 bench/run_bench.py --label "<what changed>"`. Full run history in `bench/results.md`.

The `prod` profile (dense Qwen2.5-Coder-14B) baseline: ~9.5-10.7 tok/s single-stream, ~61-68 tok/s concurrent-8, 10/10 pass@1, tool-calling **not** populated (known model/template limitation, not a vLLM config issue).

## Housekeeping (2026-09-02)

Disk cleanup pass: removed ~30 dead/superseded Docker images (vllm-ascend/CANN test builds, an abandoned Huawei POC image, gpt-oss and MindIE remnants) and several declined/superseded model checkpoints, freeing ~385GB (736G → 351G used on `/`). Docker images went from 120 (335.9GB) to 42 (94.55GB).

**Still pending:** two root-owned directories need manual `sudo rm` (not run yet):
```bash
sudo rm -rf /home/skortscheff/Models/Qwen3.6-35B-A3B-w8a8 /home/skortscheff/Models/Huihui-Qwen3.8-27B-abliterated-w8a8
```
(38GB — the declined official non-abliterated w8a8 Qwen3.6 checkpoint, plus an 8KB stray leftover from an abandoned quantization attempt.)

**Kept despite being a "test" image:** `nightly-releases-v0.25.1rc-310p-openeuler` — still relevant to an open question (see below).

## Open items

1. Real soak test of the current production config under sustained multi-turn Open WebUI usage — only bench-harness runs and manual canary requests have been done so far.
2. If ~5.9 tok/s proves too slow in practice, the w8a8 Qwen3.6 MoE model (~31 tok/s, on disk) is the documented rollback — see "Production Setup" above.
3. Whether to repin the `prod` profile (dense Qwen2.5-Coder-14B, still on `main-310p-openeuler-stable`) to `nightly-releases-v0.25.1rc-310p-openeuler` — untested claim from before this baseline reset was a "zero-downside" speed win for that model; needs re-verification, not assumed still true.
4. Run the pending `sudo rm` above once convenient.
