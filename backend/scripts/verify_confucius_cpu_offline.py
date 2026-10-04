"""Run real CPU inference with offline llama-server and blocked client networking."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from confucius_cpu_server import server_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', choices=['r2t2', 't3po'])
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--server', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--startup-timeout', type=int, default=600)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    server = args.server or root / 'runtime' / 'llama-cpu' / 'llama-server.exe'
    report_dir = root / 'runtime' / 'confucius-verification'
    report_dir.mkdir(parents=True, exist_ok=True)
    port = 18273 if args.model == 'r2t2' else 18010
    command = server_command(server, args.model, root / 'weights' / 'confucius' / args.model,
                             port=port, threads=4, context=4096)
    command.extend(['-lv', '5'])
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    log_path = report_dir / (args.model + '-server.log')
    import requests
    from flask import Flask
    from services.confucius import transcribe, translate
    original_connect = socket.socket.connect
    def local_only(sock, address):
        if isinstance(address, tuple) and not ipaddress.ip_address(address[0]).is_loopback:
            raise RuntimeError('External network blocked by offline verification')
        return original_connect(sock, address)
    socket.socket.connect = local_only
    original_dns = socket.getaddrinfo
    def local_dns(host, *params, **kwargs):
        if host not in ('127.0.0.1', '::1', 'localhost'):
            raise RuntimeError('External DNS blocked by offline verification')
        return original_dns(host, *params, **kwargs)
    socket.getaddrinfo = local_dns
    report = {'model': args.model, 'command': command, 'cpuOnly': True,
              'runtimeOffline': True, 'clientExternalNetworkBlocked': True, 'passed': False}
    started = time.monotonic()
    try:
        with requests.Session() as session:
            session.trust_env = False
            try:
                session.get('https://example.org', timeout=2)
            except RuntimeError:
                report['networkGuardVerified'] = True
            else:
                raise RuntimeError('Offline network guard was not enforced')
        with log_path.open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    deadline = time.monotonic() + args.startup_timeout
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError(f'llama-server exited: {process.returncode}; inspect {log_path}')
                        try:
                            if session.get(f'http://127.0.0.1:{port}/health', timeout=2).status_code == 200:
                                break
                        except requests.RequestException:
                            pass
                        time.sleep(1)
                    else:
                        raise RuntimeError('llama-server health timeout')
                print(f'{args.model}: local CPU model ready; starting offline inference', flush=True)
                report['startupSeconds'] = round(time.monotonic() - started, 2)
                app = Flask(__name__)
                prefix = 'CONFUCIUS_R2T2' if args.model == 'r2t2' else 'CONFUCIUS_T3PO'
                app.config.update({prefix + '_BACKEND': 'llama-cpu',
                                   prefix + '_CPU_URL': f'http://127.0.0.1:{port}',
                                   prefix + '_CPU_MAX_TOKENS': 128,
                                   'CONFUCIUS_CPU_TIMEOUT_SECONDS': args.timeout})
                with app.app_context():
                    if args.model == 'r2t2':
                        audio = args.audio or root / 'weights' / 'confucius' / 'test-audio.wav'
                        result = transcribe(str(audio), language='zh')
                        report['results'] = [result]
                    else:
                        report['results'] = []
                        for text, direction in [('你好。', 'zh2en'), ('Hello.', 'en2zh')]:
                            result = translate(text, direction=direction)
                            report['results'].append(result)
                            print(json.dumps(result, ensure_ascii=False), flush=True)
                report['passed'] = True
                print(json.dumps(report['results'], ensure_ascii=False), flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        socket.socket.connect = original_connect
        socket.getaddrinfo = original_dns
        report['elapsedSeconds'] = round(time.monotonic() - started, 2)
        (report_dir / (args.model + '-offline.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
