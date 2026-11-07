"""Own-process local servers for reproducible demos; never attach to user services."""

import multiprocessing
import threading
import time

import httpx
import uvicorn


def _worker(kind, config, ready, stop):
    if kind == "sentinel":
        from .app import create_app

        app = create_app(config["db"], config["admin"])
    else:
        from .demo_app import create_documents_app

        app = create_documents_app(
            config["sentinel_url"], config["collector"], timeout=config.get("timeout", 2)
        )
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=config["port"], log_level="error", access_log=False
        )
    )

    def controller():
        while not server.started and not stop.wait(0.02):
            pass
        if server.started:
            ready.set()
        stop.wait()
        server.should_exit = True

    threading.Thread(target=controller, daemon=True).start()
    server.run()


class ProcessServer:
    def __init__(self, kind, config):
        self.config = config
        self.url = f"http://127.0.0.1:{config['port']}"
        ctx = multiprocessing.get_context("spawn")
        self.ready, self.stop = ctx.Event(), ctx.Event()
        self.process = ctx.Process(target=_worker, args=(kind, config, self.ready, self.stop))

    def __enter__(self):
        self.process.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if not self.process.is_alive():
                raise RuntimeError(f"Demo server exited: {self.process.exitcode}")
            if self.ready.wait(0.05):
                with httpx.Client(trust_env=False, timeout=3) as client:
                    client.get(self.url + "/healthz").raise_for_status()
                return self
        self.close()
        raise RuntimeError("Demo readiness timeout")

    def close(self):
        if self.process.pid is None:
            return
        self.stop.set()
        self.process.join(timeout=10)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)
            raise RuntimeError("Demo server required forced termination")
        if self.process.exitcode != 0:
            raise RuntimeError(f"Demo server failed: {self.process.exitcode}")

    def __exit__(self, *args):
        self.close()
