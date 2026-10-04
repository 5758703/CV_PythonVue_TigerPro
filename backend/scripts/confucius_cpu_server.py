"""Download official GGUF assets and run one CPU-only llama-server.

Run from any directory: python backend/scripts/confucius_cpu_server.py --help
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

MODELS = {
    'r2t2': ('netease-youdao/Confucius4-R2T2-GGUF', 'Confucius4-R2T2',
             'Confucius4-R2T2-Q4_K_M.gguf', 'mmproj-Confucius4-R2T2-Q8_0.gguf', 8273),
    't3po': ('netease-youdao/Confucius4-T3PO-GGUF', 'Confucius4-T3PO',
             'Confucius4-T3PO-Q5_K_M.gguf', None, 8010),
}


def server_command(executable, model, folder, *, port=None, threads=4, context=4096):
    _, alias, filename, projector, default_port = MODELS[model]
    if threads < 1 or context < 1024 or not 1 <= (port or default_port) <= 65535:
        raise ValueError('invalid threads, context or port')
    files = [filename] + ([projector] if projector else [])
    for name in files:
        path = Path(folder) / name
        if not path.is_file():
            raise ValueError(f'Missing {path}; run with --download first')
        with path.open('rb') as handle:
            if handle.read(4) != b'GGUF':
                raise ValueError(f'Not a GGUF file: {path}')
    command = [str(executable), '-m', str(Path(folder) / filename), '--alias', alias,
               '--host', '127.0.0.1', '--port', str(port or default_port),
               '--offline', '--device', 'none', '--no-op-offload',
               '-ngl', '0', '--threads', str(threads), '--ctx-size', str(context),
               '--threads-batch', str(threads), '--batch-size', '256', '--ubatch-size', '128',
               '--no-warmup', '--parallel', '1', '--jinja']
    if projector:
        command.extend(['--mmproj', str(Path(folder) / projector), '--no-mmproj-offload'])
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', choices=MODELS)
    parser.add_argument('--server', default='llama-server', help='Path to a recent llama-server executable')
    parser.add_argument('--weights-dir', type=Path)
    parser.add_argument('--download', action='store_true', help='Download required official files before launch')
    parser.add_argument('--download-only', action='store_true', help='Download files without starting a server')
    parser.add_argument('--threads', type=int, default=max(1, min(os.cpu_count() or 4, 4)))
    parser.add_argument('--context', type=int, default=4096)
    parser.add_argument('--port', type=int)
    parser.add_argument('--check', action='store_true', help='Validate files and print launch arguments without launching')
    args = parser.parse_args()
    repo, _, filename, projector, _ = MODELS[args.model]
    folder = (args.weights_dir or Path(__file__).resolve().parents[1] / 'weights' / 'confucius' / args.model).resolve()
    if args.download or args.download_only:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            parser.error('Install the downloader first: pip install huggingface_hub')
        snapshot_download(repo_id=repo, local_dir=str(folder),
                          allow_patterns=[filename] + ([projector] if projector else []))
    if args.download_only:
        print(f'Weights saved to {folder}')
        return 0
    executable = shutil.which(args.server)
    if not executable and args.server == 'llama-server':
        bundled = Path(__file__).resolve().parents[1] / 'runtime' / 'llama-cpu' / ('llama-server.exe' if os.name == 'nt' else 'llama-server')
        if bundled.is_file():
            executable = str(bundled)
    if not executable:
        parser.error('llama-server was not found; install a recent llama.cpp CPU build or pass --server')
    try:
        command = server_command(executable, args.model, folder, port=args.port,
                                 threads=args.threads, context=args.context)
    except ValueError as exc:
        parser.error(str(exc))
    print(subprocess.list2cmdline(command), flush=True)
    if args.check:
        return 0
    # Console lifecycle is intentional: Ctrl+C stops this dedicated model service.
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    return subprocess.call(command, env=environment)


if __name__ == '__main__':
    raise SystemExit(main())
