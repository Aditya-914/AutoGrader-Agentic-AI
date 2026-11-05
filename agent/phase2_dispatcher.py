import os
import sys
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from typing import Dict, Any, List

from phase1_coordinator import AutoGraderCoordinator
from analyzers import ANALYZER_REGISTRY


class Phase2Dispatcher:
    """
    Dispatches all scheduled analyzers concurrently after Phase 1 completes.
    Each analyzer runs in a thread with a per-analyzer timeout to prevent hangs.
    """

    # Maximum wall-clock time (seconds) any single analyzer is allowed before being abandoned
    PER_ANALYZER_TIMEOUT_S = 180

    def __init__(self, coordinator: AutoGraderCoordinator):
        self.coordinator = coordinator

    def _run_single_metric(self, metric_rule: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a single expert analyzer and computes its weighted score contribution."""
        metric_name = metric_rule["name"]
        analyzer_key = metric_rule["analyzer"]
        weight = float(metric_rule["weight"])
        params = metric_rule.get("params", {})

        analyzer_fn = ANALYZER_REGISTRY.get(analyzer_key)
        if not analyzer_fn:
            return {
                "name": metric_name,
                "analyzer": analyzer_key,
                "score": 0.0,
                "weight": weight,
                "contribution": 0.0,
                "evidence": {"error": f"Unknown analyzer '{analyzer_key}'"},
                "feedback": f"Analyzer '{analyzer_key}' is not registered."
            }

        try:
            res = analyzer_fn(
                submission_path=self.coordinator.sandboxed_src_path,
                binary_path=self.coordinator.binary_path,
                sandbox_dir=self.coordinator.sandbox_dir,
                params=params,
                time_limit_s=int(self.coordinator.rules.get("time_limit_s", 1)),
                memory_limit_mb=int(self.coordinator.rules.get("memory_limit_mb", 64)),
                problem_description=self.coordinator.rules.get("problem_description", ""),
                llm_config=self.coordinator.rules.get(
                    "llm_config",
                    {"model": "llama3.1", "temperature": 0, "seed": 42}
                ),
                sample_input=self.coordinator.rules.get("sample_input", ""),
                sample_output=self.coordinator.rules.get("sample_output", ""),
                problem=self.coordinator.rules.get("problem", "")
            )
        except Exception as e:
            res = {
                "score": 0.0,
                "evidence": {"error": str(e)},
                "feedback": f"Analyzer '{analyzer_key}' crashed: {e}"
            }

        raw_score = float(res.get("score", 0.0))
        contribution = round(raw_score * weight * 100.0, 2)

        return {
            "name": metric_name,
            "analyzer": analyzer_key,
            "score": raw_score,
            "weight": weight,
            "contribution": contribution,
            "evidence": res.get("evidence", {}),
            "feedback": res.get("feedback", "")
        }

    def dispatch_all(
        self,
        first_pass=None,
        max_workers: int = 4
    ) -> Dict[str, Any]:
        """
        Runs Phase 1 (if not already done) and dispatches all scheduled Phase 2
        analyzers concurrently. Accepts pre-computed first_pass to avoid re-running.

        Args:
            first_pass: Pre-computed FirstPassResult. If None, Phase 1 is run.
            max_workers: Max concurrent analyzer threads.
        """
        if first_pass is None:
            first_pass = self.coordinator.run_first_pass()

        plan = self.coordinator.plan_analyzer_dispatch(first_pass)

        metric_results: List[Dict[str, Any]] = []

        # 1. Dispatch scheduled analyzers in parallel with per-analyzer timeout
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_metric = {
                executor.submit(self._run_single_metric, m): m
                for m in plan["scheduled"]
            }

            for future in as_completed(future_to_metric, timeout=self.PER_ANALYZER_TIMEOUT_S * 2):
                metric_def = future_to_metric[future]
                try:
                    result = future.result(timeout=self.PER_ANALYZER_TIMEOUT_S)
                    metric_results.append(result)
                except FuturesTimeout:
                    metric_results.append({
                        "name": metric_def["name"],
                        "analyzer": metric_def["analyzer"],
                        "score": 0.0,
                        "weight": float(metric_def["weight"]),
                        "contribution": 0.0,
                        "evidence": {"error": "Analyzer timed out"},
                        "feedback": f"Analyzer '{metric_def['analyzer']}' exceeded the {self.PER_ANALYZER_TIMEOUT_S}s timeout."
                    })
                except Exception as e:
                    metric_results.append({
                        "name": metric_def["name"],
                        "analyzer": metric_def["analyzer"],
                        "score": 0.0,
                        "weight": float(metric_def["weight"]),
                        "contribution": 0.0,
                        "evidence": {"error": str(e)},
                        "feedback": f"Analyzer '{metric_def['analyzer']}' failed: {e}"
                    })

        # 2. Record 0-score entries for analyzers skipped due to infinite loop or compile error
        for skipped_metric in plan["skipped"]:
            metric_results.append({
                "name": skipped_metric["name"],
                "analyzer": skipped_metric["analyzer"],
                "score": 0.0,
                "weight": float(skipped_metric["weight"]),
                "contribution": 0.0,
                "evidence": {"skipped": True, "reason": skipped_metric["skip_reason"]},
                "feedback": f"Skipped: {skipped_metric['skip_reason']}"
            })

        # Preserve original metric ordering from the rules JSON
        rule_order = {
            m["name"]: idx
            for idx, m in enumerate(self.coordinator.rules.get("metrics", []))
        }
        metric_results.sort(key=lambda x: rule_order.get(x["name"], 999))

        total_grade = round(sum(m["contribution"] for m in metric_results), 2)

        flags = []
        if first_pass.suspected_infinite_loop:
            flags.append("suspected_infinite_loop")
        if first_pass.crashed:
            flags.append(f"smoke_run_crashed_rc_{first_pass.return_code}")
        if not first_pass.static_sanity_ok:
            flags.append("failed_static_sanity")
        for m in metric_results:
            if m["analyzer"] == "similarity_flag" and m["evidence"].get("flagged"):
                flags.append("plagiarism_or_llm_similarity_flagged")

        return {
            "submission": os.path.basename(self.coordinator.submission_path),
            "rules_hash": self.coordinator.rules_hash,
            "grade": total_grade,
            "first_pass": {
                "compiled": first_pass.compiled,
                "smoke_ok": first_pass.smoke_ok,
                "suspected_infinite_loop": first_pass.suspected_infinite_loop,
                "static_sanity_ok": first_pass.static_sanity_ok,
                "static_sanity_details": first_pass.static_sanity_details,
                "compile_warnings": first_pass.compile_warnings,
                "smoke_stdout": first_pass.smoke_stdout.strip()
            },
            "metrics": metric_results,
            "flags": flags
        }


if __name__ == "__main__":
    rules_path = sys.argv[1] if len(sys.argv) > 1 else "rules/add_rules.json"
    sub_path = sys.argv[2] if len(sys.argv) > 2 else "submissions/add.c"

    coord = AutoGraderCoordinator(rules_path, sub_path)
    try:
        print(f"[Phase 1] Running first pass on {os.path.basename(sub_path)}...", flush=True)
        first_pass_res = coord.run_first_pass()

        print(f"[Phase 1] compiled={first_pass_res.compiled}, "
              f"smoke_ok={first_pass_res.smoke_ok}, "
              f"infinite_loop={first_pass_res.suspected_infinite_loop}", flush=True)

        dispatcher = Phase2Dispatcher(coord)
        print("[Phase 2] Dispatching analyzers...", flush=True)
        full_evaluation = dispatcher.dispatch_all(first_pass=first_pass_res)

        print(json.dumps(full_evaluation, indent=2))
    finally:
        coord.cleanup()
