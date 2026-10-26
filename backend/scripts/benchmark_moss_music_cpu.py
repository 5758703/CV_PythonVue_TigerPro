"""Measure complete CPU CLI calls, including model load, on an actual audio file."""
import argparse
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from flask import Flask
    from config import Config
    from services.moss_music import analyze
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--mode', choices=['lyrics', 'prose', 'mm3'], default='lyrics')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--max-tokens', type=int, default=128)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    app = Flask('benchmark-moss-music')
    app.config.from_object(Config)
    app.config.update(MOSS_MUSIC_THREADS=args.threads, MOSS_MUSIC_MAX_TOKENS=args.max_tokens)
    runs = []
    with app.app_context():
        for index in range(max(1, args.runs)):
            result = analyze(str(args.audio.resolve()), mode=args.mode)
            runs.append(result)
            print(json.dumps({'run': index + 1, **result}, ensure_ascii=False), flush=True)
    report = dict(backend='hot-step-cpu', threads=args.threads, maxTokens=args.max_tokens,
                  note='每次调用均重新加载模型；后续调用仅可能受益于操作系统文件缓存，不代表常驻模型热推理。',
                  medianSeconds=statistics.median(r['elapsedSeconds'] for r in runs),
                  medianRTF=statistics.median(r['rtf'] for r in runs), runs=runs)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'runs'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
