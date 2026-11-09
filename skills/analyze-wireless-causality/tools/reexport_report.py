"""Re-export a trusted frozen package using the currently selected Python.

Run the packaged reexport.py with --output-dir pointing to a fresh sibling
directory. Hash checks establish integrity, not trust in executable source.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def settings_digest(presentation, theme):
    payload = json.dumps([presentation, theme], ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def reexport(root, output, formats=('html','markdown','json')):
    root=Path(root).resolve(); target=Path(output)
    if target.exists() or target.is_symlink(): raise ValueError('Use a fresh export directory')
    target=target.resolve()
    if target == root or root in target.parents or target in root.parents:
        raise ValueError('Export into a separate directory outside the frozen package')
    if not formats or any(f not in {'html','markdown','json'} for f in formats) or len(set(formats)) != len(formats):
        raise ValueError('Choose distinct html/markdown/json formats')
    manifest_path=root/'snapshot_manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest_hash=digest(manifest_path)

    def located(relative):
        path=(root/relative).resolve()
        if path == root or root not in path.parents: raise ValueError('Resource escapes frozen package')
        return path

    ledger=manifest['archived_ledger']
    entries=[{'snapshot_path':ledger['path'], 'sha256':ledger['sha256']}]
    entries += manifest['runtime_resources']+manifest['artifacts']+manifest.get('explicit_configuration',[])
    hashes={}
    for item in entries:
        path=located(item['snapshot_path']); expected=item['sha256']
        if not path.is_file() or digest(path) != expected: raise ValueError('Missing or changed package resource: '+str(path))
        if path in hashes and hashes[path] != expected: raise ValueError('Conflicting package hashes')
        hashes[path]=expected
    renderer=located('skill/tools/write_report.py')
    if renderer not in hashes: raise ValueError('Renderer must be included in verified resources')
    configuration=[]
    for entry in manifest.get('explicit_configuration',[]):
        if entry['usage'] not in {'presentation','theme'}: raise ValueError('Unsupported export configuration')
        configuration.extend(['--'+entry['usage'], str(located(entry['snapshot_path']))])
    target.parent.mkdir(parents=True,exist_ok=True); target.mkdir()
    runs=[]
    expected_settings = manifest.get('source_reader_edition', {}).get('settings_sha256')
    reader_settings_match = None
    for fmt in formats:
        suffix={'html':'html','markdown':'md','json':'json'}[fmt]
        command=[sys.executable,'-B','-X','utf8',str(renderer),'--ledger',str(located(ledger['path'])),
                 '--format',fmt,'--output',str(target/('report.'+suffix)),*configuration]
        completed=subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8')
        runs.append({'argv':command,'exit_code':completed.returncode,'stdout':completed.stdout,'stderr':completed.stderr})
        if completed.returncode: break
        if expected_settings is not None and fmt in {'html', 'markdown'}:
            audit_file = target/'report.audit.json'
            try:
                with audit_file.open(encoding='utf-8') as stream:
                    trace = json.load(stream)['presentation']
                reader_settings_match = settings_digest(trace['presentation'], trace['theme']) == expected_settings
            except (OSError, ValueError, KeyError, TypeError) as exc:
                reader_settings_match = False
                runs[-1]['reader_audit_error'] = str(exc)
            if not reader_settings_match:
                break
    unchanged=digest(manifest_path)==manifest_hash and all(p.is_file() and digest(p)==h for p,h in hashes.items())
    result={'exports':runs,'package_inputs_unchanged':unchanged,'visual_review':'not_checked',
            'source_reader_settings_match': reader_settings_match,
            'scope':'Frozen evidence and renderer re-export only; original analysis is not rerun.'}
    (target/'reexport_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not unchanged or reader_settings_match is False or any(r['exit_code'] for r in runs):
        raise ValueError('Re-export failed; see reexport_result.json')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',default=str(Path(__file__).resolve().parent))
    p.add_argument('--output-dir',required=True)
    p.add_argument('--format',action='append',choices=['html','markdown','json'])
    a=p.parse_args(); reexport(a.snapshot,a.output_dir,a.format or ('html','markdown','json'))


if __name__ == '__main__': main()
