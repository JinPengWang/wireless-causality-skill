"""Describe windowed outcomes and compare matched independent runs."""
import argparse
from collections import defaultdict
import numpy as np
from common import number,read_json,write_json


def weighted_quantile(values,weights,q):
    order=np.argsort(values);v=np.asarray(values)[order];w=np.asarray(weights)[order]
    return float(v[min(len(v)-1,np.searchsorted(np.cumsum(w),q*sum(w),side='left'))])


def summarize(windows,min_coverage=0.8):
    if not 0<min_coverage<=1: raise ValueError('min_coverage must be in (0,1]')
    groups=defaultdict(list)
    for w in windows:
        if not 0<=w['coverage']<=1+1e-8 or w['end_s']<=w['start_s']: raise ValueError('Invalid window')
        groups[(w['run_id'],w['entity'],w['direction'],w['condition'],w['pair_id'],w['metric'],w['unit'])].append(w)
    result=[]
    for key,rows in groups.items():
        rows=sorted(rows,key=lambda r:r['start_s'])
        if any(b['start_s']<a['end_s']-1e-9 for a,b in zip(rows,rows[1:])):raise ValueError('Overlapping outcome windows')
        valid=[r for r in rows if number(r['value']) is not None and r['coverage']>=min_coverage]
        exposure=sum(r['end_s']-r['start_s'] for r in rows)
        item=dict(zip(['run_id','entity','direction','condition','pair_id','metric','unit'],key))
        item.update(valid_windows=len(valid),valid_seconds=sum((r['end_s']-r['start_s'])*r['coverage'] for r in valid),
                    analyzed_span_s=exposure)
        if valid:
            v=[r['value'] for r in valid];wt=[(r['end_s']-r['start_s'])*r['coverage'] for r in valid]
            kinds={r.get('kind','external_interval_mean') for r in valid}
            if len(kinds)!=1: raise ValueError('Inconsistent metric aggregation semantics')
            kind=next(iter(kinds))
            mean=float(np.average(v,weights=wt))
            item['mean_aggregation']='valid_duration_weighted'
            if kind in {'ratio','event_mean','event_fraction'}:
                if any('aggregation_numerator' not in r or 'aggregation_denominator' not in r or 'scale' not in r for r in valid):
                    raise ValueError('Count/observation metrics require retained numerators, denominators and scale')
                scales={r['scale'] for r in valid}
                if len(scales)!=1: raise ValueError('Inconsistent metric scale')
                denominator=sum(r['aggregation_denominator'] for r in valid)
                mean=sum(r['aggregation_numerator'] for r in valid)/denominator*next(iter(scales)) if denominator else None
                item['mean_aggregation']='pooled_counts_or_observations'
            item.update(mean=mean,p10=weighted_quantile(v,wt,.1),
                        median=weighted_quantile(v,wt,.5),p90=weighted_quantile(v,wt,.9))
            item['spread_p90_p10']=item['p90']-item['p10']
        else:item.update(mean=None,p10=None,median=None,p90=None,spread_p90_p10=None)
        result.append(item)
    return result


def paired_compare(summaries,reference,seed=0,bootstrap=1000,min_pairs=8):
    if min_pairs<2 or bootstrap<100: raise ValueError('Invalid inference budget')
    strata=defaultdict(dict);entities=set(); duplicates=[]
    for s in summaries:
        entities.add(s['entity'])
        if s['mean'] is None:continue
        if s['pair_id'] in {'unknown','unpaired'} or s['condition']=='unknown' or s['direction']=='unknown':continue
        key=(s['direction'],s['condition'],s['pair_id'],s['metric'],s['unit'])
        if s['entity'] in strata[key]: duplicates.append(key)
        strata[key][s['entity']]=s
    if duplicates:raise ValueError('Multiple runs per entity/pair/condition: define independent units before comparison')
    if reference not in entities:raise ValueError('Reference entity absent')
    output=[];rng=np.random.default_rng(seed)
    contrasts=defaultdict(list)
    families={(k[0],k[3],k[4]) for k in strata}
    for direction,metric,unit in sorted(families):
        for target in sorted(entities-{reference}):
            keys=[k for k in strata if (k[0],k[3],k[4])==(direction,metric,unit)]
            refkeys=[k for k in keys if reference in strata[k]]
            targetkeys=[k for k in keys if target in strata[k]]
            common=[k for k in refkeys if target in strata[k]]
            pair_differences=defaultdict(list)
            for k in common:pair_differences[k[2]].append(strata[k][target]['mean']-strata[k][reference]['mean'])
            diffs=np.array([np.mean(v) for v in pair_differences.values()])
            r={'reference':reference,'target':target,'direction':direction,'metric':metric,'unit':unit,
               'n_pairs':len(diffs),'common_conditions':len(common),
               'reference_support_fraction':len(common)/len(refkeys) if refkeys else 0,
               'target_support_fraction':len(common)/len(targetkeys) if targetkeys else 0,
               'unmatched_reference':[list(k) for k in refkeys if k not in common],
               'unmatched_target':[list(k) for k in targetkeys if k not in common],
               'mean_target_minus_reference':float(diffs.mean()) if len(diffs) else None,
               'ci95':None,'status':'descriptive_paired' if len(diffs) else 'blocked_no_common_support'}
            if len(diffs)>=min_pairs:
                draws=np.mean(rng.choice(diffs,(bootstrap,len(diffs)),replace=True),axis=1)
                r['ci95']=[float(x) for x in np.quantile(draws,[.025,.975])]
            r['assumptions']='Equal weight per declared independent pair; conditions averaged within pair. CI conditional on independence, marginal not simultaneous. Not a causal vendor effect.'
            output.append(r)
    if not output:return [{'status':'blocked_no_eligible_pairs','reason':'Provide verified pair identities, conditions, directions and at least two entities'}]
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--windows',required=True);p.add_argument('--output',required=True)
    p.add_argument('--reference');p.add_argument('--min-coverage',type=float,default=.8);p.add_argument('--seed',type=int,default=0)
    a=p.parse_args();q=read_json(a.windows);s=summarize(q['windows'],a.min_coverage)
    from pathlib import Path
    if Path(a.output).resolve()==Path(a.windows).resolve():p.error('Output cannot overwrite input')
    write_json(a.output,{'summaries':s,'comparisons':paired_compare(s,a.reference,a.seed) if a.reference else [],
                         'min_coverage':a.min_coverage,'seed':a.seed})

if __name__=='__main__':main()
