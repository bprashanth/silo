#!/usr/bin/env python3
"""Generate the intelligence vs. score vs. smallest hardware cost (INR) chart
for the 2026-11-26 Jetson 8GB quantization & 4B model shootout (435 blind-graded turns).

Usage:
    uv run --with matplotlib --with numpy python3 \
        benchmarks/runs/2026-11-26-jetson-quant-shootout/plot_shootout.py
"""

from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

REPO = Path(__file__).resolve().parents[3]
OUT_PNG = REPO / "narrative" / "images" / "jetson-8gb-model-cost-frontier.png"
OUT_PNG.parent.mkdir(parents=True, exist_ok=True)

# Verified blind-graded shootout results (87 turns/arm x 5 arms = 435 turns, frozen 49cd8e6)
ARMS = [
    {
        "key": "qwen35_4b_q5",
        "label": "Qwen3.5-4B\nQ5_K_M",
        "short": "Qwen3.5-4B (Q5)",
        "params_b": 4.0,
        "disk_gb": 2.93,
        "gpu_gib": 3.39,
        "correct": 24,
        "partial": 22,
        "wrong": 41,
        "wa_ev_pct": 100.0 * 5 / 16,   # 31.25%
        "cli_errors": 28,
        "hw_label": "₹28k* / ₹20k CPU",
        "color": "#c0392b",
    },
    {
        "key": "gemma4_e4b_q5",
        "label": "Gemma-4-E4B\nQ5_K_M",
        "short": "Gemma-4-E4B (Q5)",
        "params_b": 4.5,
        "disk_gb": 5.11,
        "gpu_gib": 3.75,
        "correct": 30,
        "partial": 22,
        "wrong": 35,
        "wa_ev_pct": 100.0 * 6 / 16,   # 37.50%
        "cli_errors": 14,
        "hw_label": "₹28k* / ₹20k CPU",
        "color": "#d97706",
    },
    {
        "key": "qwen35_9b_iq4xs",
        "label": "Qwen3.5-9B\nIQ4_XS (8k)",
        "short": "Qwen3.5-9B (IQ4_XS)",
        "params_b": 9.0,
        "disk_gb": 4.81,
        "gpu_gib": 4.75,
        "correct": 44,
        "partial": 23,
        "wrong": 20,
        "wa_ev_pct": 100.0 * 12 / 16,  # 75.00%
        "cli_errors": 8,
        "hw_label": "₹28k* (Jetson 8GB)",
        "color": "#0d9488",
    },
    {
        "key": "qwen35_9b_q4",
        "label": "Qwen3.5-9B\nQ4_K_M (8k) ★",
        "short": "Qwen3.5-9B (Q4_K_M) ★",
        "params_b": 9.0,
        "disk_gb": 5.29,
        "gpu_gib": 5.23,
        "correct": 41,
        "partial": 26,
        "wrong": 20,
        "wa_ev_pct": 100.0 * 14 / 16,  # 87.50%
        "cli_errors": 5,
        "hw_label": "₹28k* (Jetson 8GB)",
        "color": "#059669",
    },
    {
        "key": "qwen35_9b_q5",
        "label": "Qwen3.5-9B\nQ5_K_M (65k+vis)",
        "short": "Qwen3.5-9B (Q5 DGX)",
        "params_b": 9.0,
        "disk_gb": 6.13,
        "gpu_gib": 8.39,
        "correct": 41,
        "partial": 25,
        "wrong": 21,
        "wa_ev_pct": 100.0 * 14 / 16,  # 87.50%
        "cli_errors": 5,
        "hw_label": "₹60k (Mac mini 16GB)",
        "color": "#2563eb",
    },
]

TOTAL = 87
for a in ARMS:
    a["correct_pct"] = 100.0 * a["correct"] / TOTAL
    a["partial_pct"] = 100.0 * a["partial"] / TOTAL
    a["non_wrong_pct"] = 100.0 * (a["correct"] + a["partial"]) / TOTAL
    a["wrong_pct"] = 100.0 * a["wrong"] / TOTAL

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": "#cbd5e1",
    "axes.linewidth": 0.9,
})

fig = plt.figure(figsize=(16.0, 8.2), dpi=220, facecolor="#ffffff")
gs = fig.add_gridspec(1, 2, width_ratios=[1.20, 1.0], wspace=0.24, left=0.055, right=0.975, top=0.835, bottom=0.205)
ax1 = fig.add_subplot(gs[0, 0])
ax2 = fig.add_subplot(gs[0, 1])

# Overall header
fig.text(
    0.055, 0.945,
    "Silo Model Sizing: Intelligence vs. Blind Score vs. Smallest Hardware Cost (₹)",
    fontsize=16.5, fontweight="bold", color="#0f172a"
)
fig.text(
    0.055, 0.903,
    "435 blind-graded turns (87 cases × 5 arms: WhatsApp, Drive/Sheets, Mail, Calendar, Mixed) · Embeddings & reranker off-box",
    fontsize=10.3, color="#475569"
)

# =============================================================================
# PANEL A: GPU Footprint & Hardware Cost Tiers vs. Blind Score
# =============================================================================
ax1.set_facecolor("#fcfcfd")
ax1.set_xlim(2.6, 9.75)
ax1.set_ylim(18, 102)

# Shaded hardware-cost bands
# Band 1: <= 5.8 GiB GPU -> Headless 8 GB Edge (Jetson Orin Nano Super 8GB)
ax1.axvspan(2.6, 5.85, color="#ecfdf5", alpha=0.85, zorder=0)
# Band 2: 5.85 - 9.75 GiB GPU -> 16 GB Unified / 12 GB dGPU Tier
ax1.axvspan(5.85, 9.75, color="#eff6ff", alpha=0.85, zorder=0)

# Vertical ceiling line for 8 GB headless Jetson
ax1.axvline(5.85, color="#059669", linestyle="--", linewidth=1.4, alpha=0.8, zorder=1)
ax1.text(
    5.78, 21.0,
    "8 GB headless Jetson ceiling\n(~5.8 GiB GPU after JetPack OS)",
    ha="right", va="bottom", fontsize=8.3, color="#047857", fontweight="bold",
    bbox=dict(boxstyle="round,pad=0.25", facecolor="#ffffff", edgecolor="#a7f3d0", alpha=0.92)
)

# Hardware tier headers at top of Panel A
ax1.text(
    4.22, 98.2,
    "8 GB Edge GPU Tier\nJetson Orin Nano Super 8GB\n₹28k–₹30k* ($249) · ₹47k–₹65k India retail",
    ha="center", va="top", fontsize=8.4, fontweight="bold", color="#065f46",
    bbox=dict(boxstyle="round,pad=0.35", facecolor="#d1fae5", edgecolor="#6ee7b7", linewidth=0.9)
)
ax1.text(
    7.82, 98.2,
    "16 GB Unified / 12 GB dGPU Tier\nMac mini M4 16GB (₹59.9k) or RTX 3060 PC\n(Jetson Orin NX 16GB: ₹1.15L+)",
    ha="center", va="top", fontsize=8.4, fontweight="bold", color="#1e40af",
    bbox=dict(boxstyle="round,pad=0.35", facecolor="#dbeafe", edgecolor="#93c5fd", linewidth=0.9)
)

# Subtle horizontal grid
ax1.grid(axis="y", linestyle=":", color="#cbd5e1", linewidth=0.8, zorder=1)

xs = [a["gpu_gib"] for a in ARMS]
ys_nw = [a["non_wrong_pct"] for a in ARMS]
ys_wa = [a["wa_ev_pct"] for a in ARMS]
sizes = [125 if a["params_b"] < 6 else 260 for a in ARMS]

# Lines showing the cliff & plateau
ax1.plot(xs, ys_nw, color="#0f172a", linewidth=2.4, zorder=3, label="All-87 Non-Wrong % (bubble size = 4B vs 9B)")
ax1.plot(xs, ys_wa, color="#6366f1", linewidth=1.8, linestyle="--", zorder=3, label="WhatsApp Evidence Recall % (blind-v3, n=16)")

# Scatter points
for a, sz in zip(ARMS, sizes):
    edge = "#0f172a" if a["key"] != "qwen35_9b_q4" else "#022c22"
    lw = 2.4 if a["key"] == "qwen35_9b_q4" else 1.5
    ax1.scatter(a["gpu_gib"], a["non_wrong_pct"], s=sz, color=a["color"], edgecolor=edge, linewidth=lw, zorder=5)
    ax1.scatter(a["gpu_gib"], a["wa_ev_pct"], s=56, marker="D", color="#ffffff", edgecolor="#4f46e5", linewidth=1.7, zorder=4)

# Careful non-overlapping point annotations
annotations = [
    ("qwen35_4b_q5", (3.39, 52.9), (3.15, 64.0), "Qwen3.5-4B Q5\n53% non-wrong\n28 CLI errors", "center"),
    ("gemma4_e4b_q5", (3.75, 59.8), (3.72, 80.5), "Gemma-4-E4B Q5\n60% non-wrong\n14 CLI errors", "center"),
    ("qwen35_9b_iq4xs", (4.75, 77.0), (5.05, 50.0), "9B IQ4_XS (4.75 GiB)\n77% non-wrong · 44/87 strict\nWA ev: 75% (12/16)", "center"),
    ("qwen35_9b_q4", (5.23, 77.0), (6.08, 67.5), "★ 9B Q4_K_M (5.23 GiB)\n77% non-wrong · 5 errors\nWA ev: 87.5% (14/16)", "left"),
    ("qwen35_9b_q5", (8.39, 75.9), (8.40, 53.5), "9B Q5_K_M DGX (8.39 GiB)\n76% non-wrong · 65k + vision\nNo accuracy gain over Q4", "center"),
]

for key, xy, xytext, text, ha in annotations:
    is_rec = key == "qwen35_9b_q4"
    fc = "#ecfdf5" if is_rec else "#ffffff"
    ec = "#059669" if is_rec else "#cbd5e1"
    lw = 1.4 if is_rec else 0.9
    ax1.annotate(
        text,
        xy=xy, xytext=xytext,
        ha=ha, va="center", fontsize=8.0,
        fontweight="bold" if is_rec else "normal",
        color="#064e3b" if is_rec else "#1e293b",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=fc, edgecolor=ec, linewidth=lw, alpha=0.96),
        arrowprops=dict(arrowstyle="->", color=ec if is_rec else "#64748b", lw=1.1, shrinkA=4, shrinkB=7),
        zorder=6,
    )

# Label the WA evidence recall cliff explicitly
ax1.annotate(
    "4B CLIFF\n−50 pts WA recall\n(87.5% → 37.5%)",
    xy=(4.15, 52.0), xytext=(3.30, 41.5),
    ha="center", va="center", fontsize=8.1, fontweight="bold", color="#991b1b",
    bbox=dict(boxstyle="round,pad=0.32", facecolor="#fef2f2", edgecolor="#fca5a5", linewidth=1.1),
    arrowprops=dict(arrowstyle="->", color="#dc2626", lw=1.3),
    zorder=6,
)

# Off-chart reference note for 30B / BF16 tier
ax1.text(
    9.62, 21.0,
    "Off-chart DGX models (stopped):\n• 9B-BF16: 18.0 GiB (₹1.5L+)\n• Muse-30B: 25.2 GiB (₹1.9L–₹6.9L)",
    ha="right", va="bottom", fontsize=7.8, color="#475569",
    bbox=dict(boxstyle="round,pad=0.3", facecolor="#f8fafc", edgecolor="#cbd5e1", alpha=0.95),
    zorder=5,
)

ax1.set_title("A. Accuracy vs. GPU Footprint & Hardware Cost Band", fontsize=11.5, fontweight="bold", color="#0f172a", pad=10, loc="left")
ax1.set_xlabel("Measured GPU Memory Footprint (GiB, nvidia-smi)", fontsize=10, fontweight="bold", color="#334155", labelpad=8)
ax1.set_ylabel("Blind-Graded Score (%)", fontsize=10, fontweight="bold", color="#334155")
ax1.legend(loc="upper left", bbox_to_anchor=(0.0, -0.135), ncol=2, frameon=False, fontsize=8.3)
ax1.spines["top"].set_visible(False)
ax1.spines["right"].set_visible(False)

# =============================================================================
# PANEL B: Stacked Verdict Breakdown + Reliability & Min Hardware Cost
# =============================================================================
ax2.set_facecolor("#ffffff")

# Order top-to-bottom from largest to smallest so dropoff reads downward
ordered = list(reversed(ARMS))
y_pos = np.arange(len(ordered))
bar_h = 0.56

c_vals = [a["correct_pct"] for a in ordered]
p_vals = [a["partial_pct"] for a in ordered]
w_vals = [a["wrong_pct"] for a in ordered]

bars_c = ax2.barh(y_pos, c_vals, height=bar_h, color="#10b981", edgecolor="#ffffff", linewidth=0.8, label="Strict Correct")
bars_p = ax2.barh(y_pos, p_vals, left=c_vals, height=bar_h, color="#fbbf24", edgecolor="#ffffff", linewidth=0.8, label="Partial (--no-yes / incomplete)")
bars_w = ax2.barh(y_pos, w_vals, left=np.array(c_vals) + np.array(p_vals), height=bar_h, color="#f87171", alpha=0.88, edgecolor="#ffffff", linewidth=0.8, label="Wrong / Miss")

# Highlight the recommended row (Qwen3.5-9B Q4_K_M at index 1)
ax2.axhspan(1 - 0.42, 1 + 0.42, color="#ecfdf5", zorder=0)

# Inside-bar count labels
for i, a in enumerate(ordered):
    ax2.text(a["correct_pct"] / 2, i, f'{a["correct"]}', ha="center", va="center", fontsize=8.8, fontweight="bold", color="#ffffff")
    ax2.text(a["correct_pct"] + a["partial_pct"] / 2, i, f'{a["partial"]}', ha="center", va="center", fontsize=8.5, fontweight="bold", color="#78350f")
    ax2.text(a["correct_pct"] + a["partial_pct"] + a["wrong_pct"] / 2, i, f'{a["wrong"]}', ha="center", va="center", fontsize=8.8, fontweight="bold", color="#ffffff")

# Right-hand aligned telemetry columns
col_x_err = 104
col_x_hw = 123
ax2.text(col_x_err, -0.68, "CLI\nErrors", ha="center", va="bottom", fontsize=8.3, fontweight="bold", color="#334155")
ax2.text(col_x_hw, -0.68, "Smallest Fast\nHardware (₹)", ha="left", va="bottom", fontsize=8.3, fontweight="bold", color="#334155")

for i, a in enumerate(ordered):
    err_color = "#dc2626" if a["cli_errors"] >= 14 else ("#d97706" if a["cli_errors"] >= 8 else "#047857")
    ax2.text(col_x_err, i, f'{a["cli_errors"]}', ha="center", va="center", fontsize=9.2, fontweight="bold", color=err_color)
    hw_weight = "bold" if a["key"] == "qwen35_9b_q4" else "normal"
    hw_col = "#047857" if a["key"] in ("qwen35_9b_q4", "qwen35_9b_iq4xs") else "#334155"
    ax2.text(col_x_hw, i, a["hw_label"], ha="left", va="center", fontsize=8.4, fontweight=hw_weight, color=hw_col)

# Horizontal divider separating 9B plateau from 4B dropoff
ax2.axhline(2.5, color="#dc2626", linestyle=":", linewidth=1.3, alpha=0.8)
ax2.text(50, 2.5, "  ▼  9B → 4B cliff: errors jump 3–6×, wrong turns double  ▼  ", ha="center", va="center",
         fontsize=7.9, fontweight="bold", color="#991b1b",
         bbox=dict(boxstyle="round,pad=0.22", facecolor="#fef2f2", edgecolor="#fca5a5", linewidth=0.8))

ax2.set_yticks(y_pos)
ax2.set_yticklabels([a["label"] for a in ordered], fontsize=8.8, fontweight="bold", color="#1e293b")
ax2.invert_yaxis()
ax2.set_xlim(0, 178)
ax2.set_xticks([0, 25, 50, 75, 100])
ax2.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=8.5)
ax2.set_ylim(len(ordered) - 0.35, -1.05)
ax2.set_title("B. Verdict Split (n=87), CLI Errors & Hardware Floor", fontsize=11.5, fontweight="bold", color="#0f172a", pad=10, loc="left")
ax2.set_xlabel("Share of All 87 Blind-Graded Turns (counts inside bars)", fontsize=10, fontweight="bold", color="#334155", labelpad=8)
ax2.legend(loc="upper left", bbox_to_anchor=(0.0, -0.135), ncol=3, frameon=False, fontsize=8.3)
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)

# Footnote (wrapped cleanly onto two lines well below both legends)
fig.text(
    0.055, 0.022,
    "*Pricing note (India, Nov 2026): Jetson Orin Nano Super 8GB is $249 MSRP (~₹28k–₹30k landed/direct; ₹47k–₹65k via Indian resellers like Robu). "
    "Mac mini M4 16GB is ₹59,900 official Apple India MRP (cheapest retail 16 GB unified-memory box).\n"
    " 4B models can also run slowly on CPU-only Raspberry Pi 5 8GB kits (~₹20k), but collapse on Silo accuracy. "
    "Google banks ran with --no-yes across all 5 arms uniformly, so confirmation cards count as Partial across every arm.",
    fontsize=7.9, color="#64748b", linespacing=1.4
)

fig.savefig(OUT_PNG, dpi=220)
print(f"Wrote {OUT_PNG} ({OUT_PNG.stat().st_size:,} bytes)")
