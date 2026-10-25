"""Validate an evidence ledger and render a concise Markdown diagnosis."""
import argparse
from pathlib import Path
from common import read_json,sha256

STATUSES={'observed','candidate','supported_candidate','validated_mechanism','unresolved','refuted'}


def validate_evidence(report,base):
    needed={'question','scope','measurement_contract','phenomena','findings','limitations','reproduce'}
    if not needed<=report.keys():raise ValueError('Missing report sections: '+str(needed-report.keys()))
    if not report['phenomena']:raise ValueError('State observed phenomena before hypotheses')
    ids=set()
    for item in report['phenomena']+report['findings']:
        required={'id','statement','status','calculation','evidence','figures','limitations'}
        if not required<=item.keys():raise ValueError('Incomplete evidence item')
        if item['id'] in ids:raise ValueError('Duplicate evidence id')
        ids.add(item['id'])
        if item['status'] not in STATUSES:raise ValueError('Unknown evidence status')
        if not item['evidence'] or not item['calculation']:raise ValueError('Every item requires calculations and evidence')
        if not 1<=len(item['figures'])<=2:raise ValueError('Use one or two readable figures per item')
        for e in item['evidence']:
            path=(base/e['path']).resolve()
            if not path.is_file() or sha256(path)!=e['sha256']:raise ValueError('Missing or changed evidence artifact')
            if not e.get('locator'):raise ValueError('Evidence needs a row/key/window locator')
        for f in item['figures']:
            if not (base/f['path']).is_file() or not f.get('caption'):raise ValueError('Missing figure or explanatory caption')
        if item in report['findings']:
            for k in ['priority','priority_reason','mechanism','support','counterevidence','next_test']:
                if k not in item:raise ValueError('Finding missing '+k)
            if not isinstance(item['priority'],int) or item['priority']<1:raise ValueError('Priority must be an explicit positive ordinal')
            if item['status']=='validated_mechanism':
                v=item.get('validation',{})
                if not v.get('design') or not v.get('independent_replication') or not v.get('reviewer_assessment'):
                    raise ValueError('Validated mechanisms require design, independent replication and an explicit reviewer assessment')
                evidence_paths={e['path'] for e in item['evidence']}
                if v.get('result_path') not in evidence_paths:
                    raise ValueError('Validation result must be a hashed evidence artifact')
    return report


def render(report,base,output):
    report=validate_evidence(report,base)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    import os
    lines=['# Wireless performance diagnosis','',report['question'],'','## Scope','',report['scope'],'',
           '## Measurement contract','',report['measurement_contract'],'','## Observed phenomena','']
    def item_text(item):
        s=[f"### {item['id']}: {item['statement']}",'',f"Evidence status: **{item['status']}**",'',
           '**Calculation and selection:** '+item['calculation'],'']
        for f in item['figures']:
            path=os.path.relpath((base/f['path']).resolve(),output.parent.resolve()).replace('\\','/')
            if ' ' in path:raise ValueError('Use Markdown-safe artifact names without spaces')
            s.extend([f"![{item['id']}]({path})",'',f['caption'],''])
        for k in ['priority_reason','mechanism','support','counterevidence','limitations','next_test']:
            if k in item:s.extend([f"**{k.replace('_',' ').capitalize()}:** {item[k]}",''])
        s.append('Evidence: '+ '; '.join(f"{e['path']} [{e['locator']}], SHA256 {e['sha256']}" for e in item['evidence']))
        return s+['']
    for p in report['phenomena']:lines+=item_text(p)
    lines+=['## Prioritized mechanisms and unresolved candidates','',
            'Priority expresses investigation importance, not a probability of causation.','']
    for f in sorted(report['findings'],key=lambda x:(x['priority'],x['id'])):lines+=item_text(f)
    lines+=['## Limitations and missing evidence','',report['limitations'],'','## Reproduction','',report['reproduce'],'']
    output.write_text('\n'.join(lines),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ledger',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();src=Path(a.ledger).resolve();out=Path(a.output).resolve()
    if out==src or out.suffix!='.md':p.error('Write a separate .md report')
    render(read_json(src),src.parent,out)

if __name__=='__main__':main()
