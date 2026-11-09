"""Explicit service entrypoint. Importing the package never starts a server."""

import argparse
import importlib
import json
import ctypes
import os
from pathlib import Path

from .bridge import Application, make_server
from .game_bindings import configure_locations, seed_locations


def load_application(config_path: str | Path):
    path = Path(config_path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    def resolve(name):
        value = Path(name)
        return value if value.is_absolute() else path.parent / value
    def secret(name):
        return resolve(name).read_text(encoding="utf-8").strip()
    configure = None
    if config.get("project_hook"):
        module, separator, function = config["project_hook"].partition(":")
        if not separator:
            raise ValueError("project_hook must be module:function")
        configure = getattr(importlib.import_module(module), function)
        if not callable(configure):
            raise ValueError("Project hook must be callable")
    project_configure = configure
    if config.get("location_catalog"):
        def configure(store, scheduler, scripts, hub):
            configure_locations(store, scheduler, scripts, hub)
            if project_configure:
                project_configure(store, scheduler, scripts, hub)
    application = Application(resolve(config["database"]), config["worlds"], secret(config["engine_token_file"]),
                              {name: secret(file) for name, file in config["controllers"].items()}, configure=configure)
    if config.get("location_catalog"):
        seed_locations(application, json.loads(resolve(config["location_catalog"]).read_text(encoding="utf-8")))
    port = config.get("port", 8775)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Service port must be an integer in 1..65535")
    return application, port


def main():
    parser = argparse.ArgumentParser(description="Run the world-independent local platform service")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    application, port = load_application(args.config)
    handle = None
    if args.parent_pid and os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, args.parent_pid)
        if not handle:
            raise RuntimeError("Launch parent is unavailable")
    def parent_alive():
        if handle:
            return kernel.WaitForSingleObject(handle, 0) == 258
        return args.parent_pid is None or os.getppid() == args.parent_pid
    try:
        with make_server(application, port=port) as server:
            print(f"Platform service listening on http://127.0.0.1:{port}", flush=True)
            server.timeout = 0.2
            try:
                while parent_alive() and not (args.stop_file and args.stop_file.exists()):
                    server.handle_request()
            except KeyboardInterrupt:
                pass
    finally:
        if handle:
            kernel.CloseHandle(handle)
