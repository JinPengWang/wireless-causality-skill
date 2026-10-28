"""Small semantic writer for equivalent Markdown and offline HTML reports."""
import base64
import html
import json
import mimetypes
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote
from report_design import stylesheet


def md(value):
    text = re.sub(r'([\\`*_\[\]<>|#~])', r'\\\1', str(value).replace('&', '&amp;')).replace('\r', '')
    text = re.sub(r'(?m)^([ \t]*)([-+]|[0-9]+[.)])(?=\s|$)',
                  lambda m: m[1]+m[2][:-1]+'\\'+m[2][-1], text)
    text = re.sub(r'(?m)^([ \t]*)([=-]{2,})\s*$',
                  lambda m: m[1]+''.join('\\'+c for c in m[2]), text)
    return re.sub(r'(?m)^( {4,}|\t+)', lambda m: '&#32;'*len(m[0]), text)


def anchor(kind, identity):
    return kind+'-'+str(identity).encode('utf-8').hex()


def image_data(path):
    path = Path(path)
    payload = path.read_bytes()
    if path.suffix.lower() == '.svg':
        root = ET.fromstring(payload)
        for node in root.iter():
            if node.tag.split('}')[-1].lower() in {'script', 'foreignobject'}:
                raise ValueError('Active SVG content is not supported in reports')
            for key, value in node.attrib.items():
                key = key.split('}')[-1].lower()
                if key.startswith('on') or (key in {'href', 'src'} and not value.startswith('#')):
                    raise ValueError('External or active SVG resources are not supported')
        text = payload.decode('utf-8-sig')
        if re.search(r'@import|url\(\s*[\"\']?(?!#)', text, re.I):
            # Matplotlib commonly uses url(#clip-id), which is a local reference.
            for target in re.findall(r'url\(([^)]*)\)', text, re.I):
                if not target.strip(' \"\'').startswith('#'):
                    raise ValueError('SVG must be self-contained')
            if '@import' in text.lower():
                raise ValueError('SVG imports are not supported')
    mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return 'data:'+mime+';base64,'+base64.b64encode(payload).decode('ascii')


class Writer:
    def __init__(self, output, output_format, title, language, theme):
        self.output = Path(output)
        self.html = output_format == 'html'
        self.title, self.language, self.theme = title, {'Chinese': 'zh-CN', '中文': 'zh-CN', 'English': 'en'}.get(language, language), theme
        self.parts = []
        self.sources = []

    def relative(self, path):
        try:
            relative = os.path.relpath(Path(path).resolve(), self.output.parent.resolve()).replace('\\', '/')
        except ValueError:
            return Path(path).resolve().as_uri()
        return quote(relative, safe='/.-_~')

    def heading(self, level, text, identity=None):
        if self.html:
            attr = ' id="'+html.escape(identity, quote=True)+'"' if identity else ''
            self.parts.append(f'<h{level}{attr}>'+html.escape(text)+f'</h{level}>')
        else:
            if identity:
                self.parts.append('<a id="'+identity+'"></a>\n')
            self.parts.append('#'*level+' '+md(text)+'\n')

    def paragraph(self, text, css=None):
        for part in re.split(r'\n\s*\n', str(text).strip()):
            if self.html:
                attr = ' class="'+css+'"' if css else ''
                self.parts.append('<p'+attr+'>'+html.escape(part).replace('\n', '<br>')+'</p>')
            else:
                self.parts.append(md(part)+'\n')

    def field(self, label, text, css=None):
        if self.html:
            self.parts.append('<p'+(' class="'+css+'"' if css else '')+'><strong>'+html.escape(label)+': </strong>'+html.escape(str(text)).replace('\n', '<br>')+'</p>')
        else:
            self.parts.append('**'+md(label)+':** '+md(text)+'\n')

    def references(self, label, pairs):
        if self.html:
            links = ['<a href="'+html.escape(url, quote=True)+'">'+html.escape(text)+'</a>' for text, url in pairs]
            self.parts.append('<p class="meta">'+html.escape(label)+': '+' · '.join(links)+'</p>')
        else:
            self.parts.append(md(label)+': '+' · '.join('['+md(text)+']('+url+')' for text, url in pairs)+'\n')

    def container(self, tag, css, begin=True):
        if self.html:
            self.parts.append('<'+tag+' class="'+css+'">' if begin else '</'+tag+'>')

    def code(self, text):
        if self.html:
            self.parts.append('<pre><code>'+html.escape(text)+'</code></pre>')
        else:
            fence = '`'*(max([len(s) for s in re.findall(r'`+', text)]+[2])+1)
            self.parts.append(fence+'text\n'+text+'\n'+fence+'\n')

    def figure(self, path, caption, number, label):
        title = label+' '+str(number)+'. '+caption
        if self.html:
            self.parts.append('<figure><img src="'+image_data(path)+'" alt="'+html.escape(title, quote=True)+'"><figcaption>'+html.escape(title)+'</figcaption></figure>')
        else:
            self.parts.append('!['+md(title)+']('+self.relative(path)+')\n\n'+md(title)+'\n')

    def table(self, headers, rows, caption=None):
        headers = [' '.join(str(h).split()) for h in headers]
        def cell(c):
            return c if isinstance(c, dict) else {'text': str(c), 'number': False}
        rows = [[cell(c) for c in r] for r in rows]
        numeric = [bool(rows) and all(r[i].get('number') for r in rows) for i in range(len(headers))]
        if self.html:
            self.parts.append('<div class="table-wrap'+(' small-table' if len(rows) <= 8 else ' large-table')+'"><table>')
            if caption:
                self.parts.append('<caption>'+html.escape(caption)+'</caption>')
            self.parts.append('<thead><tr>'+''.join('<th scope="col"'+(' class="number"' if numeric[i] else '')+'>'+html.escape(h)+'</th>' for i, h in enumerate(headers))+'</tr></thead><tbody>')
            for row in rows:
                self.parts.append('<tr>')
                for c in row:
                    ref = (' <a class="claim-ref" href="#'+anchor('claim', c['claim_id'])+'">['+html.escape(c['claim_id'])+']</a>') if c.get('claim_id') else ''
                    self.parts.append('<td'+(' class="number"' if c.get('number') else '')+(' title="'+html.escape(c['raw'], quote=True)+'"' if 'raw' in c else '')+'>'+html.escape(c['text']).replace('\n', '<br>')+ref+'</td>')
                self.parts.append('</tr>')
            self.parts.append('</tbody></table></div>')
        else:
            if caption:
                self.paragraph(caption)
            self.parts += ['| '+' | '.join(md(h) for h in headers)+' |', '| '+' | '.join('---:' if n else '---' for n in numeric)+' |']
            for row in rows:
                self.parts.append('| '+' | '.join(md(c['text']).replace('\n', '<br>')+(' ['+md(c['claim_id'])+'](#'+anchor('claim', c['claim_id'])+')' if c.get('claim_id') else '') for c in row)+' |')
            self.parts.append('')

    def finish(self):
        content = '\n'.join(self.parts)+'\n'
        if not self.html:
            return content
        csp = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
        return ('<!doctype html>\n<html lang="'+html.escape(self.language, quote=True)+'"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="generator" content="wireless-whitepaper-v1">'
                '<meta name="wireless-source-manifest" content="'+html.escape(json.dumps(self.sources, ensure_ascii=False), quote=True)+'">'
                '<meta http-equiv="Content-Security-Policy" content="'+html.escape(csp, quote=True)+'">'
                '<title>'+html.escape(self.title)+'</title><style>'+stylesheet(self.theme)+'</style></head><body><main>'+content+'</main></body></html>\n')
