"""Validate a language-independent evidence ledger, then export JSON or localized Markdown."""
import argparse
import json
import os
from pathlib import Path
from common import atomic_text, ensure_output_safe, read_json
from evidence_model import validate_evidence, verify_locator, verify_figure, protected_artifacts, numerical_checks

EN = {
 'title':'Wireless performance investigation', 'analysis_status':'Execution status', 'scope':'Scope',
 'measurement_contract':'Measurement contract', 'phenomena':'Observed phenomena', 'findings':'Mechanisms and unresolved candidates',
 'calculation':'Calculation and selection', 'status':'Evidence status', 'priority_reason':'Priority rationale',
 'mechanism':'Mechanism', 'prediction':'Expected observation', 'strongest_alternative':'Strongest alternative explanation',
 'support':'Support', 'counterevidence':'Counterevidence', 'limitations':'Limitations', 'next_test':'Next discriminating check',
 'explains':'Explains phenomena', 'validation':'Validation', 'evidence':'Evidence records', 'reproduce':'Reproduction',
 'assessment':'Completion and answer assessment', 'numerical_claims':'Numerical claim checks', 'claim_type':'Type of claim',
 'priority_note':'Priority expresses investigation importance, not probability of causation.',
 'verification_note':'Integrity, location and arithmetic checks do not certify meaning, population selection or causal truth.',
 'claim_review':'Manual review of claim mapping', 'provenance':'Version, configuration and execution provenance',
 'execution':'Execution', 'data_capability':'Data capability', 'question_answer':'Question answered', 'delivery_quality':'Delivery quality',
 'delivery_checks':'Delivery checks', 'design':'Design', 'independent_replication':'Independent replication',
 'reviewer_assessment':'Reviewer assessment', 'result_path':'Result artifact', 'identification_scope':'Identification scope',
 'computed':'Recomputed', 'asserted':'Asserted', 'unit':'Unit', 'tolerance':'Tolerance', 'supports':'Supports', 'ledger':'Evidence ledger'
}
ZH = dict(zip(EN, [
 '无线性能调查','执行状态','范围','测量定义','观察到的现象','机制与未解决候选',
 '计算与选择规则','证据状态','优先级理由','机制','预期观察','最强替代解释',
 '支持证据','反证','限制','下一项区分检查','解释的现象','验证','证据记录','复现',
 '完成度与回答程度','数值主张核验','主张类型',
 '优先级表示调查重要程度，不代表因果概率。',
 '完整性、位置与算术核验不证明语义、样本选择或因果真实性。',
 '主张映射人工审查','版本、配置与执行来源','执行完成度','数据能力','问题回答程度','交付质量',
 '交付检查','设计','独立重复','审查者评估','结果文件','识别范围',
 '重算值','声明值','单位','容差','支持内容','证据账本'
]))


def labels(report, presentation=None):
    language = report.get('language', 'en')
    if presentation is not None:
        if presentation.get('language') != language or not set(EN) <= presentation.get('labels', {}).keys():
            raise ValueError('Presentation must match ledger language and provide every label; see EN in write_report.py')
        result = presentation['labels']
    elif language in {'en', 'en-US', 'English'}:
        result = EN
    elif language in {'zh', 'zh-CN', 'Chinese', '中文'}:
        result = ZH
    else:
        raise ValueError('Supply a presentation label mapping for this language, or export the JSON model')
    if any(not isinstance(v, str) or not v.strip() for v in result.values()):
        raise ValueError('Presentation labels must be nonempty strings')
    return result


def render(report, base, output, ledger_path=None, presentation=None, output_format='markdown'):
    base, output = Path(base), Path(output)
    if output_format not in {'markdown', 'json'}:
        raise ValueError('Use a separate exporter for other requested formats; do not relabel Markdown as another format')
    ensure_output_safe(output, protected_artifacts(report, base, ledger_path), '.json' if output_format == 'json' else '.md')
    report = validate_evidence(report, base)
    checks = numerical_checks(report, base)
    model = {'schema_version': 1, 'ledger_base': str(base.resolve()), 'ledger': report,
             'numerical_checks': checks, 'semantic_truth_verified_by_software': False}
    if output_format == 'json':
        atomic_text(output, json.dumps(model, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        return model
    label = labels(report, presentation)
    def link(path):
        relative = os.path.relpath(Path(path).resolve(), output.parent.resolve()).replace('\\', '/')
        if any(c in relative for c in [' ', '\n', '\r', '<', '>']):
            raise ValueError('Use Markdown-safe artifact paths')
        return relative
    lines = ['# ' + report.get('title', label['title']), '', report['question'], '',
             '**' + label['analysis_status'] + ':** ' + report['analysis_status'], '', label['verification_note'], '',
             '## ' + label['scope'], '', report['scope'], '', '## ' + label['measurement_contract'], '', report['measurement_contract'], '']
    if report.get('assessment'):
        lines += ['## '+label['assessment'], '']
        for key, assessment in report['assessment'].items():
            lines += ['**'+label[key]+': '+assessment['status']+'** — '+assessment['reason'], '']
        for check in report['assessment']['delivery_quality']['checks']:
            lines += ['- '+check['id']+': '+check['status']+' — '+check['reason']]
        lines += ['']
    numeric = {c['id']: c for c in checks.get('claims', [])}
    def item_text(item):
        rendered = [f"### {item['id']}: {item['statement']}", '', label['status']+f": **{item['status']}**", '',
                    '**'+label['calculation']+':** '+item['calculation'], '']
        if item.get('claim_type'):
            rendered += ['**'+label['claim_type']+':** '+item['claim_type'], '']
        for figure in item['figures']:
            rendered += [f"![{item['id']}]({link(base/figure['path'])})", '', figure['caption'], '']
        for key in ['priority_reason', 'mechanism', 'prediction', 'strongest_alternative', 'support', 'counterevidence', 'limitations', 'next_test']:
            if key in item:
                rendered += ['**'+label[key]+':** '+item[key], '']
        if item.get('explains'):
            rendered += ['**'+label['explains']+':** '+', '.join(item['explains']), '']
        if item.get('validation'):
            for key in ['design', 'independent_replication', 'reviewer_assessment', 'result_path', 'identification_scope']:
                if key in item['validation']:
                    rendered += ['**'+label['validation']+' — '+label[key]+':** '+item['validation'][key], '']
        for identity in item.get('claim_ids', []):
            check = numeric[identity]
            rendered += ['**'+label['numerical_claims']+' '+identity+':** '+check['status'], '']
            if 'recomputed_value' in check:
                rendered += [f"{label['computed']}: {check['recomputed_value']:.12g}; {label['asserted']}: {check['asserted_value']:.12g}; "
                             +f"{label['unit']}: {check['unit']}; `{check['expression']}`; {label['tolerance']}: {check['allowed_error']:.12g}.", '']
            for name, operand in check.get('operands', {}).items():
                rendered += [f"- `{name}`: `{operand['artifact']}`; `{json.dumps(operand['locator'], ensure_ascii=False)}`; "
                             +f"{label['unit']}: {operand['unit']}; {operand['unit_check']}."]
            if check.get('reason'):
                rendered += [check['reason']]
            rendered += ['']
        if ledger_path:
            rendered += [f"{label['evidence']}: {item['id']} — [{label['ledger']}]({link(ledger_path)}).", '']
        for evidence in item['evidence']:
            status = verify_locator((base/evidence['path']).resolve(), evidence['locator'])
            rendered += [f"{label['evidence']}: [{evidence['path']}]({link(base/evidence['path'])}); "
                         +f"`{json.dumps(evidence['locator'], ensure_ascii=False)}`; {status}; SHA256 `{evidence['sha256']}`.", '']
            if evidence.get('supports'):
                rendered += [label['supports']+': '+evidence['supports'], '']
        return rendered
    lines += ['## '+label['phenomena'], '']
    for item in report['phenomena']:
        lines += item_text(item)
    lines += ['## '+label['findings'], '', label['priority_note'], '']
    for item in sorted(report['findings'], key=lambda x: (x['priority'], x['id'])):
        lines += item_text(item)
    lines += ['## '+label['limitations'], '', report['limitations'], '', '## '+label['reproduce'], '', report['reproduce'], '']
    for key in ['claim_review', 'provenance']:
        if key in report:
            lines += ['## '+label[key], '', '```json', json.dumps(report[key], ensure_ascii=False, indent=2), '```', '']
    atomic_text(output, '\n'.join(lines))
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--format', choices=['markdown', 'json'], default='markdown')
    parser.add_argument('--presentation', help='Optional language and complete presentation labels JSON')
    args = parser.parse_args()
    source = Path(args.ledger).resolve()
    if args.presentation:
        ensure_output_safe(args.output, [args.presentation])
    render(read_json(source), source.parent, args.output, source,
           read_json(args.presentation) if args.presentation else None, args.format)


if __name__ == '__main__':
    main()
