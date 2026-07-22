#!/usr/bin/env python3
"""
Benchmark harness for the vllm-atlas stack (Qwen2.5-Coder-14B on Ascend 310P).

Measures three things against the live OpenAI-compatible endpoint:
  1. Throughput   - single-stream tok/s (+ a small concurrent run for context)
  2. Accuracy     - pass@1 on a fixed set of small coding problems (code is
                    executed in a subprocess sandbox against known asserts)
  3. Tool calling - whether a function-calling request populates the
                    `tool_calls` array (vs leaking raw <tools> text into content)

Stdlib only (urllib) - the environment's curl hook redirects, so we avoid curl.
Run with vLLM already serving. Append results to bench/results.md via --label.

Usage:
  python3 run_bench.py --label "baseline fp16 eager"
  python3 run_bench.py --model Qwen2.5-Coder-14B-Instruct-abliterated \
      --temperature 0 --label "greedy"
  python3 run_bench.py --only throughput   # subset: throughput|accuracy|tools
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:8002/v1"
DEFAULT_MODEL = "Qwen2.5-Coder-14B-Instruct-abliterated"

# --- Throughput prompts (kept short, ~CLAUDE.md baseline style) -------------
THROUGHPUT_PROMPTS = [
    "Write a Python function that returns the nth Fibonacci number iteratively.",
    "Explain what a hash map is and give a short Python example.",
    "Write a function to check whether a string is a palindrome.",
    "Implement binary search over a sorted list in Python.",
]

# --- Coding accuracy tasks (pass@1) -----------------------------------------
# Each task: the model is asked to implement `entry_point`; `test` is appended
# to the returned code and the whole thing is run. Exit 0 == pass.
CODING_TASKS = [
    {
        "name": "reverse_string",
        "prompt": "Write a Python function `reverse_string(s)` that returns the reversed string. Respond with only the function in a python code block.",
        "test": "assert reverse_string('abc') == 'cba'\nassert reverse_string('') == ''\nassert reverse_string('a') == 'a'",
    },
    {
        "name": "is_prime",
        "prompt": "Write a Python function `is_prime(n)` that returns True if n is prime, else False. Respond with only the function in a python code block.",
        "test": "assert is_prime(2) and is_prime(13)\nassert not is_prime(1) and not is_prime(15) and not is_prime(0)",
    },
    {
        "name": "fizzbuzz",
        "prompt": "Write a Python function `fizzbuzz(n)` returning a list of strings for 1..n with 'Fizz'/'Buzz'/'FizzBuzz' rules, numbers as strings otherwise. Respond with only the function in a python code block.",
        "test": "assert fizzbuzz(5) == ['1','2','Fizz','4','Buzz']\nassert fizzbuzz(15)[-1] == 'FizzBuzz'",
    },
    {
        "name": "two_sum",
        "prompt": "Write a Python function `two_sum(nums, target)` returning indices of the two numbers that add up to target. Respond with only the function in a python code block.",
        "test": "r = two_sum([2,7,11,15], 9)\nassert sorted(r) == [0,1]",
    },
    {
        "name": "gcd",
        "prompt": "Write a Python function `gcd(a, b)` computing the greatest common divisor. Respond with only the function in a python code block.",
        "test": "assert gcd(12, 8) == 4\nassert gcd(17, 5) == 1\nassert gcd(0, 5) == 5",
    },
    {
        "name": "flatten",
        "prompt": "Write a Python function `flatten(nested)` that flattens an arbitrarily nested list of integers into a flat list. Respond with only the function in a python code block.",
        "test": "assert flatten([1,[2,[3,4]],5]) == [1,2,3,4,5]\nassert flatten([]) == []",
    },
    {
        "name": "count_vowels",
        "prompt": "Write a Python function `count_vowels(s)` returning the number of vowels (aeiou, case-insensitive) in s. Respond with only the function in a python code block.",
        "test": "assert count_vowels('Hello') == 2\nassert count_vowels('xyz') == 0\nassert count_vowels('AEIOU') == 5",
    },
    {
        "name": "merge_sorted",
        "prompt": "Write a Python function `merge_sorted(a, b)` that merges two sorted lists into one sorted list. Respond with only the function in a python code block.",
        "test": "assert merge_sorted([1,3,5],[2,4,6]) == [1,2,3,4,5,6]\nassert merge_sorted([],[1]) == [1]",
    },
    {
        "name": "anagram",
        "prompt": "Write a Python function `is_anagram(a, b)` returning True if a and b are anagrams (ignoring case and spaces). Respond with only the function in a python code block.",
        "test": "assert is_anagram('Listen','Silent')\nassert not is_anagram('abc','abd')",
    },
    {
        "name": "roman",
        "prompt": "Write a Python function `to_roman(n)` converting an integer 1..3999 to a Roman numeral string. Respond with only the function in a python code block.",
        "test": "assert to_roman(4) == 'IV'\nassert to_roman(9) == 'IX'\nassert to_roman(58) == 'LVIII'\nassert to_roman(1994) == 'MCMXCIV'",
    },
]

WEATHER_TOOL = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    },
}]


def chat(base_url, model, messages, tools=None, temperature=None, top_p=None,
         top_k=None, max_tokens=512, timeout=180):
    """POST /chat/completions. Returns (response_dict, elapsed_seconds)."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools is not None:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if temperature is not None:
        body["temperature"] = temperature
    if top_p is not None:
        body["top_p"] = top_p
    if top_k is not None:
        body["top_k"] = top_k
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=data, headers={"Content-Type": "application/json"},
    )
    start = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read())
    return out, time.time() - start


def extract_code(text):
    """Pull python from a ```python ... ``` fence, else return text as-is."""
    if "```" not in text:
        return text
    parts = text.split("```")
    # fenced blocks are odd-indexed
    for i in range(1, len(parts), 2):
        block = parts[i]
        if block.startswith("python"):
            block = block[len("python"):]
        elif block.startswith("py"):
            block = block[len("py"):]
        return block.strip()
    return text


def run_code(code, test, timeout=15):
    """Run code + test in a subprocess. Return True if exit 0."""
    script = code + "\n\n" + test + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True,
                           timeout=timeout)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    finally:
        os.unlink(path)


def bench_throughput(base_url, model, sp, runs=3):
    """Single-stream tok/s averaged over prompts*runs, + 8-way concurrent."""
    toks, secs = 0, 0.0
    per = []
    for _ in range(runs):
        for p in THROUGHPUT_PROMPTS:
            out, dt = chat(base_url, model, [{"role": "user", "content": p}],
                          max_tokens=256, **sp)
            ct = out["usage"]["completion_tokens"]
            toks += ct
            secs += dt
            per.append(ct / dt if dt else 0)
    single = toks / secs if secs else 0

    # concurrent: 8 identical requests at once, wall-clock aggregate tok/s
    conc_n = 8
    prompt = THROUGHPUT_PROMPTS[0]
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=conc_n) as ex:
        futs = [ex.submit(chat, base_url, model,
                          [{"role": "user", "content": prompt}], None,
                          sp.get("temperature"), sp.get("top_p"),
                          sp.get("top_k"), 256) for _ in range(conc_n)]
        results = [f.result() for f in futs]
    wall = time.time() - start
    conc_toks = sum(o["usage"]["completion_tokens"] for o, _ in results)
    concurrent_tps = conc_toks / wall if wall else 0

    return {
        "single_stream_tps": round(single, 2),
        "single_min_tps": round(min(per), 2),
        "single_max_tps": round(max(per), 2),
        "concurrent8_tps": round(concurrent_tps, 2),
        "total_completion_tokens": toks,
    }


def bench_accuracy(base_url, model, sp):
    passed, details = 0, []
    for task in CODING_TASKS:
        try:
            out, _ = chat(base_url, model,
                         [{"role": "user", "content": task["prompt"]}],
                         max_tokens=512, **sp)
            content = out["choices"][0]["message"]["content"] or ""
            ok = run_code(extract_code(content), task["test"])
        except Exception as e:
            ok = False
            details.append(f"{task['name']}: ERROR {e}")
        if ok:
            passed += 1
        else:
            details.append(f"{task['name']}: FAIL")
    return {
        "pass_at_1": f"{passed}/{len(CODING_TASKS)}",
        "pass_rate": round(passed / len(CODING_TASKS), 3),
        "failures": details,
    }


def bench_tools(base_url, model, sp):
    try:
        out, _ = chat(base_url, model,
                     [{"role": "user", "content": "What is the weather in Paris?"}],
                     tools=WEATHER_TOOL, max_tokens=256, **sp)
        msg = out["choices"][0]["message"]
        tc = msg.get("tool_calls") or []
        content = msg.get("content") or ""
        if tc:
            fn = tc[0].get("function", {})
            return {"tool_calls_populated": True,
                    "called": fn.get("name"),
                    "arguments": fn.get("arguments")}
        return {"tool_calls_populated": False,
                "leaked_content": content[:200]}
    except Exception as e:
        return {"tool_calls_populated": False, "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--label", default="unlabeled",
                    help="run label recorded in results.md")
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--top-p", type=float, default=None)
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", choices=["throughput", "accuracy", "tools"],
                    default=None, help="run only one section")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                   "results.md"))
    args = ap.parse_args()

    sp = {}
    if args.temperature is not None:
        sp["temperature"] = args.temperature
    if args.top_p is not None:
        sp["top_p"] = args.top_p
    if args.top_k is not None:
        sp["top_k"] = args.top_k

    result = {"label": args.label, "model": args.model, "sampling": sp or "server-default"}
    sections = [args.only] if args.only else ["throughput", "accuracy", "tools"]

    if "throughput" in sections:
        print("== throughput ==", file=sys.stderr)
        result["throughput"] = bench_throughput(args.base_url, args.model, sp, args.runs)
        print(json.dumps(result["throughput"], indent=2), file=sys.stderr)
    if "accuracy" in sections:
        print("== accuracy ==", file=sys.stderr)
        result["accuracy"] = bench_accuracy(args.base_url, args.model, sp)
        print(json.dumps(result["accuracy"], indent=2), file=sys.stderr)
    if "tools" in sections:
        print("== tools ==", file=sys.stderr)
        result["tools"] = bench_tools(args.base_url, args.model, sp)
        print(json.dumps(result["tools"], indent=2), file=sys.stderr)

    # Append a compact record to results.md
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(args.out, "a") as f:
        f.write(f"\n## {ts} — {args.label}\n")
        f.write(f"- model: `{args.model}`  sampling: `{sp or 'server-default'}`\n")
        if "throughput" in result:
            t = result["throughput"]
            f.write(f"- **single-stream: {t['single_stream_tps']} tok/s** "
                    f"(min {t['single_min_tps']}, max {t['single_max_tps']}); "
                    f"concurrent-8: {t['concurrent8_tps']} tok/s\n")
        if "accuracy" in result:
            a = result["accuracy"]
            f.write(f"- **coding pass@1: {a['pass_at_1']}** ({a['pass_rate']})\n")
            if a["failures"]:
                f.write(f"  - failures: {', '.join(a['failures'])}\n")
        if "tools" in result:
            tl = result["tools"]
            if tl.get("tool_calls_populated"):
                f.write(f"- tool-calls: ✅ populated — {tl.get('called')}({tl.get('arguments')})\n")
            else:
                f.write(f"- tool-calls: ❌ not populated — {tl.get('leaked_content', tl.get('error',''))!r}\n")

    print(f"\nAppended results to {args.out}", file=sys.stderr)
    print(json.dumps(result))  # machine-readable to stdout


if __name__ == "__main__":
    main()
