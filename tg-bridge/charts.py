"""Render model-emitted ```chart JSON blocks into a dashboard PNG.

The model never runs code: it emits a declarative spec, validated here.

Spec:
  {"title": "...",
   "panels": [
     {"type": "kpi",   "title": "Total spend", "value": "$1.2M", "note": "+8% YoY"},
     {"type": "bar" | "barh" | "line" | "stacked_bar" | "pie" | "donut",
      "title": "...", "labels": [...],
      "series": [{"name": "...", "values": [...]}],
      "unit": "$"}  # optional axis/value prefix
   ]}
"""
import io
import json
import math
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

BLOCK = re.compile(r"```chart\s*\n(.*?)```", re.S)
PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#f97316", "#64748b"]
CHART_TYPES = {"bar", "barh", "line", "stacked_bar", "pie", "donut"}

SYSTEM_HINT = """
When the user asks for charts, graphs, plots or a dashboard, include ONE fenced block
tagged `chart` containing JSON (no comments) in this shape, using numbers taken from the data:
```chart
{"title": "Dashboard title",
 "panels": [
  {"type": "kpi", "title": "Total spend", "value": "$1.2M", "note": "vs budget $1.3M"},
  {"type": "bar", "title": "Spend by program", "labels": ["A","B"], "series": [{"name": "Actual", "values": [10, 20]}], "unit": "$"},
  {"type": "pie", "title": "Share by category", "labels": ["A","B"], "series": [{"name": "Share", "values": [60, 40]}]}
 ]}
```
Panel types: kpi, bar, barh, line, stacked_bar, pie, donut. Use 4-8 panels for a dashboard,
put kpi panels first, values must be plain numbers. The chart is rendered and sent as an image;
outside the block, give a short written summary of the key insights.
"""


def extract(text):
    """Return (text_without_blocks, [spec, ...], [error, ...])."""
    specs, errors = [], []
    for raw in BLOCK.findall(text):
        try:
            specs.append(validate(json.loads(raw)))
        except Exception as e:
            errors.append(str(e))
    return BLOCK.sub("", text).strip(), specs, errors


def validate(spec):
    panels = spec.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError("chart spec needs a non-empty 'panels' list")
    for p in panels:
        t = p.get("type")
        if t == "kpi":
            p.setdefault("value", "")
            continue
        if t not in CHART_TYPES:
            raise ValueError(f"unknown panel type {t!r}")
        n = len(p.get("labels", []))
        for s in p.get("series", []):
            s["values"] = [float(v or 0) for v in s["values"]]
            if len(s["values"]) != n:
                raise ValueError(f"panel {p.get('title')!r}: series length != labels length")
        if not p.get("series"):
            raise ValueError(f"panel {p.get('title')!r} has no series")
    return spec


def _fmt(unit):
    def f(v, _=None):
        a = abs(v)
        s = f"{v / 1e6:.1f}M" if a >= 1e6 else f"{v / 1e3:.0f}k" if a >= 1e3 else f"{v:g}"
        return f"{unit}{s}"
    return f


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#cbd5e1")
    ax.spines["bottom"].set_color("#cbd5e1")
    ax.tick_params(colors="#475569", labelsize=8)
    ax.grid(axis="y", color="#e2e8f0", lw=0.8)
    ax.set_axisbelow(True)


def _panel(ax, p):
    t, unit = p["type"], p.get("unit", "")
    labels, series = p.get("labels", []), p.get("series", [])
    ax.set_title(p.get("title", ""), loc="left", fontsize=10, fontweight="bold", color="#0f172a")
    if t in ("pie", "donut"):
        vals = series[0]["values"]
        ax.pie(vals, labels=labels, colors=PALETTE, autopct="%1.0f%%", startangle=90,
               pctdistance=0.78 if t == "donut" else 0.6, textprops={"fontsize": 8},
               wedgeprops={"width": 0.45} if t == "donut" else None)
        ax.axis("equal")
        return
    _style(ax)
    x = range(len(labels))
    if t == "line":
        for i, s in enumerate(series):
            ax.plot(labels, s["values"], marker="o", ms=3, lw=2, color=PALETTE[i % 8], label=s["name"])
    elif t == "barh":
        h = 0.8 / len(series)
        for i, s in enumerate(series):
            ax.barh([y + i * h for y in x], s["values"], h, color=PALETTE[i % 8], label=s["name"])
        ax.set_yticks([y + h * (len(series) - 1) / 2 for y in x], labels)
        ax.invert_yaxis()
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color="#e2e8f0", lw=0.8)
        ax.xaxis.set_major_formatter(FuncFormatter(_fmt(unit)))
    elif t == "stacked_bar":
        bottom = [0.0] * len(labels)
        for i, s in enumerate(series):
            ax.bar(x, s["values"], 0.65, bottom=bottom, color=PALETTE[i % 8], label=s["name"])
            bottom = [a + b for a, b in zip(bottom, s["values"])]
        ax.set_xticks(list(x), labels)
    else:  # bar
        w = 0.8 / len(series)
        for i, s in enumerate(series):
            ax.bar([v + i * w for v in x], s["values"], w, color=PALETTE[i % 8], label=s["name"])
        ax.set_xticks([v + w * (len(series) - 1) / 2 for v in x], labels)
    if t != "barh":
        ax.yaxis.set_major_formatter(FuncFormatter(_fmt(unit)))
        if max((len(str(lb)) for lb in labels), default=0) > 6 or len(labels) > 6:
            plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    if len(series) > 1:
        ax.legend(fontsize=7, frameon=False)


def render(spec):
    """Return PNG bytes for a validated spec."""
    kpis = [p for p in spec["panels"] if p["type"] == "kpi"]
    charts = [p for p in spec["panels"] if p["type"] != "kpi"]
    cols = 2 if len(charts) > 1 else 1
    rows = math.ceil(len(charts) / cols)
    kpi_h = 1.3 if kpis else 0
    fig = plt.figure(figsize=(12, kpi_h + 4 * rows + 0.8), facecolor="white")
    fig.suptitle(spec.get("title", "Dashboard"), x=0.02, ha="left", fontsize=15,
                 fontweight="bold", color="#0f172a")
    outer = fig.add_gridspec(
        2 if kpis else 1, 1, height_ratios=([kpi_h] if kpis else []) + [4 * rows],
        top=1 - 0.8 / (kpi_h + 4 * rows + 0.8), bottom=0.06, left=0.09, right=0.97, hspace=0.25,
    )
    if kpis:
        sub = outer[0].subgridspec(1, len(kpis), wspace=0.08)
        for i, k in enumerate(kpis):
            ax = fig.add_subplot(sub[0, i])
            ax.set_xticks([]), ax.set_yticks([])
            ax.set_facecolor("#f1f5f9")
            for s in ax.spines.values():
                s.set_visible(False)
            ax.text(0.06, 0.72, k.get("title", ""), fontsize=9, color="#475569", transform=ax.transAxes)
            ax.text(0.06, 0.32, str(k["value"]), fontsize=18, fontweight="bold", color="#0f172a",
                    transform=ax.transAxes)
            if k.get("note"):
                ax.text(0.06, 0.08, k["note"], fontsize=8, color="#64748b", transform=ax.transAxes)
    grid = outer[-1].subgridspec(rows, cols, hspace=0.5, wspace=0.35)
    for i, p in enumerate(charts):
        r, c = divmod(i, cols)
        last_odd = cols == 2 and i == len(charts) - 1 and len(charts) % 2
        _panel(fig.add_subplot(grid[r, :] if last_odd else grid[r, c]), p)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    return buf.getvalue()

