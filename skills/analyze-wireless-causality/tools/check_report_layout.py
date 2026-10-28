"""Check a generated offline HTML report; optionally capture previews and export PDF.

Automatic structural/overflow checks never certify visual quality or causal truth.
Browser operations require an existing Chromium executable and optional websocket-client.
"""
import argparse
import importlib.metadata
import json
import re
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname
from common import ensure_output_safe, sha256, write_json


class Structure(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.links, self.images, self.headings, self.errors = [], [], [], [], []
        self.generated = False
        self.sources = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name') == 'generator' and attrs.get('content') == 'wireless-whitepaper-v1':
            self.generated = True
        if tag == 'meta' and attrs.get('name') == 'wireless-source-manifest':
            try:
                if self.sources is not None:
                    raise ValueError('Duplicate source manifest')
                self.sources = json.loads(attrs.get('content', ''))
            except (ValueError, TypeError):
                self.errors.append('Invalid source protection manifest')
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        if tag == 'a':
            self.links.append(attrs.get('href', ''))
        if tag == 'img':
            self.images.append(attrs)
        if re.fullmatch('h[1-6]', tag):
            self.headings.append(int(tag[1]))
        if tag in {'script', 'iframe', 'object', 'embed', 'link', 'form', 'base'} or any(k.lower().startswith('on') for k in attrs):
            self.errors.append('Active or external resource element: '+tag)


def local_path(link, parent):
    url = urlsplit(link)
    if url.scheme == 'file' and url.netloc in {'', 'localhost'}:
        return Path(url2pathname(url.path)).resolve()
    if url.scheme or url.netloc:
        raise ValueError('Expected a local file reference')
    return (Path(parent)/unquote(url.path)).resolve()


def inspect_html(source):
    source = Path(source).resolve()
    text = source.read_text(encoding='utf-8-sig')
    parser = Structure()
    parser.feed(text)
    errors, warnings, protected = list(parser.errors), [], [source]
    if not parser.generated:
        errors.append('Only generated wireless-whitepaper-v1 HTML is supported')
    if not isinstance(parser.sources, list) or not parser.sources:
        errors.append('Missing source protection manifest')
    else:
        for item in parser.sources:
            if not isinstance(item, dict) or set(item) != {'path', 'sha256'} or not isinstance(item['path'], str):
                errors.append('Invalid protected artifact entry')
                continue
            url = urlsplit(item['path'])
            if url.scheme not in {'', 'file'} or url.netloc not in {'', 'localhost'}:
                errors.append('Protected artifact must be local')
                continue
            path = local_path(item['path'], source.parent)
            protected.append(path)
            if not path.is_file() or sha256(path) != item['sha256']:
                errors.append('Protected artifact is missing or changed: '+item['path'])
    if len(set(parser.ids)) != len(parser.ids):
        errors.append('Duplicate HTML ids')
    if parser.headings.count(1) != 1 or any(b > a+1 for a, b in zip(parser.headings, parser.headings[1:])) or any(h > 3 for h in parser.headings):
        errors.append('Use one title and a continuous hierarchy no deeper than h3')
    for link in parser.links:
        url = urlsplit(link)
        if url.scheme not in {'', 'file'} or url.netloc not in {'', 'localhost'}:
            errors.append('Expected local evidence or internal navigation link: '+link)
        elif url.path:
            path = local_path(link, source.parent)
            protected.append(path)
            if not path.is_file():
                errors.append('Broken artifact link: '+link)
        elif url.fragment not in parser.ids:
            errors.append('Broken internal anchor: '+link)
    for image in parser.images:
        if not image.get('alt', '').strip():
            errors.append('Figure has no accessible caption')
        if not image.get('src', '').startswith('data:image/'):
            errors.append('Report figures must be embedded for offline reading')
    for css in re.findall(r'<style[^>]*>(.*?)</style>', text, re.I | re.S):
        if re.search(r'@import|url\s*\(', css, re.I):
            errors.append('External/URL-based CSS is unsupported')
    if text.count('<h3') > 40:
        warnings.append('Long report: inspect navigation and appendix density')
    return {'errors': errors, 'warnings': warnings, 'images': len(parser.images)}, protected, text


def find_browser(explicit=None):
    if explicit:
        candidate = shutil.which(explicit) or explicit
        if not Path(candidate).is_file():
            raise ValueError('Browser executable not found: '+explicit)
        return str(Path(candidate).resolve())
    candidates = [shutil.which(n) for n in ['chromium', 'chromium-browser', 'google-chrome', 'chrome', 'msedge']]
    candidates += [r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                   r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                   '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


def check(source, output, preview_dir=None, pdf=None, browser=None, use_browser=True, work_dir=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    initial = sha256(source)
    structure, protected, text = inspect_html(source)
    ensure_output_safe(output, protected, '.json')
    if output.exists():
        raise ValueError('Use a fresh layout-check output path; existing files are not overwritten')
    artifacts = []
    if preview_dir:
        for name in ['desktop.png', 'mobile.png']:
            artifacts.append(Path(preview_dir).resolve()/name)
    if pdf:
        artifacts.append(Path(pdf).resolve())
        ensure_output_safe(pdf, protected+[output], '.pdf')
    for path in artifacts:
        ensure_output_safe(path, protected+[output]+[p for p in artifacts if p != path])
        if path.exists():
            raise ValueError('Use a fresh preview/PDF path; existing artifacts are not overwritten: '+str(path))
    result = {'schema_version': 1, 'html': str(source), 'html_sha256': initial, 'static': structure,
              'browser': {'status': 'not_checked', 'reason': 'Browser execution not requested'},
              'pdf': {'status': 'not_requested'}, 'visual_review': {'status': 'not_checked',
              'reason': 'Inspect actual previews and PDF pages; automatic checks do not assess aesthetics, glyph coverage or meaning'},
              'commands': [], 'artifacts': []}
    try:
        dependency_version = importlib.metadata.version('websocket-client')
    except importlib.metadata.PackageNotFoundError:
        dependency_version = None
    result['checker_provenance'] = {'websocket_client': dependency_version,
                                    'tool_sha256': sha256(__file__),
                                    'browser_transport_sha256': sha256(Path(__file__).with_name('browser_render.py'))}
    if not structure['errors'] and use_browser:
        try:
            from browser_render import Chromium
            executable = find_browser(browser)
            if not executable:
                raise ImportError('No existing Chromium browser was found')
            output.parent.mkdir(parents=True, exist_ok=True)
            screens = []
            with tempfile.TemporaryDirectory(prefix='wireless_report_', dir=work_dir or output.parent, ignore_cleanup_errors=True) as temporary:
                directory = Path(temporary)
                with Chromium(executable, directory, result['commands']) as session:
                    for name, width in [('desktop', 1280), ('mobile', 390)]:
                        record = session.load(source, width)
                        screens.append(record)
                        if preview_dir:
                            capture = directory/(name+'.png')
                            session.screenshot(capture)
                            destination = Path(preview_dir).resolve()/capture.name
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(capture, destination)
                            result['artifacts'].append({'path': str(destination), 'sha256': sha256(destination), 'scope': 'first viewport only'})
                    failed = any(s['page_overflow'] or s['overflow'] or s['failed_images'] or not s['fonts_ready'] or not s['viewport_matches'] for s in screens)
                    result['browser'] = {'status': 'failed' if failed else 'passed', 'screens': screens,
                                         'scope': 'Exact-viewport DOM horizontal overflow, image decode and font-loading checks only'}
                    if pdf:
                        capture = directory/'print.pdf'
                        session.load(source, 1280)
                        session.pdf(capture)
                        Path(pdf).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(capture, pdf)
                        result['pdf'] = {'status': 'exported', 'path': str(Path(pdf).resolve()), 'sha256': sha256(pdf),
                                         'pagination_review': 'not_checked'}
        except ImportError as exc:
            result['browser'] = {'status': 'unsupported', 'reason': str(exc)}
            if pdf:
                result['pdf'] = {'status': 'unsupported', 'reason': str(exc)}
        except Exception as exc:
            result['browser'] = {'status': 'failed', 'reason': type(exc).__name__+': '+str(exc)}
            if pdf:
                result['pdf'] = {'status': 'failed', 'reason': 'Browser rendering failed'}
    elif pdf:
        result['pdf'] = {'status': 'not_checked', 'reason': 'Static checks failed or browser execution was disabled'}
    if sha256(source) != initial:
        result['static']['errors'].append('HTML changed during layout checks')
    failed = bool(result['static']['errors']) or result['browser']['status'] == 'failed' or result['pdf']['status'] == 'failed'
    result['automatic_status'] = 'failed' if failed else ('passed' if result['browser']['status'] == 'passed' else 'partial')
    write_json(output, result, protected+artifacts)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--html', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--preview-dir')
    p.add_argument('--pdf', help='Optional PDF destination; never inferred from completion of HTML export')
    p.add_argument('--browser', help='Existing Chrome/Edge/Chromium executable')
    p.add_argument('--static-only', action='store_true')
    p.add_argument('--work-dir', help='Existing writable directory for a temporary isolated browser profile')
    a = p.parse_args()
    result = check(a.html, a.output, a.preview_dir, a.pdf, a.browser, not a.static_only, a.work_dir)
    print(json.dumps({'automatic_status': result['automatic_status'], 'visual_review': 'not_checked', 'output': a.output}))
    raise SystemExit(2 if result['automatic_status'] == 'failed' or (a.pdf and result['pdf']['status'] != 'exported') else 0)


if __name__ == '__main__':
    main()
