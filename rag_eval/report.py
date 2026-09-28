"""report：把 results.json 渲染成单文件 HTML 报告（无外部依赖，双击即开）。

覆盖出分场景的六个视图：排行榜 / 指标雷达 / 题型·行业热力 / 错误归因堆叠 /
Pareto 散点 / 逐题对比。图表全部是内联 SVG，配色遵循项目 dataviz 规范：
- 系统色按固定槽位分配（身份色，不随排名重排）；浅色模式 3 个低对比槽位
  由「表格视图 + 直接标签」兜底（relief 规则）
- 量值（热力图）用单色 sequential；Pareto 散点 >3 系统时改用 emphasis 编码
- N/A 不画成 0：缺指标的轴/单元格/点直接排除并注明
"""
from __future__ import annotations

import html
from pathlib import Path

# ---------------------------------------------------------------- 配色
# 与 dataviz 参考调色板一致；顺序即槽位，系统按名字排序后固定占用
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
# sequential（热力图，浅→深）
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ_DARK = ["#104281", "#184f95", "#256abf", "#2a78d6", "#5598e7", "#86b6ef", "#cde2fb"]
# 状态色（固定，不参与身份分配）
GOOD, CRITICAL = "#0ca30c", "#d03b3b"
GRAY_MARK = "#898781"  # emphasis 编码的「其余」

# 错误归因：固定槽位顺序（身份色，各图一致）
ERROR_ORDER = [
    ("retrieval_error", "检索"),
    ("ranking_error", "排序"),
    ("context_error", "上下文"),
    ("generation_error", "生成"),
    ("citation_error", "引用"),
    ("no_answer_error", "拒答"),
    ("system_error", "系统"),
]

# 雷达轴：(results.json 路径, 展示名)。只取 0-1 归一的量
RADAR_AXES = [
    (("retrieval", "hit@5"), "Hit@5"),
    (("retrieval", "recall@5"), "Recall@5"),
    (("retrieval", "mrr@5"), "MRR@5"),
    (("retrieval", "ndcg@5"), "NDCG@5"),
    (("__correct__",), "正确率"),
]

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; background: #f9f9f7; color: #0b0b0b;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.55;
}
.viz-root {
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
  --s5: #e87ba4; --s6: #008300; --s7: #4a3aa7; --s8: #e34948;
  --good: #0ca30c; --critical: #d03b3b; --mark-gray: #898781;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) { color-scheme: dark; }
  :root:where(:not([data-theme="light"])) body { background: #0d0d0d; color: #fff; }
  :root:where(:not([data-theme="light"])) .viz-root {
    --surface-1: #1a1a19; --page: #0d0d0d;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
    --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
  }
}
:root[data-theme="dark"] { color-scheme: dark; }
:root[data-theme="dark"] body { background: #0d0d0d; color: #fff; }
:root[data-theme="dark"] .viz-root {
  --surface-1: #1a1a19; --page: #0d0d0d;
  --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
  --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
}
main { max-width: 1080px; margin: 0 auto; padding: 28px 20px 64px; }
header.top { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
h1 { font-size: 22px; margin: 0; }
.sub { color: var(--text-secondary); font-size: 13px; }
button.theme {
  margin-left: auto; border: 1px solid var(--border); background: var(--surface-1);
  color: var(--text-secondary); border-radius: 8px; padding: 4px 12px; cursor: pointer;
  font-size: 12px;
}
section {
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
  padding: 18px 20px; margin-top: 18px;
}
h2 { font-size: 15px; margin: 0 0 2px; }
.note { color: var(--text-muted); font-size: 12px; margin: 0 0 12px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--grid); }
th:first-child, td:first-child { text-align: left; }
thead th { color: var(--text-secondary); font-weight: 600; white-space: nowrap; }
td, th { font-variant-numeric: tabular-nums; }
tr.hero-row td { font-weight: 600; }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--text-secondary); margin: 8px 0 0; }
.legend .key { display: inline-flex; align-items: center; gap: 6px; }
.legend .chip { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
svg text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.chart-wrap { overflow-x: auto; }
details { margin-top: 10px; font-size: 12px; }
details summary { cursor: pointer; color: var(--text-secondary); }
details table { margin-top: 8px; font-size: 12px; }
#tip {
  position: fixed; pointer-events: none; z-index: 10; display: none;
  background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px;
  font-size: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); max-width: 280px;
  white-space: pre-line;
}
.hit { cursor: default; }
.ok { color: var(--good); font-weight: 600; }
.bad { color: var(--critical); font-weight: 600; }
.na { color: var(--text-muted); }
.pill {
  display: inline-block; font-size: 11px; padding: 1px 8px; border-radius: 999px;
  border: 1px solid var(--border); color: var(--text-secondary); margin-left: 6px;
}
"""

JS = """
(function () {
  var b = document.querySelector('button.theme');
  b.addEventListener('click', function () {
    var r = document.documentElement, cur = r.getAttribute('data-theme');
    if (!cur) cur = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    r.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
  });
  var tip = document.getElementById('tip');
  function show(e, t) {
    tip.textContent = t; tip.style.display = 'block';
    var x = e.clientX + 14, y = e.clientY + 12;
    if (x + tip.offsetWidth > innerWidth - 8) x = e.clientX - tip.offsetWidth - 10;
    if (y + tip.offsetHeight > innerHeight - 8) y = e.clientY - tip.offsetHeight - 10;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  function hide() { tip.style.display = 'none'; }
  document.querySelectorAll('[data-tip]').forEach(function (el) {
    el.addEventListener('mousemove', function (e) { show(e, el.getAttribute('data-tip')); });
    el.addEventListener('mouseleave', hide);
  });
})();
"""


def ink_on(hex_color: str) -> str:
    """填充块内标签选白/墨：按 WCAG 对比度取更高的一侧。"""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    contrast_dark = (lum + 0.05) / 0.05  # vs #0b0b0b 近似
    contrast_white = 1.05 / (lum + 0.05)
    return "#ffffff" if contrast_white >= contrast_dark else "var(--text-primary)"


def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def pct(v: float | None, digits: int = 1) -> str:
    return "N/A" if v is None else f"{v * 100:.{digits}f}%"


def num(v: float | None, digits: int = 1) -> str:
    return "N/A" if v is None else f"{v:,.{digits}f}"


def pick_system_colors(names: list[str]) -> dict[str, str]:
    """系统按名字排序占固定槽位。颜色跟实体走，不随成绩排名重排。"""
    return {name: SERIES_LIGHT[i % len(SERIES_LIGHT)] for i, name in enumerate(sorted(names))}


def var_color(idx: int) -> str:
    return f"var(--s{(idx % 8) + 1})"


def svg_radar(systems: dict, names: list[str], colors: dict[str, str]) -> tuple[str, list[str]]:
    """指标雷达。轴值全部 0-1；缺值的轴整根排除（N/A 不画成 0）。"""
    import math

    size, cx, cy, r = 340, 170, 160, 96
    axes = []
    for path, label in RADAR_AXES:
        vals = []
        for n in names:
            obj = systems[n]
            if path == ("__correct__",):
                vals.append(obj.get("correct_rate"))
            else:
                v = obj
                for k in path:
                    v = (v or {}).get(k) if isinstance(v, dict) else None
                vals.append(v)
        if all(v is not None for v in vals):
            axes.append((label, vals))
    kept = {a[0] for a in axes}
    skipped = [label for _, label in RADAR_AXES if label not in kept]

    if len(axes) < 3:
        return "<p class='note'>可用指标不足 3 个，无法成雷达图。</p>", skipped

    n = len(axes)
    parts = [f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img">']
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = []
        for i in range(n):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            pts.append(f"{cx + r * ring * math.cos(ang):.1f},{cy + r * ring * math.sin(ang):.1f}")
        parts.append(
            f'<polygon points="{" ".join(pts)}" fill="none" stroke="var(--grid)" stroke-width="1"/>'
        )
    for i in range(n):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        x2, y2 = cx + r * math.cos(ang), cy + r * math.sin(ang)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="var(--grid)" stroke-width="1"/>')
        lx, ly = cx + (r + 24) * math.cos(ang), cy + (r + 20) * math.sin(ang)
        anchor = "middle" if abs(math.cos(ang)) < 0.3 else ("start" if math.cos(ang) > 0 else "end")
        # 越界翻转锚点，标签不被画布裁切
        if anchor == "start" and lx + 56 > size:
            anchor, lx = "end", size - 4
        elif anchor == "end" and lx - 56 < 0:
            anchor, lx = "start", 4
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" fill="var(--text-muted)" text-anchor="{anchor}">{esc(axes[i][0])}</text>'
        )
    # 各系统：10% 面积 + 2px 折线 + 顶点 4.5px（2px surface ring）
    for si, name in enumerate(names):
        pts = []
        for i, (_, vals) in enumerate(axes):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            rr = r * max(0.0, min(1.0, float(vals[si])))
            pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        c = colors[name]
        parts.append(f'<polygon points="{poly}" fill="{c}" fill-opacity="0.10"/>')
        parts.append(
            f'<polygon points="{poly}" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/>'
        )
        for (x, y), (alabel, vals) in zip(pts, axes):
            tip = f"{name} · {alabel}: {float(vals[si]) * 100:.1f}%"
            parts.append(
                f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="12" fill="transparent" '
                f'data-tip="{esc(tip)}"/>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{c}" stroke="var(--surface-1)" stroke-width="2"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts), skipped


def svg_heatmap(rows: list[str], cols: list[str], values: dict[tuple[str, str], float | None],
                row_label: str) -> str:
    """题型×系统热力图：sequential 单色（量值编码），N/A 单元格留白不涂色。"""
    cw, ch, pad_l, pad_t = 96, 34, 88, 34
    w = pad_l + cw * len(cols) + 12
    h = pad_t + ch * len(rows) + 10
    parts = [f'<svg width="{w}" height="{h}" role="img">']
    for j, c in enumerate(cols):
        parts.append(
            f'<text x="{pad_l + cw * j + cw / 2:.0f}" y="{pad_t - 12}" font-size="11" '
            f'fill="var(--text-secondary)" text-anchor="middle">{esc(c)}</text>'
        )
    for i, rname in enumerate(rows):
        parts.append(
            f'<text x="{pad_l - 8}" y="{pad_t + ch * i + ch / 2 + 4:.0f}" font-size="11" '
            f'fill="var(--text-secondary)" text-anchor="end">{esc(rname)}</text>'
        )
        for j, cname in enumerate(cols):
            v = values.get((rname, cname))
            x, y = pad_l + cw * j + 1, pad_t + ch * i + 1
            bw, bh = cw - 2, ch - 2  # 2px surface gap
            if v is None:
                parts.append(
                    f'<rect class="hit" x="{x}" y="{y}" width="{bw}" height="{bh}" rx="4" '
                    f'fill="none" stroke="var(--grid)" data-tip="{esc(rname)} · {esc(cname)}: N/A"/>'
                    f'<text x="{x + bw / 2:.0f}" y="{y + bh / 2 + 4:.0f}" font-size="11" '
                    f'fill="var(--text-muted)" text-anchor="middle">N/A</text>'
                )
                continue
            step = min(6, int(v * 7)) if v < 1 else 6
            fill = f"var(--heat-{step})"
            ink = "#ffffff" if step >= 3 else "var(--text-primary)"
            parts.append(
                f'<rect class="hit" x="{x}" y="{y}" width="{bw}" height="{bh}" rx="4" fill="{fill}" '
                f'data-tip="{esc(rname)} · {esc(cname)}: {v * 100:.0f}%"/>'
                f'<text x="{x + bw / 2:.0f}" y="{y + bh / 2 + 4:.0f}" font-size="11" fill="{ink}" '
                f'text-anchor="middle">{v * 100:.0f}</text>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


def svg_stacked(names: list[str], colors_order: list[tuple[str, str]],
                breakdown: dict[str, dict[str, int]]) -> tuple[str, str]:
    """错误归因堆叠条（横向）：2px surface gap 分段，段太窄不放内标签。"""
    row_h, bar_h = 38, 22
    # 左槽位按最长系统名留宽，标签不被画布裁切
    pad_l = max(108, max((len(n) for n in names), default=0) * 7 + 16)
    max_total = max((sum(breakdown.get(n, {}).values()) or 0) for n in names) or 1
    w = max(620, pad_l + 420)
    h = row_h * len(names) + 14
    scale = (w - pad_l - 60) / max_total
    parts = [f'<svg width="{w}" height="{h}" role="img">']
    for i, n in enumerate(names):
        y = row_h * i + (row_h - bar_h) / 2
        parts.append(
            f'<text x="{pad_l - 10}" y="{y + bar_h / 2 + 4:.0f}" font-size="12" '
            f'fill="var(--text-secondary)" text-anchor="end">{esc(n)}</text>'
        )
        x = pad_l
        total = sum(breakdown.get(n, {}).values())
        if total == 0:
            parts.append(
                f'<text x="{pad_l + 6}" y="{y + bar_h / 2 + 4:.0f}" font-size="11" fill="var(--text-muted)">无错误</text>'
            )
            continue
        for k, (key, label) in enumerate(colors_order):
            cnt = breakdown.get(n, {}).get(key, 0)
            if cnt <= 0:
                continue
            bw = cnt * scale
            seg_w = max(0.0, bw - 2)  # 2px gap
            # 最后一段圆角数据端，基线端方角
            rx = 4 if x + bw >= pad_l + total * scale - 0.5 else 0
            tip = f"{n} · {label}错误: {cnt}"
            parts.append(
                f'<rect class="hit" x="{x:.1f}" y="{y:.1f}" width="{seg_w:.1f}" height="{bar_h}" rx="{rx}" '
                f'fill="var(--s{k + 1})" data-tip="{esc(tip)}"/>'
            )
            if seg_w >= 28:  # 放得下才放内标签；墨色按段色对比度选
                parts.append(
                    f'<text x="{x + seg_w / 2:.1f}" y="{y + bar_h / 2 + 4:.0f}" font-size="11" '
                    f'fill="{ink_on(SERIES_LIGHT[k])}" text-anchor="middle">{cnt}</text>'
                )
            x += bw
        parts.append(
            f'<text x="{x + 8:.1f}" y="{y + bar_h / 2 + 4:.0f}" font-size="11" fill="var(--text-muted)">{total}</text>'
        )
    parts.append("</svg>")
    legend = " ".join(
        f'<span class="key"><span class="chip" style="background:var(--s{k + 1})"></span>{esc(label)}</span>'
        for k, (_, label) in enumerate(colors_order)
    )
    return "\n".join(parts), f'<div class="legend">{legend}</div>'


def svg_pareto(names: list[str], systems: dict, colors: dict[str, str]) -> str:
    """Pareto 散点：x=P95 延迟，y=正确率，点面积∝成本。>3 系统改 emphasis 编码。"""
    import math

    pts = []
    for n in names:
        s = systems[n]
        lat = (s.get("system") or {}).get("latency_p95_ms")
        corr = s.get("correct_rate")
        cost = (s.get("system") or {}).get("cost_per_query_usd")
        if lat is None or corr is None:
            continue
        pts.append((n, lat, corr, cost))
    if not pts:
        return "<p class='note'>无延迟/正确率数据，跳过 Pareto 图。</p>"

    w, h, pad_l, pad_b, pad_t, pad_r = 620, 320, 56, 46, 16, 24
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    x_min, x_max = 0.0, max(xs) * 1.15 or 1.0
    y_min, y_max = 0.0, max(1.0, max(ys) * 1.15)
    costs = [p[3] for p in pts if p[3] is not None] or [1.0]
    c_min, c_max = min(costs), max(costs)

    def X(v: float) -> float:
        return pad_l + (v - x_min) / (x_max - x_min) * (w - pad_l - pad_r)

    def Y(v: float) -> float:
        return h - pad_b - (v - y_min) / (y_max - y_min) * (h - pad_b - pad_t)

    # >3 系统：emphasis（一个色 + 灰），否则身份色
    emphasis = len(pts) > 3
    front = set()
    for i, (n1, l1, c1, _) in enumerate(pts):
        dominated = any(
            (l2 <= l1 and c2 >= c1 and (l2 < l1 or c2 > c1))
            for j, (n2, l2, c2, _) in enumerate(pts)
            if j != i
        )
        if not dominated:
            front.add(n1)

    parts = [f'<svg width="{w}" height="{h}" role="img">']
    # 网格 + 轴，hairline；x 刻度取整（目标 4 档：0/10k/20k/30k）
    raw = x_max / 4 if x_max > 0 else 1.0
    mag = 10 ** math.floor(math.log10(raw))
    step_x = next(mag * m for m in (1, 2, 5, 10) if mag * m >= raw)
    xv = 0.0
    while xv <= x_max + 1e-9:
        parts.append(
            f'<text x="{X(xv):.1f}" y="{h - pad_b + 18}" font-size="11" fill="var(--text-muted)" text-anchor="middle">{xv:,.0f}</text>'
        )
        xv += step_x
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        yv = y_min + (y_max - y_min) * t
        parts.append(
            f'<line x1="{pad_l}" y1="{Y(yv):.1f}" x2="{w - pad_r}" y2="{Y(yv):.1f}" stroke="var(--grid)" stroke-width="1"/>'
            f'<text x="{pad_l - 8}" y="{Y(yv) + 4:.1f}" font-size="11" fill="var(--text-muted)" text-anchor="end">{yv * 100:.0f}%</text>'
        )
    parts.append(
        f'<text x="{(pad_l + w - pad_r) / 2:.0f}" y="{h - 6}" font-size="11" fill="var(--text-secondary)" text-anchor="middle">P95 延迟 (ms) →</text>'
    )
    parts.append(
        f'<text x="12" y="{(pad_t + h - pad_b) / 2:.0f}" font-size="11" fill="var(--text-secondary)" text-anchor="middle" transform="rotate(-90 12 {(pad_t + h - pad_b) / 2:.0f})">正确率 →</text>'
    )
    for n, lat, corr, cost in pts:
        rad = 6.0 if cost is None or c_max == c_min else 6.0 + 8.0 * ((cost - c_min) / (c_max - c_min)) ** 0.5
        # >3 系统 all-pairs 不过线，改 emphasis：前沿用槽位 1，其余灰；≤3 保持身份色
        c = ("#2a78d6" if n in front else GRAY_MARK) if emphasis else colors[n]
        tip = f"{n}\n正确率 {corr * 100:.1f}% · P95 {lat:,.0f}ms · 成本/题 {'N/A' if cost is None else f'${cost:.4f}'}"
        tip += " · Pareto 前沿" if n in front else ""
        # 2px surface ring；hit 圆 ≥24px
        parts.append(
            f'<circle class="hit" cx="{X(lat):.1f}" cy="{Y(corr):.1f}" r="{rad:.1f}" fill="{c}" '
            f'fill-opacity="0.85" stroke="var(--surface-1)" stroke-width="2" '
            f'data-tip="{esc(tip).replace(chr(10), "&#10;")}"/>'
        )
        parts.append(
            f'<circle cx="{X(lat):.1f}" cy="{Y(corr):.1f}" r="{max(rad + 8, 12):.1f}" fill="transparent"/>'
        )
        parts.append(
            f'<text x="{X(lat) + rad + 5:.1f}" y="{Y(corr) + 4:.1f}" font-size="11" fill="var(--text-secondary)">{esc(n)}</text>'
        )
    parts.append("</svg>")
    legend = (
        '<div class="legend"><span class="key"><span class="chip" style="background:#2a78d6"></span>Pareto 前沿</span>'
        '<span class="key"><span class="chip" style="background:#898781"></span>被支配</span>'
        f'<span class="key">点面积 ∝ 成本/题</span></div>'
        if emphasis
        else '<div class="legend"><span class="key">点面积 ∝ 成本/题 · 每点直接标名</span></div>'
    )
    return "\n".join(parts) + legend


# ---CHUNK-END---

HEAT_VARS = """
.viz-root { --heat-0: #cde2fb; --heat-1: #9ec5f4; --heat-2: #6da7ec; --heat-3: #3987e5;
            --heat-4: #256abf; --heat-5: #184f95; --heat-6: #0d366b; }
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    --heat-0: #104281; --heat-1: #184f95; --heat-2: #256abf; --heat-3: #2a78d6;
    --heat-4: #5598e7; --heat-5: #86b6ef; --heat-6: #cde2fb; }
}
:root[data-theme="dark"] .viz-root {
  --heat-0: #104281; --heat-1: #184f95; --heat-2: #256abf; --heat-3: #2a78d6;
  --heat-4: #5598e7; --heat-5: #86b6ef; --heat-6: #cde2fb; }
"""


def legend_html(names: list[str], colors: dict[str, str]) -> str:
    chips = " ".join(
        f'<span class="key"><span class="chip" style="background:{esc(colors[n])}"></span>{esc(n)}</span>'
        for n in names
    )
    return f'<div class="legend">{chips}</div>'


def table_html(headers: list[str], rows: list[list[str]], hero: str | None = None) -> str:
    th = "".join(f"<th>{h}</th>" for h in headers)
    body = []
    for r in rows:
        cls = ' class="hero-row"' if hero and r and r[0] == hero else ""
        body.append(f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render(results: dict, title: str = "RAG 评测对比报告") -> str:
    systems = results.get("systems") or {}
    names = sorted(systems)
    colors = pick_system_colors(names)
    judge = results.get("judge") or "rule-based (approx_correct)"
    front = results.get("pareto_front") or []

    sections = []

    # ---------- 1. 排行榜 ----------
    rows = []
    for n in names:
        s = systems[n]
        sysm = s.get("system") or {}
        ret = s.get("retrieval") or {}
        mark = f'<span class="pill">Pareto</span>' if n in front else ""
        rows.append([
            f'<span class="swatch" style="background:{esc(colors[n])}"></span>{esc(n)}{mark}',
            pct(s.get("correct_rate")),
            pct(ret.get("hit@5")),
            pct(ret.get("recall@5")),
            num(ret.get("mrr@5"), 3),
            pct(ret.get("ndcg@5")),
            num(sysm.get("latency_p95_ms"), 0) + " ms",
            "N/A" if sysm.get("cost_per_query_usd") is None else f"${sysm['cost_per_query_usd']:.4f}",
            pct(sysm.get("error_rate")),
            str(s.get("n_judged", "N/A")),
        ])
    sections.append(
        "<section><h2>排行榜</h2>"
        "<p class='note'>判定来源: " + esc(judge) + " · 缺字段显示 N/A 不计 0 分 · "
        "不给单一总分（权重依业务而定，见《检测RAG质量.md》§56）</p>"
        + table_html(
            ["系统", "正确率", "Hit@5", "Recall@5", "MRR@5", "NDCG@5", "P95 延迟", "成本/题", "错误率", "判定数"],
            rows,
        )
        + "</section>"
    )

    # ---------- 2. 指标雷达 ----------
    radar_svg, skipped = svg_radar(systems, names, colors)
    note = "轴: Hit@5 / Recall@5 / MRR@5 / NDCG@5 / 正确率（0-100%）"
    if skipped:
        note += f" · 因缺数据排除: {', '.join(skipped)}（N/A 不画成 0）"
    sections.append(
        f"<section><h2>指标雷达</h2><p class='note'>{esc(note)}</p>"
        f'<div class="chart-wrap">{radar_svg}</div>'
        + (legend_html(names, colors) if len(names) > 1 else "")
        + "</section>"
    )

    # ---------- 3. 题型热力 / 4. 行业热力 ----------
    for key, heading, rlabel in (
        ("by_category", "题型 × 系统 正确率", "题型"),
        ("by_domain", "行业 × 系统 正确率", "行业"),
    ):
        union_rows: list[str] = sorted({r for n in names for r in (systems[n].get(key) or {})})
        if not union_rows:
            continue
        vals: dict[tuple[str, str], float | None] = {}
        for rn in union_rows:
            for n in names:
                cell = (systems[n].get(key) or {}).get(rn) or {}
                vals[(rn, n)] = cell.get("correct_rate")
        svg = svg_heatmap(union_rows, names, vals, rlabel)
        nrows = table_html(
            [rlabel] + names,
            [[esc(rn)] + [pct(vals[(rn, n)]) for n in names] for rn in union_rows],
        )
        sections.append(
            f"<section><h2>{esc(heading)}</h2>"
            "<p class='note'>sequential 单色（深=正确率高）· N/A 留白不涂色，不计 0 分</p>"
            f'<div class="chart-wrap">{svg}</div>'
            f"<details><summary>表格视图</summary>{nrows}</details></section>"
        )

    # ---------- 5. 错误归因 ----------
    breakdown = {n: systems[n].get("error_breakdown") or {} for n in names}
    if any(breakdown.values()):
        s_svg, s_legend = svg_stacked(names, ERROR_ORDER, breakdown)
        rows = [[esc(n)] + [str(breakdown[n].get(k, 0)) for k, _ in ERROR_ORDER] for n in names]
        sections.append(
            "<section><h2>错误归因</h2>"
            "<p class='note'>六类归因决策树输出（《检测RAG质量.md》§53）· 段内标注仅在够宽时显示，精确值见表格</p>"
            f'<div class="chart-wrap">{s_svg}</div>{s_legend}'
            f"<details><summary>表格视图</summary>"
            + table_html(["系统"] + [lb for _, lb in ERROR_ORDER], rows)
            + "</details></section>"
        )

    # ---------- 6. Pareto ----------
    p_svg = svg_pareto(names, systems, colors)
    p_rows = [
        [
            esc(n),
            pct(systems[n].get("correct_rate")),
            num((systems[n].get("system") or {}).get("latency_p95_ms"), 0),
            "N/A" if (systems[n].get("system") or {}).get("cost_per_query_usd") is None
            else f"${systems[n]['system']['cost_per_query_usd']:.4f}",
            "是" if n in front else "否",
        ]
        for n in names
    ]
    sections.append(
        "<section><h2>Pareto 权衡（质量 vs 延迟 vs 成本）</h2>"
        "<p class='note'>三目标支配关系，非加权总分 · x=P95 延迟（越左越好）· y=正确率（越上越好）· 点面积∝成本/题</p>"
        f'<div class="chart-wrap">{p_svg}</div>'
        f"<details><summary>表格视图</summary>"
        + table_html(["系统", "正确率", "P95 延迟 (ms)", "成本/题", "在前沿"], p_rows)
        + "</details></section>"
    )

    # ---------- 7. 逐题对比 ----------
    all_q: dict[str, dict] = {}
    for n in names:
        for rec in systems[n].get("per_question") or []:
            all_q.setdefault(rec.get("question_id") or "?", {})[n] = rec
    if all_q:
        rows = []
        for qid in sorted(all_q):
            recs = all_q[qid]
            any_rec = next(iter(recs.values()))
            row = [esc(qid), esc(any_rec.get("category") or "?"), esc(any_rec.get("domain") or "?")]
            for n in names:
                rec = recs.get(n)
                if rec is None:
                    row.append('<span class="na">未作答</span>')
                    continue
                ok = rec.get("is_correct")
                mark = '<span class="ok">✓ 对</span>' if ok else '<span class="bad">✗ 错</span>'
                if ok is None:
                    mark = '<span class="na">N/A</span>'
                tri = (rec.get("triage") or {}).get("label") or ""
                row.append(f"{mark} <span class='na'>{esc(tri)}</span>")
            rows.append(row)
        sections.append(
            "<section><h2>逐题对比</h2>"
            "<p class='note'>✓/✗ 为判定结果，灰字为错误归因 · 全部值亦可从 results.json 的 per_question 取得</p>"
            + table_html(["题号", "题型", "行业"] + names, rows)
            + "</section>"
        )

    # ---------- 表格视图检查：雷达 ----------
    if len(names) > 0:
        rrows = []
        for path, label in RADAR_AXES:
            row = [esc(label)]
            for n in names:
                obj = systems[n]
                if path == ("__correct__",):
                    v = obj.get("correct_rate")
                else:
                    v = obj
                    for k in path:
                        v = (v or {}).get(k) if isinstance(v, dict) else None
                row.append(pct(v))
            rrows.append(row)
        sections.append(
            "<section><h2>指标一览（表格）</h2><p class='note'>雷达图的表格视图，保证每个图都有等价可读表</p>"
            + table_html(["指标"] + names, rrows)
            + "</section>"
        )

    css = CSS + HEAT_VARS
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(title)}</title>
<style>{css}</style>
</head>
<body>
<div class="viz-root">
<main>
<header class="top">
  <h1>{esc(title)}</h1>
  <span class="sub">{len(names)} 个系统 · {len(all_q)} 题 · 判定: {esc(judge)}</span>
  <button class="theme" type="button">切换主题</button>
</header>
{''.join(sections)}
<p class="note" style="margin-top:24px">由 rag-eval report 生成 · 单文件 HTML · 图表为内联 SVG · 项目: RAG-verify</p>
</main>
</div>
<div id="tip"></div>
<script>{JS}</script>
</body>
</html>
"""


def write_report(results_path: Path, out: Path, title: str = "RAG 评测对比报告") -> int:
    import json

    results = json.loads(results_path.read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(results, title), encoding="utf-8")
    n = len(results.get("systems") or {})
    print(f"[报告] {n} 个系统 -> {out}  ({out.stat().st_size // 1024} KB)")
    return 0
