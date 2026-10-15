"""jpegtran of libjpeg-turbo into system_core\\jpegtran: turns and mirrors of a JPEG without loss.

The official build of libjpeg-turbo for Windows is an installer; it is never run. 7-Zip (the one of PeaZip
first) opens it as an archive, and only what jpegtran needs is taken: jpegtran.exe, jpeg62.dll and the
licence texts. The version is fixed here with the SHA-256 GitHub publishes for it: a file that does
not match is not used. A newer version: change VERSION and SHA256 to those of its release page.

    runtime\\python.exe install\\get_jpegtran.py           fetch (once) into install\\download, then put in place
    runtime\\python.exe install\\get_jpegtran.py --check   only say whether system_core\\jpegtran answers
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

VERSION = "3.2.0"
ASSET = f"libjpeg-turbo-{VERSION}-vc-x64.exe"
URL = f"https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/{VERSION}/{ASSET}"
SIZE = 2361008
SHA256 = "662761d8ba8dae04aec74023ebaeceb856c2b56b9b59cfd180759d26300dda42"
TAKEN = {"bin/jpegtran.exe": "jpegtran.exe", "bin/jpeg62.dll": "jpeg62.dll", "doc/LICENSE.md": "LICENSE.md", "doc/README.ijg": "README.ijg"}

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD = ROOT / "install" / "download"
TARGET = ROOT / "system_core" / "jpegtran"
SEVEN_ZIP = (Path(r"C:\Program Files\PeaZip\res\bin\7z\7z.exe"), Path(r"C:\Program Files (x86)\PeaZip\res\bin\7z\7z.exe"),
             Path(r"C:\Program Files\7-Zip\7z.exe"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def answers() -> str:
    """The version jpegtran tells of itself; "" when it is not there or does not start."""
    exe = TARGET / "jpegtran.exe"
    if not exe.is_file():
        return ""
    try:
        done = subprocess.run([str(exe), "-version"], capture_output=True, text=True, timeout=20)
    except OSError:
        return ""
    said = (done.stdout + done.stderr).strip().splitlines()
    return said[0] if said else ""


def fetch() -> Path:
    DOWNLOAD.mkdir(parents=True, exist_ok=True)
    installer = DOWNLOAD / ASSET
    if installer.is_file() and installer.stat().st_size == SIZE and sha256(installer) == SHA256:
        print(f"[OK] already downloaded: {installer}")
        return installer
    print(f"[DOWNLOAD] {URL}")
    draft = installer.with_name(installer.name + ".part")
    with urllib.request.urlopen(URL, timeout=120) as answer, draft.open("wb") as handle:
        shutil.copyfileobj(answer, handle)
    size, digest = draft.stat().st_size, sha256(draft)
    if size != SIZE or digest != SHA256:
        draft.unlink(missing_ok=True)
        raise SystemExit(f"[ERR] the file is not the published one: {size} bytes, sha256 {digest}")
    draft.replace(installer)
    print(f"[OK] {ASSET}: {SIZE} bytes, sha256 as published")
    return installer


def put_in_place(installer: Path) -> None:
    seven = next((path for path in SEVEN_ZIP if path.is_file()), None) or shutil.which("7z")
    if not seven:
        raise SystemExit("[ERR] 7-Zip is not found (PeaZip carries one): the installer cannot be opened")
    with tempfile.TemporaryDirectory(prefix="jpegtran_") as folder:
        # Only the named files, each by its path inside; nothing of the installer is run.
        names = [name.replace("/", "\\") for name in TAKEN]
        done = subprocess.run([str(seven), "x", str(installer), f"-o{folder}", "-y", *names], capture_output=True, text=True)
        if done.returncode != 0:
            raise SystemExit(f"[ERR] 7-Zip: {done.stdout.strip()[-400:]} {done.stderr.strip()[-400:]}")
        staged = TARGET.with_name(TARGET.name + ".new")
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True)
        for inside, name in TAKEN.items():
            found = Path(folder) / Path(inside)
            if not found.is_file():
                raise SystemExit(f"[ERR] not in the installer: {inside}")
            shutil.copyfile(found, staged / name)
        old = TARGET.with_name(TARGET.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if TARGET.exists():
            TARGET.rename(old)
        staged.rename(TARGET)
        shutil.rmtree(old, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="jpegtran of libjpeg-turbo into system_core\\jpegtran")
    parser.add_argument("--check", action="store_true", help="Only say whether jpegtran answers")
    args = parser.parse_args()
    if not args.check:
        put_in_place(fetch())
    said = answers()
    if not said:
        print(f"[ERR] {TARGET / 'jpegtran.exe'} does not answer")
        return 1
    print(f"[OK] jpegtran answers: {said}")
    print(f"[OK] in place: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
