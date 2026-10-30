"""Archive a validated report ledger, exact evidence bytes and offline renderer.

This is a file-only operation. Historical source code is copied, never imported
or executed. An explicit historical source root may recover provenance tools
only when every recorded SHA256 still matches; evidence hashes are never reset.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from common import read_json, sha256
from evidence_model import validate_evidence


DEFAULT_SKILL = Path(__file__).resolve().parents[1]


def _relative(path, root):
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def _references(report):
    """Yield only schema-declared file references, with their JSON pointers."""
    for section in ['phenomena', 'findings']:
        for index, item in enumerate(report.get(section, [])):
            for kind in ['evidence', 'figures']:
                for number, artifact in enumerate(item.get(kind, [])):
                    yield f'/{section}/{index}/{kind}/{number}', kind, artifact
    for key, artifact in report.get('numeric_claims', {}).get('artifacts', {}).items():
        token = key.replace('~', '~0').replace('/', '~1')
        yield '/numeric_claims/artifacts/'+token, 'numeric', artifact
    for index, artifact in enumerate(report.get('provenance', {}).get('artifacts', [])):
        yield f'/provenance/artifacts/{index}', 'provenance', artifact


def _runtime_files(root):
    tools, assets = root/'tools', root/'assets'/'report'
    if not tools.is_dir() or not assets.is_dir():
        raise ValueError('Renderer source root needs tools/ and assets/report/: '+str(root))
    paths = sorted(tools.glob('*.py'))+sorted(p for p in assets.rglob('*') if p.is_file())
    if (root/'SKILL.md').is_file():
        paths.append(root/'SKILL.md')
    for path in paths:
        if not path.is_file() or _relative(path.resolve(), root) is None:
            raise ValueError('Runtime resource escapes its source root: '+str(path))
    if not (tools/'write_report.py').is_file():
        raise ValueError('Renderer source root has no tools/write_report.py')
    for name in ['theme.json', 'whitepaper.css']:
        if not (assets/name).is_file():
            raise ValueError('Missing renderer asset: '+str(assets/name))
    return paths


def _check_output(output, skill_root, source_root, ledger):
    if output.exists() or output.is_symlink():
        raise ValueError('Use a fresh output directory; snapshots are never overwritten: '+str(output))
    for root in {skill_root, source_root}:
        if output == root or _relative(root, output) is not None:
            raise ValueError('Output must not contain or replace a source root')
        for protected in [root/'tools', root/'assets'/'report']:
            if _relative(output, protected) is not None:
                raise ValueError('Output overlaps renderer source resources')
    if output == ledger or _relative(ledger, output) is not None:
        raise ValueError('Output must not contain or replace the original ledger')


def _verify_unchanged(hashes):
    for path, digest in hashes.items():
        if not path.is_file() or sha256(path) != digest:
            raise ValueError('An original input or source resource changed during snapshot: '+str(path))


def snapshot(ledger_path, output_dir, skill_root=None, source_root=None,
             presentation_path=None, theme_path=None, *, _invocation=None):
    """Return the manifest of a fresh, independently re-exportable snapshot.

    Existing ledger text, semantic statements, assessment and historical command
    records are retained. Only declared file paths and validation.result_path
    links change in the copied ledger. snapshot_manifest.json describes this
    operation separately and never certifies historical visual review anew.
    """
    ledger = Path(ledger_path).resolve()
    requested_output = Path(output_dir)
    if requested_output.exists() or requested_output.is_symlink():
        raise ValueError('Use a fresh output directory; snapshots are never overwritten: '+str(requested_output))
    output = requested_output.resolve()
    skill_root = Path(skill_root if skill_root is not None else DEFAULT_SKILL).resolve()
    source_root = Path(source_root if source_root is not None else skill_root).resolve()
    _check_output(output, skill_root, source_root, ledger)
    if not ledger.is_file():
        raise ValueError('Missing source ledger: '+str(ledger))
    ledger_digest = sha256(ledger)
    report = read_json(ledger)
    if sha256(ledger) != ledger_digest:
        raise ValueError('Source ledger changed while reading')
    archived = copy.deepcopy(report)
    original_hashes = {ledger: ledger_digest}
    destinations = {}
    resource_entries, artifact_entries, explicit_configs = [], [], []

    def observe(path):
        digest = sha256(path)
        previous = original_hashes.setdefault(path, digest)
        if digest != previous:
            raise ValueError('An original input or source resource changed during snapshot: '+str(path))
        return digest

    def plan(source, destination, expected):
        if not source.is_file() or observe(source) != expected:
            raise ValueError('Missing or changed artifact; exact recorded SHA256 required: '+str(source))
        old = destinations.get(destination)
        if old is not None and old[1] != expected:
            raise ValueError('Conflicting snapshot resource destination: '+destination.as_posix())
        destinations.setdefault(destination, (source, expected))

    # Protect the code performing this operation even when a different skill
    # root was supplied. Historical code is never loaded into this process.
    for path in [Path(__file__), Path(__file__).with_name('evidence_model.py'), Path(__file__).with_name('common.py')]:
        observe(path.resolve())

    # Observe the live source as well as recovered source bytes; neither may be
    # changed by this operation. Copy only the bounded renderer dependency tree.
    for root in {skill_root, source_root}:
        for path in _runtime_files(root):
            observe(path.resolve())
    for path in _runtime_files(source_root):
        relative = path.relative_to(source_root)
        destination = Path('skill')/relative
        digest = observe(path.resolve())
        plan(path.resolve(), destination, digest)
        resource_entries.append({'source_path': str(path.resolve()), 'snapshot_path': destination.as_posix(), 'sha256': digest})

    originals = list(_references(report))
    copies = list(_references(archived))
    canonical_paths, tool_paths = {}, {}
    for pointer, kind, artifact in originals:
        path_text, expected = artifact.get('path'), artifact.get('sha256')
        if not isinstance(path_text, str) or not path_text or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Every archived artifact requires a path and exact lowercase SHA256: '+pointer)
        original = (ledger.parent/path_text).resolve()
        canonical_paths.setdefault(original, Path('artifacts')/(expected+original.suffix.lower()))
        relative = _relative(original, skill_root) if kind == 'provenance' and artifact.get('role') == 'tool' else None
        if relative is not None:
            tool_paths[original] = relative
            canonical_paths[original] = Path('skill')/relative
    rewritten_paths = {}
    for (pointer, kind, artifact), (_, _, copied) in zip(originals, copies):
        path_text, expected = artifact.get('path'), artifact.get('sha256')
        original = (ledger.parent/path_text).resolve()
        source = original
        role = artifact.get('role') if kind == 'provenance' else kind
        relative = tool_paths.get(original)
        if relative is not None:
            candidate = source_root/relative
            # A present but mismatched historical candidate is an error. Only a
            # missing candidate permits fallback to the exact original tool.
            if candidate.exists():
                source = candidate.resolve()
                if _relative(source, source_root) is None:
                    raise ValueError('Historical tool escapes its source root: '+str(candidate))
        # One file can legitimately be both located code evidence and a tool.
        # Resolve that identity before rewriting either reference, including
        # aliases and exact historical tool recovery. Every reference's own
        # expected hash is still checked below; other evidence is never remapped.
        destination = canonical_paths[original]
        original_observed = observe(original) if original.is_file() else None
        plan(source, destination, expected)
        copied['path'] = destination.as_posix()
        old_rewrite = rewritten_paths.setdefault(path_text, copied['path'])
        if old_rewrite != copied['path']:
            raise ValueError('Ambiguous schema path has multiple archive destinations: '+path_text)
        artifact_entries.append({'pointer': pointer, 'role': role, 'original_path': path_text,
                                 'original_resolved_path': str(original), 'original_observed_sha256': original_observed,
                                 'source_path': str(source), 'snapshot_path': copied['path'], 'sha256': expected})

    for usage, supplied in [('presentation', presentation_path), ('theme', theme_path)]:
        if supplied is None:
            continue
        original = Path(supplied).resolve()
        if not original.is_file():
            raise ValueError('Missing explicit '+usage+' configuration: '+str(original))
        digest = observe(original)
        read_json(original)
        destination = Path('configuration')/(usage+'.json')
        plan(original, destination, digest)
        explicit_configs.append({'usage': usage, 'original_path': str(original),
                                 'snapshot_path': destination.as_posix(), 'sha256': digest,
                                 'historical_authentication': 'not_established_by_snapshot'})

    for section in ['phenomena', 'findings']:
        for item in archived.get(section, []):
            validation = item.get('validation', {})
            if 'result_path' in validation and validation['result_path'] in rewritten_paths:
                validation['result_path'] = rewritten_paths[validation['result_path']]

    invocation = copy.deepcopy(_invocation) if _invocation is not None else {
        'invocation': 'python_api', 'argv': list(getattr(sys, 'orig_argv', [sys.executable]+sys.argv)),
        'call': {'function': 'snapshot_report.snapshot', 'ledger_path': str(ledger), 'output_dir': str(output),
                 'skill_root': str(skill_root), 'source_root': str(source_root),
                 'presentation_path': str(Path(presentation_path).resolve()) if presentation_path is not None else None,
                 'theme_path': str(Path(theme_path).resolve()) if theme_path is not None else None}}
    invocation.update({'cwd': str(Path.cwd().resolve()),
                       'scope': ['exact byte hashes for directly declared evidence, figures, numeric and provenance artifacts',
                                 'bounded copy of renderer tools/*.py and assets/report resources',
                                 'explicit presentation/theme bytes preserved; historical configuration identity requires separate comparison',
                                 'current validator checks on the rewritten ledger without executing recovered source code',
                                 'historical assessments and commands retained as recorded; semantic truth is not certified'],
                       'visual_review': 'not_checked'})
    renderer, archived_ledger = output/'skill'/'tools'/'write_report.py', output/'ledger.json'
    commands = {fmt: [sys.executable, '-B', '-X', 'utf8', str(renderer), '--ledger', str(archived_ledger),
                      '--output', str(output/('report.'+suffix)), '--format', fmt]
                for fmt, suffix in [('html', 'html'), ('markdown', 'md'), ('json', 'json')]}
    for command in commands.values():
        for config in explicit_configs:
            command.extend(['--'+config['usage'], str(output/config['snapshot_path'])])
    manifest = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                'source_ledger': {'path': str(ledger), 'sha256': ledger_digest},
                'skill_root': str(skill_root), 'source_root': str(source_root),
                'snapshot_operation': invocation, 'artifacts': artifact_entries,
                'explicit_configuration': explicit_configs,
                'runtime_resources': resource_entries, 'reexport_commands': commands,
                'verification': {'original_inputs_unchanged': True, 'recorded_hashes_preserved': True,
                                 'ledger_validation': 'passed', 'visual_review': 'not_checked',
                                 'semantic_truth_verified_by_software': False}}
    # Stage and validate away from original inputs. The final directory appears
    # only after all hash checks and schema/numerical validation have passed.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='s_', dir=output.parent) as temporary:
        staging = Path(temporary)
        for destination, (source, digest) in destinations.items():
            target = staging/destination
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as reader, target.open('xb') as writer:
                for block in iter(lambda: reader.read(1024*1024), b''):
                    writer.write(block)
            if sha256(target) != digest:
                raise ValueError('Artifact changed while archiving: '+str(source))
        validate_evidence(archived, staging)
        copied_digest = hashlib.sha256((json.dumps(archived, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')).hexdigest()
        manifest['archived_ledger'] = {'path': 'ledger.json', 'sha256': copied_digest}
        for name, payload in [('ledger.json', archived), ('snapshot_manifest.json', manifest)]:
            (staging/name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
        _verify_unchanged(original_hashes)
        # Exclusive mkdir prevents replacing an output that appears during the
        # staging operation, including an empty directory on POSIX systems.
        output.mkdir()
        for child in staging.iterdir():
            os.replace(child, output/child.name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--skill-root', default=str(DEFAULT_SKILL))
    parser.add_argument('--source-root', help='Previously verified historical skill source root; exact tool hashes remain mandatory')
    parser.add_argument('--presentation', help='Explicit presentation JSON to archive; historical identity is not inferred')
    parser.add_argument('--theme', help='Explicit theme JSON to archive; historical identity is not inferred')
    args = parser.parse_args()
    manifest = snapshot(args.ledger, args.output_dir, args.skill_root, args.source_root, args.presentation, args.theme,
                        _invocation={'invocation': 'cli', 'argv': list(getattr(sys, 'orig_argv', [sys.executable]+sys.argv))})
    print(json.dumps({'snapshot_manifest': str(Path(args.output_dir).resolve()/'snapshot_manifest.json'),
                      'reexport_commands': manifest['reexport_commands']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
