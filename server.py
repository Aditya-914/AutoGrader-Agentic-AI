#!/usr/bin/env python3
"""
AutoGrader Web Server
Provides a zero-dependency REST API and static file server for the AutoGrader frontend.
"""

import os
import sys
import json
import time
import shutil
import signal
import tempfile
import hashlib
import mimetypes
import subprocess
import threading
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
SUBMISSIONS_DIR = os.path.join(BASE_DIR, "submissions")
RULES_DIR = os.path.join(BASE_DIR, "rules")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
TESTS_DIR = os.path.join(BASE_DIR, "tests")
BIN_DIR = os.path.join(BASE_DIR, "bin")

os.environ["PATH"] = BIN_DIR + ":" + os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")

os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
os.makedirs(RULES_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


def check_tool(cmd: list) -> dict:
    """Checks if a command-line tool is installed and returns version/status."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if proc.returncode == 0 or proc.stdout or proc.stderr:
            first_line = (proc.stdout or proc.stderr).strip().splitlines()[0]
            return {"installed": True, "details": first_line}
    except Exception as e:
        return {"installed": False, "details": str(e)}
    return {"installed": False, "details": "not found"}


def check_libasan() -> bool:
    """Checks if libasan / address sanitizer can compile and link on this system."""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as tf:
            tf.write("int main(void){return 0;}")
            c_path = tf.name
        out_bin = c_path + ".bin"
        proc = subprocess.run(
            ["gcc", "-fsanitize=address", c_path, "-o", out_bin],
            capture_output=True,
            timeout=5
        )
        for p in [c_path, out_bin]:
            if os.path.exists(p):
                os.remove(p)
        return proc.returncode == 0
    except Exception:
        return False


def get_system_status() -> dict:
    """Returns real-time status of tools, models, and workspace."""
    gcc_status = check_tool(["gcc", "--version"])
    cppcheck_status = check_tool(["cppcheck", "--version"])
    ollama_status = check_tool(["ollama", "--version"])
    libasan_ok = check_libasan()

    # Check if lizard is available in Python
    try:
        sys.path.insert(0, os.path.join(BASE_DIR, "agent"))
        import lizard
        lizard_ok = True
        lizard_ver = "installed"
    except Exception:
        lizard_ok = False
        lizard_ver = "unavailable"

    # Count files
    sub_count = len([f for f in os.listdir(SUBMISSIONS_DIR) if f.endswith(".c")])
    rules_count = len([f for f in os.listdir(RULES_DIR) if f.endswith(".json")])
    reports_count = len([f for f in os.listdir(REPORTS_DIR) if f.endswith(".json")])

    return {
        "status": "ready",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tools": {
            "gcc": gcc_status,
            "cppcheck": cppcheck_status,
            "ollama": ollama_status,
            "libasan": {"installed": libasan_ok, "details": "Available" if libasan_ok else "Missing runtime libasan.so"},
            "lizard": {"installed": lizard_ok, "details": lizard_ver}
        },
        "stats": {
            "submissions": sub_count,
            "rulesets": rules_count,
            "reports": reports_count
        }
    }


class AutoGraderHandler(BaseHTTPRequestHandler):
    server_version = "AutoGraderServer/1.0"

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def end_headers(self):
        try:
            # Enable CORS for local development flexibility
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            super().end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_OPTIONS(self):
        try:
            self.send_response(200)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def send_json(self, data: dict, status_code: int = 200):
        try:
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def send_error_json(self, message: str, status_code: int = 400):
        try:
            self.send_json({"error": message}, status_code=status_code)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def read_post_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON payload: {e}")

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            # ── API Endpoints ───────────────────────────────────────────────
            if path == "/api/status":
                return self.send_json(get_system_status())

            if path == "/api/presets":
                return self.handle_get_presets()

            if path == "/api/rules":
                return self.handle_list_rules()

            if path.startswith("/api/rules/"):
                filename = os.path.basename(path[len("/api/rules/"):])
                return self.handle_get_rule_file(filename)

            if path == "/api/submissions":
                return self.handle_list_submissions()

            if path.startswith("/api/submissions/"):
                filename = os.path.basename(path[len("/api/submissions/"):])
                return self.handle_get_submission_file(filename)

            if path == "/api/reports":
                return self.handle_list_reports()

            if path.startswith("/api/reports/"):
                filename = os.path.basename(path[len("/api/reports/"):])
                return self.handle_get_report_file(filename)

            # ── Static File Serving ─────────────────────────────────────────
            self.serve_static(path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == "/api/grade":
                return self.handle_post_grade()

            if path == "/api/quick-run":
                return self.handle_post_quick_run()

            if path == "/api/submissions":
                return self.handle_post_submission()

            if path == "/api/rules":
                return self.handle_post_rules()

            self.send_error_json(f"Endpoint not found: {path}", status_code=404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                self.send_error_json(str(e), status_code=500)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/submissions/"):
            filename = os.path.basename(path[len("/api/submissions/"):])
            file_path = os.path.join(SUBMISSIONS_DIR, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    return self.send_json({"deleted": filename, "success": True})
                except Exception as e:
                    return self.send_error_json(f"Failed to delete: {e}", status_code=500)
            return self.send_error_json("File not found", status_code=404)

        self.send_error_json("Invalid DELETE target", status_code=404)

    # ── Handlers ────────────────────────────────────────────────────────

    def handle_get_presets(self):
        presets = [
            {
                "id": "mcm.c",
                "name": "Matrix Chain Multiplication (mcm.c)",
                "description": "Dynamic programming solution finding minimum scalar multiplications.",
                "file": "mcm.c",
                "default_rules": "mcm_rules.json"
            },
            {
                "id": "maze.c",
                "name": "Rat in a Maze (maze.c)",
                "description": "Backtracking algorithm finding paths in an N x M binary matrix.",
                "file": "maze.c",
                "default_rules": "maze_rules.json"
            },
            {
                "id": "substring.c",
                "name": "Substrings with a,b,c (substring.c)",
                "description": "Counts substrings containing at least one occurrence of characters a, b and c.",
                "file": "substring.c",
                "default_rules": "new_rules.json"
            },
            {
                "id": "add_safe.c",
                "name": "Modular 64-bit Safe (add_safe.c)",
                "description": "Uses 64-bit long long, extracts add_safe() helper function, includes comments. Achieves top scores.",
                "file": "add_safe.c",
                "default_rules": "add_rules.json"
            },
            {
                "id": "add.c",
                "name": "Naive 32-bit Add with Overflow (add.c)",
                "description": "Naive 32-bit addition demonstrating overflow on INT_MAX edge case.",
                "file": "add.c",
                "default_rules": "add_rules.json"
            },
            {
                "id": "add_slow.c",
                "name": "Inefficient O(N) Loop (add_slow.c)",
                "description": "Implements addition via iterative increment loops, demonstrating complexity analysis.",
                "file": "add_slow.c",
                "default_rules": "add_rules.json"
            },
            {
                "id": "infinite_loop.c",
                "name": "Infinite Loop Bug (infinite_loop.c)",
                "description": "Triggers suspected infinite loop in Phase 1 smoke test with RLIMIT_CPU containment.",
                "file": "infinite_loop.c",
                "default_rules": "add_rules.json"
            },
            {
                "id": "syntax_error.c",
                "name": "Syntax Error (syntax_error.c)",
                "description": "Demonstrates compilation failure handling and intelligent routing to skip execution tests.",
                "file": "syntax_error.c",
                "default_rules": "add_rules.json"
            }
        ]
        self.send_json({"presets": presets})

    def handle_list_rules(self):
        files = []
        for f in sorted(os.listdir(RULES_DIR)):
            if f.endswith(".json"):
                full_path = os.path.join(RULES_DIR, f)
                try:
                    with open(full_path, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    files.append({
                        "filename": f,
                        "problem": data.get("problem", f),
                        "description": data.get("problem_description", ""),
                        "metrics_count": len(data.get("metrics", [])),
                        "time_limit_s": data.get("time_limit_s", 1),
                        "memory_limit_mb": data.get("memory_limit_mb", 64)
                    })
                except Exception:
                    files.append({"filename": f, "problem": f, "error": "Invalid JSON"})
        self.send_json({"rules": files})

    def handle_get_rule_file(self, filename: str):
        full_path = os.path.join(RULES_DIR, filename)
        if not os.path.exists(full_path):
            return self.send_error_json("Rule file not found", 404)
        with open(full_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return self.send_json(data)
            except Exception as e:
                return self.send_error_json(f"Corrupt JSON: {e}", 500)

    def handle_post_rules(self):
        payload = self.read_post_json()
        filename = payload.get("filename", "custom_rules.json")
        if not filename.endswith(".json"):
            filename += ".json"
        rules_data = payload.get("rules", payload)
        metrics = rules_data.get("metrics", [])
        total_weight = sum(float(m.get("weight", 0.0)) for m in metrics)
        if abs(total_weight - 1.0) > 1e-4:
            return self.send_error_json(f"Metric weights must sum to 1.00, got {total_weight:.4f}", 400)
        # Default plagiarism corpus_dir to corpus/
        for m in metrics:
            if m.get("analyzer") == "similarity_flag":
                params = m.setdefault("params", {})
                if not params.get("corpus_dir") or params.get("corpus_dir") in ("submissions/", "submissions"):
                    params["corpus_dir"] = "corpus/"
        full_path = os.path.join(RULES_DIR, filename)
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(rules_data, f, indent=2)
        self.send_json({"success": True, "filename": filename, "rules": rules_data})

    def handle_list_submissions(self):
        submissions = []
        for f in sorted(os.listdir(SUBMISSIONS_DIR)):
            if f.endswith(".c"):
                path = os.path.join(SUBMISSIONS_DIR, f)
                stat = os.stat(path)
                submissions.append({
                    "filename": f,
                    "size_bytes": stat.st_size,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
                })
        self.send_json({"submissions": submissions})

    def handle_get_submission_file(self, filename: str):
        full_path = os.path.join(SUBMISSIONS_DIR, filename)
        if not os.path.exists(full_path):
            return self.send_error_json("Submission file not found", 404)
        with open(full_path, "r", encoding="utf-8") as f:
            code = f.read()
        self.send_json({"filename": filename, "code": code})

    def handle_post_submission(self):
        payload = self.read_post_json()
        filename = payload.get("filename", "user_code.c")
        if not filename.endswith(".c"):
            filename += ".c"
        code = payload.get("code", "")
        if not code.strip():
            return self.send_error_json("Code cannot be empty", 400)

        full_path = os.path.join(SUBMISSIONS_DIR, filename)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(code)

        self.send_json({"success": True, "filename": filename, "bytes_written": len(code)})

    def handle_list_reports(self):
        reports = []
        for f in sorted(os.listdir(REPORTS_DIR)):
            if f.endswith(".json"):
                full_path = os.path.join(REPORTS_DIR, f)
                try:
                    with open(full_path, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    stat = os.stat(full_path)
                    reports.append({
                        "filename": f,
                        "submission": data.get("submission", f),
                        "grade": data.get("grade", 0.0),
                        "graded_at": data.get("graded_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.localtime(stat.st_mtime))),
                        "total_time_s": data.get("total_time_s", 0.0),
                        "compiled": data.get("first_pass", {}).get("compiled", False)
                    })
                except Exception:
                    pass
        # Sort newest first
        reports.sort(key=lambda r: r.get("graded_at", ""), reverse=True)
        self.send_json({"reports": reports})

    def handle_get_report_file(self, filename: str):
        full_path = os.path.join(REPORTS_DIR, filename)
        if not os.path.exists(full_path):
            return self.send_error_json("Report not found", 404)

        if filename.endswith(".json"):
            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return self.send_json(data)
        elif filename.endswith(".txt"):
            with open(full_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(text.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(text.encode("utf-8"))
            return
        else:
            return self.send_error_json("Unsupported report type", 400)

    def handle_post_quick_run(self):
        """Compiles and executes C code against custom standard input in a sandbox."""
        payload = self.read_post_json()
        code = payload.get("code", "")
        stdin_data = payload.get("stdin", "")
        if not code.strip():
            return self.send_error_json("No C code provided", 400)

        temp_dir = tempfile.mkdtemp(prefix="quick_run_")
        c_file = os.path.join(temp_dir, "run.c")
        bin_file = os.path.join(temp_dir, "run_bin")

        with open(c_file, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            # 1. Compile
            t0 = time.time()
            compile_proc = subprocess.run(
                ["gcc", "-O2", "-Wall", "-Wextra", "-std=c11", c_file, "-o", bin_file, "-lm"],
                capture_output=True,
                text=True,
                timeout=10
            )
            compile_time = round(time.time() - t0, 3)

            if compile_proc.returncode != 0:
                return self.send_json({
                    "compiled": False,
                    "compile_output": compile_proc.stderr or compile_proc.stdout,
                    "compile_time_s": compile_time,
                    "stdout": "",
                    "stderr": "",
                    "returncode": compile_proc.returncode,
                    "timed_out": False
                })

            # 2. Execute
            t1 = time.time()
            exec_proc = subprocess.run(
                [bin_file],
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=3,
                cwd=temp_dir
            )
            exec_time = round(time.time() - t1, 3)

            return self.send_json({
                "compiled": True,
                "compile_output": compile_proc.stderr,
                "compile_time_s": compile_time,
                "stdout": exec_proc.stdout,
                "stderr": exec_proc.stderr,
                "returncode": exec_proc.returncode,
                "execution_time_s": exec_time,
                "timed_out": False
            })
        except subprocess.TimeoutExpired:
            return self.send_json({
                "compiled": True,
                "compile_output": "",
                "stdout": "",
                "stderr": "Execution timed out (exceeded 3s limit). Possible infinite loop.",
                "returncode": -1,
                "timed_out": True
            })
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def handle_post_grade(self):
        """Runs the complete auto-grading agent pipeline on a submission."""
        payload = self.read_post_json()
        code = payload.get("code")
        submission_filename = payload.get("submission_file", "add.c")
        rules_filename = payload.get("rules_file", "add_rules.json")
        custom_rules = payload.get("rules")

        # Determine submission path
        if code:
            # Save or overwrite custom code
            sub_stem = os.path.splitext(submission_filename)[0]
            clean_sub_name = f"{sub_stem}.c"
            sub_path = os.path.join(SUBMISSIONS_DIR, clean_sub_name)
            with open(sub_path, "w", encoding="utf-8") as f:
                f.write(code)
        else:
            sub_path = os.path.join(SUBMISSIONS_DIR, submission_filename)
            if not os.path.exists(sub_path):
                return self.send_error_json(f"Submission file not found: {submission_filename}", 404)

        # Determine rules path — use custom_rules inline, or specified rules_file
        if custom_rules:
            rules_path = os.path.join(RULES_DIR, "_temp_grade_rules.json")
            with open(rules_path, "w", encoding="utf-8") as f:
                json.dump(custom_rules, f, indent=2)
        else:
            rules_path = os.path.join(RULES_DIR, rules_filename)
            if not os.path.exists(rules_path):
                return self.send_error_json(f"Rules file not found: {rules_filename}", 404)

        # Run main.py grading process
        sub_stem = os.path.splitext(os.path.basename(sub_path))[0]
        report_json_path = os.path.join(REPORTS_DIR, f"{sub_stem}.json")
        report_txt_path = os.path.join(REPORTS_DIR, f"{sub_stem}.txt")

        cmd = [
            sys.executable,
            os.path.join(BASE_DIR, "main.py"),
            rules_path,
            sub_path,
            "--output", report_json_path,
            "--text-output", report_txt_path,
            "--verbose"
        ]

        t0 = time.time()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=BASE_DIR
        )
        total_time = round(time.time() - t0, 2)

        if os.path.exists(report_json_path):
            with open(report_json_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            
            # Read text output if available
            txt_report = ""
            if os.path.exists(report_txt_path):
                with open(report_txt_path, "r", encoding="utf-8") as f:
                    txt_report = f.read()

            report_data["text_report"] = txt_report
            report_data["cli_stdout"] = proc.stdout
            report_data["cli_stderr"] = proc.stderr
            return self.send_json(report_data)
        else:
            return self.send_error_json(
                f"Grading finished without generating report. Stderr: {proc.stderr}\nStdout: {proc.stdout}",
                500
            )

    def serve_static(self, path: str):
        if path == "/" or path == "":
            path = "/index.html"

        # Sanitize path to prevent directory traversal
        rel_path = path.lstrip("/")
        full_path = os.path.normpath(os.path.join(FRONTEND_DIR, rel_path))

        if not full_path.startswith(FRONTEND_DIR) or not os.path.exists(full_path) or os.path.isdir(full_path):
            # Fallback to index.html for SPA routes if available
            index_path = os.path.join(FRONTEND_DIR, "index.html")
            if os.path.exists(index_path):
                full_path = index_path
            else:
                self.send_error_json("Frontend file not found", 404)
                return

        ctype, _ = mimetypes.guess_type(full_path)
        if not ctype:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"

        try:
            with open(full_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error_json(str(e), 500)


def run_server(port: int = 8000, open_browser: bool = False):
    server_address = ("0.0.0.0", port)
    httpd = ThreadingHTTPServer(server_address, AutoGraderHandler)
    url = f"http://localhost:{port}"
    print(f"=================================================")
    print(f"  AutoGrader Agentic AI Web Interface Running")
    print(f"  URL: {url}")
    print(f"  Press Ctrl+C to terminate the server")
    print(f"=================================================")
    if open_browser:
        try:
            import webbrowser
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AutoGrader Frontend Web Server")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--open", "-o", action="store_true", help="Automatically open browser")
    args = parser.parse_args()
    run_server(args.port, open_browser=args.open)
