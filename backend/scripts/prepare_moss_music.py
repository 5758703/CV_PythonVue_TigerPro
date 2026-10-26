"""Prepare the pinned HOT-Step CPU runtime and the two MOSS-Music GGUF files.

Run from any directory: python backend/scripts/prepare_moss_music.py --check
Use --runtime-only to install the small runtime without downloading 10.43GB.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
RELEASE = 'v1.4.2'
ARCHIVE = f'HOT-Step-CPP-{RELEASE}-win-x64-cpu.zip'
BASE_URL = f'https://github.com/scragnog/HOT-Step-CPP/releases/download/{RELEASE}/'


def install_runtime(destination):
    import requests
    if os.name != 'nt':
        raise ValueError('此自动安装器适用于 Windows x64；其他平台请安装 HOT-Step CPU 版并配置 MOSS_MUSIC_EXECUTABLE')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination).free < 400 * 1024**2:
        raise ValueError('CPU 运行时准备需要至少 400 MiB 可用磁盘空间')
    checksum = requests.get(BASE_URL + ARCHIVE + '.sha256', timeout=60)
    checksum.raise_for_status()
    match = re.search(r'\b[0-9a-fA-F]{64}\b', checksum.text)
    if not match:
        raise RuntimeError('发布包 SHA256 校验文件格式无效')
    with tempfile.TemporaryDirectory(prefix='moss_setup_', dir=destination.parent) as work:
        archive = Path(work) / ARCHIVE
        digest = hashlib.sha256()
        total = 0
        with requests.get(BASE_URL + ARCHIVE, stream=True, timeout=(30, 120)) as response:
            response.raise_for_status()
            with archive.open('wb') as out:
                for chunk in response.iter_content(1024 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                    if total % (20 * 1024**2) == 0:
                        print(f'Runtime: {total // 1024**2} MiB', flush=True)
        if digest.hexdigest().lower() != match.group().lower():
            raise RuntimeError('HOT-Step 发布包 SHA256 不匹配')
        with zipfile.ZipFile(archive) as package:
            executables = [i for i in package.infolist() if Path(i.filename).name == 'ace-caption.exe']
            if len(executables) != 1:
                raise RuntimeError('发布包缺少唯一的 ace-caption.exe')
            binary_dir = Path(executables[0].filename).parent
            selected = [i for i in package.infolist() if not i.is_dir() and (
                (Path(i.filename).parent == binary_dir and
                 (Path(i.filename).suffix.lower() == '.dll' or Path(i.filename).name == 'ace-caption.exe')) or
                'license' in Path(i.filename).name.lower() or 'notice' in Path(i.filename).name.lower())]
            for entry in selected:
                relative = Path(entry.filename)
                if relative.parent == binary_dir:
                    target = destination / relative.name
                else:
                    target = destination / 'licenses' / relative
                resolved = target.resolve()
                if not resolved.is_relative_to(destination.resolve()):
                    raise RuntimeError('发布包中包含无效路径')
                resolved.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, resolved.open('wb') as out:
                    shutil.copyfileobj(source, out)
        (destination / 'release.json').write_text(json.dumps({
            'release': RELEASE, 'source': BASE_URL + ARCHIVE, 'sha256': digest.hexdigest(),
            'backend': 'CPU'}, indent=2), encoding='utf-8')
    print(f'CPU runtime installed: {destination / "ace-caption.exe"}')


def main():
    from flask import Flask
    from config import Config
    from services.moss_music import MODEL_KEY, download_weights, model_directory, runtime_status
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-only', action='store_true')
    parser.add_argument('--weights-only', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--register', action='store_true', help='仅幂等登记模型到当前数据库，不启动完整应用')
    args = parser.parse_args()
    app = Flask('prepare-moss-music')
    app.config.from_object(Config)
    with app.app_context():
        if args.register:
            from extensions import db
            from seed import _ensure_ai_model
            from services.moss_music import MODEL_FIELDS
            db.init_app(app)
            _ensure_ai_model(MODEL_KEY, MODEL_FIELDS)
            print('MOSS-Music model registered')
        elif args.check:
            print(json.dumps(runtime_status(), ensure_ascii=False, indent=2))
            print(f'Free disk: {shutil.disk_usage(BACKEND).free / 1024**3:.2f} GiB')
        else:
            if not args.weights_only:
                install_runtime(BACKEND / 'runtime' / 'hot-step')
            if not args.runtime_only:
                download_weights(model_directory(), token=app.config.get('HF_TOKEN'))
            print(json.dumps(runtime_status(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'MOSS-Music 准备失败：{exc}', file=sys.stderr)
        sys.exit(1)
