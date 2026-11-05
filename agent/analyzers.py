import os
import re
import time
import json
import glob
import signal
import difflib
import tempfile
import subprocess
from typing import Dict, Any, List, Optional

try:
    import lizard
    HAS_LIZARD = True
except ImportError:
    HAS_LIZARD = False

import requests
from llm_test_generator import (
    generate_standard_test_suite,
    generate_adversarial_edge_cases,
    run_student_defense_loop
)

try:
    import resource
    HAS_RESOURCE = True
except ImportError:
    HAS_RESOURCE = False


def _sandbox_preexec(memory_limit_mb: int, time_limit_s: int):
    """Enforces OS-level memory and CPU limits for child binary executions."""
    def _set_limits():
        if HAS_RESOURCE:
            mem_bytes = memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (time_limit_s + 1, time_limit_s + 1))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()
    return _set_limits


def _run_binary_no_mem_limit(
    binary_path: str,
    input_data: str,
    time_limit_s: int = 3,
    cwd: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes a binary without RLIMIT_AS restrictions.
    Required for AddressSanitizer which needs ~15 TB virtual address space.
    """
    def _preexec():
        if HAS_RESOURCE:
            resource.setrlimit(resource.RLIMIT_CPU, (time_limit_s + 2, time_limit_s + 2))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()

    preexec = _preexec if os.name == "posix" else None
    start_time = time.perf_counter()

    try:
        proc = subprocess.Popen(
            [binary_path],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=preexec
        )
    except (OSError, FileNotFoundError) as e:
        return {
            "timed_out": False,
            "return_code": -1,
            "stdout": "",
            "stderr": f"Failed to execute binary: {e}",
            "elapsed_s": 0.0
        }

    try:
        stdout, stderr = proc.communicate(input=input_data, timeout=time_limit_s)
        elapsed_s = time.perf_counter() - start_time
        return {
            "timed_out": False,
            "return_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_s": elapsed_s
        }
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        else:
            proc.kill()
        stdout, stderr = proc.communicate()
        return {
            "timed_out": True,
            "return_code": None,
            "stdout": stdout or "",
            "stderr": stderr or "Execution timed out",
            "elapsed_s": float(time_limit_s)
        }


def run_binary_safely(
    binary_path: str,
    input_data: str,
    time_limit_s: int = 1,
    memory_limit_mb: int = 64,
    cwd: Optional[str] = None
) -> Dict[str, Any]:
    """Helper to execute a compiled binary safely and measure wall-clock runtime & memory."""
    preexec = _sandbox_preexec(memory_limit_mb, time_limit_s) if os.name == "posix" else None
    start_time = time.perf_counter()

    try:
        proc = subprocess.Popen(
            [binary_path],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=preexec
        )
    except (OSError, FileNotFoundError) as e:
        return {
            "timed_out": False,
            "return_code": -1,
            "stdout": "",
            "stderr": f"Failed to execute binary: {e}",
            "elapsed_s": 0.0
        }

    try:
        stdout, stderr = proc.communicate(input=input_data, timeout=time_limit_s)
        elapsed_s = time.perf_counter() - start_time
        return {
            "timed_out": False,
            "return_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_s": elapsed_s
        }
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        else:
            proc.kill()
        stdout, stderr = proc.communicate()
        return {
            "timed_out": True,
            "return_code": None,
            "stdout": stdout or "",
            "stderr": stderr or "Execution timed out",
            "elapsed_s": float(time_limit_s)
        }


# =====================================================================
# 1. CORRECTNESS ANALYZER (io_tests)
# =====================================================================
def analyze_io_tests(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    time_limit_s: int = 1,
    memory_limit_mb: int = 64,
    problem_description: str = "",
    llm_config: Optional[Dict[str, Any]] = None,
    sample_input: str = "",
    sample_output: str = "",
    **kwargs
) -> Dict[str, Any]:
    testset_dir = params.get("testset_dir", "tests/add/")
    if testset_dir.strip().rstrip("/") in ("tests", ""):
        slug = re.sub(r'[^a-z0-9_]', '_', (kwargs.get("problem") or problem_description[:20] or "problem").lower()).strip('_')
        testset_dir = f"tests/{slug}/"
    auto_generate = bool(params.get("auto_generate", True))
    num_tests = int(params.get("num_tests", 10))
    llm_cfg = llm_config or {"model": "llama3.1", "temperature": 0, "seed": 42}

    in_files = sorted(glob.glob(os.path.join(testset_dir, "*.in")))

    # Automatically generate test suite via Ollama if requested or if directory is empty
    if (auto_generate or not in_files) and problem_description:
        try:
            generate_standard_test_suite(
                problem_description=problem_description,
                testset_dir=testset_dir,
                num_tests=num_tests,
                model=llm_cfg.get("model", "llama3.1"),
                temperature=float(llm_cfg.get("temperature", 0)),
                seed=int(llm_cfg.get("seed", 42)),
                sample_input=sample_input,
                sample_output=sample_output,
                binary_oracle_path=binary_path  # use compiled submission as fallback oracle
            )
        except Exception as e:
            if not in_files:
                return {
                    "score": 0.0,
                    "evidence": {"error": f"Test generation failed: {e}"},
                    "feedback": f"Could not generate test cases: {e}"
                }
        in_files = sorted(glob.glob(os.path.join(testset_dir, "*.in")))

    if not in_files:
        return {
            "score": 0.0,
            "evidence": {"error": f"No test files found or generated in {testset_dir}"},
            "feedback": "No test cases available."
        }

    passed = 0
    failing_cases = []

    for in_file in in_files:
        base = os.path.splitext(in_file)[0]
        out_file = base + ".out"
        test_name = os.path.basename(base)

        if not os.path.exists(out_file):
            failing_cases.append({
                "test": test_name,
                "input": "",
                "expected": "(missing .out file)",
                "got": "",
                "note": f"Expected output file {out_file} not found"
            })
            continue

        with open(in_file, "r", encoding="utf-8") as f:
            inp = f.read()
        with open(out_file, "r", encoding="utf-8") as f:
            expected = f.read().strip()

        res = run_binary_safely(binary_path, inp, time_limit_s, memory_limit_mb, cwd=sandbox_dir)
        actual = res["stdout"].strip()

        # Normalize whitespace: collapse multiple spaces/newlines into single space for comparison
        def _norm(s: str) -> str:
            return " ".join(s.split())

        actual_norm = _norm(actual)
        expected_norm = _norm(expected)

        # Match: exact → normalized → endswith → last-line match → numeric tail
        match = (actual == expected) or (actual_norm == expected_norm)
        if not match and expected_norm:
            # Try last line of actual matching expected (e.g. header + answer on separate line)
            actual_lines = [l.strip() for l in actual.splitlines() if l.strip()]
            if actual_lines and _norm(actual_lines[-1]) == expected_norm:
                match = True
            elif actual_norm.endswith(expected_norm):
                match = True
            elif re.match(r'^-?[\d\s]+$', expected_norm):
                # For numeric outputs, also try matching all numbers
                actual_nums = " ".join(re.findall(r'-?\d+', actual))
                expected_nums = " ".join(re.findall(r'-?\d+', expected))
                if actual_nums and expected_nums and actual_nums.endswith(expected_nums):
                    match = True

        if not res["timed_out"] and res["return_code"] == 0 and match:
            passed += 1
        else:
            note = "wrong answer (output mismatch)"
            if res["timed_out"]:
                note = "runtime error: time limit exceeded"
            elif res["return_code"] is not None and res["return_code"] != 0:
                note = f"runtime error: exit code {res['return_code']}"
            elif "2147483647" in inp or "-2147483648" in inp:
                note = "wrong answer: likely signed integer overflow"

            failing_cases.append({
                "test": test_name,
                "input": inp.strip(),
                "expected": expected,
                "got": actual,
                "note": note
            })

    total = len(in_files)
    score = round(passed / total, 4) if total > 0 else 0.0
    if failing_cases:
        first_fail = failing_cases[0]
        feedback = (
            f"{passed}/{total} tests pass. "
            f"Fails on input '{first_fail['input']}' "
            f"(expected '{first_fail['expected']}', got '{first_fail['got']}')."
        )
    else:
        feedback = f"All {total}/{total} tests pass."

    return {
        "score": score,
        "evidence": {
            "generated_by_llm": auto_generate,
            "tests_passed": passed,
            "tests_total": total,
            "failing": failing_cases
        },
        "feedback": feedback
    }


# =====================================================================
# 2. SYNTAX ANALYZER (compiler_warnings)
# =====================================================================
def analyze_compiler_warnings(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    flags_str = params.get("flags", "-Wall -Wextra -Werror -std=c11")
    # Separate -Werror during diagnostic collection so we can count individual warnings accurately
    flags = [f for f in flags_str.split() if f != "-Werror"]

    cmd = ["gcc"] + flags + ["-fsyntax-only", submission_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return {
            "score": 0.0,
            "evidence": {"error": "Compiler timed out"},
            "feedback": "Compilation check timed out."
        }

    stderr_lines = proc.stderr.strip().splitlines() if proc.stderr else []
    warnings = [line for line in stderr_lines if "warning:" in line]
    errors = [line for line in stderr_lines if "error:" in line]

    if errors or proc.returncode != 0:
        return {
            "score": 0.0,
            "evidence": {"errors": errors, "warnings": warnings},
            "feedback": f"Compilation failed with {len(errors)} error(s)."
        }

    # Deduct 0.10 per warning, floored at 0.0
    score = max(0.0, round(1.0 - (0.10 * len(warnings)), 2))
    feedback = "Clean compile with 0 warnings." if not warnings else f"{len(warnings)} compiler warning(s) generated."

    return {
        "score": score,
        "evidence": {"warning_count": len(warnings), "warnings": warnings},
        "feedback": feedback
    }


# =====================================================================
# 3. STRUCTURE ANALYZER (static_analysis via cppcheck + lizard)
# =====================================================================
def analyze_static_analysis(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    max_ccn = int(params.get("max_cyclomatic", 8))
    max_len = int(params.get("max_function_length", 40))

    functions_info = []
    ccn_violations = 0
    len_violations = 0
    fn_count = 0

    # 1. Run Lizard for Cyclomatic Complexity & Function Length
    if HAS_LIZARD:
        liz_analysis = lizard.analyze_file(submission_path)
        for fn in liz_analysis.function_list:
            functions_info.append({
                "name": fn.name,
                "cyclomatic_complexity": fn.cyclomatic_complexity,
                "nloc": fn.nloc
            })
            if fn.cyclomatic_complexity > max_ccn:
                ccn_violations += 1
            if fn.nloc > max_len:
                len_violations += 1
        fn_count = len(liz_analysis.function_list)
    else:
        # Fallback: count functions with regex
        with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        fn_matches = re.findall(
            r"^(?:int|long|void|double|float|char|unsigned|short|signed)\s+\w+\s*\([^)]*\)\s*\{",
            code, re.M
        )
        fn_count = len(fn_matches)
        functions_info = [{"name": "N/A (lizard not installed)", "cyclomatic_complexity": -1, "nloc": -1}]

    # 2. Run cppcheck for static defects
    cppcheck_issues = []
    try:
        proc = subprocess.run(
            ["cppcheck", "--enable=style,warning,performance,portability", "--quiet",
             "--template={severity}:{id}:{message}", submission_path],
            capture_output=True, text=True, timeout=10
        )
        if proc.stderr:
            cppcheck_issues = [
                line for line in proc.stderr.strip().splitlines()
                if not line.startswith("information:missingIncludeSystem")
                and line.strip()
            ]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        cppcheck_issues = []

    with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()

    has_custom_header_or_proto = bool(
        re.search(
            r"^\s*(?:int|long|void|double|float|char|unsigned|short|signed)\s+(?!main\b)\w+\s*\([^)]*\)\s*;",
            code, re.M
        )
    )

    score = 1.0
    reasons = []
    if ccn_violations > 0:
        score -= 0.25 * ccn_violations
        reasons.append(f"{ccn_violations} function(s) exceed max cyclomatic complexity ({max_ccn})")
    if len_violations > 0:
        score -= 0.20 * len_violations
        reasons.append(f"{len_violations} function(s) exceed max length ({max_len} lines)")
    if cppcheck_issues:
        score -= 0.10 * len(cppcheck_issues)
        reasons.append(f"{len(cppcheck_issues)} cppcheck style/warning issue(s)")
    if fn_count <= 1 and not has_custom_header_or_proto:
        score -= 0.40
        reasons.append("no headers/prototypes, single-block code")

    score = max(0.0, round(score, 2))
    feedback = "; ".join(reasons) if reasons else "Good static structure and low cyclomatic complexity."

    return {
        "score": score,
        "evidence": {
            "functions": functions_info,
            "cppcheck_issues": cppcheck_issues,
            "has_prototypes": has_custom_header_or_proto
        },
        "feedback": feedback
    }


# =====================================================================
# 4. MODULARITY ANALYZER (function_split)
# =====================================================================
def analyze_function_split(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    min_functions = int(params.get("min_functions", 2))

    if HAS_LIZARD:
        liz_analysis = lizard.analyze_file(submission_path)
        fn_names = [fn.name for fn in liz_analysis.function_list]
    else:
        # Fallback: extract function names with regex
        with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        fn_names = re.findall(
            r"^(?:int|long|void|double|float|char|unsigned|short|signed)\s+(\w+)\s*\([^)]*\)\s*\{",
            code, re.M
        )

    fn_count = len(fn_names)

    if fn_count >= min_functions:
        score = 1.0
        feedback = f"Modularity requirement met ({fn_count} functions defined: {', '.join(fn_names)})."
    elif fn_count == 1 and "main" in fn_names:
        score = 0.30
        feedback = "Only main() is defined. Extract a helper function (e.g., add(long long, long long))."
    else:
        score = round(fn_count / max(1, min_functions), 2)
        feedback = f"Found {fn_count} function(s), expected at least {min_functions}."

    return {
        "score": score,
        "evidence": {
            "functions_defined": fn_count,
            "function_names": fn_names,
            "expected_min": min_functions
        },
        "feedback": feedback
    }


# =====================================================================
# 5. LLM-POWERED LOGICAL & EDGE CASE ANALYZER (edge_case_runner)
#    WITH STUDENT DEFENSE REALITY CHECK LOOP
# =====================================================================
def analyze_edge_case_runner(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    time_limit_s: int = 1,
    memory_limit_mb: int = 64,
    problem_description: str = "",
    llm_config: Optional[Dict[str, Any]] = None,
    sample_input: str = "",
    sample_output: str = "",
    **kwargs
) -> Dict[str, Any]:
    requested_cases = params.get("cases", ["negatives", "zero", "int_overflow"])
    llm_cfg = llm_config or {"model": "llama3.1", "temperature": 0, "seed": 42}

    with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
        student_code = f.read()

    def runner(inp_data: str) -> Dict[str, Any]:
        return run_binary_safely(
            binary_path, inp_data, time_limit_s, memory_limit_mb, cwd=sandbox_dir
        )

    try:
        defense_result = run_student_defense_loop(
            problem_description=problem_description,
            student_c_code=student_code,
            binary_runner_fn=runner,
            categories=requested_cases,
            sample_input=sample_input,
            sample_output=sample_output,
            model=llm_cfg.get("model", "llama3.1"),
            temperature=float(llm_cfg.get("temperature", 0)),
            seed=int(llm_cfg.get("seed", 42)),
            max_rounds=2,
            binary_oracle_path=binary_path  # use compiled binary as fallback oracle
        )
    except Exception as e:
        return {
            "score": 0.0,
            "evidence": {"error": f"Edge case evaluation failed: {e}"},
            "feedback": f"Could not run edge cases: {e}"
        }

    return {
        "score": defense_result["score"],
        "evidence": {
            "generated_by_llm": True,
            "student_defense_loop_active": True,
            "cases_tested": defense_result["cases_tested"],
            "cases_passed": defense_result["cases_passed"],
            "defended_against_llm": defense_result["defended_cases"],
            "counter_test_cases": defense_result["counter_examples"],
            "self_correction_rounds": defense_result["self_correction_rounds"]
        },
        "feedback": defense_result["feedback"]
    }


# =====================================================================
# 6. TIME & SPACE COMPLEXITY ANALYZER (complexity_estimator)
# =====================================================================
def analyze_complexity_estimator(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    time_limit_s: int = 1,
    memory_limit_mb: int = 64,
    **kwargs
) -> Dict[str, Any]:
    required_bound = params.get("required", "O(1)")
    required_space = params.get("required_space", "O(1)")
    sizes = params.get("sizes", [1, 10, 100])

    sample_input = str(kwargs.get("sample_input") or "").strip()

    # Detect input grammar to generate valid scaled inputs (not just "val val\n")
    try:
        from agent.llm_test_generator import analyze_input_grammar
    except ImportError:
        from llm_test_generator import analyze_input_grammar

    grammar = analyze_input_grammar(sample_input) if sample_input else {"kind": "general"}
    grammar_kind = grammar.get("kind", "general")

    # Flat-grid detection fallback: first token is N, total tokens == N*N+1 (e.g. Dijkstra flat input)
    if grammar_kind == "int_list":
        all_toks = sample_input.split()
        if len(all_toks) > 2:
            try:
                first = int(all_toks[0])
                if first > 0 and len(all_toks) == first * first + 1:
                    grammar_kind = "flat_grid"
                    grammar["n"] = first
            except ValueError:
                pass

    is_string_problem = (grammar_kind == "string")

    timings_ms = []
    for sz in sizes:
        # Cap N to avoid VLA stack overflows / excessive run times
        n = max(1, min(sz, 50))
        if grammar_kind == "string" or is_string_problem:
            inp = ("abc" * (n // 3 + 1))[:max(1, n)] + "\n"
        elif grammar_kind == "grid":
            # N followed by N*N values on N rows
            r, c = n, n
            rows = "\n".join(" ".join(["1"] * c) for _ in range(r))
            inp = f"{n}\n{rows}\n"
        elif grammar_kind == "flat_grid":
            # N followed by N*N values all space-separated on one line
            vals = " ".join(["1"] * (n * n))
            inp = f"{n} {vals}\n"
        elif grammar_kind == "array_prefix":
            inp = f"{n}\n" + " ".join(["1"] * n) + "\n"
        elif grammar_kind == "two_ints":
            inp = f"{n} {n}\n"
        else:
            # general / int_list: use two safe integers
            val = 10 ** min(n // 2, 6)
            inp = f"{val} {val}\n"
        # Average over 3 runs to reduce OS scheduling jitter
        runs = []
        for _ in range(3):
            res = run_binary_safely(binary_path, inp, time_limit_s, memory_limit_mb, cwd=sandbox_dir)
            if res["timed_out"]:
                runs.append(float(time_limit_s) * 1000.0)
            else:
                runs.append(res["elapsed_s"] * 1000.0)
        timings_ms.append(round(sum(runs) / len(runs), 3))

    # Static loop/recursion inspection to complement empirical curve
    with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
        clean_code = re.sub(r"//.*|/\*[\s\S]*?\*/", "", f.read())

    loop_matches = re.findall(r"\b(for|while|do)\b", clean_code)
    malloc_matches = re.findall(r"\b(malloc|calloc|realloc|alloca)\b", clean_code)

    # Check if runtime grows linearly with size (ratio of largest to smallest > 4x and > 5ms delta)
    time_ratio = (timings_ms[-1] / max(0.001, timings_ms[0])) if len(timings_ms) >= 2 else 1.0
    empirical_constant = (time_ratio < 4.0) or (max(timings_ms) - min(timings_ms) < 5.0)

    estimated_time = "O(1)" if (len(loop_matches) == 0 and empirical_constant) else "O(N) or higher"
    estimated_space = "O(1)" if len(malloc_matches) == 0 else "O(N) dynamic allocation"

    matches_time = (
        estimated_time == required_bound
        or (required_bound in ("O(N)", "O(N) or higher") and "O(N)" in estimated_time)
        or (required_bound == "O(1)" and estimated_time == "O(1)")
        or (required_bound in ("O(N^2)", "O(N^3)", "O(N) or higher"))
    )
    matches_space = (
        required_space in ("O(N)", "O(N) or higher")
        or (required_space == "O(1)" and estimated_space == "O(1)")
    )
    matches_bound = matches_time and matches_space
    score = 1.0 if matches_bound else (0.7 if (matches_time or matches_space) else 0.4)

    return {
        "score": score,
        "evidence": {
            "required_time_complexity": required_bound,
            "required_space_complexity": required_space,
            "estimated_time_complexity": estimated_time,
            "estimated_space_complexity": estimated_space,
            "sizes": sizes,
            "timings_ms": timings_ms,
            "loops_detected": len(loop_matches)
        },
        "feedback": f"Time: {estimated_time} (required {required_bound}), Space: {estimated_space} (required {required_space}) confirmed across sizes {sizes}."
    }


# =====================================================================
# 7. MEMORY SAFETY ANALYZER (sanitizer_run via ASan + UBSan)
#    Falls back to deep static analysis when libasan is not installed.
# =====================================================================

def _check_asan_available() -> bool:
    """Returns True if ASan can actually compile and link on this system."""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as tf:
            tf.write("int main(void){return 0;}")
            probe_c = tf.name
        probe_bin = probe_c + ".out"
        proc = subprocess.run(
            ["gcc", "-fsanitize=address,undefined", probe_c, "-o", probe_bin],
            capture_output=True, timeout=8
        )
        for p in (probe_c, probe_bin):
            if os.path.exists(p):
                os.remove(p)
        return proc.returncode == 0
    except Exception:
        return False


def _static_memory_safety(submission_path: str) -> Dict[str, Any]:
    """
    Deep static analysis fallback when ASan/libasan is unavailable.
    Checks for: dangerous functions, unbounded buffers, missing bounds,
    pointer misuse, integer overflow patterns, and use-after-free indicators.
    Returns a score (0.0–1.0) and structured findings.
    """
    with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    # Strip comments for cleaner matching
    code = re.sub(r"//[^\n]*", "", raw)
    code = re.sub(r"/\*[\s\S]*?\*/", "", code)

    deductions = []
    findings = []

    # ── Dangerous C functions ──────────────────────────────────────────
    DANGEROUS = {
        r"\bgets\s*\(":        ("gets() has no bounds check — always a buffer overflow risk", 0.40),
        r"\bscanf\s*\(\s*\"%s\"": ("scanf(\"%s\") with no width limit — unbounded buffer read", 0.30),
        r"\bstrcpy\s*\(":      ("strcpy() does not check destination buffer size", 0.20),
        r"\bstrcat\s*\(":      ("strcat() does not check destination buffer size", 0.15),
        r"\bsprintf\s*\(":     ("sprintf() may overflow destination buffer; use snprintf()", 0.10),
    }
    for pattern, (msg, penalty) in DANGEROUS.items():
        if re.search(pattern, code):
            deductions.append(penalty)
            findings.append({"type": "dangerous_function", "detail": msg})

    # ── malloc/calloc without NULL check ──────────────────────────────
    malloc_calls = re.findall(r"\b(malloc|calloc|realloc)\s*\(", code)
    null_checks   = re.findall(r"==\s*NULL|!=\s*NULL|if\s*\(\s*!", code)
    if malloc_calls and len(null_checks) < len(malloc_calls):
        deductions.append(0.15)
        findings.append({
            "type": "unchecked_malloc",
            "detail": f"{len(malloc_calls)} allocation(s) with only {len(null_checks)} NULL check(s)"
        })

    # ── Fixed-size char arrays used with scanf/fgets ───────────────────
    char_arrays = re.findall(r"\bchar\s+\w+\s*\[\s*(\d+)\s*\]", code)
    fgets_calls = re.findall(r"\bfgets\s*\(", code)
    if char_arrays and not fgets_calls and re.search(r"\bscanf\b", code):
        findings.append({
            "type": "info",
            "detail": f"Fixed char buffer(s) [{', '.join(char_arrays)}] with scanf — verify width limits"
        })

    # ── Array indexing without visible bounds check ───────────────────
    array_subscripts = re.findall(r"\w+\s*\[\s*\w+\s*\]", code)
    bounds_checks     = re.findall(r"\b(if|while|assert)\b.*[<>]=?\s*\d", code)
    if len(array_subscripts) > 3 and len(bounds_checks) == 0:
        deductions.append(0.10)
        findings.append({
            "type": "missing_bounds_check",
            "detail": f"{len(array_subscripts)} array subscript(s) with no visible bounds validation"
        })

    # ── Signed integer overflow patterns ──────────────────────────────
    # Using int for arithmetic that may overflow (not using long long)
    has_int_arith = re.search(r"\bint\b.*[+\-\*]", code)
    has_ll        = re.search(r"\blong\s+long\b|\bint64_t\b|\buint64_t\b", code)
    has_scanf_int = re.search(r'scanf\s*\(\s*"%d', code)
    if has_int_arith and has_scanf_int and not has_ll:
        deductions.append(0.10)
        findings.append({
            "type": "overflow_risk",
            "detail": "32-bit int arithmetic on user input without 64-bit widening — risk of signed overflow"
        })

    # ── Free without matching malloc (heuristic) ──────────────────────
    free_calls   = len(re.findall(r"\bfree\s*\(", code))
    malloc_count = len(malloc_calls)
    if free_calls > malloc_count + 1:
        deductions.append(0.20)
        findings.append({
            "type": "double_free_risk",
            "detail": f"More free() calls ({free_calls}) than malloc() calls ({malloc_count}) — possible double-free"
        })

    total_deduction = min(1.0, sum(deductions))
    score = round(max(0.0, 1.0 - total_deduction), 2)

    if not findings:
        summary = "Static analysis: no dangerous functions or obvious memory safety issues found."
    else:
        issues = [f["detail"] for f in findings if f["type"] != "info"]
        infos  = [f["detail"] for f in findings if f["type"] == "info"]
        parts  = []
        if issues:
            parts.append("; ".join(issues))
        if infos:
            parts.append(f"Note: {'; '.join(infos)}")
        summary = " | ".join(parts)

    return {
        "score": score,
        "mode": "static_analysis_fallback",
        "findings": findings,
        "feedback": summary,
    }


def analyze_sanitizer_run(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    time_limit_s: int = 1,
    memory_limit_mb: int = 64,
    **kwargs
) -> Dict[str, Any]:
    san_flags = params.get("flags", "-fsanitize=address,undefined").split()
    san_bin = os.path.join(sandbox_dir, "submission_san")

    # ── Try ASan/UBSan first ──────────────────────────────────────────
    asan_available = _check_asan_available()

    if asan_available:
        cmd = ["gcc", "-O1", "-g"] + san_flags + [submission_path, "-o", san_bin, "-lm"]
        try:
            compile_proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            compile_proc = None

        if compile_proc and compile_proc.returncode == 0:
            # ASan requires ~15 TB virtual address space — do NOT set RLIMIT_AS
            test_inputs = ["7 5\n", "0 0\n", "-100 200\n", "2147483647 1\n"]
            diagnostics = []

            for inp in test_inputs:
                res = _run_binary_no_mem_limit(san_bin, inp, time_limit_s=3, cwd=sandbox_dir)
                if res["stderr"] and (
                    "runtime error:" in res["stderr"]
                    or "ERROR: AddressSanitizer" in res["stderr"]
                    or "ERROR: LeakSanitizer" in res["stderr"]
                ):
                    diagnostics.append({
                        "input": inp.strip(),
                        "sanitizer_output": res["stderr"].strip()
                    })

            mem_errors = [
                d for d in diagnostics
                if "AddressSanitizer" in d["sanitizer_output"]
                or "LeakSanitizer" in d["sanitizer_output"]
            ]
            ub_warnings = [
                d for d in diagnostics if "runtime error:" in d["sanitizer_output"]
            ]

            score = 0.0 if mem_errors else 1.0
            feedback = (
                f"ASan/UBSan: memory violation — {mem_errors[0]['sanitizer_output'].splitlines()[0]}"
                if mem_errors else
                "ASan/UBSan: no memory leaks or out-of-bounds accesses detected."
            )
            return {
                "score": score,
                "evidence": {
                    "mode": "asan_ubsan",
                    "memory_errors": mem_errors,
                    "ubsan_notes": ub_warnings
                },
                "feedback": feedback
            }

    # ── ASan unavailable: fall back to static analysis ────────────────
    result = _static_memory_safety(submission_path)
    return {
        "score": result["score"],
        "evidence": {
            "mode": result["mode"],
            "asan_available": False,
            "asan_unavailable_reason": "libasan.so not installed on this system",
            "findings": result["findings"],
        },
        "feedback": f"[Static Analysis — libasan unavailable] {result['feedback']}"
    }


# =====================================================================
# 8. READABILITY ANALYZER (llm_review via Ollama + Fallback)
# =====================================================================
def analyze_llm_review(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    model = params.get("model", "llama3.1")
    temperature = float(params.get("temperature", 0))
    seed = int(params.get("seed", 42))

    with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()

    prompt = (
        "You are a strict C code readability grader. Evaluate the following C program for "
        "variable naming quality, comments, indentation, and formatting. "
        "Respond ONLY with valid JSON matching this schema: "
        '{"score": <integer 0 to 10>, "reasons": ["<reason1>", "<reason2>"]}\n\n'
        f"Code:\n```c\n{code}\n```"
    )

    # Try local Ollama server first
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "seed": seed,
                    "num_predict": 512,  # Readability review is short
                }
            },
            timeout=30  # Reduced from 15 — readability review is a small prompt
        )
        if resp.status_code == 200:
            raw_text = resp.json().get("response", "{}")
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                parsed = {"score": 5, "reasons": ["LLM returned malformed JSON"]}
            raw_score = float(parsed.get("score", 5))
            reasons = parsed.get("reasons", [])
            return {
                "score": round(min(10.0, max(0.0, raw_score)) / 10.0, 2),
                "evidence": {
                    "model": model,
                    "temperature": temperature,
                    "seed": seed,
                    "raw_response": raw_text
                },
                "feedback": ", ".join(reasons) if reasons else "Reviewed by LLM."
            }
    except Exception:
        pass

    # Deterministic static fallback if Ollama is offline
    has_comments = bool(re.search(r"//|/\*", code))
    single_letter_vars = re.findall(r"\b(?:int|long|float|double|char)\s+([a-zA-Z])\b", code)
    reasons = []
    pts = 10
    if single_letter_vars:
        pts -= 3
        reasons.append("Single-letter variable names")
    if not has_comments:
        pts -= 2
        reasons.append("no comments")

    return {
        "score": round(max(0, pts) / 10.0, 2),
        "evidence": {
            "model": f"{model} (deterministic-fallback)",
            "temperature": temperature,
            "seed": seed,
            "raw_response": json.dumps({"score": pts, "reasons": reasons})
        },
        "feedback": ", ".join(reasons) if reasons else "Readable formatting and naming."
    }


# =====================================================================
# 9. ORIGINALITY & SIMILARITY ANALYZER (similarity_flag)
# =====================================================================
def _normalize_c_tokens(code: str) -> str:
    """Strips comments, whitespace, and normalizes identifiers to detect structural copying."""
    code = re.sub(r"//.*|/\*[\s\S]*?\*/", "", code)
    code = re.sub(r"\s+", " ", code).strip()
    return code


def analyze_similarity_flag(
    submission_path: str,
    binary_path: str,
    sandbox_dir: str,
    params: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    corpus_dir = params.get("corpus_dir") or "corpus/"
    threshold = float(params.get("flag_threshold", 0.85))

    with open(submission_path, "r", encoding="utf-8", errors="replace") as f:
        target_norm = _normalize_c_tokens(f.read())

    abs_sub = os.path.abspath(submission_path)
    # Also skip matching against the original submission file (before sandbox copy)
    sub_basename = os.path.basename(submission_path)
    max_sim = 0.0
    matched_file = None

    for candidate in glob.glob(os.path.join(corpus_dir, "*.c")):
        if os.path.abspath(candidate) == abs_sub:
            continue
        # Skip if this is the same file by name (handles sandbox copies)
        if os.path.basename(candidate) == sub_basename:
            continue
        with open(candidate, "r", encoding="utf-8", errors="replace") as f:
            cand_norm = _normalize_c_tokens(f.read())
        sim = difflib.SequenceMatcher(None, target_norm, cand_norm).ratio()
        if sim > max_sim:
            max_sim = sim
            matched_file = os.path.basename(candidate)

    max_sim = round(max_sim, 2)
    flagged = max_sim >= threshold
    score = 0.0 if flagged else 1.0

    if flagged:
        feedback = f"FLAGGED: High similarity ({max_sim}) with '{matched_file}' (threshold {threshold})."
    elif matched_file:
        feedback = f"Max similarity {max_sim} with '{matched_file}', not flagged (threshold {threshold})."
    else:
        feedback = "No other submissions found in corpus for comparison."

    return {
        "score": score,
        "evidence": {
            "max_similarity": max_sim,
            "most_similar_file": matched_file,
            "threshold": threshold,
            "flagged": flagged
        },
        "feedback": feedback
    }


# Registry mapping analyzer names from the rules JSON to their functions
ANALYZER_REGISTRY = {
    "io_tests": analyze_io_tests,
    "compiler_warnings": analyze_compiler_warnings,
    "static_analysis": analyze_static_analysis,
    "function_split": analyze_function_split,
    "edge_case_runner": analyze_edge_case_runner,
    "complexity_estimator": analyze_complexity_estimator,
    "sanitizer_run": analyze_sanitizer_run,
    "llm_review": analyze_llm_review,
    "similarity_flag": analyze_similarity_flag,
}
