# Changelog

All notable changes to this project are documented here.

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
