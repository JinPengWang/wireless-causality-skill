"""Reproducible investigation I/O; records attest execution, not causal validity."""
import hashlib
import importlib.metadata
import platform
import sys
from pathlib import Path
from common import read_json, parse_json, sha256, ensure_output_safe, write_json


def artifact(base, spec):
    path = (Path(base) / spec['path']).resolve()
    if not path.is_file() or sha256(path) != spec.get('sha256'):
        raise ValueError('Missing or changed input artifact: ' + str(path))
    return path


def snapshot_json(path, expected=None):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError('Changed input artifact: ' + str(path))
    return parse_json(raw.decode('utf-8-sig')), digest


def provenance(request_path, paths, tool_files, argv=None):
    packages = {}
    for name in ['numpy', 'openpyxl', 'scipy', 'tigramite']:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        'request': {'path': str(Path(request_path).resolve()), 'sha256': sha256(request_path)},
        'sources': [{'path': str(Path(p).resolve()), 'sha256': sha256(p)} for p in dict.fromkeys(paths)],
        'tools': [{'path': str(Path(p).resolve()), 'sha256': sha256(p)} for p in tool_files],
        'runtime': {'executable': sys.executable, 'python': platform.python_version(), 'packages': packages},
        'command_argv': [sys.executable] + list(sys.argv if argv is None else argv),
        'verification_scope': 'Artifact integrity and executed calculations; no semantic or causal certification.'
    }


def run_analysis_cli(analyze, tool_file, description):
    import argparse
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    request_path = Path(args.request).resolve()
    request, request_digest = snapshot_json(request_path)
    data_path = artifact(request_path.parent, request['data'])
    data, data_digest = snapshot_json(data_path, request['data']['sha256'])
    sources = [artifact(data_path.parent, spec) for spec in data.get('sources', [])]
    protected = [request_path, data_path] + sources
    ensure_output_safe(args.output, protected, '.json')
    before = {str(request_path): request_digest, str(data_path): data_digest}
    before.update({str(path): spec['sha256'] for path, spec in zip(sources, data.get('sources', []))})
    result = analyze(request, data)
    result['provenance'] = provenance(request_path, [data_path] + sources,
        [tool_file, Path(__file__), Path(__file__).with_name('common.py')])
    result['inputs_unchanged'] = all(sha256(p) == h for p, h in before.items())
    if not result['inputs_unchanged']:
        raise ValueError('Input changed during analysis; do not publish stale results')
    write_json(args.output, result, inputs=protected)
    return result
