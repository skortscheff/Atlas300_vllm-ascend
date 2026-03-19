# Changelog

All notable changes to this project are documented here.

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
