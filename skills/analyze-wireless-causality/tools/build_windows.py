"""Build comparable windows from explicit table mappings, never from column guesses."""
import argparse
import math
from collections import defaultdict
from pathlib import Path
from common import number, read_json, require_keys, sha256, table_rows, write_json

META = {'run_id','entity','direction','condition','pair_id'}
KINDS = {'interval_mean','interval_amount','ratio','event_mean','event_sum','event_count','event_fraction'}


def build(request):
    require_keys(request, {'schema_version','window_s','sources'},
                 {'schema_version','window_s','sources'}, 'window request')
    if request['schema_version'] != 1:
        raise ValueError('Unsupported window request version')
    width = number(request['window_s'])
    if width is None or width <= 0:
        raise ValueError('window_s must be positive')
    out, provenance = [], []
    unique_sources = set()
    run_metadata = {}
    for src in request['sources']:
        require_keys(src, {'path','metadata','time','metrics'},
                     {'path','sheet','header_row','where','metadata','time','metrics','capture_complete'}, 'source')
        meta = src['metadata']
        require_keys(meta, META, META, 'metadata')
        if any(not isinstance(meta[k],str) or not meta[k].strip() for k in META):
            raise ValueError('Metadata must contain explicit nonempty strings; use unknown for unavailable matching fields')
        if meta['run_id'] in run_metadata and run_metadata[meta['run_id']] != meta:
            raise ValueError('Conflicting metadata for the same run_id')
        run_metadata[meta['run_id']] = meta
        time = src['time']
        require_keys(time, {'start','scale','origin','split_policy'},
                     {'start','end','scale','origin','split_policy','observation_interval'}, 'time')
        scale, origin = number(time['scale']), number(time['origin'])
        if scale is None or scale <= 0 or origin is None:
            raise ValueError('Explicit finite time scale and origin are required')
        if time['split_policy'] not in {'reject','uniform'}:
            raise ValueError('Unknown split_policy')
        event = 'end' not in time
        exposure = time.get('observation_interval')
        if event and (not exposure or len(exposure)!=2 or not all(number(x) is not None for x in exposure) or exposure[1]<=exposure[0]):
            raise ValueError('Event data require a declared observation_interval in normalized seconds')
        if event and src.get('capture_complete') not in {True,False}:
            raise ValueError('Declare capture_complete; false leaves empty event windows missing')
        specs = src['metrics']
        if not specs or len({s['name'] for s in specs}) != len(specs):
            raise ValueError('Metrics must be nonempty with distinct names')
        for spec in specs:
            require_keys(spec, {'name','unit','kind','scale'},
                         {'name','unit','kind','scale','column','numerator','denominator','definition','value_map'},'metric')
            if spec['kind'] not in KINDS or spec['kind'].startswith('event') != event:
                raise ValueError('Metric kind does not match event/interval time model')
            if number(spec['scale']) is None:
                raise ValueError('Finite metric scale required')
            key=(meta['run_id'],spec['name'])
            if key in unique_sources:
                raise ValueError('A run/metric may have only one source; reconcile duplicate sources explicitly')
            unique_sources.add(key)
            if not spec.get('definition'):
                raise ValueError('Provide a measurement definition, including layer/direction and denominator where relevant')
        before=sha256(src['path'])
        bins=defaultdict(lambda:defaultdict(lambda:{'num':0.,'den':0.,'coverage':0.,'rows':[]}))
        previous_end=None; lower=None; upper=None; filtered=0; missing=defaultdict(int)
        for rowno,row in table_rows(src['path'],src.get('sheet'),src.get('header_row',1)):
            if any(row.get(k) not in vals for k,vals in src.get('where',{}).items()):
                continue
            filtered+=1
            for spec in specs:
                fields = [spec['numerator'],spec['denominator']] if spec['kind']=='ratio' else ([] if spec['kind']=='event_count' else [spec['column']])
                if any(f not in row for f in fields): raise ValueError('Mapped metric column is absent')
            start=number(row.get(time['start']))
            end=number(row.get(time['end'])) if not event else start
            if start is None or end is None:
                raise ValueError(f'Missing/invalid time at source row {rowno}')
            start=start*scale-origin; end=end*scale-origin
            if not event:
                if end<=start or (previous_end is not None and start<previous_end-1e-9):
                    raise ValueError(f'Nonpositive, overlapping or unsorted intervals at row {rowno}')
                previous_end=end
            elif not exposure[0] <= start < exposure[1]:
                raise ValueError(f'Event outside declared observation_interval at row {rowno}')
            lower=start if lower is None else min(lower,start)
            upper=end if upper is None else max(upper,end)
            first=math.floor(start/width)
            last=first if event else math.ceil(end/width-1e-10)-1
            if last-first>100000:
                raise ValueError('Excessive window expansion: check time units')
            if not event and last>first and time['split_policy']=='reject':
                raise ValueError('A source interval crosses windows; coarsen or explicitly allow uniform allocation')
            for spec in specs:
                kind=spec['kind']; raw_value=row.get(spec.get('column',''))
                if 'value_map' in spec: raw_value=spec['value_map'].get(str(raw_value))
                value=number(raw_value)
                num=number(row.get(spec.get('numerator','')))
                den=number(row.get(spec.get('denominator','')))
                if kind=='event_count': value=1.
                if kind=='ratio':
                    if num is None or den is None: missing[spec['name']]+=1; continue
                    if num<0 or den<0 or num>den: raise ValueError('Ratio requires 0 <= numerator <= denominator')
                elif value is None:
                    missing[spec['name']]+=1; continue
                if kind=='event_fraction' and value not in {0.,1.}:
                    raise ValueError('event_fraction needs explicitly normalized 0/1 values')
                for idx in range(first,last+1):
                    overlap=0. if event else min(end,(idx+1)*width)-max(start,idx*width)
                    b=bins[idx][spec['name']]; b['rows'].append(rowno)
                    if not event: b['coverage']+=overlap
                    if kind=='ratio':
                        b['num']+=num*overlap/(end-start); b['den']+=den*overlap/(end-start)
                    elif kind=='interval_mean': b['num']+=value*overlap; b['den']+=overlap
                    elif kind=='interval_amount': b['num']+=value*overlap/(end-start); b['den']+=overlap
                    elif kind in {'event_mean','event_fraction'}: b['num']+=value; b['den']+=1
                    else: b['num']+=value; b['den']+=1
        if filtered==0: raise ValueError('Source selection is empty')
        lo,hi=exposure if event else (lower,upper)
        begin=math.floor(lo/width); finish=math.ceil(hi/width-1e-10)
        if finish-begin>100000: raise ValueError('Excessive window count')
        for idx in range(begin,finish):
            for spec in specs:
                b=bins[idx][spec['name']]; kind=spec['kind']
                exposure_s=max(0.,min(hi,(idx+1)*width)-max(lo,idx*width))
                cov=exposure_s/width if event else b['coverage']/width
                if event and not b['rows'] and not src['capture_complete']: cov=0.
                if kind in {'event_sum','event_count'}:
                    value=b['num']/exposure_s if cov>0 else None
                else: value=b['num']/b['den'] if b['den']>0 else None
                if value is not None: value*=spec['scale']
                out.append({**meta,'metric':spec['name'],'unit':spec['unit'],
                            'start_s':idx*width,'end_s':(idx+1)*width,'value':value,'coverage':cov,
                            'source_rows':b['rows'],'source_path':str(Path(src['path']).resolve()),
                            'source_sheet':src.get('sheet'),'kind':kind,
                            'aggregation_numerator':b['num'],
                            'aggregation_denominator':exposure_s if kind in {'event_sum','event_count'} else b['den'],
                            'valid_observations':len(b['rows']),'scale':spec['scale'],'definition':spec['definition']})
        if sha256(src['path'])!=before: raise RuntimeError('Source changed during processing')
        provenance.append({'path':str(Path(src['path']).resolve()),'sha256':before,'mapping':src,
                           'selected_rows':filtered,'invalid_metric_rows':dict(missing)})
    return {'schema_version':1,'window_s':width,'sources':provenance,'windows':out,
            'limitations':['Uniform interval splitting, when enabled, assumes uniform values/counts within source intervals.',
                           'Event coverage describes declared capture exposure, not proof that every transmitted frame was observed.']}


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--request',required=True);p.add_argument('--output',required=True)
    a=p.parse_args(); req=read_json(a.request)
    output=Path(a.output).resolve()
    if output==Path(a.request).resolve() or any(output==Path(s['path']).resolve() for s in req['sources']):
        p.error('Output must not overwrite inputs')
    write_json(output,build(req))

if __name__=='__main__': main()
