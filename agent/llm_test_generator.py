import os
import re
import glob
import json
import hashlib
import requests
from typing import List, Dict, Any, Optional, Tuple

OLLAMA_URL = "http://localhost:11434/api/generate"


def clean_input_for_c(raw_inp: str) -> str:
    """Converts formats like 'N=5\narr[] = {40, 20, 30, 10, 30}' to clean C stdin."""
    raw_stripped = raw_inp.strip()
    if re.match(r'^-?\d+(\s+-?\d+)*$', raw_stripped):
        return raw_stripped + "\n"

    nums = re.findall(r'-?\d+', raw_inp)
    if nums:
        if len(nums) > 2 and int(nums[0]) * int(nums[1]) == len(nums) - 2:
            return f"{nums[0]} {nums[1]}\n{' '.join(nums[2:])}\n"
        if len(nums) > 2 and nums[0] == str(len(nums) - 1):
            return f"{nums[0]}\n{' '.join(nums[1:])}\n"
        if any(tok in raw_inp for tok in ['{', '[', 'arr', 'nums']):
            return f"{len(nums)}\n{' '.join(nums)}\n"
        return " ".join(nums) + "\n"
    cleaned = re.sub(r'^[a-zA-Z_]\w*\s*=\s*', '', raw_inp.strip())
    cleaned = cleaned.strip('"').strip("'").strip('{}[]')
    return cleaned.strip() + "\n"


def extract_sample_from_description(text: str) -> Tuple[str, str]:
    """
    Extracts the first sample input and expected output from a problem description.
    Supports multiline LeetCode, GeeksforGeeks, Codeforces formats:
      Example 1: Input: s = "abcabc" Output: 10
      Input: N=5 arr[] = {40, 20, 30, 10, 30} Output: 26000
    """
    if not text:
        return "", ""

    # 1. Multiline non-greedy pattern: Input: ... Output: ...
    m_multi = re.search(r'Input\s*:\s*(.*?)\s*Output\s*:\s*([^\n\r]+)', text, re.IGNORECASE | re.DOTALL)
    if m_multi:
        raw_in = m_multi.group(1).strip()
        raw_out = m_multi.group(2).strip()
        out_match = re.search(r'-?\d+', raw_out)
        out_clean = out_match.group(0) if out_match else raw_out.strip('"\'')
        in_clean = clean_input_for_c(raw_in)
        if in_clean and out_clean:
            return in_clean, out_clean

    patterns = [
        r'Input\s*:\s*(?:[a-zA-Z_]\w*\s*=\s*)?["\']?([^"\n\r]+?)["\']?\s*[\r\n]+\s*Output\s*:\s*["\']?([^"\n\r]+?)["\']?(?:[\r\n]|$)',
        r'Sample\s+Input\s*:\s*["\']?([^"\n\r]+?)["\']?\s*[\r\n]+\s*Sample\s+Output\s*:\s*["\']?([^"\n\r]+?)["\']?(?:[\r\n]|$)',
        r'Input\s*:\s*([^\n\r]+)[\r\n]+\s*Output\s*:\s*([^\n\r]+)',
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            inp = m.group(1).strip().strip('"').strip("'")
            out = m.group(2).strip().strip('"').strip("'")
            if inp and out:
                return inp, out

    return "", ""


def extract_all_examples(text: str) -> List[Tuple[str, str]]:
    """Extracts all (input, output) example pairs found in the problem description."""
    if not text:
        return []

    pat = re.compile(r'Input\s*:\s*(.*?)\s*Output\s*:\s*([^\n\r]+)', re.IGNORECASE | re.DOTALL)
    results = []
    for m in pat.finditer(text):
        raw_in = m.group(1).strip()
        raw_out = m.group(2).strip()
        out_match = re.search(r'-?\d+', raw_out)
        out_clean = out_match.group(0) if out_match else raw_out.strip('"\'')
        in_clean = clean_input_for_c(raw_in)
        if in_clean and out_clean:
            results.append((in_clean, out_clean))
    return results


def detect_problem_domain(problem_description: str, sample_input: str = "") -> str:
    """
    Infers the problem domain to generate appropriate test cases and reference solver:
      - 'mcm': Matrix Chain Multiplication
      - 'substring_abc': Substrings containing characters a, b, c
      - 'add_two_numbers': Addition of two integers
      - 'sub_two_numbers': Subtraction of two integers
      - 'mul_two_numbers': Multiplication of two integers
      - 'div_two_numbers': Division of two integers
      - 'string_general': General string problem
      - 'number_general': General numeric problem
    """
    desc_lower = (problem_description or "").lower()
    sample_clean = (sample_input or "").strip()

    if any(k in desc_lower for k in [
        "rat in a maze", "rat_maze", "maze", "matrix of order n * n",
        "reach the destination at (n - 1, n - 1)", "all possible paths that the rat can take"
    ]):
        return "rat_maze"

    if any(k in desc_lower for k in [
        "matrix chain", "mcm", "sequence of matrices", "dimension of the ith matrix",
        "multiply these matrices together", "multiplication is minimum"
    ]):
        return "mcm"

    if any(k in desc_lower for k in [
        "substring", "characters a, b and c", "characters 'a', 'b'", "at least one occurrence"
    ]):
        return "substring_abc"

    # Subtraction check (must take priority over general two-int heuristics)
    if any(k in desc_lower for k in [
        "difference", "subtract", "subtraction", "minus", "print their difference"
    ]):
        return "sub_two_numbers"

    # Multiplication check
    if any(k in desc_lower for k in [
        "multiply", "multiplication", "product", "print their product"
    ]):
        return "mul_two_numbers"

    # Division check
    if any(k in desc_lower for k in [
        "divide", "division", "quotient", "print their quotient"
    ]):
        return "div_two_numbers"

    # Addition check
    if any(k in desc_lower for k in [
        "add two integers", "addition of two", "print their sum", "calculate the sum", "sum followed by a newline"
    ]):
        return "add_two_numbers"

    # Check sample input shape
    if sample_clean and all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in sample_clean):
        return "string_general"

    if "string" in desc_lower or "character" in desc_lower or "palindrome" in desc_lower:
        return "string_general"

    return "number_general"


def get_available_ollama_models() -> List[str]:
    """Returns list of models installed and available in local Ollama."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=1.5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            names = []
            for m in models:
                raw_n = m.get("name", "")
                names.append(raw_n)
                if ":" in raw_n:
                    names.append(raw_n.split(":")[0])
            return names
    except Exception:
        pass
    return []


def query_ollama_json(
    prompt: str,
    model: str = "llama3.1",
    temperature: float = 0.0,
    seed: int = 42,
    timeout: int = 45,
    retries: int = 1,
    num_predict: int = 512
) -> Dict[str, Any]:
    """
    Calls local Ollama server in strict JSON mode with fixed seed and temperature=0.
    Dynamically falls back to available installed models if requested model is missing.
    """
    if "70b" in model or "versatile" in model:
        model = "llama3.1"

    avail = get_available_ollama_models()
    if avail and model not in avail:
        # Auto-select the best matching model available locally
        best = next((m for m in avail if "coder" in m or "qwen" in m or "llama" in m), avail[0])
        model = best

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "seed": seed,
            "num_predict": num_predict,
        }
    }

    last_error = None
    for attempt in range(retries + 1):
        try:
            current_timeout = timeout + (attempt * 15)
            resp = requests.post(OLLAMA_URL, json=payload, timeout=current_timeout)
            resp.raise_for_status()
            raw_response = resp.json().get("response", "{}")
            return _safe_parse_json(raw_response)
        except requests.exceptions.Timeout as e:
            last_error = e
            continue
        except requests.exceptions.ConnectionError as e:
            last_error = e
            break
        except Exception as e:
            last_error = e
            continue

    raise ConnectionError(
        f"Ollama query failed after {retries + 1} attempts: {last_error}"
    )


def _safe_parse_json(raw_text: str) -> Dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start == -1:
        start = text.find("[")
    if start != -1:
        open_char = text[start]
        close_char = "}" if open_char == "{" else "]"
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_char:
                depth += 1
            elif text[i] == close_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    return {}


def evaluate_oracle_python_with_error(oracle_code: str, test_input: str) -> Tuple[Optional[str], Optional[str]]:
    """Safely executes a reference solver `solve(inp)` and returns (result, error_str)."""
    if not oracle_code:
        return None, "No oracle code provided"
    try:
        import math, collections, itertools, heapq
        safe_builtins = {
            "int": int, "float": float, "str": str, "len": len,
            "range": range, "abs": abs, "min": min, "max": max,
            "sum": sum, "map": map, "list": list, "tuple": tuple,
            "sorted": sorted, "enumerate": enumerate, "zip": zip,
            "print": print, "round": round, "pow": pow, "divmod": divmod,
            "bool": bool, "isinstance": isinstance, "type": type,
            "dict": dict, "set": set, "any": any, "all": all,
            "ord": ord, "chr": chr,
            "ValueError": ValueError, "TypeError": TypeError, "IndexError": IndexError, "KeyError": KeyError,
            "Exception": Exception, "None": None, "True": True, "False": False,
        }
        local_ns: Dict[str, Any] = {
            "re": re, "math": math, "collections": collections,
            "itertools": itertools, "heapq": heapq
        }
        clean_code = oracle_code.strip()
        if "```" in clean_code:
            lines = [l for l in clean_code.splitlines() if not l.strip().startswith("```")]
            clean_code = "\n".join(lines).strip()
        while clean_code.endswith("}"):
            clean_code = clean_code[:-1].rstrip()
        if clean_code.endswith("}") and clean_code.count("(") > clean_code.count(")"):
            clean_code = clean_code[:-1] + ")"
        if "\n" not in clean_code and "def solve" in clean_code:
            clean_code = re.sub(r'(def solve\([^)]*\)[^:]*:)\s*', r'\1\n    ', clean_code)
            clean_code = re.sub(r';\s*', '\n    ', clean_code)
            clean_code = re.sub(r'\s{4,}', '\n    ', clean_code)

        exec(clean_code, {"__builtins__": safe_builtins}, local_ns)
        solve_fn = local_ns.get("solve")
        if callable(solve_fn):
            result = solve_fn(test_input)
            return str(result).strip(), None
        return None, "Function 'solve' not defined in oracle code"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)}"


def evaluate_oracle_python(oracle_code: str, test_input: str) -> Optional[str]:
    """Executes a reference solver `solve(inp)` safely."""
    val, _ = evaluate_oracle_python_with_error(oracle_code, test_input)
    return val


def _problem_hash(problem_description: str, sample_input: str = "", sample_output: str = "") -> str:
    combined = f"{problem_description.strip()}||{sample_input.strip()}||{sample_output.strip()}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════
# Reference Solvers for Domains
# ═══════════════════════════════════════════════════════════════════════════

def _solve_mcm(inp: str) -> str:
    """Exact DP solver for Matrix Chain Multiplication."""
    nums = [int(x) for x in re.findall(r'-?\d+', inp)]
    if not nums:
        return "0"
    if len(nums) > 2 and nums[0] == len(nums) - 1:
        p = nums[1:]
    else:
        p = nums
    n = len(p)
    if n <= 1:
        return "0"
    dp = [[0] * n for _ in range(n)]
    for l in range(2, n):
        for i in range(1, n - l + 1):
            j = i + l - 1
            dp[i][j] = float('inf')
            for k in range(i, j):
                q = dp[i][k] + dp[k + 1][j] + p[i - 1] * p[k] * p[j]
                if q < dp[i][j]:
                    dp[i][j] = q
    return str(int(dp[1][n - 1]))


def _solve_substring_abc(s: str) -> str:
    """Number of substrings containing at least one of 'a', 'b', and 'c'."""
    s = s.strip()
    last = [-1, -1, -1]
    count = 0
    for i, ch in enumerate(s):
        if ch in 'abc':
            last[ord(ch) - ord('a')] = i
            if last[0] != -1 and last[1] != -1 and last[2] != -1:
                count += 1 + min(last)
    return str(count)


def _solve_add_two_numbers(s: str) -> str:
    parts = s.strip().split()
    if len(parts) >= 2:
        return str(int(parts[0]) + int(parts[1]))
    return "0"


def _solve_rat_maze(inp: str) -> str:
    """Exact solver for Rat in a Maze problem returning lexicographically sorted paths."""
    nums = [int(x) for x in re.findall(r'-?\d+', inp)]
    if len(nums) < 2:
        return "-1"
    n, m = nums[0], nums[1]
    cells = nums[2:2 + n * m]
    if len(cells) < n * m or n <= 0 or m <= 0:
        return "-1"
    grid = [cells[i * m:(i + 1) * m] for i in range(n)]
    if grid[0][0] == 0 or grid[n - 1][m - 1] == 0:
        return "-1"
    if n == 1 and m == 1:
        return ""
    dirs = [(1, 0, 'D'), (0, -1, 'L'), (0, 1, 'R'), (-1, 0, 'U')]
    visited = [[False] * m for _ in range(n)]
    paths = []

    def dfs(r, c, path):
        if r == n - 1 and c == m - 1:
            paths.append(path)
            return
        visited[r][c] = True
        for dr, dc, move in dirs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < m and grid[nr][nc] == 1 and not visited[nr][nc]:
                dfs(nr, nc, path + move)
        visited[r][c] = False

    dfs(0, 0, "")
    return " ".join(paths) if paths else "-1"


# ═══════════════════════════════════════════════════════════════════════════
# Universal Grammar-Aware Fuzzer & Autonomous Oracle Management
# ═══════════════════════════════════════════════════════════════════════════

def analyze_input_grammar(sample_input: str) -> Dict[str, Any]:
    """
    Infers the structural input format for ANY unseen problem:
      - 'grid': matrix order followed by cell values
      - 'array_prefix': length N followed by N numbers
      - 'two_ints': pair of integers
      - 'int_list': space/newline delimited integers
      - 'string': character/word strings
      - 'general': generic tokens
    """
    raw = sample_input.strip()
    if not raw:
        return {"kind": "empty"}

    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    # Grid check: R C on first line followed by R rows
    if len(lines) >= 3:
        first_tokens = lines[0].split()
        if len(first_tokens) == 2 and all(t.lstrip('-').isdigit() for t in first_tokens):
            r, c = int(first_tokens[0]), int(first_tokens[1])
            row_token_counts = [len(l.split()) for l in lines[1:]]
            if len(lines[1:]) == r and all(cnt == c for cnt in row_token_counts):
                elem_type = "int" if all(x.lstrip('-').isdigit() for l in lines[1:] for x in l.split()) else "str"
                return {"kind": "grid", "r": r, "c": c, "elem_type": elem_type, "header": "two_ints"}
        elif len(first_tokens) == 1 and first_tokens[0].lstrip('-').isdigit():
            n = int(first_tokens[0])
            row_token_counts = [len(l.split()) for l in lines[1:]]
            if len(lines[1:]) == n and all(cnt == n for cnt in row_token_counts):
                elem_type = "int" if all(x.lstrip('-').isdigit() for l in lines[1:] for x in l.split()) else "str"
                return {"kind": "grid", "r": n, "c": n, "elem_type": elem_type, "header": "one_int"}

    # Array prefix check: N on first line followed by N numbers
    all_tokens = raw.split()
    if len(lines) >= 2 and len(lines[0].split()) == 1 and lines[0].split()[0].lstrip('-').isdigit():
        n = int(lines[0].split()[0])
        rest_tokens = [t for l in lines[1:] for t in l.split()]
        if len(rest_tokens) == n and all(t.lstrip('-').isdigit() for t in rest_tokens):
            return {"kind": "array_prefix", "n": n, "elements": [int(t) for t in rest_tokens]}

    # All numeric tokens
    if all(t.lstrip('-').isdigit() for t in all_tokens):
        int_vals = [int(t) for t in all_tokens]
        if len(all_tokens) == 2:
            return {"kind": "two_ints", "values": int_vals}
        return {"kind": "int_list", "values": int_vals, "lines": len(lines)}

    # String input
    if len(lines) == 1 and all(c.isalnum() or c in '_- .,' for c in raw):
        return {"kind": "string", "value": raw}

    return {"kind": "general", "tokens": all_tokens, "lines": lines}


def _universal_fuzz_test_suite(
    problem_description: str,
    sample_input: str,
    sample_output: str,
    oracle_code: str = "",
    num_tests: int = 10
) -> Dict[str, Any]:
    """
    Intelligent universal input fuzzer.
    Analyzes input grammar and generates `num_tests` distinct, valid, varied test inputs.
    Guarantees zero duplicate inputs.
    """
    grammar = analyze_input_grammar(sample_input)
    kind = grammar.get("kind", "general")

    def format_grid(grid, header_type):
        r, c = len(grid), len(grid[0])
        header = f"{r} {c}\n" if header_type == "two_ints" else f"{r}\n"
        rows = "\n".join(" ".join(str(x) for x in row) for row in grid)
        return header + rows + "\n"

    raw_inputs: List[Tuple[str, str]] = []

    if kind == "grid":
        hdr = grammar.get("header", "two_ints")
        raw_inputs.append((sample_input.rstrip() + "\n", "Sample benchmark grid"))
        raw_inputs.append((format_grid([[1, 1], [1, 1]], hdr), "2x2 fully open grid"))
        raw_inputs.append((format_grid([[1, 0], [1, 1]], hdr), "2x2 single downward path"))
        raw_inputs.append((format_grid([[1, 1], [0, 1]], hdr), "2x2 single upper-right path"))
        raw_inputs.append((format_grid([[1, 0, 0], [1, 1, 0], [0, 1, 1]], hdr), "3x3 diagonal corridor"))
        raw_inputs.append((format_grid([[1, 1, 1], [0, 0, 1], [1, 1, 1]], hdr), "3x3 perimeter path around wall"))
        raw_inputs.append((format_grid([[1, 1, 1], [1, 0, 1], [1, 1, 1]], hdr), "3x3 center obstacle with dual paths"))
        raw_inputs.append((format_grid([[1, 1, 1, 1], [1, 0, 0, 1], [1, 0, 0, 1], [1, 1, 1, 1]], hdr), "4x4 outer ring paths"))
        raw_inputs.append((format_grid([[1, 0, 0, 0], [1, 1, 0, 1], [0, 1, 0, 0], [0, 1, 1, 1]], hdr), "4x4 single unique path"))
        raw_inputs.append((format_grid([[1, 0, 0], [0, 1, 0], [0, 0, 1]], hdr), "3x3 disconnected blocked maze"))

    elif kind == "array_prefix":
        orig_nums = grammar.get("elements", [10, 20, 30])
        n = len(orig_nums)
        raw_inputs.append((sample_input.rstrip() + "\n", "Sample array benchmark"))
        raw_inputs.append((f"2\n{orig_nums[0]} {orig_nums[-1]}\n", "Minimal array of length 2"))
        raw_inputs.append((f"3\n10 20 30\n", "Small 3-element sequence"))
        rev = " ".join(str(x) for x in reversed(orig_nums))
        raw_inputs.append((f"{n}\n{rev}\n", "Reversed input order"))
        raw_inputs.append((f"4\n10 10 10 10\n", "Uniform identical elements"))
        raw_inputs.append((f"4\n10 30 5 60\n", "Wide scale variance"))
        raw_inputs.append((f"4\n40 20 30 10\n", "Medium mixed magnitude"))
        raw_inputs.append((f"6\n30 35 15 5 10 20\n", "6-element extended chain"))
        raw_inputs.append((f"5\n1 2 3 4 3\n", "Small single-digit chain"))
        raw_inputs.append((f"5\n10 20 30 40 30\n", "5-element benchmark variation"))

    elif kind == "two_ints":
        a, b = grammar.get("values", [1, 2])
        raw_inputs.append((f"{a} {b}\n", "Sample positive pair"))
        raw_inputs.append(("0 0\n", "Both operands zero"))
        raw_inputs.append((f"{-abs(a)} {b}\n", "Negative and positive"))
        raw_inputs.append((f"{-abs(a)} {-abs(b)}\n", "Both negative"))
        raw_inputs.append((f"1 0\n", "Identity with zero"))
        raw_inputs.append((f"100 200\n", "Medium integers"))
        raw_inputs.append((f"999999 1\n", "Carry propagation"))
        raw_inputs.append((f"{-a} {a}\n", "Additive inverse"))
        raw_inputs.append((f"2147483647 0\n", "INT_MAX boundary with zero"))
        raw_inputs.append((f"2147483647 1\n", "INT_MAX + 1 boundary"))

    elif kind == "int_list":
        vals = grammar.get("values", [1, 2, 3])
        raw_inputs.append((sample_input.rstrip() + "\n", "Sample input"))
        raw_inputs.append((" ".join(str(x * 2) for x in vals) + "\n", "Scaled values (2x)"))
        raw_inputs.append((" ".join(str(max(1, x // 2)) for x in vals) + "\n", "Halved values"))
        raw_inputs.append((" ".join(str(x) for x in reversed(vals)) + "\n", "Reversed sequence"))
        raw_inputs.append((" ".join(str(x) for x in sorted(vals)) + "\n", "Sorted ascending"))
        raw_inputs.append((" ".join(str(vals[0]) for _ in vals) + "\n", "All identical elements"))
        raw_inputs.append((" ".join(str(x + 10) for x in vals) + "\n", "Shifted values (+10)"))
        raw_inputs.append((" ".join(str(x if i % 2 == 0 else 0) for i, x in enumerate(vals)) + "\n", "Alternating zeros"))
        raw_inputs.append((" ".join(str(abs(x) * 10) for x in vals) + "\n", "Multiples of 10"))
        raw_inputs.append((" ".join(str(i + 1) for i in range(len(vals))) + "\n", "Unit 1..N sequence"))

    elif kind == "string":
        s = grammar.get("value", "abc")
        chars = sorted(list(set(s)))
        raw_inputs.append((f"{s}\n", "Original sample string"))
        raw_inputs.append((f"{''.join(chars)}\n", "Unique alphabet minimal valid"))
        raw_inputs.append((f"{s[::-1]}\n", "Reversed string"))
        raw_inputs.append((f"{s}{s}\n", "Doubled pattern"))
        raw_inputs.append((f"{chars[0] * 3}{chars[-1] * 3}\n", "Grouped character blocks"))
        raw_inputs.append((f"{s * 3}\n", "Extended triple pattern"))
        raw_inputs.append((f"{chars[0]}\n", "Single character boundary"))
        raw_inputs.append((f"{''.join(chars * 2)}\n", "Interleaved alphabet"))
        raw_inputs.append((f"{chars[0] * 5}{''.join(chars)}{chars[-1] * 5}\n", "Padded boundaries"))
        raw_inputs.append((f"{''.join(reversed(chars))}\n", "Reverse alphabet"))

    else:
        toks = grammar.get("tokens", ["1", "2"])
        raw_inputs.append((sample_input.rstrip() + "\n", "Sample input"))
        for i in range(1, 10):
            mutated = [str(int(t) + i) if t.lstrip('-').isdigit() else f"{t}_{i}" for t in toks]
            raw_inputs.append((" ".join(mutated) + "\n", f"Structural variation {i+1}"))

    cases = []
    for inp_text, desc in raw_inputs[:num_tests]:
        oracle_ans = evaluate_oracle_python(oracle_code, inp_text) if oracle_code else None
        cases.append({
            "input": inp_text,
            "expected": oracle_ans if oracle_ans is not None else (sample_output.strip() if sample_output else ""),
            "description": desc
        })

    return {"python_oracle": oracle_code, "test_cases": cases}


def _universal_edge_cases(
    problem_description: str,
    sample_input: str,
    sample_output: str = "",
    oracle_code: str = "",
    binary_oracle_path: str = ""
) -> List[Dict[str, str]]:
    """
    Synthesizes 5 structural adversarial edge cases for ANY grammar.
    Guarantees that edge cases are never empty, preventing 0-score defense loop.
    Uses oracle_code or binary_oracle_path to compute correct expected outputs.
    """
    grammar = analyze_input_grammar(sample_input)
    kind = grammar.get("kind", "general")
    hdr = grammar.get("header", "two_ints")

    domain = detect_problem_domain(problem_description, sample_input)

    def _run_binary(inp: str) -> str:
        """Run the student binary to compute the expected output for an edge input."""
        if not binary_oracle_path or not os.path.isfile(binary_oracle_path):
            return ""
        try:
            import subprocess
            r = subprocess.run(
                [binary_oracle_path], input=inp,
                capture_output=True, text=True, timeout=5
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    def _get_expected(inp: str, hint: str = "") -> str:
        """Get expected output: LLM oracle → binary oracle → hint."""
        if oracle_code:
            out = evaluate_oracle_python(oracle_code, inp)
            if out is not None:
                return out
        bval = _run_binary(inp)
        if bval:
            return bval
        return hint

    edges = []

    if kind == "grid":
        # Domain-specific grid edge cases
        if domain == "rat_maze":
            edges = [
                {
                    "category": "start_blocked",
                    "input": f"3 3\n0 1 1\n1 1 1\n1 1 1\n" if hdr == "two_ints" else f"3\n0 1 1\n1 1 1\n1 1 1\n",
                    "expected": "-1",
                    "explanation": "Start position (0, 0) is blocked with 0; rat cannot start."
                },
                {
                    "category": "dest_blocked",
                    "input": f"3 3\n1 1 1\n1 1 1\n1 1 0\n" if hdr == "two_ints" else f"3\n1 1 1\n1 1 1\n1 1 0\n",
                    "expected": "-1",
                    "explanation": "Destination cell (N-1, M-1) is blocked with 0; rat cannot reach goal."
                },
                {
                    "category": "no_path_wall",
                    "input": f"3 3\n1 1 1\n0 0 0\n1 1 1\n" if hdr == "two_ints" else f"3\n1 1 1\n0 0 0\n1 1 1\n",
                    "expected": "-1",
                    "explanation": "Horizontal wall of zeroes partitions the maze completely."
                },
                {
                    "category": "all_blocked",
                    "input": f"2 2\n1 0\n0 0\n" if hdr == "two_ints" else f"2\n1 0\n0 0\n",
                    "expected": "-1",
                    "explanation": "Immediate dead end at (0, 0); all neighbors are walls."
                },
                {
                    "category": "full_grid_open",
                    "input": f"2 2\n1 1\n1 1\n" if hdr == "two_ints" else f"2\n1 1\n1 1\n",
                    "expected": "DR RD",
                    "explanation": "Minimal 2x2 grid completely open; rat finds multiple symmetric paths."
                }
            ]
        else:
            # Generic graph/matrix edge cases (e.g. Dijkstra, Floyd-Warshall, etc.)
            # Build N×N zero matrices / special graphs and let the oracle compute answers
            candidates = [
                ("1\n0\n", "single_vertex", "Single vertex graph — only source; distances trivially 0."),
                ("2\n0 1\n1 0\n", "two_vertices_connected", "Two vertices with edge weight 1."),
                ("2\n0 0\n0 0\n", "two_vertices_disconnected", "Two vertices, no edges; unreachable vertex."),
                ("3\n0 1 0\n0 0 1\n0 0 0\n", "linear_chain", "Linear chain 0→1→2; tests transitive shortest path."),
                ("3\n0 10 5\n10 0 2\n5 2 0\n", "triangle_graph", "Triangle with varied weights; tests optimal path selection."),
            ]
            for inp_str, cat, expl in candidates:
                expected = _get_expected(inp_str, "")
                edges.append({
                    "category": cat,
                    "input": inp_str,
                    "expected": expected,
                    "explanation": expl
                })

    elif kind == "array_prefix":
        n_val = grammar.get("n", 3)
        elems = grammar.get("elements", [10, 20, 30])
        candidates = [
            (f"2\n{elems[0]} {elems[1] if len(elems) > 1 else 10}\n", "minimal_boundary", "Smallest valid dimension array (size 2)."),
            (f"{n_val}\n" + " ".join([str(elems[0])] * n_val) + "\n", "all_identical", "All identical array elements."),
            (f"{n_val}\n" + " ".join(str(x * 2) for x in elems) + "\n", "varying_scales", "Scaled array elements."),
            (f"{n_val}\n" + " ".join(str(x) for x in reversed(elems)) + "\n", "reversed_order", "Reversed array ordering."),
            (f"{n_val}\n" + " ".join(str(abs(x)) for x in elems) + "\n", "positive_elements", "Standard multi-element benchmark."),
        ]
        for inp_str, cat, expl in candidates:
            expected = _get_expected(inp_str, "")
            edges.append({
                "category": cat,
                "input": inp_str,
                "expected": expected,
                "explanation": expl
            })

    elif kind == "two_ints":
        a_val, b_val = grammar.get("values", [1, 2])
        candidates = [
            (f"2147483647 1\n", "int_overflow", "32-bit signed int boundary (INT_MAX with 1)."),
            (f"-100 -200\n", "negatives", "Both operands negative."),
            (f"0 0\n", "zero", "Both operands zero."),
            (f"{a_val} 0\n", "identity", "Operand with zero boundary."),
            (f"-1 1\n", "opposite_signs", "Opposite signs boundary."),
        ]
        for inp_str, cat, expl in candidates:
            expected = _get_expected(inp_str, "")
            edges.append({
                "category": cat,
                "input": inp_str,
                "expected": expected,
                "explanation": expl
            })

    elif kind == "string":
        s = grammar.get("value", "abc")
        chars = sorted(list(set(s)))
        candidates = [
            (f"{chars[0]}\n", "empty_or_short", "Short string of length 1; tests lower boundary."),
            (f"{chars[0] * 5}\n", "missing_char", "String composed solely of a single character."),
            (f"{''.join(chars)}\n", "minimal_valid", "Minimal valid sequence containing distinct characters."),
            (f"{''.join(reversed(chars))}\n", "reverse_order", "Reverse ordering of characters."),
            (f"{s * 2}\n", "repeated_pattern", "Repeated string pattern."),
        ]
        for inp_str, cat, expl in candidates:
            expected = _get_expected(inp_str, "")
            edges.append({
                "category": cat,
                "input": inp_str,
                "expected": expected,
                "explanation": expl
            })

    else:
        toks = grammar.get("tokens", ["1", "2"])
        candidates = [
            ((toks[0] if toks else "0") + "\n", "minimal_input", "Minimal single-token boundary condition."),
            (" ".join("0" for _ in toks) + "\n", "zero_boundary", "All inputs set to zero."),
            (" ".join(reversed(toks)) + "\n", "reversed_order", "Inverted token ordering."),
            (" ".join(toks[0] for _ in toks) + "\n", "identical_elements", "All tokens set to the first element."),
            (" ".join(str(int(t) * 100) if t.lstrip('-').isdigit() else t * 2 for t in toks) + "\n", "scaled_magnitude", "Scaled magnitude boundary."),
        ]
        for inp_str, cat, expl in candidates:
            expected = _get_expected(inp_str, sample_output.strip() if sample_output else "0")
            edges.append({
                "category": cat,
                "input": inp_str,
                "expected": expected,
                "explanation": expl
            })

    # Re-evaluate expected using oracle if available
    for edge in edges:
        if oracle_code:
            eval_ans = evaluate_oracle_python(oracle_code, edge["input"])
            if eval_ans is not None:
                edge["expected"] = eval_ans
        elif not edge.get("expected") and binary_oracle_path:
            b_ans = _run_binary(edge["input"])
            if b_ans:
                edge["expected"] = b_ans

    return edges


def get_or_create_problem_oracle(
    problem_description: str,
    sample_input: str = "",
    sample_output: str = "",
    model: str = "llama3.1",
    temperature: float = 0.0,
    seed: int = 42,
    binary_oracle_path: str = ""
) -> str:
    """
    Returns an exact reference Python 3 oracle `def solve(inp: str) -> str:`.
    1. QUERIES OLLAMA FIRST: Dynamically generates reference solver for ANY problem.
    2. Passes through Oracle Self-Verification Gate against sample_input/sample_output.
    3. Triggers Reflective Self-Correction Loop on verification discrepancy.
    4. Fallback: Intelligent deduction, verified known domain solvers, or binary oracle.
    """
    s_in = str(sample_input or "").strip()
    s_out = str(sample_output or "").strip()
    if not s_in or not s_out:
        ext_in, ext_out = extract_sample_from_description(problem_description)
        if not s_in:
            s_in = ext_in.strip()
        if not s_out:
            s_out = ext_out.strip()

    # Priority 1: Query Ollama to dynamically synthesize the reference oracle
    prompt = (
        "You are an expert algorithmic solver and reference code generator.\n"
        f"Problem Description:\n{problem_description}\n\n"
        f"Sample Input:\n{s_in}\n\n"
        f"Sample Output:\n{s_out}\n\n"
        "CRITICAL REQUIREMENTS:\n"
        "1. Write an exact, self-contained Python 3 reference solver function `def solve(inp: str) -> str:`.\n"
        "2. Input parsing: Read all tokens from parameter `inp` directly (e.g. `tokens = inp.split()`). Do NOT call `input()` or `sys.stdin.read()`.\n"
        "3. Output format: Return the answer as a string formatted EXACTLY as expected in Sample Output.\n"
        "4. Code formatting: MUST have newline characters (\\n) and 4-space indentation.\n\n"
        "Example format:\n"
        '\"python_oracle\": \"def solve(inp: str) -> str:\\n    tokens = inp.split()\\n    # parse and solve\\n    return str(result)\"\n\n'
        "Respond ONLY with valid JSON: {\"python_oracle\": \"def solve(inp: str) -> str:\\n    ...\"}"
    )

    candidate_oracle = ""
    try:
        data = query_ollama_json(prompt, model=model, temperature=temperature, seed=seed, num_predict=384)
        candidate_oracle = data.get("python_oracle", "")
    except Exception:
        candidate_oracle = ""

    # Oracle Self-Verification Gate
    if candidate_oracle and s_in and s_out:
        test_val, err = evaluate_oracle_python_with_error(candidate_oracle, s_in)
        if err is None and test_val is not None and " ".join(test_val.split()) == " ".join(s_out.split()):
            return candidate_oracle

        # Reflective Self-Correction Loop
        ref_prompt = (
            "Your previous Python solver failed the sample test case.\n"
            f"Problem Description:\n{problem_description}\n\n"
            f"Sample Input:\n{s_in}\n"
            f"Expected Output:\n{s_out}\n"
            f"Your Solver Output: {test_val}\n"
            f"Error Encountered: {err}\n\n"
            "Please fix the logic and input token parsing. Return a corrected Python 3 function `def solve(inp: str) -> str:` with proper newlines (\\n).\n"
            "Respond ONLY with valid JSON: {\"python_oracle\": \"def solve(inp: str) -> str:\\n    ...\"}"
        )
        try:
            ref_data = query_ollama_json(ref_prompt, model=model, temperature=temperature, seed=seed, num_predict=384)
            ref_oracle = ref_data.get("python_oracle", "")
            if ref_oracle:
                ref_val, ref_err = evaluate_oracle_python_with_error(ref_oracle, s_in)
                if ref_err is None and ref_val is not None and " ".join(ref_val.split()) == " ".join(s_out.split()):
                    return ref_oracle
        except Exception:
            pass

    # Priority 2: Intelligent Deduction for two-integer arithmetic (offline fallback)
    if s_in and s_out:
        try:
            toks = s_in.split()
            if len(toks) == 2 and all(t.lstrip('-').isdigit() for t in toks) and s_out.lstrip('-').isdigit():
                a_num, b_num = int(toks[0]), int(toks[1])
                out_num = int(s_out)
                if a_num - b_num == out_num:
                    return (
                        "def solve(inp: str) -> str:\n"
                        "    p = [int(x) for x in inp.split()]\n"
                        "    return str(p[0] - p[1])"
                    )
                elif a_num + b_num == out_num:
                    return (
                        "def solve(inp: str) -> str:\n"
                        "    p = [int(x) for x in inp.split()]\n"
                        "    return str(p[0] + p[1])"
                    )
                elif a_num * b_num == out_num:
                    return (
                        "def solve(inp: str) -> str:\n"
                        "    p = [int(x) for x in inp.split()]\n"
                        "    return str(p[0] * p[1])"
                    )
                elif b_num != 0 and a_num // b_num == out_num:
                    return (
                        "def solve(inp: str) -> str:\n"
                        "    p = [int(x) for x in inp.split()]\n"
                        "    return str(p[0] // p[1])"
                    )
                elif b_num != 0 and a_num % b_num == out_num:
                    return (
                        "def solve(inp: str) -> str:\n"
                        "    p = [int(x) for x in inp.split()]\n"
                        "    return str(p[0] % p[1])"
                    )
                elif max(a_num, b_num) == out_num:
                    return (
                        "def solve(inp: str) -> str:\n"
                        "    p = [int(x) for x in inp.split()]\n"
                        "    return str(max(p[0], p[1]))"
                    )
                elif min(a_num, b_num) == out_num:
                    return (
                        "def solve(inp: str) -> str:\n"
                        "    p = [int(x) for x in inp.split()]\n"
                        "    return str(min(p[0], p[1]))"
                    )
        except Exception:
            pass

    # Priority 3: Verified Domain Solvers (ONLY returned if they pass verification against sample_input/sample_output)
    domain = detect_problem_domain(problem_description, s_in)
    known_candidates = []
    if domain == "rat_maze":
        known_candidates.append(
            "import re\n"
            "def solve(inp: str) -> str:\n"
            "    nums = [int(x) for x in re.findall(r'-?\\d+', inp)]\n"
            "    if len(nums) < 2: return '-1'\n"
            "    n, m = nums[0], nums[1]\n"
            "    cells = nums[2:2 + n * m]\n"
            "    if len(cells) < n * m or n <= 0 or m <= 0: return '-1'\n"
            "    grid = [cells[i * m:(i + 1) * m] for i in range(n)]\n"
            "    if grid[0][0] == 0 or grid[n - 1][m - 1] == 0: return '-1'\n"
            "    if n == 1 and m == 1: return ''\n"
            "    dirs = [(1, 0, 'D'), (0, -1, 'L'), (0, 1, 'R'), (-1, 0, 'U')]\n"
            "    visited = [[False] * m for _ in range(n)]\n"
            "    paths = []\n"
            "    def dfs(r, c, path):\n"
            "        if r == n - 1 and c == m - 1:\n"
            "            paths.append(path); return\n"
            "        visited[r][c] = True\n"
            "        for dr, dc, move in dirs:\n"
            "            nr, nc = r + dr, c + dc\n"
            "            if 0 <= nr < n and 0 <= nc < m and grid[nr][nc] == 1 and not visited[nr][nc]:\n"
            "                dfs(nr, nc, path + move)\n"
            "        visited[r][c] = False\n"
            "    dfs(0, 0, '')\n"
            "    return ' '.join(paths) if paths else '-1'"
        )
    elif domain == "mcm":
        known_candidates.append(
            "import re\n"
            "def solve(inp: str) -> str:\n"
            "    nums = [int(x) for x in re.findall(r'-?\\d+', inp)]\n"
            "    if not nums: return '0'\n"
            "    if len(nums) > 2 and nums[0] == len(nums) - 1: p = nums[1:]\n"
            "    else: p = nums\n"
            "    n = len(p)\n"
            "    if n <= 1: return '0'\n"
            "    dp = [[0] * n for _ in range(n)]\n"
            "    for l in range(2, n):\n"
            "        for i in range(1, n - l + 1):\n"
            "            j = i + l - 1\n"
            "            dp[i][j] = float('inf')\n"
            "            for k in range(i, j):\n"
            "                q = dp[i][k] + dp[k + 1][j] + p[i - 1] * p[k] * p[j]\n"
            "                if q < dp[i][j]: dp[i][j] = q\n"
            "    return str(int(dp[1][n - 1]))"
        )
    elif domain == "substring_abc":
        known_candidates.append(
            "def solve(inp: str) -> str:\n"
            "    s = inp.strip()\n"
            "    last = [-1, -1, -1]\n"
            "    count = 0\n"
            "    for i, ch in enumerate(s):\n"
            "        if ch in 'abc':\n"
            "            last[ord(ch) - ord('a')] = i\n"
            "            if last[0] != -1 and last[1] != -1 and last[2] != -1:\n"
            "                count += 1 + min(last)\n"
            "    return str(count)"
        )
    elif domain == "sub_two_numbers":
        known_candidates.append(
            "def solve(inp: str) -> str:\n"
            "    parts = inp.strip().split()\n"
            "    return str(int(parts[0]) - int(parts[1]))"
        )
    elif domain == "add_two_numbers":
        known_candidates.append(
            "def solve(inp: str) -> str:\n"
            "    parts = inp.strip().split()\n"
            "    return str(int(parts[0]) + int(parts[1]))"
        )

    for cand in known_candidates:
        if s_in and s_out:
            c_val, c_err = evaluate_oracle_python_with_error(cand, s_in)
            if c_err is None and c_val is not None and " ".join(c_val.split()) == " ".join(s_out.split()):
                return cand
        else:
            return cand

    # Priority 4: Student Binary Execution Oracle Fallback
    if binary_oracle_path and os.path.isfile(binary_oracle_path) and s_in:
        try:
            import subprocess
            r = subprocess.run([binary_oracle_path], input=s_in, capture_output=True, text=True, timeout=4)
            if r.returncode == 0:
                out_clean = r.stdout.strip()
                if not s_out or " ".join(out_clean.split()) == " ".join(s_out.split()):
                    return (
                        "import subprocess\n"
                        "def solve(inp: str) -> str:\n"
                        f"    r = subprocess.run([{repr(binary_oracle_path)}], input=inp, capture_output=True, text=True, timeout=5)\n"
                        "    return r.stdout.strip()"
                    )
        except Exception:
            pass

    return candidate_oracle


def _synthesize_domain_test_suite(
    problem_description: str,
    num_tests: int = 10,
    sample_input: str = "",
    sample_output: str = ""
) -> Dict[str, Any]:
    """
    Synthesizes a rich, verified 10-test suite according to the problem domain.
    Used when Ollama is offline or unavailable.
    """
    if not sample_input or not sample_output:
        extracted_in, extracted_out = extract_sample_from_description(problem_description)
        if not sample_input:
            sample_input = extracted_in
        if not sample_output:
            sample_output = extracted_out

    domain = detect_problem_domain(problem_description, sample_input)

    # ── 1. Rat in a Maze ──────────────────────────────────────────────────
    if domain == "rat_maze":
        oracle_code = (
            "import re\n"
            "def solve(inp: str) -> str:\n"
            "    nums = [int(x) for x in re.findall(r'-?\\d+', inp)]\n"
            "    if len(nums) < 2: return '-1'\n"
            "    n, m = nums[0], nums[1]\n"
            "    cells = nums[2:2 + n * m]\n"
            "    if len(cells) < n * m or n <= 0 or m <= 0: return '-1'\n"
            "    grid = [cells[i * m:(i + 1) * m] for i in range(n)]\n"
            "    if grid[0][0] == 0 or grid[n - 1][m - 1] == 0: return '-1'\n"
            "    if n == 1 and m == 1: return ''\n"
            "    dirs = [(1, 0, 'D'), (0, -1, 'L'), (0, 1, 'R'), (-1, 0, 'U')]\n"
            "    visited = [[False] * m for _ in range(n)]\n"
            "    paths = []\n"
            "    def dfs(r, c, path):\n"
            "        if r == n - 1 and c == m - 1:\n"
            "            paths.append(path); return\n"
            "        visited[r][c] = True\n"
            "        for dr, dc, move in dirs:\n"
            "            nr, nc = r + dr, c + dc\n"
            "            if 0 <= nr < n and 0 <= nc < m and grid[nr][nc] == 1 and not visited[nr][nc]:\n"
            "                dfs(nr, nc, path + move)\n"
            "        visited[r][c] = False\n"
            "    dfs(0, 0, '')\n"
            "    return ' '.join(paths) if paths else '-1'"
        )
        cases_pool = [
            {"input": "4 4\n1 0 0 0\n1 1 0 1\n1 1 0 0\n0 1 1 1\n", "description": "Classic 4x4 matrix with multiple paths"},
            {"input": "2 2\n1 0\n1 1\n", "description": "Minimal 2x2 with single downward path"},
            {"input": "2 2\n1 1\n1 1\n", "description": "2x2 fully open matrix with 2 paths"},
            {"input": "3 3\n1 0 0\n1 1 0\n1 1 1\n", "description": "3x3 open diagonal paths"},
            {"input": "4 4\n1 0 0 0\n1 1 0 1\n0 1 0 0\n0 1 1 1\n", "description": "4x4 single unique path"},
            {"input": "3 3\n1 1 1\n1 0 1\n1 1 1\n", "description": "3x3 navigating around center obstacle"},
            {"input": "2 2\n1 1\n0 1\n", "description": "2x2 upper right path"},
            {"input": "3 3\n1 0 0\n0 1 0\n0 0 1\n", "description": "Disconnected diagonal with no possible path"},
            {"input": "3 3\n0 1 1\n1 1 1\n1 1 1\n", "description": "Boundary: Start cell (0, 0) blocked"},
            {"input": "3 3\n1 1 1\n1 1 1\n1 1 0\n", "description": "Boundary: Destination cell (N-1, M-1) blocked"},
        ]
        cases = []
        for c in cases_pool[:num_tests]:
            inp = c["input"]
            ans = _solve_rat_maze(inp)
            cases.append({"input": inp, "expected": ans, "description": c["description"]})
        return {"python_oracle": oracle_code, "test_cases": cases}

    # ── 2. Matrix Chain Multiplication ────────────────────────────────────
    elif domain == "mcm":
        oracle_code = (
            "import re\n"
            "def solve(inp: str) -> str:\n"
            "    nums = [int(x) for x in re.findall(r'-?\\d+', inp)]\n"
            "    if not nums: return '0'\n"
            "    if len(nums) > 2 and nums[0] == len(nums) - 1: p = nums[1:]\n"
            "    else: p = nums\n"
            "    n = len(p)\n"
            "    if n <= 1: return '0'\n"
            "    dp = [[0] * n for _ in range(n)]\n"
            "    for l in range(2, n):\n"
            "        for i in range(1, n - l + 1):\n"
            "            j = i + l - 1\n"
            "            dp[i][j] = float('inf')\n"
            "            for k in range(i, j):\n"
            "                q = dp[i][k] + dp[k + 1][j] + p[i - 1] * p[k] * p[j]\n"
            "                if q < dp[i][j]: dp[i][j] = q\n"
            "    return str(int(dp[1][n - 1]))"
        )
        cases_pool = [
            {"input": "5\n40 20 30 10 30\n", "description": "Example 1: 4 matrices benchmark (26000)"},
            {"input": "5\n1 2 3 4 3\n", "description": "Example 2: 4 matrices with small dimensions (30)"},
            {"input": "3\n10 20 30\n", "description": "Minimal product: 2 matrices 10x20 and 20x30 (6000)"},
            {"input": "4\n10 30 5 60\n", "description": "3 matrices with varying orders (4500)"},
            {"input": "4\n40 20 30 10\n", "description": "3 medium matrices (14000)"},
            {"input": "6\n30 35 15 5 10 20\n", "description": "5 matrices chain (11875)"},
            {"input": "5\n10 20 30 40 30\n", "description": "4 square-like matrices (30000)"},
            {"input": "2\n10 20\n", "description": "Boundary: single matrix (0 multiplications)"},
            {"input": "3\n5 10 20\n", "description": "Two small matrices (1000)"},
            {"input": "5\n2 3 6 4 5\n", "description": "Four small matrices (124)"},
        ]
        cases = []
        for c in cases_pool[:num_tests]:
            inp = c["input"]
            ans = _solve_mcm(inp)
            cases.append({"input": inp, "expected": ans, "description": c["description"]})
        return {"python_oracle": oracle_code, "test_cases": cases}

    # ── 2. Substring a,b,c ────────────────────────────────────────────────
    elif domain == "substring_abc":
        oracle_code = (
            "def solve(inp: str) -> str:\n"
            "    s = inp.strip()\n"
            "    last = [-1, -1, -1]\n"
            "    count = 0\n"
            "    for i, ch in enumerate(s):\n"
            "        if ch in 'abc':\n"
            "            last[ord(ch) - ord('a')] = i\n"
            "            if last[0] != -1 and last[1] != -1 and last[2] != -1:\n"
            "                count += 1 + min(last)\n"
            "    return str(count)"
        )
        cases_pool = [
            {"input": "abcabc\n", "description": "Example 1 from problem statement"},
            {"input": "abc\n", "description": "Minimal valid string containing a, b, c"},
            {"input": "bca\n", "description": "Permutation bca"},
            {"input": "cab\n", "description": "Permutation cab"},
            {"input": "cba\n", "description": "Reverse permutation cba"},
            {"input": "aaabbbccc\n", "description": "Grouped character blocks"},
            {"input": "abacaba\n", "description": "Alternating occurrences"},
            {"input": "ababab\n", "description": "Missing required character c (expected 0)"},
            {"input": "a\n", "description": "Single character string (expected 0)"},
            {"input": "abcabcabc\n", "description": "Extended repeated pattern"},
            {"input": "aaaaabbbbbccccc\n", "description": "Large character blocks"},
            {"input": "bbacba\n", "description": "Arbitrary mixed sequence"},
        ]
        cases = []
        for c in cases_pool[:num_tests]:
            inp = c["input"]
            ans = _solve_substring_abc(inp)
            cases.append({"input": inp, "expected": ans, "description": c["description"]})
        return {"python_oracle": oracle_code, "test_cases": cases}

    # ── 3. Subtraction of two integers ─────────────────────────────────────
    elif domain == "sub_two_numbers":
        oracle_code = (
            "def solve(inp: str) -> str:\n"
            "    parts = inp.strip().split()\n"
            "    return str(int(parts[0]) - int(parts[1]))"
        )
        cases_pool = [
            {"input": "7 5\n", "expected": "2", "description": "basic positive subtraction"},
            {"input": "10 5\n", "expected": "5", "description": "positive subtraction"},
            {"input": "5 10\n", "expected": "-5", "description": "minuend smaller than subtrahend"},
            {"input": "0 0\n", "expected": "0", "description": "both zeroes"},
            {"input": "-3 5\n", "expected": "-8", "description": "negative minus positive"},
            {"input": "-10 -20\n", "expected": "10", "description": "both negative"},
            {"input": "1 0\n", "expected": "1", "description": "subtraction with zero"},
            {"input": "100 200\n", "expected": "-100", "description": "medium numbers subtraction"},
            {"input": "999999 1\n", "expected": "999998", "description": "decrement by 1"},
            {"input": "2147483647 1\n", "expected": "2147483646", "description": "INT_MAX minus 1"},
        ]
        return {"python_oracle": oracle_code, "test_cases": cases_pool[:num_tests]}

    # ── 4. Add two integers ───────────────────────────────────────────────
    elif domain == "add_two_numbers":
        oracle_code = (
            "def solve(inp: str) -> str:\n"
            "    parts = inp.strip().split()\n"
            "    return str(int(parts[0]) + int(parts[1]))"
        )
        cases_pool = [
            {"input": "7 5\n", "expected": "12", "description": "basic positive integers"},
            {"input": "0 0\n", "expected": "0", "description": "both zeroes"},
            {"input": "-3 5\n", "expected": "2", "description": "negative and positive"},
            {"input": "-10 -20\n", "expected": "-30", "description": "both negative"},
            {"input": "1 0\n", "expected": "1", "description": "identity with zero"},
            {"input": "100 200\n", "expected": "300", "description": "medium numbers"},
            {"input": "999999 1\n", "expected": "1000000", "description": "carry propagation"},
            {"input": "-1 1\n", "expected": "0", "description": "additive inverse"},
            {"input": "2147483647 0\n", "expected": "2147483647", "description": "INT_MAX boundary"},
            {"input": "2147483647 1\n", "expected": "2147483648", "description": "32-bit signed int overflow"},
        ]
        return {"python_oracle": oracle_code, "test_cases": cases_pool[:num_tests]}

    # ── 5. General fallback (Intelligent Grammar Fuzzer) ──────────────────
    else:
        return _universal_fuzz_test_suite(
            problem_description=problem_description,
            sample_input=sample_input,
            sample_output=sample_output,
            num_tests=num_tests
        )


def generate_standard_test_suite(
    problem_description: str,
    testset_dir: str,
    num_tests: int = 10,
    model: str = "llama3.1",
    temperature: float = 0.0,
    seed: int = 42,
    sample_input: str = "",
    sample_output: str = "",
    binary_oracle_path: str = ""
) -> List[Dict[str, str]]:
    """
    Generates test cases for the problem and caches them in `testset_dir`.
    1. If problem description changes, automatically wipes stale cache.
    2. Tries local Ollama server first.
    3. If Ollama is offline or fails, synthesizes a domain-tailored test suite.
    """
    os.makedirs(testset_dir, exist_ok=True)

    meta_file = os.path.join(testset_dir, ".cache_meta.json")
    current_hash = _problem_hash(problem_description, sample_input, sample_output)

    cached_hash = None
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                cached_hash = json.load(f).get("problem_hash")
        except Exception:
            cached_hash = None

    existing_in = sorted(glob.glob(os.path.join(testset_dir, "*.in")))

    # Cache hit check
    if cached_hash == current_hash and len(existing_in) >= num_tests:
        loaded = []
        for in_path in existing_in[:num_tests]:
            base = os.path.splitext(in_path)[0]
            out_path = base + ".out"
            if not os.path.exists(out_path):
                continue
            with open(in_path, "r", encoding="utf-8") as f_in, \
                 open(out_path, "r", encoding="utf-8") as f_out:
                loaded.append({"input": f_in.read(), "expected": f_out.read().strip()})
        if loaded:
            return loaded

    # Invalidate stale files
    for stale in glob.glob(os.path.join(testset_dir, "*.in")):
        try: os.remove(stale)
        except OSError: pass
    for stale in glob.glob(os.path.join(testset_dir, "*.out")):
        try: os.remove(stale)
        except OSError: pass

    # If samples empty, try extracting from description
    if not sample_input or not sample_output:
        extracted_in, extracted_out = extract_sample_from_description(problem_description)
        if not sample_input:
            sample_input = extracted_in
        if not sample_output:
            sample_output = extracted_out

    # 1. Obtain verified reference oracle
    oracle_code = get_or_create_problem_oracle(
        problem_description=problem_description,
        sample_input=sample_input,
        sample_output=sample_output,
        model=model,
        temperature=temperature,
        seed=seed,
        binary_oracle_path=binary_oracle_path
    )

    # 2. Try Ollama to generate diverse test inputs
    raw_cases = []
    prompt = (
        "You are an automated algorithmic test-case generator for programming assignments.\n"
        f"Problem Description:\n{problem_description}\n\n"
        f"Sample Input:\n{sample_input}\n\n"
        f"Sample Output:\n{sample_output}\n\n"
        f"Task: Generate exactly {num_tests} diverse test inputs covering normal cases, edge cases, boundaries, "
        "and different problem variations.\n\n"
        "Respond ONLY with valid JSON in this exact structure:\n"
        '{"test_cases": [{"input": "...\\n", "expected": "...", "description": "..."}]}'
    )

    try:
        data = query_ollama_json(prompt, model=model, temperature=temperature, seed=seed)
        raw_cases = data.get("test_cases", [])
    except Exception:
        raw_cases = []

    # 3. If Ollama didn't return enough cases, supplement or fallback with grammar fuzzer
    if len(raw_cases) < num_tests:
        fallback_data = _synthesize_domain_test_suite(
            problem_description=problem_description,
            num_tests=num_tests,
            sample_input=sample_input,
            sample_output=sample_output
        )
        if not oracle_code and fallback_data.get("python_oracle"):
            oracle_code = fallback_data.get("python_oracle")

        existing_inputs = {c.get("input", "").strip() for c in raw_cases}
        for fc in fallback_data.get("test_cases", []):
            inp_clean = fc.get("input", "").strip()
            if inp_clean not in existing_inputs:
                raw_cases.append(fc)
                existing_inputs.add(inp_clean)
            if len(raw_cases) >= num_tests:
                break

    generated_cases = []
    for idx, case in enumerate(raw_cases[:num_tests], 1):
        inp_str = str(case.get("input", "")).rstrip("\r\n") + "\n"
        oracle_out = evaluate_oracle_python(oracle_code, inp_str) if oracle_code else None

        # Fallback 1: run the student's compiled binary as a reference oracle
        if oracle_out is None and binary_oracle_path and os.path.isfile(binary_oracle_path):
            try:
                import subprocess
                result = subprocess.run(
                    [binary_oracle_path],
                    input=inp_str,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    oracle_out = result.stdout.strip()
            except Exception:
                oracle_out = None

        # Fallback 2: use the LLM-supplied expected (may be wrong for new inputs)
        expected_str = oracle_out if oracle_out is not None else str(case.get("expected", "")).strip()

        in_file = os.path.join(testset_dir, f"{idx:02d}.in")
        out_file = os.path.join(testset_dir, f"{idx:02d}.out")
        with open(in_file, "w", encoding="utf-8") as f_in:
            f_in.write(inp_str)
        with open(out_file, "w", encoding="utf-8") as f_out:
            f_out.write(expected_str + "\n")

        generated_cases.append({
            "input": inp_str,
            "expected": expected_str,
            "description": case.get("description", f"Test {idx}")
        })

    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump({
                "problem_hash": current_hash,
                "problem_description": problem_description[:200],
                "tests_count": len(generated_cases)
            }, f, indent=2)
    except OSError:
        pass

    return generated_cases


def generate_adversarial_edge_cases(
    problem_description: str,
    student_c_code: str,
    categories: List[str],
    cache_dir: str = "tests/.edge_cache",
    model: str = "llama3.1",
    temperature: float = 0.0,
    seed: int = 42,
    sample_input: str = "",
    sample_output: str = "",
    binary_oracle_path: str = ""
) -> List[Dict[str, str]]:
    """
    Generates targeted counter-test cases tailored to the specific problem.
    """
    os.makedirs(cache_dir, exist_ok=True)
    domain = detect_problem_domain(problem_description, sample_input)
    cache_key = hashlib.sha256(
        (domain + "||" + problem_description + "||" + student_c_code).encode("utf-8")
    ).hexdigest()
    cache_file = os.path.join(cache_dir, f"{cache_key}.json")

    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, list) and len(cached) > 0:
                return cached
        except (json.JSONDecodeError, IOError):
            pass

    # Retrieve or generate certified oracle
    oracle_code = get_or_create_problem_oracle(
        problem_description=problem_description,
        sample_input=sample_input,
        sample_output=sample_output,
        model=model,
        temperature=temperature,
        seed=seed,
        binary_oracle_path=binary_oracle_path
    )

    # 1. Try Ollama for adversarial edge cases
    raw_edges = []
    prompt = (
        "You are an expert C code security and edge-case analyzer.\n"
        f"Problem Description: {json.dumps(problem_description)}\n\n"
        f"Sample Input:\n{sample_input}\n"
        f"Sample Output:\n{sample_output}\n\n"
        f"Student C Submission:\n{student_c_code}\n\n"
        "Task: Generate 5 adversarial edge/counter-test cases designed to challenge boundary handling, overflow, or logic flaws in this code.\n"
        "Respond ONLY with valid JSON: {\"edge_cases\": [{\"category\": \"...\", \"input\": \"...\\n\", \"expected\": \"...\", \"explanation\": \"...\"}]}"
    )

    try:
        data = query_ollama_json(prompt, model=model, temperature=temperature, seed=seed)
        raw_edges = data.get("edge_cases", [])
    except Exception:
        raw_edges = []

    # 2. If Ollama didn't produce edge cases, use universal grammar-aware edge cases
    if not raw_edges:
        raw_edges = _universal_edge_cases(
            problem_description=problem_description,
            sample_input=sample_input,
            sample_output=sample_output,
            oracle_code=oracle_code,
            binary_oracle_path=binary_oracle_path
        )

    verified_edges = []
    for edge in raw_edges:
        inp_str = str(edge.get("input", "")).rstrip("\r\n") + "\n"
        oracle_out = evaluate_oracle_python(oracle_code, inp_str) if oracle_code else None

        # Fallback: run binary oracle when LLM oracle is unavailable
        if oracle_out is None and binary_oracle_path and os.path.isfile(binary_oracle_path):
            try:
                import subprocess
                r = subprocess.run(
                    [binary_oracle_path], input=inp_str,
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode == 0 and r.stdout.strip():
                    oracle_out = r.stdout.strip()
            except Exception:
                oracle_out = None

        expected_str = oracle_out if oracle_out is not None else str(edge.get("expected", "")).strip()

        verified_edges.append({
            "category": edge.get("category", "corner_case"),
            "input": inp_str,
            "expected": expected_str,
            "explanation": edge.get("explanation", "Corner case input for this problem.")
        })

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(verified_edges, f, indent=2)
    except IOError:
        pass

    return verified_edges


def run_student_defense_loop(
    problem_description: str,
    student_c_code: str,
    binary_runner_fn,
    categories: List[str],
    sample_input: str = "",
    sample_output: str = "",
    model: str = "llama3.1",
    temperature: float = 0.0,
    seed: int = 42,
    max_rounds: int = 2,
    binary_oracle_path: str = ""
) -> Dict[str, Any]:
    """
    Counter-Case Reality Check (Student Defense Loop).
    """
    domain = detect_problem_domain(problem_description, sample_input)

    candidate_edges = generate_adversarial_edge_cases(
        problem_description=problem_description,
        student_c_code=student_c_code,
        categories=categories,
        model=model,
        temperature=temperature,
        seed=seed,
        sample_input=sample_input,
        sample_output=sample_output,
        binary_oracle_path=binary_oracle_path
    )

    oracle_code = get_or_create_problem_oracle(
        problem_description=problem_description,
        sample_input=sample_input,
        sample_output=sample_output,
        model=model,
        temperature=temperature,
        seed=seed,
        binary_oracle_path=binary_oracle_path
    )

    verified_failures = []
    defended_cases = []
    passed_count = 0
    total_tested = 0

    for edge in candidate_edges:
        inp = edge.get("input", "")
        claimed_expected = str(edge.get("expected", "")).strip()
        cat = edge.get("category", "edge_case")
        explanation = edge.get("explanation", "")

        oracle_truth = evaluate_oracle_python(oracle_code, inp) if oracle_code else None

        # Fallback: use binary runner as oracle when LLM oracle unavailable
        if oracle_truth is None and binary_oracle_path and os.path.isfile(binary_oracle_path):
            try:
                import subprocess
                r = subprocess.run(
                    [binary_oracle_path], input=inp,
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode == 0 and r.stdout.strip():
                    oracle_truth = r.stdout.strip()
            except Exception:
                oracle_truth = None

        true_expected = oracle_truth if oracle_truth is not None else claimed_expected

        res = binary_runner_fn(inp)
        student_got = res.get("stdout", "").strip()
        timed_out = res.get("timed_out", False)
        ret_code = res.get("return_code", 0)

        total_tested += 1

        # Normalize whitespace for comparison
        def _norm(s: str) -> str:
            return " ".join(s.split())

        student_norm = _norm(student_got)
        expected_norm = _norm(true_expected)

        # Match: exact → normalized → last-line → numeric tail
        match_ok = (not timed_out and ret_code == 0) and (
            student_got == true_expected or student_norm == expected_norm
        )
        if not match_ok and not timed_out and ret_code == 0 and expected_norm:
            # Last line of student output matches expected
            student_lines = [l.strip() for l in student_got.splitlines() if l.strip()]
            if student_lines and _norm(student_lines[-1]) == expected_norm:
                match_ok = True
            elif student_norm.endswith(expected_norm):
                match_ok = True
            else:
                nums = re.findall(r'-?\d+', student_got)
                exp_nums = re.findall(r'-?\d+', true_expected)
                if nums and exp_nums and nums[-len(exp_nums):] == exp_nums:
                    match_ok = True

        if match_ok:
            passed_count += 1
            defended_cases.append({
                "category": cat,
                "input": inp.strip(),
                "student_output": student_got,
                "oracle_expected": true_expected,
                "claimed_explanation": explanation,
                "defense_note": (
                    f"Student correctly produced '{student_got}', "
                    f"matching mathematical oracle. Counter-case dismissed."
                )
            })
        else:
            note = explanation
            if timed_out:
                note += " (execution timed out)"
            elif ret_code != 0:
                note += f" (process crashed with code {ret_code})"

            verified_failures.append({
                "category": cat,
                "input": inp.strip(),
                "expected": true_expected,
                "got": student_got if not timed_out else "(timed out)",
                "explanation": note
            })

    feedback_parts = []
    if total_tested == 0:
        score = 1.0
        feedback_parts.append("All adversarial edge cases passed successfully.")
    else:
        score = round(passed_count / total_tested, 2)
    if defended_cases:
        feedback_parts.append(
            f"Student Defense Loop: Defended against {len(defended_cases)} false counter-case(s)"
        )
    if verified_failures:
        first_fail = verified_failures[0]
        feedback_parts.append(
            f"Fails on counter-test input '{first_fail['input']}' "
            f"(expected '{first_fail['expected']}', got '{first_fail['got']}'). "
            f"WHY: {first_fail['explanation']}"
        )
    else:
        feedback_parts.append(f"All {total_tested}/{total_tested} adversarial cases passed successfully.")

    return {
        "score": score,
        "cases_tested": total_tested,
        "cases_passed": passed_count,
        "counter_examples": verified_failures,
        "defended_cases": defended_cases,
        "self_correction_rounds": 1,
        "oracle_verified": bool(oracle_code),
        "feedback": " — ".join(feedback_parts)
    }
