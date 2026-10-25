"""Protocol-specific primitives for reviewed IEEE 802.11 frame adapters."""
import argparse
import re
from collections import defaultdict
from common import finite_number, number, read_json, write_json, ensure_output_safe, require_keys


def decode_compressed_ba(start_seq, wire_hex, bitmap_bits):
    """Only single-TID compressed BA, in on-wire byte order; not a BA/MPDU matcher."""
    if type(bitmap_bits) is not int or bitmap_bits not in {64,256} or type(start_seq) is not int or not 0<=start_seq<4096:
        raise ValueError('Supported: compressed 64/256-bit bitmap and a 12-bit starting sequence number')
    if not isinstance(wire_hex,str) or not re.fullmatch(r'[0-9a-fA-F :]+',wire_hex):
        raise ValueError('Provide explicit on-wire octets, not a display integer or an unknown encoding')
    raw=bytes.fromhex(wire_hex.replace(':',' '))
    if len(raw)*8!=bitmap_bits: raise ValueError('Bitmap length does not match the declared variant')
    return {(start_seq+i)%4096:bool(raw[i//8] & (1<<(i%8))) for i in range(bitmap_bits)}


def observed_ba_status(start_seq, wire_hex, bitmap_bits, observed_sequences):
    bits=decode_compressed_ba(start_seq,wire_hex,bitmap_bits)
    if not isinstance(observed_sequences,list) or any(type(x) is not int or not 0<=x<4096 for x in observed_sequences):
        raise ValueError('Invalid observed sequence number')
    return {str(s):('acknowledged' if bits[s] else 'not_acknowledged_in_this_bitmap')
            if s in bits else 'outside_bitmap' for s in set(observed_sequences)}


def observed_retry_chains(frames, max_gap_s):
    max_gap_s=finite_number(max_gap_s,'max_gap_s',positive=True)
    required={'capture_id','transmitter','receiver','tid','seq','fragment','time_s','retry','source_row'}
    active={}; chains=[]; previous=defaultdict(lambda:float('-inf'))
    def close(key, reason):
        chain=active.pop(key)
        chain['end_reason']=reason
        chain['right_censored']=True  # Without explicit ACK/lifetime evidence, no completed success/failure claim.
        chain['duration_observed_s']=chain['last_s']-chain['first_s']
        chains.append(chain)
    for f in frames:
        if not required<=f.keys() or any(f[k] is None for k in required):
            raise ValueError('Retry reconstruction requires capture, TA/RA, TID, sequence, fragment, time, retry and source row')
        if any(not isinstance(f[k],str) or not f[k].strip() or f[k].strip().lower() in {'unknown','unavailable'} for k in ['capture_id','transmitter','receiver']):
            raise ValueError('Explicit capture and transmitter/receiver identities are required')
        if any(type(f[k]) is not int for k in ['seq','tid','fragment','source_row']) or not 0<=f['fragment']<=15 or f['source_row']<1:
            raise ValueError('Sequence, TID, fragment and source row require valid integers')
        if type(f['retry']) is not int or f['retry'] not in {0,1} or not 0<=f['seq']<4096 or not 0<=f['tid']<=15:
            raise ValueError('Invalid normalized retry, sequence or TID')
        t=number(f['time_s'])
        if t is None or t<previous[f['capture_id']]: raise ValueError('Frames must be time-ordered per capture')
        previous[f['capture_id']]=t
        key=tuple(f[k] for k in ['capture_id','transmitter','receiver','tid','seq','fragment'])
        if key in active and (t-active[key]['last_s']>max_gap_s or (f['retry']==0 and t>active[key]['last_s'])):
            close(key,'gap_or_sequence_reuse')
        if key not in active:
            active[key]={'key':list(key),'first_s':t,'last_s':t,'attempts_observed':0,
                         'retry_flags_observed':0,'left_censored':f['retry']==1,
                         'duplicate_time_observations':0,'source_rows':[]}
        c=active[key]
        if c['attempts_observed'] and c['last_s']==t: c['duplicate_time_observations']+=1
        c['last_s']=t; c['attempts_observed']+=1;c['retry_flags_observed']+=f['retry'];c['source_rows'].append(f['source_row'])
    for key in list(active): close(key,'capture_end_or_unobserved_completion')
    return {'chains':chains,'interpretation':'Observed attempt chains; not configured retry limits or proven final losses.',
            'limitations':['Capture losses, duplicate observations and sequence reuse can change apparent chain length.',
                           'TA/RA and TID must be decoded; address aliases or missing TID cannot silently substitute.']}


def effective_rate_proxy(rate_mbps, failures, attempts):
    if any(x is None for x in [rate_mbps,failures,attempts]): return None
    rate_mbps,failures,attempts=[finite_number(x,'rate/proxy input') for x in [rate_mbps,failures,attempts]]
    if rate_mbps<0 or failures<0 or attempts<0 or failures>attempts: raise ValueError('Invalid rate or error counts')
    return rate_mbps*(1-failures/attempts) if attempts>0 else None


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();q=read_json(a.request)
    ensure_output_safe(a.output,[a.request],'.json')
    fields={'decode_compressed_ba':{'start_seq','wire_hex','bitmap_bits','observed_sequences'},
            'observed_retry_chains':{'frames','max_gap_s'},
            'effective_rate_proxy':{'rate_mbps','failures','attempts'}}
    required=fields.get(q.get('operation'))
    if required is None: raise ValueError('Unsupported operation')
    require_keys(q,required|{'operation'},required|{'operation'},'Wi-Fi request')
    if q['operation']=='decode_compressed_ba':
        result=observed_ba_status(q['start_seq'],q['wire_hex'],q['bitmap_bits'],q['observed_sequences'])
    elif q['operation']=='observed_retry_chains': result=observed_retry_chains(q['frames'],q['max_gap_s'])
    elif q['operation']=='effective_rate_proxy':
        result={'effective_rate_proxy_mbps':effective_rate_proxy(q['rate_mbps'],q['failures'],q['attempts']),
                'interpretation':'PHY rate adjusted by the explicitly supplied error fraction; not application goodput'}
    else: raise ValueError('Unsupported operation')
    write_json(a.output,result,[a.request])

if __name__=='__main__':main()
