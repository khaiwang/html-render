#!/usr/bin/env python3
"""Smoke-test the html-render server.

Starts it on a random port pointing at a temp dir, posts two HTML fixtures,
and asserts the index page lists them with their titles, newest first.
"""

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "plugins" / "html-render" / "server" / "server.py"


def free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="htmlrender-test-"))
    port = free_port()

    older = tmp / "20260526-100000-plan.html"
    older.write_text(
        "<!DOCTYPE html><html><head><title>Older Plan</title></head>"
        "<body>plan body</body></html>"
    )
    # Force older mtime
    older_ts = time.time() - 3600
    os.utime(older, (older_ts, older_ts))

    newer = tmp / "20260526-110000-diff.html"
    newer.write_text(
        "<!DOCTYPE html><html><head><title>Newer Diff</title></head>"
        "<body>diff body</body></html>"
    )

    env = {**os.environ, "HTML_RENDER_DIR": str(tmp), "HTML_RENDER_PORT": str(port)}
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        # Wait for server to come up.
        deadline = time.time() + 5
        index_body = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
                    index_body = r.read().decode("utf-8")
                    break
            except OSError:
                time.sleep(0.1)
        if index_body is None:
            print("FAIL  server did not become reachable")
            return 1

        ok = True
        if "Newer Diff" not in index_body:
            print("FAIL  index missing 'Newer Diff'")
            ok = False
        if "Older Plan" not in index_body:
            print("FAIL  index missing 'Older Plan'")
            ok = False
        if index_body.index("Newer Diff") >= index_body.index("Older Plan"):
            print("FAIL  ordering wrong — newer should come first")
            ok = False
        if 'tag-diff' not in index_body:
            print("FAIL  diff tag chip missing")
            ok = False
        if 'tag-plan' not in index_body:
            print("FAIL  plan tag chip missing")
            ok = False

        # Test serving an actual file
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/{newer.name}", timeout=1
        ) as r:
            body = r.read().decode("utf-8")
            if "diff body" not in body:
                print("FAIL  static file content not served")
                ok = False

        if ok:
            print("PASS  server: index renders, ordering correct, tags present, static files served")
            return 0
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
