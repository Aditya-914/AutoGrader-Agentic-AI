#!/usr/bin/env python3
"""
Auto-Grading Agent — Main Entry Point

Grades a C code submission against a mutable JSON rule set.
Uses an LLM (Ollama/llama3.1) as a helper to generate test and edge cases.

Outputs:
  - Machine-readable JSON report (reports/<submission>.json)
  - Student-readable Text report (reports/<submission>.txt)

Usage:
    python3 main.py [rules.json] [submission.c] [--output json_path] [--text-output txt_path] [--verbose]

Examples:
    python3 main.py rules/add_rules.json submissions/add.c
    python3 main.py rules/add_rules.json submissions/add.c --verbose
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone

# Ensure agent/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent"))

from phase1_coordinator import AutoGraderCoordinator
from phase2_dispatcher import Phase2Dispatcher
from report_generator import build_final_json_report, build_final_text_report


def main():
    parser = argparse.ArgumentParser(
        description="Auto-grade a C submission against a JSON rule set."
    )
    parser.add_argument(
        "rules",
        nargs="?",
        default="rules/add_rules.json",
        help="Path to the rules JSON file (default: rules/add_rules.json)"
    )
    parser.add_argument(
        "submission",
        nargs="?",
        default="submissions/add.c",
        help="Path to the C submission file (default: submissions/add.c)"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Path for machine JSON report (default: reports/<submission_stem>.json)"
    )
    parser.add_argument(
        "--text-output", "-t",
        default=None,
        help="Path for student text report (default: reports/<submission_stem>.txt)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print progress messages to stderr"
    )
    args = parser.parse_args()

    def log(msg):
        if args.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)

    log(f"Rules:      {args.rules}")
    log(f"Submission: {args.submission}")

    coordinator = AutoGraderCoordinator(args.rules, args.submission)
    try:
        # ── Phase 1: First Pass ──────────────────────────────────────────
        log("Phase 1: Running first pass (static sanity, compile, smoke test)...")
        t0 = time.time()
        first_pass = coordinator.run_first_pass()
        log(f"Phase 1 complete in {time.time() - t0:.1f}s — "
            f"compiled={first_pass.compiled}, smoke_ok={first_pass.smoke_ok}, "
            f"infinite_loop={first_pass.suspected_infinite_loop}")

        if not first_pass.compiled:
            log("⚠ Compilation failed — execution-based analyzers will be skipped.")
        if first_pass.suspected_infinite_loop:
            log("⚠ Smoke test timed out — suspected infinite loop.")

        # ── Phase 2: Parallel Analyzer Dispatch ──────────────────────────
        log("Phase 2: Dispatching analyzers in parallel...")
        t1 = time.time()
        dispatcher = Phase2Dispatcher(coordinator)
        eval_report = dispatcher.dispatch_all(first_pass=first_pass)
        log(f"Phase 2 complete in {time.time() - t1:.1f}s")

        # ── Enrich report with metadata, tool versions, usefulness & limits ─
        eval_report["graded_at"] = datetime.now(timezone.utc).isoformat()
        eval_report["total_time_s"] = round(time.time() - t0, 2)
        final_json_data = build_final_json_report(eval_report)

        # ── Format Student Text Report ────────────────────────────────────
        final_text_content = build_final_text_report(final_json_data)

        # ── Determine Output Paths ───────────────────────────────────────
        sub_stem = os.path.splitext(os.path.basename(args.submission))[0]
        json_out_path = args.output or os.path.join("reports", f"{sub_stem}.json")
        text_out_path = args.text_output or os.path.join("reports", f"{sub_stem}.txt")

        # Write JSON report
        os.makedirs(os.path.dirname(json_out_path) or ".", exist_ok=True)
        with open(json_out_path, "w", encoding="utf-8") as f:
            json.dump(final_json_data, f, indent=2)
        log(f"Machine JSON report written to {json_out_path}")

        # Write Text report
        os.makedirs(os.path.dirname(text_out_path) or ".", exist_ok=True)
        with open(text_out_path, "w", encoding="utf-8") as f:
            f.write(final_text_content + "\n")
        log(f"Student Text report written to {text_out_path}")

        # Print student text report to stdout for immediate display
        print(final_text_content)

    finally:
        coordinator.cleanup()
        log("Sandbox cleaned up.")


if __name__ == "__main__":
    main()
