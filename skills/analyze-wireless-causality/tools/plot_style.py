"""Shared, configurable report figure typography and entity styles."""
import textwrap
from matplotlib import rc_context, font_manager


def context(theme):
    available = {f.name for f in font_manager.fontManager.ttflist}
    preferred = ['Microsoft YaHei', 'Noto Sans CJK SC']+theme['font_families']+['DejaVu Sans']
    fonts = list(dict.fromkeys(f for f in preferred if f in available))
    return rc_context({'font.family': fonts, 'font.size': theme['plot_font_pt'],
                       'axes.titlesize': theme['plot_font_pt'], 'axes.labelsize': theme['plot_font_pt'],
                       'legend.fontsize': theme['plot_font_pt']-1, 'axes.labelcolor': theme['text_color'],
                       'text.color': theme['text_color'], 'xtick.color': theme['muted_color'],
                       'ytick.color': theme['muted_color'], 'axes.spines.top': False, 'axes.spines.right': False,
                       'axes.edgecolor': theme['rule_color'], 'axes.unicode_minus': False,
                       'savefig.facecolor': 'white', 'svg.fonttype': 'path', 'pdf.fonttype': 42})


def entity_styles(identities, theme):
    colors = theme['series_colors']
    lines = ['-', '--', '-.', ':']
    return {name: {'color': colors[i % len(colors)], 'linestyle': lines[(i // len(colors)) % len(lines)]}
            for i, name in enumerate(sorted(set(identities)))}


def wrap(text, width=48):
    return '\n'.join(textwrap.wrap(str(text), width=width, break_long_words=True, break_on_hyphens=False))


def labels(language='en', custom=None):
    en = {'ecdf': 'Time-weighted ECDF; equal run weights', 'time': 'Source-relative time (s); no event alignment', 'runs': 'runs'}
    zh = {'ecdf': '按有效时长加权的累积分布；录制等权', 'time': '源相对时间 (s)；未进行事件对齐', 'runs': '录制数'}
    if custom is not None:
        if not isinstance(custom, dict) or set(custom) != set(en) or any(not isinstance(s, str) or not s.strip() for s in custom.values()):
            raise ValueError('Plot labels must define ecdf, time and runs')
        return custom
    if language in {'en', 'en-US', 'English'}:
        return en
    if language in {'zh', 'zh-CN', 'Chinese', '中文'}:
        return zh
    raise ValueError('Provide plot labels for the requested language')
