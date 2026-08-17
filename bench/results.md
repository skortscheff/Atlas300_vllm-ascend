# Benchmark Results

Reproducible measurements from `bench/run_bench.py` against the live vLLM
endpoint (`http://localhost:8002/v1`). Each run records single-stream tok/s,
coding pass@1 (10 small problems executed against known asserts), and whether
tool-calling populates the `tool_calls` array.

Run: `python3 bench/run_bench.py --label "<what changed>"`

## 2026-07-09 20:13:31 — prefix-caching+chunked-prefill+tool-calling baseline (2026-07-09)
- model: `Qwen2.5-Coder-14B-Instruct-abliterated`  sampling: `server-default`
- **single-stream: 9.61 tok/s** (min 9.57, max 9.62); concurrent-8: 43.81 tok/s
- **coding pass@1: 10/10** (1.0)
- tool-calls: ❌ not populated — '<tools>\n{\n  "name": "get_weather",\n  "arguments": {\n    "location": "Paris"\n  }\n}\n</tools>'

## 2026-07-15 16:48:18 — post driver/firmware upgrade 25.3.rc1
- model: `Qwen2.5-Coder-14B-Instruct-abliterated`  sampling: `server-default`
- **single-stream: 9.53 tok/s** (min 9.51, max 9.55); concurrent-8: 61.31 tok/s
- **coding pass@1: 10/10** (1.0)
- tool-calls: ❌ not populated — '<tools>\n{\n  "name": "get_weather",\n  "arguments": {\n    "location": "Paris"\n  }\n}\n</tools>'

## 2026-07-15 20:09:07 — POC image ACLGraph non-eager test (dense 14B)
- model: `Qwen2.5-Coder-14B-Instruct-abliterated`  sampling: `server-default`
- **single-stream: 11.26 tok/s** (min 11.24, max 11.27); concurrent-8: 58.88 tok/s
- **coding pass@1: 10/10** (1.0)
- tool-calls: ❌ not populated — 'HTTP Error 400: Bad Request'

## 2026-07-21 18:08:20 — v0.23.0rc1 Qwen3.5-35B-A3B-w8a8-mtp triton-stub-removed
- model: `qwen3.5`  sampling: `server-default`
- **single-stream: 29.62 tok/s** (min 29.45, max 29.67); concurrent-8: 43.24 tok/s
- **coding pass@1: 1/10** (0.1)
  - failures: is_prime: FAIL, fizzbuzz: FAIL, two_sum: FAIL, gcd: FAIL, flatten: FAIL, count_vowels: FAIL, merge_sorted: FAIL, anagram: FAIL, roman: FAIL
- tool-calls: ❌ not populated — 'HTTP Error 400: Bad Request'

## 2026-07-21 20:57:15 — Qwen3.6-35B-A3B bf16->fp16, v0.23.0rc1, triton-stub-removed, maxlen4096
- model: `qwen3.6`  sampling: `server-default`
- **single-stream: 28.62 tok/s** (min 28.49, max 28.77); concurrent-8: 44.1 tok/s
- **coding pass@1: 0/10** (0.0)
  - failures: reverse_string: FAIL, is_prime: FAIL, fizzbuzz: FAIL, two_sum: FAIL, gcd: FAIL, flatten: FAIL, count_vowels: FAIL, merge_sorted: FAIL, anagram: FAIL, roman: FAIL
- tool-calls: ❌ not populated — 'HTTP Error 400: Bad Request'

## 2026-08-04 16:44:36 — nightly-releases-v0.25.1rc-310p-openeuler, triton-stub-removed, dense Qwen2.5-Coder-14B
- model: `Qwen2.5-Coder-14B-Instruct-abliterated`  sampling: `server-default`
- **single-stream: 10.74 tok/s** (min 10.7, max 10.76); concurrent-8: 67.62 tok/s
- **coding pass@1: 10/10** (1.0)
- tool-calls: ❌ not populated — '<tools>\n{\n  "name": "get_weather",\n  "arguments": {\n    "location": "Paris"\n  }\n}\n</tools>'

## 2026-08-04 16:53:36 — nightly-releases-v0.25.1rc-310p-openeuler, ACLGraph FULL_DECODE_ONLY, dense Qwen2.5-Coder-14B, maxlen16384
- model: `Qwen2.5-Coder-14B-Instruct-abliterated`  sampling: `server-default`
- **single-stream: 11.15 tok/s** (min 11.09, max 11.16); concurrent-8: 65.47 tok/s
- **coding pass@1: 10/10** (1.0)
- tool-calls: ❌ not populated — '<tools>\n{\n  "name": "get_weather",\n  "arguments": {\n    "location": "Paris"\n  }\n}\n</tools>'

## 2026-08-17 17:17:05 — v0.23.0-stable-vs-rc1
- model: `qwen3.6-moe`  sampling: `server-default`
- **single-stream: 27.04 tok/s** (min 26.21, max 27.14); concurrent-8: 40.67 tok/s
- **coding pass@1: 0/10** (0.0)
  - failures: reverse_string: FAIL, is_prime: FAIL, fizzbuzz: FAIL, two_sum: FAIL, gcd: FAIL, flatten: FAIL, count_vowels: FAIL, merge_sorted: FAIL, anagram: FAIL, roman: FAIL
- tool-calls: ❌ not populated — ''

## 2026-08-17 17:36:52 — w8a8-v0.23.0stable-24576ctx
- model: `qwen3.6-w8a8`  sampling: `server-default`
- **single-stream: 31.08 tok/s** (min 30.98, max 31.13); concurrent-8: 39.44 tok/s
- **coding pass@1: 1/10** (0.1)
  - failures: is_prime: FAIL, fizzbuzz: FAIL, two_sum: FAIL, gcd: FAIL, flatten: FAIL, count_vowels: FAIL, merge_sorted: FAIL, anagram: FAIL, roman: FAIL
- tool-calls: ✅ populated — get_weather({"location": "Paris"})
