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
from report_design import ASSETS, load_theme
from plot_style import context, entity_styles, wrap, labels


def ecdf_points(values, weights):
    """Include the zero-to-one jump even for a constant/singleton population."""
    values, inverse = np.unique(np.asarray(values), return_inverse=True)
    mass = np.zeros(len(values))
    np.add.at(mass, inverse, weights)
    cumulative = np.cumsum(mass) / mass.sum()
    return np.r_[values[0], values], np.r_[0., cumulative]


def plot(windows, output_dir, mode='distribution', min_coverage=.8, protected_paths=(), theme_path=None, language='en', plot_labels=None):
    theme = load_theme(theme_path)
    protected = list(protected_paths)+[ASSETS/'theme.json']+([theme_path] if theme_path else [])
    with context(theme):
        return _plot(windows, output_dir, mode, min_coverage, protected, theme, labels(language, plot_labels))


def _plot(windows, output_dir, mode, min_coverage, protected_paths, theme, label):
    min_coverage = finite_number(min_coverage, 'min_coverage', positive=True)
    if min_coverage > 1 or mode not in {'distribution', 'timeline'}:
        raise ValueError('Invalid coverage or plot mode')
    windows = validate_windows(windows)
    styles = entity_styles([r['entity'] for r in windows], theme)
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
        count = len({entity for entity, run in runs}) if mode == 'distribution' else len(runs)
        per_page = theme['plot_series_per_panel'] if mode == 'distribution' else theme['plot_rows_per_page']
        if mode == 'distribution':
            longest = max(len(wrap(entity+' ('+label['runs']+'=999)', 36).splitlines()) for entity, run in runs)
            per_page = min(per_page, max(1, 6//longest))
        names = [f'{name}_{i + 1}' for i in range((count + per_page - 1) // per_page)]
        for filename in names:
            for suffix in ['.png', '.svg']:
                ensure_output_safe(root / (filename + suffix), protected)
        plans.append((key, rows, runs, names, per_page))
    ensure_output_safe(root / 'figures.json', protected)
    root.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for key, rows, runs, names, per_page in plans:
        direction, condition, metric, unit = key
        parts = []
        if mode == 'distribution':
            entities = defaultdict(list)
            for (entity, run), rr in runs.items():
                good = [r for r in rr if valid(r)]
                if good:
                    entities[entity].append(good)
            items = sorted(entities.items())
            all_values = [r['value'] for r in rows if valid(r)]
            low, high = min(all_values), max(all_values)
            pad = max((high-low)*.05, abs(high)*.01, .01)
            for page in range(0, len(items), per_page):
                fig, ax = plt.subplots(figsize=(theme['plot_width_in'], 5.4))
                subset = items[page:page+per_page]
                for entity, groups in subset:
                    values, weights = [], []
                    for group in groups:
                        w = np.array([(r['end_s'] - r['start_s']) * r['coverage'] for r in group])
                        values.extend(r['value'] for r in group)
                        weights.extend(w / w.sum() / len(groups))
                    x, y = ecdf_points(values, weights)
                    ax.step(x, y, where='post', linewidth=1.8, marker='.' if len(x) <= 3 else None,
                            label=wrap(f'{entity} ({label["runs"]}={len(groups)})', 36), **styles[entity])
                ax.set_xlabel(wrap(f'{metric} ({unit})'))
                ax.set_ylabel(wrap(label['ecdf'], 36))
                ax.set_xlim(low-pad, high+pad)
                ax.set_ylim(0, 1.02)
                handles, legend_labels = ax.get_legend_handles_labels()
                legend = fig.legend(handles, legend_labels, loc='lower center', bbox_to_anchor=(.5, .015), ncol=2, frameon=False)
                fig.canvas.draw()
                fig._whitepaper_bottom = legend.get_window_extent(fig.canvas.get_renderer()).y1/fig.bbox.height+.09
                parts.append((fig, names[page//per_page], [entity for entity, groups in subset]))
        else:
            items = sorted(runs.items())
            all_values = [r['value'] for r in rows if valid(r)]
            low, high = min(all_values), max(all_values)
            pad = max((high - low) * .05, abs(high) * .01, .01)
            per_page = theme['plot_rows_per_page']
            for page in range(0, len(items), per_page):
                subset = items[page:page + per_page]
                fig, axes = plt.subplots(len(subset), 1, figsize=(theme['plot_width_in'], 2.5 * len(subset)+.5), squeeze=False)
                for ax, ((entity, run), rr) in zip(axes.flat, subset):
                    for row in sorted(rr, key=lambda r: r['start_s']):
                        if valid(row):
                            ax.plot([row['start_s'], row['end_s']], [row['value'], row['value']], linewidth=1.8, **styles[entity])
                    ax.set_title(wrap(f'{entity} / {run}'), loc='left')
                    ax.set_ylim(low - pad, high + pad)
                    ax.set_ylabel(f'{metric}\n({unit})')
                    ax.set_xlabel(wrap(label['time']))
                parts.append((fig, names[page // per_page], [entity for (entity, run), rows in subset]))
        for fig, name, included_entities in parts:
            try:
                fig.suptitle(wrap(f'{direction} | {condition} | {metric}'), fontsize=theme['plot_font_pt']+1)
                for ax in fig.axes:
                    ax.grid(alpha=.2)
                fig.tight_layout(rect=(0, getattr(fig, '_whitepaper_bottom', 0), 1, .93))
                fig.savefig(root / (name + '.png'), dpi=220)
                fig.savefig(root / (name + '.svg'))
            finally:
                plt.close(fig)
            artifacts.append({'path': str((root / (name + '.png')).resolve()), 'direction': direction,
                              'condition': condition, 'metric': metric, 'unit': unit, 'mode': mode,
                              'measurement_signature': list(measurement_signature(rows[0])), 'min_coverage': min_coverage,
                              'entities': included_entities, 'entity_styles': {e: styles[e] for e in included_entities},
                              'presentation_theme': theme,
                              'calculation': 'Valid-duration weighted ECDF with equal run weights' if mode == 'distribution'
                              else 'Interval values with common y limits; gaps blank; separate run time axes'})
    return artifacts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--windows', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--mode', choices=['distribution', 'timeline'], default='distribution')
    p.add_argument('--min-coverage', type=float, default=.8)
    p.add_argument('--theme', help='Optional shared report theme overrides')
    p.add_argument('--language', default='en')
    p.add_argument('--labels', help='Optional ecdf/time/runs label mapping')
    a = p.parse_args()
    q = read_json(a.windows)
    protected = [a.windows] + source_paths(q)+([a.labels] if a.labels else [])+([a.theme] if a.theme else [])
    output = Path(a.output_dir) / 'figures.json'
    ensure_output_safe(output, protected, '.json')
    artifacts = plot(q['windows'], a.output_dir, a.mode, a.min_coverage, protected, a.theme, a.language, read_json(a.labels) if a.labels else None)
    write_json(output, artifacts, protected)


if __name__ == '__main__':
    main()
