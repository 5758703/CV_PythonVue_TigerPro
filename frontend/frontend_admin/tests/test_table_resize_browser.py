"""Chromium CDP regression; run Vite then pass --browser (requires websockets).
Uses a temporary profile and never attaches to an existing browser session.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from websockets.sync.client import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', required=True)
    parser.add_argument('--url', default='http://127.0.0.1:5188')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='tiger-resize-browser-') as profile:
        log = open(Path(profile) / 'browser.log', 'w+', encoding='utf-8')
        proc = subprocess.Popen([args.browser, '--headless=new', '--window-size=1400,1000',
                                 '--disable-gpu', '--no-first-run', '--remote-debugging-port=0',
                                 f'--user-data-dir={profile}', 'about:blank'], stdout=log, stderr=log,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ws = None
        try:
            deadline = time.monotonic() + 20
            active_port = Path(profile) / 'DevToolsActivePort'
            while not active_port.exists() and time.monotonic() < deadline:
                time.sleep(.1)
            if not active_port.exists():
                log.seek(0)
                raise RuntimeError('Chromium did not start: ' + log.read()[-2000:])
            port = int(active_port.read_text().splitlines()[0])
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as result:
                target = next(t for t in json.load(result) if t['type'] == 'page')
            ws = connect(target['webSocketDebuggerUrl'])
            run_checks(ws, args.url)
        finally:
            if ws:
                try:
                    ws.send(json.dumps({'id': 999999, 'method': 'Browser.close'}))
                except Exception:
                    pass
                ws.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)
            log.close()


def run_checks(ws, url):
    sequence = 0
    def cdp(method, params=None):
        nonlocal sequence
        sequence += 1
        ws.send(json.dumps({'id': sequence, 'method': method, 'params': params or {}}))
        while True:
            value = json.loads(ws.recv(timeout=30))
            if value.get('id') == sequence:
                if 'error' in value:
                    raise RuntimeError(value['error'])
                return value.get('result', {})

    def js(script):
        result = cdp('Runtime.evaluate', {'expression': '(function(){' + script + '})()', 'returnByValue': True})
        if 'exceptionDetails' in result:
            raise RuntimeError(result['exceptionDetails'])
        return result.get('result', {}).get('value')

    def wait(script):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if js(script):
                return
            time.sleep(.1)
        raise AssertionError('Browser condition timed out: ' + script)

    def width(selector):
        return js(f'return document.querySelector({json.dumps(selector)}).getBoundingClientRect().width')

    def drag(selector, delta):
        rect = js(f'const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return {{x:r.x+r.width/2,y:r.y+r.height/2}}')
        x, y = round(rect['x']), round(rect['y'])
        cdp('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})
        cdp('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
        for step in range(1, 11):
            cdp('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x + delta * step / 10, 'y': y, 'buttons': 1})
            time.sleep(.02)
        cdp('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x + delta, 'y': y, 'button': 'left', 'clickCount': 1})
        time.sleep(.15)

    cdp('Page.navigate', {'url': url + '/tests/resize-tables.html'})
    wait('return document.querySelectorAll("[data-testid=regular] .tiger-column-resize-handle").length === 4')
    for index, delta in [(1, 45), (2, 40), (3, 80), (4, 60)]:
        th = f'[data-testid=regular] thead th:nth-child({index})'
        before = width(th)
        drag(th + ' .tiger-column-resize-handle', delta)
        assert abs(width(th) - before - delta) < 3, (index, before, width(th))
        assert abs(width(th) - width(f'[data-testid=regular] tbody tr:first-child td:nth-child({index})')) < 2
    assert js('return resizeFixtureState()') == {'selection': 0, 'sorts': 0, 'clicks': 0}
    js('document.querySelector("[data-testid=regular] thead .el-checkbox__input").click()')
    wait('return resizeFixtureState().selection === 2')
    js('document.querySelector("[data-testid=regular] thead th.is-sortable .cell").click()')
    wait('return resizeFixtureState().sorts === 1')
    js('document.querySelector("#column").click()')
    wait('return document.querySelectorAll("[data-testid=regular] .tiger-column-resize-handle").length === 5')
    js('document.querySelector("[data-testid=regular] .el-scrollbar__wrap").scrollLeft = 10000')
    time.sleep(.2)
    dynamic = '[data-testid=regular] thead th:nth-child(4)'
    before = width(dynamic)
    drag(dynamic + ' .tiger-column-resize-handle', 50)
    assert abs(width(dynamic) - before - 50) < 3, ('dynamic', before, width(dynamic))
    tree = '[data-testid=tree] thead th:first-child'
    before = width(tree)
    drag(tree + ' .tiger-column-resize-handle', 50)
    assert abs(width(tree) - before - 50) < 3
    assert js('return document.querySelectorAll("[data-testid=tree] tbody tr").length') == 2
    native = '[data-testid=native] thead th:last-child'
    before = width(native)
    drag(native + ' .tiger-column-resize-handle', 70)
    assert abs(width(native) - before - 70) < 3
    assert abs(width(native) - width('[data-testid=native] tbody tr:first-child td:last-child')) < 2
    js('document.querySelector("[data-testid=native] tbody tr").click()')
    assert js('return resizeFixtureState().clicks') == 1
    # Unmount during a drag must remove document listeners and the resize cursor.
    js('document.querySelector("[data-testid=regular] .tiger-column-resize-handle").dispatchEvent(new PointerEvent("pointerdown", {bubbles:true, button:0,pointerId:44,clientX:40})); document.querySelector("#toggle").click()')
    wait('return !document.querySelector("[data-testid=regular]") && !document.documentElement.classList.contains("tiger-resizing-column")')
    js('document.querySelector("#toggle").click()')
    wait('return document.querySelectorAll("[data-testid=regular] .tiger-column-resize-handle").length === 5')
    print('PASS: selection/index/sortable/fixed-last columns; body alignment; selection/sorting; dynamic columns; tree/native tables; unmount cleanup')


if __name__ == '__main__':
    main()
