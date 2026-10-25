"""Plot comparable window distributions or separate, direction-specific traces."""
import argparse
import hashlib
from collections import defaultdict
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from common import (ensure_output_safe, finite_number, measurement_signature, read_json,
                    source_paths, validate_windows, write_json)


def ecdf_points(values, weights):
    """Include the zero-to-one jump even for a constant/singleton population."""
    values, inverse = np.unique(np.asarray(values), return_inverse=True)
    mass = np.zeros(len(values))
    np.add.at(mass, inverse, weights)
    cumulative = np.cumsum(mass) / mass.sum()
    return np.r_[values[0], values], np.r_[0., cumulative]


def plot(windows, output_dir, mode='distribution', min_coverage=.8, protected_paths=()):
    min_coverage = finite_number(min_coverage, 'min_coverage', positive=True)
    if min_coverage > 1 or mode not in {'distribution', 'timeline'}:
        raise ValueError('Invalid coverage or plot mode')
    windows = validate_windows(windows)
    def valid(row):
        return row['value'] is not None and row['coverage'] >= min_coverage
    if not any(valid(r) for r in windows):
        raise ValueError('No valid windows to plot')
    root = Path(output_dir)
    protected = list(protected_paths) + source_paths({'windows': windows})
    families = defaultdict(list)
    for row in windows:
        families[(row['direction'], row['condition'], row['metric'], row['unit'])].append(row)
    plans = []
    for key, rows in families.items():
        if len({measurement_signature(r) for r in rows}) != 1:
            raise ValueError('Incompatible measurement contracts in a plot family')
        if not any(valid(r) for r in rows):
            continue
        runs = defaultdict(list)
        for row in rows:
            runs[(row['entity'], row['run_id'])].append(row)
        name = hashlib.sha256(repr((key, mode)).encode()).hexdigest()[:12]
        names = [name] if mode == 'distribution' else [f'{name}_{i + 1}' for i in range((len(runs) + 5) // 6)]
        for filename in names:
            for suffix in ['.png', '.svg']:
                ensure_output_safe(root / (filename + suffix), protected)
        plans.append((key, rows, runs, names))
    ensure_output_safe(root / 'figures.json', protected)
    root.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for key, rows, runs, names in plans:
        direction, condition, metric, unit = key
        parts = []
        if mode == 'distribution':
            fig, ax = plt.subplots(figsize=(9, 5))
            entities = defaultdict(list)
            for (entity, run), rr in runs.items():
                good = [r for r in rr if valid(r)]
                if good:
                    entities[entity].append(good)
            for entity, groups in sorted(entities.items()):
                values, weights = [], []
                for group in groups:
                    w = np.array([(r['end_s'] - r['start_s']) * r['coverage'] for r in group])
                    values.extend(r['value'] for r in group)
                    weights.extend(w / w.sum() / len(groups))
                x, y = ecdf_points(values, weights)
                ax.step(x, y, where='post', marker='.' if len(x) <= 3 else None,
                        label=f'{entity} (runs={len(groups)})')
            ax.set_xlabel(f'{metric} ({unit})')
            ax.set_ylabel('Time-weighted ECDF, equal weight per run')
            ax.set_ylim(0, 1.02)
            ax.legend()
            parts.append((fig, names[0]))
        else:
            items = sorted(runs.items())
            all_values = [r['value'] for r in rows if valid(r)]
            low, high = min(all_values), max(all_values)
            pad = max((high - low) * .05, abs(high) * .01, .01)
            for page in range(0, len(items), 6):
                subset = items[page:page + 6]
                fig, axes = plt.subplots(len(subset), 1, figsize=(10, 2.5 * len(subset)), squeeze=False)
                for ax, ((entity, run), rr) in zip(axes.flat, subset):
                    for row in sorted(rr, key=lambda r: r['start_s']):
                        if valid(row):
                            ax.plot([row['start_s'], row['end_s']], [row['value'], row['value']], color='#2864b7', linewidth=1.4)
                    ax.set_title(f'{entity} / {run}', loc='left', fontsize=10)
                    ax.set_ylim(low - pad, high + pad)
                    ax.set_ylabel(f'{metric}\n({unit})')
                    ax.set_xlabel('Source-relative time (s); no event alignment implied')
                parts.append((fig, names[page // 6]))
        for fig, name in parts:
            try:
                fig.suptitle(f'{direction} | {condition} | {metric}', fontsize=12)
                for ax in fig.axes:
                    ax.grid(alpha=.2)
                fig.tight_layout(rect=(0, 0, 1, .95))
                fig.savefig(root / (name + '.png'), dpi=160)
                fig.savefig(root / (name + '.svg'))
            finally:
                plt.close(fig)
            artifacts.append({'path': str((root / (name + '.png')).resolve()), 'direction': direction,
                              'condition': condition, 'metric': metric, 'unit': unit, 'mode': mode,
                              'measurement_signature': list(measurement_signature(rows[0])), 'min_coverage': min_coverage,
                              'calculation': 'Valid-duration weighted ECDF with equal run weights' if mode == 'distribution'
                              else 'Interval values with common y limits; gaps blank; separate run time axes'})
    return artifacts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--windows', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--mode', choices=['distribution', 'timeline'], default='distribution')
    p.add_argument('--min-coverage', type=float, default=.8)
    a = p.parse_args()
    q = read_json(a.windows)
    protected = [a.windows] + source_paths(q)
    output = Path(a.output_dir) / 'figures.json'
    ensure_output_safe(output, protected, '.json')
    artifacts = plot(q['windows'], a.output_dir, a.mode, a.min_coverage, protected)
    write_json(output, artifacts, protected)


if __name__ == '__main__':
    main()
