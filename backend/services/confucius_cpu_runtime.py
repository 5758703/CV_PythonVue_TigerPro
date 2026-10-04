"""Start the prepared local CPU runtime on demand; never download assets."""
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit

from flask import current_app
import requests

_locks = {key: threading.Lock() for key in ('CONFUCIUS_R2T2', 'CONFUCIUS_T3PO')}
_processes = {}


def ensure_cpu_service(url, prefix):
    if not current_app.config.get('CONFUCIUS_CPU_AUTO_START', False):
        return
    parsed = urlsplit(url)
    # service_configuration already validates loopback. This launcher supports
    # the native server's HTTP root and /v1 endpoints only.
    if parsed.scheme != 'http' or parsed.path.rstrip('/') not in ('', '/v1'):
        raise RuntimeError('Confucius CPU 自动启动仅支持本机 HTTP 根地址或 /v1；自建服务请关闭自动启动')
    health_url = url.removesuffix('/v1').rstrip('/') + '/health'
    headers = {}
    if key := current_app.config.get(prefix + '_CPU_API_KEY'):
        headers['Authorization'] = 'Bearer ' + key
    with _locks[prefix], requests.Session() as session:
        session.trust_env = False
        deadline = time.monotonic() + float(current_app.config.get('CONFUCIUS_CPU_STARTUP_TIMEOUT_SECONDS', 600))
        process = None
        while True:
            try:
                response = session.get(health_url, headers=headers, timeout=(2, 3), allow_redirects=False)
                if response.status_code == 200:
                    return
                if response.status_code != 503:
                    raise RuntimeError(f'Confucius CPU 服务健康检查失败（HTTP {response.status_code}），请检查地址或认证配置')
                # A server is already loading. Wait instead of starting another.
            except requests.ConnectionError:
                if process is None:
                    process = _processes.get(prefix)
                    if process is None or process.poll() is not None:
                        process = _start_cpu_service(prefix, parsed.port or 80)
                        _processes[prefix] = process
            except requests.Timeout:
                pass
            if process is not None and process.poll() is not None:
                raise RuntimeError(f'Confucius CPU 服务启动失败（退出码 {process.returncode}），请检查 backend/runtime 下的模型日志')
            if time.monotonic() >= deadline:
                # Keep a loading service alive so a later request can reuse it.
                raise RuntimeError('Confucius CPU 模型仍未加载完成，请稍后重试或增加 CONFUCIUS_CPU_STARTUP_TIMEOUT_SECONDS')
            time.sleep(1)


def _start_cpu_service(prefix, port):
    from scripts.confucius_cpu_server import server_command
    root = Path(current_app.config.get('BASE_DIR') or Path(__file__).resolve().parents[1])
    executable = root / 'runtime' / 'llama-cpu' / ('llama-server.exe' if os.name == 'nt' else 'llama-server')
    model = 'r2t2' if prefix.endswith('R2T2') else 't3po'
    if not executable.is_file():
        raise RuntimeError('Confucius CPU 运行时缺失，请先准备 backend/runtime/llama-cpu；自动启动不会联网下载')
    try:
        command = server_command(executable, model, root / 'weights' / 'confucius' / model, port=port)
    except ValueError as exc:
        raise RuntimeError('Confucius CPU 本地权重缺失或无效，请先准备对应 GGUF 文件') from exc
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    log_path = root / 'runtime' / (model + '-cpu-service.log')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open('a', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except OSError as exc:
        raise RuntimeError('Confucius CPU 模型服务无法启动，请检查运行时文件及权限') from exc
    current_app.logger.info('Started %s CPU service, PID %s; log %s', model, process.pid, log_path)
    return process
