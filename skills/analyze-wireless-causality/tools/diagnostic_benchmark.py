"""Prepare reproducible synthetic cases; behavior must be reviewed separately."""
import argparse
import csv
from pathlib import Path
import sys
from common import read_json, sha256, write_json
from causal_analysis import analyze
from compare_runs import summarize
from detect_events import detect
from quality_profile import profile
from wifi_frames import observed_ba_status

SKILL = Path(__file__).resolve().parents[1]


def windows(identity, intervals, unit='Mbit/s'):
    return [{'run_id':identity,'entity':identity,'direction':'downlink','condition':'synthetic',
             'pair_id':'unknown','metric':'delivery','unit':unit,'start_s':a,'end_s':b,'value':v,
             'coverage':1.,'definition':'Declared complete synthetic interval mean','kind':'interval_mean'}
            for a,b,v in intervals]


def prepare(output):
    target=Path(output)
    if target.exists() or target.is_symlink(): raise ValueError('Use a fresh benchmark directory')
    target=target.resolve()
    if target == SKILL or SKILL in target.parents or target in SKILL.parents:
        raise ValueError('Use a run directory outside the installed skill')
    sources=[SKILL/'benchmarks'/'cases.json',SKILL/'benchmarks'/'rubric.json',SKILL/'SKILL.md']
    # Record the full declared reference/tool surface, including imported helpers.
    # Historical logs/results and test fixtures are deliberately outside this scope.
    sources += sorted((SKILL/'references').rglob('*.md'))
    sources += sorted(p for p in (SKILL/'tools').glob('*.py') if not p.name.startswith('test_'))
    before={str(p):sha256(p) for p in sources}
    cases=read_json(sources[0]); rubric=read_json(sources[1]); byid={c['id']:c['input'] for c in cases['cases']}
    target.mkdir(parents=True)
    write_json(target/'agent_input.json',cases)
    raw=target/'quality_input.csv'; b=byid['B03']
    with raw.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream); writer.writerow(b['headers']); writer.writerows(b['rows'])
    quality_request={'schema_version':1,'source':{'path':str(raw)},**b['mapping']}
    write_json(target/'quality_request.json',quality_request)
    event=byid['B04']; event_windows=windows('r1',event['intervals'])
    write_json(target/'event_windows.json',{'schema_version':1,'windows':event_windows})
    random=byid['B06']; records=[]
    for pair in random['pairs']:
        for treatment,key in [(0,'control'),(1,'treatment')]:
            records.append({'recording_id':pair['id']+'_'+key,'unit_id':pair['id'],'time_s':0,
                            'values':{'assignment':treatment,'delivery':pair[key]}})
    request={'schema_version':1,'question':'Scoped synthetic paired effect','scope':random['design']['population'],
             'independent_unit_definition':'One independently randomized synthetic pair','observation_weighting':'equal_rows_within_recording',
             'variables':{name:{'meaning':meaning,'unit':unit,'time_scale':'one observation per condition','role':'measurement','derived_from':[]}
                          for name,meaning,unit in [('assignment','Randomized condition indicator','1'),('delivery','Receiver goodput','Mbit/s')]},
             'analyses':[{'id':'paired','method':'paired_contrast','outcome':'delivery','exposure':'assignment','controls':[],
                          'control_rationale':{},'assumptions':['The supplied synthetic randomization and observation design holds'],
                          'design':random['design']}],
             'multiplicity':{'method':'none','rationale':'One prespecified exact randomization test','families':{'primary':['paired']}}}
    data={'schema_version':1,'records':records}
    write_json(target/'paired_data.json',data)
    request['data']={'path':'paired_data.json','sha256':sha256(target/'paired_data.json')}
    write_json(target/'paired_request.json',request)
    ba=byid['B01']
    reference={'B01':{'bitmap_states_only':observed_ba_status(ba['start_seq'],ba['wire_hex'],64,ba['observed_sequences'])},
               'B02':{'numeric_result':'not_computed; semantic judgment required'},
               'B03':profile(quality_request),
               'B04':detect(event_windows,event['threshold'],event['bad_direction'],event['min_duration_s'],1.,event['recovery_hold_s']),
               'B05':summarize([w for name,run in byid['B05']['runs'].items()
                                for w in windows(name,[(i,i+1,v) for i,v in enumerate(run['goodput'])])]),
               'B06':analyze(request,data)}
    write_json(target/'reference.json',reference)
    review={'benchmark_version':cases['version'],'reviewer':None,'model_and_settings':None,'response_path':None,'response_sha256':None,
            'critical_failure_status_semantics':'passed = no stated critical failure; failed = observed critical failure; not_checked = not reviewed',
            'cases':[{'id':r['id'],'criteria':[{'criterion':c,'status':'not_checked','response_locator':None} for c in r['must']],
                      'critical_failure':{'definition':r['critical_failure'],'status':'not_checked','response_locator':None}}
                     for r in rubric['cases']],
            'scope':'Unfilled human/independent review; deterministic results are not behavioral passes'}
    write_json(target/'review_template.json',review)
    if any(sha256(p)!=h for p,h in before.items()): raise ValueError('Benchmark source changed during preparation')
    write_json(target/'manifest.json',{'version':1,'sources':before,'python':sys.version,
                                     'artifacts':{p.name:sha256(p) for p in target.iterdir() if p.is_file()},
                                     'behavioral_review':'not_checked','scope':'Synthetic reference calculations and fixed cases only'})
    return reference


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output-dir',required=True)
    prepare(parser.parse_args().output_dir)
