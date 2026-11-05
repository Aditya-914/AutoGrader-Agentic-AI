# Auto-Grading Agent for C Submissions

An agentic AI-powered auto-grading system that evaluates C code submissions against a **mutable JSON rule set**. The agent uses local LLM models (**`qwen2.5-coder:1.5b`**, with native support for **`llama3.1`** and **`llama3.2`** via Ollama) to dynamically generate test cases, adversarial edge cases, reference Python oracles, and readability reviews for **any unseen algorithmic problem**.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  main.py  (CLI entry point)                                            │
│  ├── Phase 1: AutoGraderCoordinator (phase1_coordinator.py)            │
│  │   ├── Load & validate rules JSON (SHA-256 hash, weight sum)         │
│  │   ├── Static sanity checks (main, scanf, printf, return)            │
│  │   ├── Compile check (gcc -O2 -Wall -Wextra -std=c11)               │
│  │   └── Smoke test (sample input, 1s timeout, 64MB cap)              │
│  │                                                                      │
│  └── Phase 2: Phase2Dispatcher (phase2_dispatcher.py)                  │
│      ├── Intelligent routing (skip execution analyzers on fail)        │
│      └── Parallel dispatch of 9 expert analyzers:                      │
│          ├── io_tests          (Dynamic LLM functional tests)          │
│          ├── compiler_warnings (gcc -Wall -Wextra diagnostics)         │
│          ├── static_analysis   (cppcheck + lizard CCN)                 │
│          ├── function_split    (modularity check)                      │
│          ├── edge_case_runner  (LLM-generated adversarial tests)       │
│          ├── complexity_estimator (empirical O(1)/O(N)/O(N^2) check)   │
│          ├── sanitizer_run     (ASan + UBSan memory safety)            │
│          ├── llm_review        (LLM readability scoring)               │
│          └── similarity_flag   (plagiarism detection)                  │
│                                                                         │
│  LLM Engine & Oracle Verifier (llm_test_generator.py)                  │
│  ├── Active Models: qwen2.5-coder:1.5b | llama3.1 | llama3.2 (Ollama)  │
│  ├── Dynamic Problem Oracle Generator (def solve(inp: str) -> str)     │
│  ├── Oracle Self-Verification Gate (verifies solve(sample_in)==sample) │
│  ├── Reflective Self-Correction Loop (repairs failing solvers via LLM) │
│  ├── Intelligent Universal Grammar-Aware Fuzzer (10 varied tests)      │
│  ├── Student Defense Loop (Reality Check Loop)                         │
│  │   ├── Cross-checks LLM allegations against certified Python oracle  │
│  │   ├── Dismisses false counter-claims to defend student submissions   │
│  │   └── Shields students from LLM hallucinations                      │
│  └── Automatic Multi-Factor Cache Invalidation                         │
└────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites & Models

- **Python 3.10+**
- **GCC** (with `-fsanitize=address,undefined` support)
- **cppcheck** (for static analysis)
- **Ollama** running locally on `http://localhost:11434`

### Installed & Supported LLMs:
- **`qwen2.5-coder:1.5b`** (Recommended default: ultra-fast, high-precision code & oracle generation)
- **`llama3.1`** (Supported / aliased)
- **`llama3.2`** (Supported / aliased)

```bash
# Install system dependencies (Fedora / RHEL)
sudo dnf install gcc cppcheck

# Or Ubuntu / Debian
sudo apt install gcc cppcheck

# Start Ollama daemon and pull the model
ollama serve &
ollama pull qwen2.5-coder:1.5b

# Optional: pull llama3.1
ollama pull llama3.1

# Install Python dependencies
pip install -r requirements.txt
```

> **Dynamic Auto-Discovery:** The grading agent automatically checks installed models via `http://localhost:11434/api/tags`. If the rule requests `llama3.1` or `qwen2.5-coder`, the engine will auto-detect and route inference to the best locally available coding model without manual reconfiguration.

## Web Frontend & Dashboard

A zero-dependency web interface and REST API are provided for interactive evaluation, code editing, and real-time grading reports.

### Launching the Frontend:

```bash
# Start server and auto-open in browser (default port 8000)
./run_frontend.sh

# Or run directly with Python:
python3 server.py --open

# Custom port
python3 server.py --port 8080
```

Open **`http://localhost:8000`** in your browser.

### Key Frontend Features:
- 💻 **Simple & Focused 2-Column Studio**: Write or paste C code on the left, click **"Grade My Submission"**, and view your evaluation results immediately on the right with zero tab clutter.
- 🔒 **Fixed Rubric & Problem Specification**: Displays the immutable 9 grading criteria (100% total weight) set by the evaluator so submissions cannot tamper with grading rules.
- ⚡ **Instant Sandbox Runner**: Test code with custom standard input (`stdin`) before grading to verify outputs quickly.
- 📊 **Clear Grade & Verdict**: Prominent score display (e.g. `90.0 / 100`), letter grade badge (`A`, `B`, `C`, `D`, `F`), and evaluation runtime.
- 🛡️ **Student Defense Loop (Reality Check)**: Transparent breakdown of LLM-alleged edge cases that were checked and dismissed against the certified Python reference oracle to defend students from false failure claims.
- ⚠️ **What Failed & How to Improve**: Clean summary of failing test cases with Input, Expected, and Your Output, accompanied by actionable recommendations to raise the grade.
- 📄 **One-Click Export**: Easily download the student-readable text report (`.txt`) or the machine-readable report (`.json`).
- 🌙 **Dark & Light Mode**: Clean engineering theme with instant toggle.

## Quick Start (CLI)

```bash
# Grade a submission with verbose output
python3 main.py rules/add_rules.json submissions/add.c --verbose

# Save report to a file
python3 main.py rules/add_rules.json submissions/add.c --output results/report.json

# Run Phase 1 only (sanity + compile + smoke)
python3 agent/phase1_coordinator.py rules/add_rules.json submissions/add.c
```

## Rules JSON Format

Rules are fully mutable — change weights, add/remove metrics, adjust thresholds:

```json
{
  "problem": "add_two_integers",
  "problem_description": "Read two integers and print their sum...",
  "time_limit_s": 1,
  "memory_limit_mb": 64,
  "sample_input": "7 5\n",
  "llm_config": {
    "model": "qwen2.5-coder:1.5b",
    "temperature": 0,
    "seed": 42
  },
  "metrics": [
    {
      "name": "correctness",
      "analyzer": "io_tests",
      "weight": 0.20,
      "params": { "testset_dir": "tests/add/", "auto_generate": true, "num_tests": 10 }
    }
  ]
}
```

**Weights must sum to 1.00.** Each metric's contribution = `score × weight × 100`.

## Output Report

The grading report is a structured JSON with:
- `grade`: Final score out of 100
- `first_pass`: Compilation and smoke test results
- `metrics[]`: Per-analyzer scores, evidence, and feedback
- `flags[]`: Special alerts (infinite loop, plagiarism, etc.)

## Project Structure

```
Agentic AI/
├── main.py                    # CLI entry point
├── server.py                  # Zero-dependency HTTP server & REST API
├── run_frontend.sh            # Quick launcher script for frontend
├── requirements.txt           # Python dependencies
├── frontend/                  # Web dashboard SPA
│   ├── index.html             # Single-page application HTML
│   ├── css/
│   │   └── style.css          # Engineering dark/light design system
│   └── js/
│       ├── app.js             # State management, API clients, UI bindings
│       └── editor.js          # Code editor with line numbers & indentation
├── agent/
│   ├── __init__.py
│   ├── phase1_coordinator.py  # Phase 1: sanity, compile, smoke test
│   ├── phase2_dispatcher.py   # Phase 2: parallel analyzer dispatch
│   ├── analyzers.py           # 9 expert analyzer implementations
│   ├── llm_test_generator.py  # LLM-powered test case generation
│   └── report_generator.py    # JSON & student text report formatter
├── rules/
│   └── add_rules.json         # Mutable grading rules configuration
├── submissions/               # C submission files
│   ├── add.c                  # Naive submission (fails overflow)
│   ├── add_safe.c             # Modular 64-bit safe submission
│   ├── infinite_loop.c        # Infinite loop test case
│   └── syntax_error.c         # Compiler failure test case
├── tests/                     # Auto-generated & cached test cases
│   └── add/
│       ├── 01.in / 01.out
│       └── ...
└── reports/                   # Generated evaluation reports
    ├── add.json / add.txt
    └── add_safe.json / add_safe.txt
```
