"""Detect threshold excursions in one explicitly selected outcome series."""
import argparse
from common import number,read_json,write_json


def detect(rows,threshold,bad_direction,min_duration_s,min_coverage,recovery_hold_s):
    if number(threshold) is None or bad_direction not in {'below','above'}:
        raise ValueError('Explicit threshold and bad_direction are required')
    if min_duration_s<=0 or recovery_hold_s<=0 or not 0<min_coverage<=1:
        raise ValueError('Invalid event policy')
    rows=sorted(rows,key=lambda r:r['start_s'])
    if not rows:raise ValueError('Empty event selection')
    if len({(r['run_id'],r['metric'],r['direction']) for r in rows})!=1:
        raise ValueError('Select one run, metric and direction')
    if any(b['start_s']<a['end_s']-1e-9 for a,b in zip(rows,rows[1:])):raise ValueError('Overlapping windows')
    def valid(r):return number(r['value']) is not None and r['coverage']>=min_coverage
    def bad(r):return valid(r) and (r['value']<threshold if bad_direction=='below' else r['value']>threshold)
    events=[];i=0
    while i<len(rows):
        if not bad(rows[i]):i+=1;continue
        first=i;j=i+1
        while j<len(rows) and bad(rows[j]) and abs(rows[j]['start_s']-rows[j-1]['end_s'])<1e-8:j+=1
        duration=rows[j-1]['end_s']-rows[first]['start_s']
        if duration>=min_duration_s:
            previous_ok=first>0 and valid(rows[first-1]) and not bad(rows[first-1]) and abs(rows[first]['start_s']-rows[first-1]['end_s'])<1e-8
            confirmed=0.;k=j;end=rows[j-1]['end_s'];recovery=None
            while k<len(rows) and valid(rows[k]) and not bad(rows[k]) and abs(rows[k]['start_s']-end)<1e-8:
                confirmed+=rows[k]['end_s']-rows[k]['start_s'];end=rows[k]['end_s']
                if confirmed>=recovery_hold_s:recovery=rows[j]['start_s'];break
                k+=1
            events.append({'run_id':rows[i]['run_id'],'metric':rows[i]['metric'],'direction':rows[i]['direction'],
                'start_s':rows[first]['start_s'],'end_s':rows[j-1]['end_s'],'duration_s':duration,
                'onset_observed':previous_ok,'recovery_start_s':recovery,'recovery_censored':recovery is None,
                'threshold':threshold,'threshold_direction':bad_direction,
                'integrated_excursion':sum(abs(r['value']-threshold)*(r['end_s']-r['start_s'])*r['coverage'] for r in rows[first:j]),
                'source_rows':sorted({n for r in rows[first:j] for n in r.get('source_rows',[])}),
                'interpretation':'Outcome excursion; not a motion interval, intervention label or diagnosed root cause.'})
        i=j
    return events


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--windows',required=True);p.add_argument('--run-id',required=True);p.add_argument('--metric',required=True)
    p.add_argument('--direction',required=True);p.add_argument('--threshold',type=float,required=True)
    p.add_argument('--bad-direction',choices=['above','below'],required=True);p.add_argument('--min-duration-s',type=float,required=True)
    p.add_argument('--recovery-hold-s',type=float,required=True);p.add_argument('--min-coverage',type=float,default=.8)
    p.add_argument('--output',required=True);a=p.parse_args()
    rows=[r for r in read_json(a.windows)['windows'] if (r['run_id'],r['metric'],r['direction'])==(a.run_id,a.metric,a.direction)]
    from pathlib import Path
    if Path(a.output).resolve()==Path(a.windows).resolve():p.error('Output cannot overwrite input')
    write_json(a.output,{'events':detect(rows,a.threshold,a.bad_direction,a.min_duration_s,a.min_coverage,a.recovery_hold_s)})

if __name__=='__main__':main()
