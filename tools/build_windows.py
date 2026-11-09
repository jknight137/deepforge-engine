"""Build Deepforge from checked SDK archives with one compiler worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_sdk(sdk):
    downloads = sdk / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    for item in json.loads((ROOT / "build-support/sdk-inputs.json").read_text()):
        archive = downloads / item["name"]
        if not archive.exists():
            pending = archive.with_suffix(archive.suffix + ".partial")
            with urllib.request.urlopen(item["url"], timeout=60) as response, pending.open("wb") as output:
                shutil.copyfileobj(response, output)
            if digest(pending) != item["sha256"]:
                raise ValueError("SDK archive hash mismatch: " + item["name"])
            pending.replace(archive)
        if digest(archive) != item["sha256"]:
            raise ValueError("SDK archive hash mismatch: " + item["name"])
        destination = (sdk / item["destination"]).resolve()
        if not destination.is_relative_to(sdk.resolve()):
            raise ValueError("SDK destination escapes cache")
        with zipfile.ZipFile(archive) as bundle:
            members = [m for m in bundle.infolist() if not m.is_dir()]
            for member in members:
                target = (destination / member.filename).resolve()
                if not target.is_relative_to(destination):
                    raise ValueError("SDK archive member escapes destination")
                if target.exists():
                    with bundle.open(member) as expected:
                        if digest(target) != hashlib.file_digest(expected, "sha256").hexdigest():
                            raise ValueError("Existing SDK file differs: " + str(target))
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)


def run(command, environment, log):
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, env=environment, stdout=output, stderr=subprocess.STDOUT,
                                creationflags=0x08004000 if os.name == "nt" else 0)
    if result.returncode:
        print(log.read_text(encoding="utf-8", errors="replace")[-12000:])
        raise subprocess.CalledProcessError(result.returncode, command)
    print(log.name + ": passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=ROOT / ".sdk")
    parser.add_argument("--build", type=Path, default=ROOT / "build/windows")
    parser.add_argument("--output", type=Path, default=ROOT / "build/portable")
    parser.add_argument("--ninja", default=shutil.which("ninja"))
    args = parser.parse_args()
    if os.name != "nt" or not args.ninja:
        raise ValueError("Use Windows and supply --ninja when Ninja is outside PATH")
    sdk, build, portable = args.sdk.resolve(), args.build.resolve(), args.output.resolve()
    build.mkdir(parents=True, exist_ok=True)
    prepare_sdk(sdk)
    options = json.loads((ROOT / "build-support/windows-cmake.json").read_text())
    options = {k: v.replace("${CACHE}", sdk.as_posix()).replace("${NINJA}", str(args.ninja).replace("\\", "/"))
               for k, v in options.items()}
    env = dict(os.environ)
    env["PATH"] = str(sdk / "toolchain/llvm-mingw-20260616-ucrt-x86_64/bin") + os.pathsep + env["PATH"]
    command = ["cmake", "-S", str(ROOT), "-B", str(build), "-G", "Ninja"]
    command.extend(f"-D{k}={v}" for k, v in options.items())
    run(command, env, build / "configure.log")
    run(["cmake", "--build", str(build), "--parallel", "1"], env, build / "build.log")
    run(["cmake", "--install", str(build), "--prefix", str(portable)], env, build / "install.log")
    binary = portable / "bin"
    for item in json.loads((ROOT / "build-support/runtime-dlls.json").read_text()):
        path = sdk / item["source"]
        if digest(path) != item["sha256"]:
            raise ValueError("Runtime DLL differs from manifest")
        shutil.copy2(path, binary / path.name)
    for name in ("LICENSE.txt", "COPYING.LESSER", "THIRD_PARTY_NOTICES.md", "README.md"):
        shutil.copy2(ROOT / name, portable / name)
    shutil.copytree(ROOT / "licenses", portable / "licenses", dirs_exist_ok=True)
    for module in (ROOT / "platform/luanti").iterdir():
        if module.is_dir():
            shutil.copytree(module, portable / "mods" / module.name, dirs_exist_ok=True)
    print(str(portable), flush=True)


if __name__ == "__main__":
    main()
