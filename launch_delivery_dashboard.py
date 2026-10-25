"""Open the local dashboard; reuse or stop only a process owned by this launcher."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import psutil

ROOT = Path(__file__).resolve().parent


def health(url):
    try:
        with urlopen(url + "/api/health", timeout=1) as response:
            return json.load(response)
    except (URLError, OSError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stop", action="store_true")
    settings = parser.parse_args()
    if not 1 <= settings.port <= 65535:
        raise ValueError("Choose a port between 1 and 65535.")
    url = f"http://127.0.0.1:{settings.port}"
    reports = ROOT / "reports/dashboard"
    reports.mkdir(parents=True, exist_ok=True)
    owner_file = reports / f"server-{settings.port}.json"
    if settings.stop:
        if not owner_file.is_file():
            print("No dashboard instance is recorded by this launcher.")
            return
        owner = json.loads(owner_file.read_text())
        try:
            process = psutil.Process(owner["pid"])
            command = process.cmdline()
            if abs(process.create_time() - owner["created"]) > .01 or not any(Path(c).name == "run_delivery_dashboard.py" for c in command):
                raise RuntimeError("The recorded process no longer matches this dashboard; nothing was stopped.")
            if Path(process.cwd()).resolve() != ROOT:
                raise RuntimeError("The recorded process belongs to another folder; nothing was stopped.")
            process.terminate()
            process.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        owner_file.unlink(missing_ok=True)
        print("Delivery Ops stopped.")
        return
    current = health(url)
    if current is not None and current.get("application") != "delivery-ops":
        raise RuntimeError("This local port is used by another application. Choose a different --port.")
    if current is None:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", settings.port)) == 0:
                raise RuntimeError("This local port is already in use. Choose a different --port.")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with (reports / "server.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, str(ROOT / "run_delivery_dashboard.py"), "--port", str(settings.port)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        owner_file.write_text(json.dumps({"pid": process.pid, "created": psutil.Process(process.pid).create_time(), "url": url}) + "\n")
        for _ in range(80):
            current = health(url)
            if current and current.get("application") == "delivery-ops":
                break
            if process.poll() is not None:
                raise RuntimeError("The dashboard could not start. See reports/dashboard/server.log.")
            time.sleep(.25)
        else:
            raise RuntimeError("The dashboard is still starting. Open the launcher again shortly.")
    print("Delivery Ops ready: " + url)
    if not settings.no_browser:
        webbrowser.open(url)


if __name__ == "__main__":
    main()
