# Implementation Plan & Progress Report (`agentic01`)

**Project**: AutoGrader: A Rule-Driven Evaluator for C Programs  
**Repository**: Agentic AI AutoGrader  
**Date**: October 2026  

---

## 1. Executive Summary

We have designed and implemented an autonomous, rule-driven auto-grading agent for student C program submissions. The system evaluates submissions across 9 independent metrics governed by an external mutable JSON rules configuration, utilizing sandboxed execution, static code analyzers, and local LLMs (`llama3.1` via Ollama) for intelligent test generation and code quality assessment.

---

## 2. Implementation Architecture & Progress So Far

### 2.1 Completed Modules

| Component | Module | Status | Description |
|-----------|--------|--------|-------------|
| **Phase 1: Coordinator** | [`agent/phase1_coordinator.py`](agent/phase1_coordinator.py) | **Completed** | Validates rules JSON (SHA-256 integrity, 1.00 weight sum), runs static sanity checks (main, reader, writer, return), performs sandboxed compilation, and executes smoke test with resource limits (`RLIMIT_AS`, `RLIMIT_CPU`). |
| **Phase 2: Parallel Dispatcher** | [`agent/phase2_dispatcher.py`](agent/phase2_dispatcher.py) | **Completed** | Implements intelligent routing (skips execution analyzers on compile/infinite loop failures) and concurrently dispatches all active metrics with per-analyzer timeouts and error boundaries. |
| **Expert Analyzers** | [`agent/analyzers.py`](agent/analyzers.py) | **Completed** | Full suite of 9 analyzers: `io_tests`, `compiler_warnings`, `static_analysis`, `function_split`, `edge_case_runner`, `complexity_estimator`, `sanitizer_run`, `llm_review`, `similarity_flag`. |
| **LLM Test Generator** | [`agent/llm_test_generator.py`](agent/llm_test_generator.py) | **Completed** | Interfaces with local Ollama (`llama3.1`) to dynamically synthesize standard test suites, adversarial edge cases, and python reference solver oracles. Implements the **Student Defense Reality Check Loop** to filter out LLM hallucinations before grading. |
| **Report Generation** | [`agent/report_generator.py`](agent/report_generator.py) | **Completed** | Outputs machine-readable JSON (`reports/add.json`) and human-readable student feedback (`reports/add.txt`) with failing inputs, expected outputs, actionable suggestions, and tool versions. |
| **CLI & Automation** | [`main.py`](main.py) | **Completed** | Unattended end-to-end execution script with progress logging, timing, and automated report storage. |

### 2.2 Verified Results on Sample Submission (`submissions/add.c`)
- **Overall Grade**: 74.7 / 100
- **Execution Time**: ~0.3s (cached) / ~20s (first-time dynamic generation)
- **Detected Flaws**:
  1. Signed 32-bit integer overflow on `2147483647 + 1` and `-2147483648 + (-1)`
  2. Single-block code without modular helper functions
  3. Single-letter variables and absence of explanatory comments

---

## 3. Workload Distribution Among Group Members

*(For groups of up to 4 members)*

| Member Name | Role | Primary Responsibilities |
|-------------|------|--------------------------|
| **Member 1** | **System Architecture & Sandbox Lead** | Process containment, resource limits (`setrlimit`), Phase 1 sanity coordinator, infinite loop detection, and process group lifecycle management. |
| **Member 2** | **Static Analysis & Tooling Specialist** | Compiler diagnostics (`gcc -Wall -Wextra`), AST metrics (`lizard` cyclomatic complexity), defect scanning (`cppcheck`), and memory sanitizers (ASan/UBSan). |
| **Member 3** | **LLM & Adversarial Testing Lead** | Ollama integration, prompt engineering for test synthesis, adversarial corner-case generation, Python reference solver oracles, and automated fallbacks. |
| **Member 4** | **Dispatcher, Evaluation & Report Lead** | Multithreaded Phase 2 dispatcher, plagiarism/token similarity detection, report generation (JSON/text collation), documentation, and benchmark validation. |

---

## 4. Usefulness & Limitations (Real-Life Analysis)

### 4.1 Usefulness in Real-Life Settings
1. **Automated Hiring & Screening**: Fast first-round candidate filtering on low-level coding tasks with per-metric explainability.
2. **Plagiarism & AI-Code Triage**: Flags high-similarity code (>0.85 threshold) so instructors inspect only suspicious submissions.
3. **Continuous Formative Feedback**: Enables lab students to iterate against compiler, sanitizer, and corner-case feedback before grading.
4. **CI/CD Security Gate**: Prevents undefined behavior (overflows, memory leaks) from entering production C repositories.

### 4.2 Limitations & Concrete Failure Modes
1. **Tests Cannot Prove Correctness**: A submission can pass all 10 tests but fail on unexpected whitespace formatting.
2. **Heuristics Can Be Gamed**: Dummy unused helper functions can inflate modularity scores without true architectural decomposition.
3. **Empirical Timing Curve Flakiness**: System noise or server paging can cause an $O(1)$ routine to be misclassified as $O(N)$.
4. **Plagiarism False Positives on Constrained Problems**: Simple 5-line C tasks naturally share high token similarity, risking false flags.

---

## 5. Future Plan & Timeline (4-Week Schedule)

| Week | Phase | Milestone & Objectives |
|------|-------|------------------------|
| **Week 1 (Current)** | **Core Pipeline & First Pass** | Rules validation, Phase 1 coordinator, basic analyzer suite, Ollama test generator, and initial report collation. *(Achieved)* |
| **Week 2** | **Advanced Analyzers & Edge Cases** | Fine-tune sanitizer diagnostics, AST call-graph verification to prevent gaming of modularity, and expand test corpora for similarity checks. |
| **Week 3** | **Hardware Profiling & Robustness** | Add hardware instruction counter profiling (`perf`/`cachegrind`), stress test with fork bombs and recursive crashes, benchmark against 50+ student submissions. |
| **Week 4** | **Final Packaging & Presentation** | Package repository with one-line install script, finalize documentation, record 15-20 minute demonstration video, and submit final deliverables. |
