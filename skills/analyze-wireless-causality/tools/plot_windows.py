"""Plot direction-separated, unit-consistent outcome views from normalized windows."""
import argparse
import hashlib
from collections import defaultdict
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from common import number,read_json,write_json


def plot(windows,output_dir,mode='distribution',min_coverage=.8):
    if not 0<min_coverage<=1: raise ValueError('min_coverage must be in (0,1]')
    if not any(number(r['value']) is not None and r['coverage']>=min_coverage for r in windows):
        raise ValueError('No valid windows to plot')
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=True)
    families=defaultdict(list)
    for r in windows:families[(r['direction'],r['condition'],r['metric'],r['unit'])].append(r)
    artifacts=[]
    for key,rows in families.items():
        direction,condition,metric,unit=key
        if not any(number(r['value']) is not None and r['coverage']>=min_coverage for r in rows): continue
        runs=defaultdict(list)
        for r in rows:runs[(r['entity'],r['run_id'])].append(r)
        name=hashlib.sha256(repr((key,mode)).encode()).hexdigest()[:12]
        if mode=='distribution':
            fig,ax=plt.subplots(figsize=(9,5));entities=defaultdict(list)
            for (entity,run),rr in runs.items():
                good=[r for r in rr if number(r['value']) is not None and r['coverage']>=min_coverage]
                if good:entities[entity].append(good)
            for entity,groups in sorted(entities.items()):
                values=[];weights=[]
                for group in groups:
                    w=np.array([(r['end_s']-r['start_s'])*r['coverage'] for r in group])
                    values.extend(r['value'] for r in group);weights.extend(w/w.sum()/len(groups))
                order=np.argsort(values);v=np.asarray(values)[order];w=np.asarray(weights)[order]
                ax.step(v,np.cumsum(w),where='post',label=f'{entity} (runs={len(groups)})')
            ax.set_xlabel(f'{metric} ({unit})');ax.set_ylabel('Time-weighted ECDF, equal weight per run')
            ax.legend();axes=[ax];parts=[(fig,f'{name}.png')]
        else:
            parts=[];items=sorted(runs.items())
            for page in range(0,len(items),6):
                subset=items[page:page+6]
                fig,axes=plt.subplots(len(subset),1,figsize=(10,2.5*len(subset)),squeeze=False)
                for ax,((entity,run),rr) in zip(axes.flat,subset):
                    rr=sorted(rr,key=lambda r:r['start_s'])
                    for r in rr:
                        if number(r['value']) is not None and r['coverage']>=min_coverage:
                            ax.plot([r['start_s'],r['end_s']],[r['value'],r['value']],color='#2864b7',linewidth=1.4)
                    ax.set_title(f'{entity} / {run}',loc='left',fontsize=10)
                    ax.set_ylabel(f'{metric}\n({unit})');ax.set_xlabel('Source-relative time (s); no event alignment implied')
                parts.append((fig,f'{name}_{page//6+1}.png'))
        for fig,filename in parts:
            fig.suptitle(f'{direction} | {condition} | {metric}',fontsize=12)
            for ax in fig.axes:ax.grid(alpha=.2)
            fig.tight_layout(rect=(0,0,1,.95));fig.savefig(root/filename,dpi=160);fig.savefig(root/filename.replace('.png','.svg'));plt.close(fig)
            artifacts.append({'path':str((root/filename).resolve()),'direction':direction,'condition':condition,
                              'metric':metric,'unit':unit,'mode':mode,'min_coverage':min_coverage,
                              'calculation':'Valid-duration weighted ECDF with equal run weights' if mode=='distribution' else 'Piecewise interval values, gaps left blank; each run has its own time axis'})
    return artifacts


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--windows',required=True);p.add_argument('--output-dir',required=True)
    p.add_argument('--mode',choices=['distribution','timeline'],default='distribution');p.add_argument('--min-coverage',type=float,default=.8)
    a=p.parse_args();write_json(Path(a.output_dir)/'figures.json',plot(read_json(a.windows)['windows'],a.output_dir,a.mode,a.min_coverage))

if __name__=='__main__':main()
