"""Register, inspect and prepare the project's supported CPU ASR models."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def runtime_packages(python_version=None):
    """PyAV 19 requires Python 3.12; the deployed Conda backend may use 3.10."""
    version = tuple(python_version or sys.version_info[:2])
    av_version = '19.0.2' if version >= (3, 12) else '16.1.0'
    return ['sherpa-onnx==1.13.3', 'sherpa-onnx-core==1.13.3', 'faster-whisper==1.2.1',
            'moonshine-voice==0.1.5', 'ctranslate2==4.8.4', f'av=={av_version}',
            'sounddevice==0.5.6', 'google-crc32c==1.9.0']


def main():
    from flask import Flask
    from config import Config
    from services.cpu_asr import CPU_ASR_MODELS, EXTRA_PACKAGES, download_model, runtime_status, seed_cpu_asr_models
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--register', action='store_true', help='幂等登记模型，不改变用户的停用状态与自定义绑定')
    parser.add_argument('--check', action='store_true', help='只检查本地权重和依赖')
    parser.add_argument('--all', action='store_true', help='准备全部八个模型选项')
    parser.add_argument('--model', action='append', choices=tuple(CPU_ASR_MODELS), help='只准备指定模型，可重复')
    parser.add_argument('--install-deps', action='store_true', help='安装新增 SDK 到项目 runtime 目录；核心环境先按 requirements.txt 准备')
    args = parser.parse_args()
    if args.install_deps:
        packages = runtime_packages()
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-cache-dir',
                        '--target', str(EXTRA_PACKAGES), *packages], check=True)
        if str(EXTRA_PACKAGES) not in sys.path:
            sys.path.insert(0, str(EXTRA_PACKAGES))
        importlib.invalidate_caches()
    app = Flask('prepare-cpu-asr')
    app.config.from_object(Config)
    with app.app_context():
        if args.register or ((args.all or args.model) and not args.check):
            from extensions import db
            db.init_app(app)
            seed_cpu_asr_models()
            print('CPU ASR catalog registered', flush=True)
        keys = list(CPU_ASR_MODELS) if args.all or not args.model else args.model
        failed = []
        for key in keys:
            if (args.all or args.model) and not args.check:
                print(f'Preparing {key}', flush=True)
                try:
                    download_model(key, token=app.config.get('HF_TOKEN'))
                    seed_cpu_asr_models()
                except Exception as exc:
                    print(f'{key}: {exc}', file=sys.stderr, flush=True)
                    failed.append(key)
            print(json.dumps({'modelKey': key, **runtime_status(key)}, ensure_ascii=False), flush=True)
        if failed:
            raise RuntimeError('未完成模型准备：' + '、'.join(failed))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'CPU ASR 准备失败：{exc}', file=sys.stderr)
        sys.exit(1)
