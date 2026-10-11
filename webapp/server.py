#!/usr/bin/env python3
"""Small local control panel for running PPPwn on the host network interface."""
import json
import os
import queue
import shlex
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
load_dotenv(PROJECT_ROOT / ".env")


def configured_path(name, default):
    path = Path(os.environ.get(name, default)).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


BINARY = configured_path("PPPWN_BINARY", "/usr/local/bin/pppwn")
INTERFACE = os.environ.get("PPPWN_INTERFACE", "en7")
FIRMWARE = os.environ.get("PPPWN_FIRMWARE", "1100")
selected_interface = INTERFACE
STAGE1 = configured_path("PPPWN_STAGE1", "/payloads/stage1.bin")
STAGE2 = configured_path("PPPWN_STAGE2", "/payloads/stage2.bin")

lock = threading.RLock()
process = None
log_lines = []
subscribers = set()
status = {"running": False, "stage": "Idle", "progress": 0, "exit_code": None}


def uses_default_payload_paths():
    """PPPwn's default payload paths are relative to its working directory."""
    return (STAGE1 == BINARY.parent / "stage1" / "stage1.bin"
            and STAGE2 == BINARY.parent / "stage2" / "stage2.bin")


def command(interface=None):
    args = [str(BINARY), "--interface", interface or selected_interface, "--fw", FIRMWARE]
    if not uses_default_payload_paths():
        args.extend(["--stage1", str(STAGE1), "--stage2", str(STAGE2)])
    args.append("--auto-retry")
    return args


def display_command(interface=None):
    """Show a concise, project-relative command for local use where possible."""
    args = command(interface)
    for index, arg in enumerate(args):
        path = Path(arg)
        if path.is_absolute():
            try:
                args[index] = "./" + path.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                pass
    return shlex.join(args)


def list_interfaces():
    """Use PPPwn's own libpcap-backed interface listing for this host/container."""
    result = subprocess.run([str(BINARY), "list"], cwd=str(BINARY.parent),
                            capture_output=True, text=True, timeout=10, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"pppwn list exited with status {result.returncode}")
    interfaces = []
    for line in result.stdout.splitlines():
        value = line.strip()
        if not value or value.startswith("[+") or value.startswith("[-"):
            continue
        parts = value.split(None, 1)
        if parts:
            interfaces.append({"name": parts[0], "description": parts[1] if len(parts) > 1 else ""})
    return interfaces


def publish(line):
    global status
    line = line.rstrip("\r\n")
    if not line:
        return
    with lock:
        log_lines.append(line)
        del log_lines[:-1000]
        if "STAGE 0:" in line:
            status.update(stage="Stage 0: Initialization", progress=5)
        elif "STAGE 1:" in line:
            status.update(stage="Stage 1: Memory corruption", progress=20)
        elif "STAGE 2:" in line:
            status.update(stage="Stage 2: KASLR defeat", progress=45)
        elif "STAGE 3:" in line:
            status.update(stage="Stage 3: Remote code execution", progress=70)
        elif "STAGE 4:" in line:
            status.update(stage="Stage 4: Arbitrary payload execution", progress=90)
        elif "Heap grooming...done" in line:
            status.update(stage="Heap grooming complete", progress=35)
        elif "Pinning to CPU 0...done" in line:
            status.update(stage="CPU pinning complete", progress=40)
        elif "Retry after" in line:
            status.update(stage="Retrying", progress=0)
        elif "[+] Done!" in line:
            status.update(stage="Complete", progress=100)
        elif "Stopped" in line:
            status.update(stage="Stopped", progress=0)
        for subscriber in list(subscribers):
            try:
                subscriber.put_nowait(line)
            except queue.Full:
                pass


def run_process():
    global process, status
    try:
        with lock:
            status.update(running=True, stage="Starting PPPwn", progress=0, exit_code=None)
        publish("[*] Running: " + shlex.join(command()))
        proc = subprocess.Popen(command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1,
                                cwd=str(BINARY.parent) if uses_default_payload_paths() else "/",
                                env=os.environ.copy(), start_new_session=True)
        with lock:
            process = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            publish(line)
        code = proc.wait()
        with lock:
            status.update(running=False, exit_code=code)
            if status["stage"] not in ("Stopped", "Complete"):
                status["stage"] = "Finished" if code == 0 else "Exited with error"
    except Exception as exc:
        publish(f"[-] Failed to start PPPwn: {exc}")
        with lock:
            status.update(running=False, stage="Failed to start", exit_code=-1)
    finally:
        with lock:
            process = None


class Handler(BaseHTTPRequestHandler):
    def handle(self):
        # Browsers may reset connections during refresh/navigation, especially
        # while closing an EventSource stream. This is normal, not a server error.
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass

    def reply(self, code, value):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/interfaces":
            try:
                self.reply(200, {"interfaces": list_interfaces()})
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                self.reply(500, {"error": f"Could not list network interfaces: {exc}"})
        elif self.path == "/api/status":
            with lock:
                self.reply(200, {**status, "command": display_command(), "interface": selected_interface,
                                 "firmware": FIRMWARE, "logs": log_lines[-300:]})
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            subscriber = queue.Queue(maxsize=200)
            with lock:
                subscribers.add(subscriber)
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        line = subscriber.get(timeout=15)
                        data = json.dumps({"line": line}).encode()
                        self.wfile.write(b"data: " + data + b"\n\n")
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    subscribers.discard(subscriber)
        elif self.path == "/" or self.path == "/index.html":
            data = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.reply(404, {"error": "Not found"})

    def do_POST(self):
        global log_lines, selected_interface
        if self.path == "/api/run":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                requested_interface = payload.get("interface", selected_interface)
                available = {item["name"] for item in list_interfaces()}
                if requested_interface not in available:
                    self.reply(400, {"error": f"Interface is not available: {requested_interface}"})
                    return
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.reply(400, {"error": f"Invalid run request: {exc}"})
                return
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                self.reply(500, {"error": f"Could not list network interfaces: {exc}"})
                return
            with lock:
                if status["running"]:
                    self.reply(409, {"error": "PPPwn is already running"})
                    return
                if not BINARY.is_file():
                    self.reply(500, {"error": f"PPPwn binary not found: {BINARY}"})
                    return
                if not STAGE1.is_file() or not STAGE2.is_file():
                    self.reply(500, {"error": f"Payload files not found: {STAGE1} and/or {STAGE2}"})
                    return
                log_lines = []
                selected_interface = requested_interface
                status.update(running=True, stage="Starting PPPwn", progress=0, exit_code=None)
                threading.Thread(target=run_process, daemon=True).start()
            self.reply(202, {"ok": True})
        elif self.path == "/api/stop":
            with lock:
                proc = process
            if proc is None:
                self.reply(409, {"error": "PPPwn is not running"})
            else:
                proc.send_signal(__import__("signal").SIGINT)
                self.reply(202, {"ok": True})
        else:
            self.reply(404, {"error": "Not found"})


if __name__ == "__main__":
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8080"))
    print(f"PPPwn control panel listening on http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
