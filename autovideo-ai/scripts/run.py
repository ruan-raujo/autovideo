"""Start one loopback-only server and open the browser after readiness."""
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn


def open_when_ready():
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open("http://127.0.0.1:8000")
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)


if __name__ == "__main__":
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, workers=1, access_log=False)
