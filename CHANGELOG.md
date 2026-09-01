# Changelog

All notable changes to this project are documented here.

---

## [v1.16] — 2026-09-01

Summary entry bridging several months of untracked changes — see `CLAUDE.md` for the full
session-by-session narrative and every intermediate experiment. This entry captures where the
stack actually landed, not every step along the way.

### Changed
- **Compose profiles reintroduced** — `prod` (dense `Qwen2.5-Coder-14B-Instruct-abliterated`,
  `main-310p-openeuler-stable`, 32768 context) and `qwen36` (MoE, default production) now coexist
  as mutually-exclusive profiles sharing port 8002 and the NPU devices. Plain `docker compose up -d`
  with no profile only starts `openwebui` and `searxng`.
- **Production model switched to `Huihui-Qwen3.6-35B-A3B-abliterated`** (MoE, `huihui-ai` abliterated
  fork of Qwen3.6) — ~3x faster than the prior dense 14B baseline, with a known reasoning-stability
  fix (`--override-generation-config` temperature/repetition-penalty tuning) baked in server-side.
- **Production requantized to a self-quantized w8a8 checkpoint** of the same abliterated weights
  (built in-house with `msmodelslim`, since no community abliterated w8a8 release exists) —
  `--max-model-len` raised 16384 → 24576, `--quantization ascend` added, weight footprint halved.
- **vLLM image repinned** `main-310p-openeuler-stable` → `v0.23.0-310p-openeuler` (numbered stable
  release) for the `qwen36` profile, using a triton-stub-removal entrypoint workaround for a
  permanent 310P/triton-ascend platform gap (upstream PR #8181, still unmerged).
- **Model host paths renamed** to reflect abliterated/quantized provenance
  (`Qwen2.5-Coder-14B-Instruct` → `-abliterated`, new `Huihui-Qwen3.6-35B-A3B-abliterated-w8a8` path).

### Added
- **SearXNG** — self-hosted meta-search engine (`docker.io/searxng/searxng:latest`, port 8080),
  wired into Open WebUI for web search with no external API key.
- **Tool-calling support** — `--enable-auto-tool-choice --tool-call-parser qwen3_coder` on the
  `qwen36` profile actually populates `message.tool_calls` correctly (the dense `prod` profile's
  tool-calling remains a known non-working issue).
- **Reasoning-content separation** — `--reasoning-parser qwen3` routes chain-of-thought into
  `message.reasoning_content` instead of mixing it into `content`.

### Removed
- `huawei-support-case.md` and `recover-card.sh` — historical hardware-defect investigation for
  the second (now physically removed) Atlas 300I Duo card. Removed from the repo (and purged from
  git history via a history rewrite) because the writeup contained personal contact details and
  hardware serial numbers; no longer actionable since the card is gone.

### Fixed
- **Second Atlas 300I Duo card physically removed** after a confirmed, unresolvable hardware
  defect (firmware never boots, `flag_r=0x0`) — the host now runs a single 2-chip card,
  `--tensor-parallel-size 2` unchanged.

## [v1.14] — 2026-04-05

### Changed
- **Single profile** — removed `qwen35` and all other profiles. Only `qwen25coder` (Qwen2.5-Coder-14B-Instruct, port 8002) remains.
- **Context window** — increased `--max-model-len` and `--max-num-batched-tokens` from 8192 to **32768** tokens (~6 GB KV cache per chip, ~7 GB headroom remaining).
- **Device paths** — updated to `/dev/davinci0` and `/dev/davinci1` (renumbered after reboot; previously `davinci2`/`davinci3`).
- **`ASCEND_VISIBLE_DEVICES`** — updated from `"2,3"` to `"0,1"` to match new device numbering.

### Removed
- `switch.sh` — no longer needed with a single profile.
- `TROUBLESHOOTING-second-card.md` — second card investigation concluded; card remains inactive.
- `qwen35` service and profile — Qwen3.5-27B uses hybrid linear attention (Triton gated LayerNorm) which is not supported by the current vllm-ascend 310P image.

## [v1.15] — 2026-04-21

### Changed
- **Compose startup simplified** — removed Docker Compose `profiles`; the default `docker compose up -d` now starts the working `qwen25coder` stack directly.
- **Absolute model bind mount** — the compose file now mounts `${MODELS_DIR}/Qwen2.5-Coder-14B-Instruct` directly into the container, so model loading is independent of this repository's location.
- **Baseline refreshed** — `WORKING-STATE.md` and `README.md` now reflect the validated 2026-04-21 stack state and benchmark.

### Removed
- `qwen25coder-awq` service — unsupported on Ascend NPU.
- `qwen3` service — obsolete experimental path, not part of the working stack.
- `docker-compose.yml.bak`, `llama-cpp-cann.yml`, `mindie-investigation.md`, and `mindie-config/` — archived experiments removed to keep the repo focused on the working deployment.

### Performance
- OpenAI-compatible API verified on `http://127.0.0.1:8002/v1`
- Generation throughput: `10.95 tok/s` at `311` generated tokens (`47` prompt tokens, `28.394 s`, `Qwen2.5-Coder-14B-Instruct`, float16, TP=2)

---

## [v1.12] — 2026-03-24

### Added
- **Qwen2.5-Coder-14B-Instruct profile** (`qwen25coder`) — third model profile on port 8002. Purpose-built coding model; no reasoning parser required.
- **`switch.sh`** — convenience script to switch between profiles. Stops all model containers, starts the target profile, and toggles Open WebUI model visibility (hides `Qwen3-32B (fast)` when qwen3 is not active).

### Changed
- **Open WebUI connections** now managed via Admin Panel → Settings → Connections (DB-stored). Env var `OPENAI_API_BASE_URLS` is only used on first-run with an empty DB; subsequent changes require updating via the UI or directly in SQLite.
- **README** fully rewritten to reflect multi-profile setup and `switch.sh` usage.

### Removed
- `openai/gpt-oss-20b` profile — model uses MXFP4 quantization which is not supported by the Ascend vLLM backend.

---

## [v1.9] — 2026-03-19

### Added
- **Generation Stats Footer** — Outlet Filter function inserted into `openwebui-data/webui.db` that appends a stats line (`⚡ tok/s · gen tokens · ctx used/max`) to every assistant reply. Reads `usage` from the vLLM response; elapsed time measured via `inlet`/`outlet` hooks. Active globally for all users and models.

---

## [v1.8] — 2026-03-19

### Fixed
- **Reasoning display in Open WebUI** — `--reasoning-parser deepseek_r1` is required on this Ascend build; without it the raw model output is garbled. Removing it was attempted but reverted. The parser routes thinking tokens to `delta.reasoning` and the final answer to `delta.content`.
- **Open WebUI reasoning config** — documented that the **Reasoning** capability toggle must be enabled on the model in Open WebUI Admin → Models for thinking to render as a collapsible block instead of raw text.

### Reverted
- Removal of `--reasoning-parser deepseek_r1` (caused garbled output on Ascend vLLM build)

---

## [v1.6] — 2026-03-19

### Fixed
- **`--compilation-config` deprecation** — changed `{"level":0}` to `{"mode":0}` to eliminate startup warning in vLLM v0.17.0+

### Added
- **`--reasoning-parser deepseek_r1`** — enables vLLM's built-in DeepSeek-R1 reasoning parser. Strips raw `<think>...</think>` chain-of-thought tokens from the chat response; final answer is returned cleanly in `content`, with reasoning available separately in `reasoning_content`. Without this, thinking tokens bled into Open WebUI replies and were truncated mid-thought.

### Updated
- **Open WebUI** — pulled and recreated container with latest image (`ghcr.io/open-webui/open-webui:latest`, 2026-03-19)
- **README.md / CLAUDE.md** — parameters table and key params section updated to reflect both vLLM changes

---

## [v1.5] — initial setup

### Added
- README with full setup and usage documentation
- Hardware/model selection rationale (32B float16 fits in ~87 GB HBM across 2× Ascend 310P)
- NPU device mapping notes (`/dev/davinci2`, `/dev/davinci3`)

---

## [v1.0] — initial commit

### Added
- `docker-compose.yml` with vLLM (Ascend fork) + Open WebUI services
- vLLM serving `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` on port 8000
- Open WebUI on port 3000, connected to vLLM via internal `llmnet` bridge
- Named volumes `hf-cache` and `vllm-cache` for persistent model/compilation caching
- Ascend NPU driver bind mounts
