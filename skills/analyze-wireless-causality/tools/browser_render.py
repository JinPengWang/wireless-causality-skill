"""Optional Chromium DevTools transport for exact-viewport report rendering.

Uses an isolated temporary browser profile and loopback-only debugging endpoint.
No browser download, personal profile, external page or sandbox override is used.
"""
import base64
import json
import subprocess
import time
from pathlib import Path


PROBE = r"""(async () => {
  await document.fonts.ready;
  await Promise.all([...document.images].map(i => i.decode().catch(() => null)));
  const nodes = [...document.querySelectorAll('h1,h2,h3,p,td,th,figcaption,pre')];
  return {user_agent:navigator.userAgent, width:window.innerWidth,
    page_overflow:document.documentElement.scrollWidth > window.innerWidth + 2,
    overflow:nodes.filter(e => e.clientWidth > 0 && e.scrollWidth > e.clientWidth + 2)
      .map(e => ({tag:e.tagName,text:e.innerText.slice(0,100),width:e.clientWidth,scroll:e.scrollWidth})),
    failed_images:[...document.images].filter(e => !e.complete || !e.naturalWidth).map(e => e.alt),
    fonts_ready:document.fonts.status === 'loaded'};
})()"""


class Chromium:
    def __init__(self, executable, directory, commands):
        self.executable, self.directory, self.commands = executable, Path(directory), commands
        self.socket, self.process, self.log, self.session = None, None, None, None
        self.sequence = 0

    def __enter__(self):
        try:
            import websocket
        except ImportError as exc:
            raise ImportError('Browser rendering requires the optional websocket-client package in the selected environment') from exc
        try:
            profile = self.directory/'profile'
            args = [self.executable, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                    '--disable-background-networking', '--disable-component-update', '--disable-extensions',
                    '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                    '--user-data-dir='+str(profile), 'about:blank']
            self.commands.append(args)
            self.log = (self.directory/'browser.log').open('w+b')
            self.process = subprocess.Popen(args, stdout=self.log, stderr=self.log,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            port_file = profile/'DevToolsActivePort'
            deadline = time.monotonic()+15
            while not port_file.is_file():
                if self.process.poll() is not None or time.monotonic() > deadline:
                    self.log.seek(0)
                    raise RuntimeError('Chromium did not start: '+self.log.read().decode('utf-8', errors='replace')[-1400:])
                time.sleep(.05)
            port, endpoint = port_file.read_text(encoding='utf-8').splitlines()[:2]
            if not port.isdigit() or not endpoint.startswith('/devtools/browser/'):
                raise RuntimeError('Unexpected local DevTools endpoint')
            self.socket = websocket.create_connection('ws://127.0.0.1:'+port+endpoint, timeout=15, suppress_origin=True,
                                                      http_no_proxy=['127.0.0.1', 'localhost'])
            target = self.call('Target.createTarget', {'url': 'about:blank'})['targetId']
            self.session = self.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
            self.call('Page.enable')
            self.call('Runtime.enable')
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def call(self, method, params=None):
        self.sequence += 1
        packet = {'id': self.sequence, 'method': method, 'params': params or {}}
        if self.session:
            packet['sessionId'] = self.session
        self.socket.send(json.dumps(packet))
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            response = json.loads(self.socket.recv())
            if response.get('id') == self.sequence:
                if 'error' in response:
                    raise RuntimeError(method+': '+str(response['error']))
                return response.get('result', {})
        raise TimeoutError('DevTools response timed out: '+method)

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', {'expression': expression, 'awaitPromise': True, 'returnByValue': True})
        if 'exceptionDetails' in result:
            raise RuntimeError('DOM probe failed: '+str(result['exceptionDetails']))
        return result.get('result', {}).get('value')

    def load(self, source, width=1280):
        self.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1100, 'deviceScaleFactor': 1, 'mobile': False})
        url = Path(source).resolve().as_uri()
        navigation = self.call('Page.navigate', {'url': url})
        if navigation.get('errorText'):
            raise RuntimeError(navigation['errorText'])
        deadline = time.monotonic()+12
        while not self.evaluate('location.href === '+json.dumps(url)+' && document.readyState === "complete"'):
            if time.monotonic() > deadline:
                raise RuntimeError('Local report navigation did not finish')
            time.sleep(.05)
        record = self.evaluate(PROBE)
        record.update(requested_width=width, viewport_matches=record['width'] == width)
        return record

    def screenshot(self, output):
        result = self.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
        payload = base64.b64decode(result['data'], validate=True)
        if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Invalid browser screenshot')
        Path(output).write_bytes(payload)

    def pdf(self, output):
        self.call('Emulation.setEmulatedMedia', {'media': 'print'})
        result = self.call('Page.printToPDF', {'printBackground': True, 'preferCSSPageSize': True, 'displayHeaderFooter': False})
        payload = base64.b64decode(result['data'], validate=True)
        if not payload.startswith(b'%PDF-'):
            raise RuntimeError('Invalid browser PDF')
        Path(output).write_bytes(payload)

    def __exit__(self, *args):
        if self.socket:
            self.socket.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()
