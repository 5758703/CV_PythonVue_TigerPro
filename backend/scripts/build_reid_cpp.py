"""Build the optional native core without modifying the active Python environment.

MSVC/GCC/Clang: use native/reid/CMakeLists.txt. This helper also supports a
portable Zig C++ compiler on Windows (--fetch-tools); artifacts stay in runtime/.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "runtime" / "reid_cpp"
HEADER_VERSION = "v1.20.1"


def download(url, destination):
    print(f"Download {url}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as stream:
        shutil.copyfileobj(response, stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", help="Zig executable or C++ compiler executable")
    parser.add_argument("--include-dir", type=Path, help="Existing ORT SDK include directory")
    parser.add_argument("--fetch-tools", action="store_true", help="Download pinned ORT headers and portable Zig 0.13.0 (Windows x64)")
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    include = args.include_dir or BUILD / "include"
    compiler = args.compiler or shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if args.fetch_tools:
        include.mkdir(parents=True, exist_ok=True)
        for name in ("onnxruntime_c_api.h", "onnxruntime_cxx_api.h", "onnxruntime_cxx_inline.h", "onnxruntime_float16.h"):
            destination = include / name
            if not destination.is_file():
                download(f"https://raw.githubusercontent.com/microsoft/onnxruntime/{HEADER_VERSION}/include/onnxruntime/core/session/{name}", destination)
        download(f"https://raw.githubusercontent.com/microsoft/onnxruntime/{HEADER_VERSION}/LICENSE", BUILD / "ORT-LICENSE.txt")
        if not compiler:
            if os.name != "nt":
                raise SystemExit("Install a C++17 compiler or pass --compiler")
            executable = BUILD / "tools" / "zig-windows-x86_64-0.13.0" / "zig.exe"
            if not executable.is_file():
                with urllib.request.urlopen("https://ziglang.org/download/index.json", timeout=120) as response:
                    entry = json.load(response)["0.13.0"]["x86_64-windows"]
                archive = BUILD / "zig-0.13.0.zip"
                download(entry["tarball"], archive)
                if hashlib.sha256(archive.read_bytes()).hexdigest() != entry["shasum"]:
                    raise SystemExit("Zig archive checksum mismatch")
                with zipfile.ZipFile(archive) as package:
                    target = (BUILD / "tools").resolve()
                    for member in package.infolist():
                        if not (target / member.filename).resolve().is_relative_to(target):
                            raise SystemExit("Unsafe archive member")
                    package.extractall(target)
            compiler = str(executable)
    if not compiler or not (include / "onnxruntime_cxx_api.h").is_file():
        raise SystemExit("Need compiler and ORT headers: use --compiler/--include-dir, CMake, or --fetch-tools")
    command = [compiler]
    if Path(compiler).stem.lower() == "zig":
        command += ["c++"]
        # Keep the compiler cache inside the project workspace.
        os.environ["ZIG_GLOBAL_CACHE_DIR"] = str(BUILD / "zig-cache")
        os.environ["ZIG_LOCAL_CACHE_DIR"] = str(BUILD / "zig-local-cache")
    # Versioned artifacts avoid overwriting a DLL loaded by a live server.
    name = "reid_runtime_v2.dll" if os.name == "nt" else "libreid_runtime_v2.so"
    if os.sys.platform == "darwin":
        name = "libreid_runtime_v2.dylib"
    command += ["-std=c++17", "-O3", "-shared", "-DNDEBUG", "-I", str(include),
                "-I", str(ROOT / "native/reid/include"), str(ROOT / "native/reid/src/reid_runtime.cpp"),
                "-o", str(BUILD / name)]
    if os.name != "nt":
        command += ["-fPIC"]
        if os.sys.platform != "darwin":
            command += ["-ldl", "-pthread"]
    print("Build:", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)
    (BUILD / "build-info.json").write_text(json.dumps({"compiler": compiler, "headers": str(include),
                                                      "headerVersion": HEADER_VERSION if args.fetch_tools else "external",
                                                      "command": command}, indent=2), encoding="utf-8")
    print(f"Built {BUILD / name}")


if __name__ == "__main__":
    main()
