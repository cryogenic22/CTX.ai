"""Generate publication-quality figures for the CtxPack whitepaper.

Figures:
  1. Controlled scaling: fidelity vs corpus size (3 models × 3 methods)
  2. BPE token landscape: word count vs BPE tokens per method
  3. Baseline comparison: grouped bar chart (fidelity across methods)
  4. Architecture diagram: packer pipeline (text-based)

Usage: python paper/generate_figures.py
"""

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
FIG_DIR = os.path.join(SCRIPT_DIR, "figures")

# Consistent colour palette (colour-blind friendly)
COLORS = {
    "ctxpack": "#2563EB",       # blue
    "ctxpack_bpe": "#60A5FA",   # light blue
    "raw": "#DC2626",           # red
    "minified": "#F59E0B",      # amber
    "llm_summary": "#8B5CF6",   # purple
    "structured": "#10B981",    # emerald
    "sonnet": "#2563EB",
    "gpt4o": "#DC2626",
    "gemini": "#10B981",
}

STYLE = {
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "axes.spines.top": False,
    "axes.spines.right": False,
}
plt.rcParams.update(STYLE)


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────
# Figure 1: Controlled Scaling — Fidelity vs Corpus Size
# ─────────────────────────────────────────────────────────────
def fig_controlled_scaling():
    """3-panel figure: Sonnet 4.5, GPT-4o, Gemini 2.5 Pro."""
    results_dir = os.path.join(PROJECT_DIR, "ctxpack", "benchmarks", "scaling", "results")

    models = [
        ("claude-sonnet-4-5-20250929", "Sonnet 4.5", "controlled_scaling-claude-sonnet-4-5-20250929.json"),
        ("gpt-4o", "GPT-4o", "controlled_scaling-gpt4o-gpt-4o.json"),
        ("gemini-2.5-pro", "Gemini 2.5 Pro", "controlled_scaling-gemini-gemini-2.5-pro.json"),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True)

    for ax, (model_id, label, filename) in zip(axes, models):
        path = os.path.join(results_dir, filename)
        if not os.path.exists(path):
            ax.set_title(f"{label}\n(data not found)")
            continue

        data = load_json(path)
        scales = data["scales"]

        x_labels = []
        ctx_fid = []
        raw_fid = []
        min_fid = []

        for s in scales:
            name = s["name"]
            if name == "golden_set":
                x_labels.append("690")
            elif name == "scale_1000":
                x_labels.append("1.8K")
            elif name == "scale_5000":
                x_labels.append("4.7K")
            elif name == "scale_20000":
                x_labels.append("15.9K")
            else:
                x_labels.append(name)

            ctx_fid.append(s["methods"]["ctxpack_l2"]["fidelity"] * 100)
            raw_fid.append(s["methods"]["raw_stuffing"]["fidelity"] * 100)
            min_fid.append(s["methods"]["minified"]["fidelity"] * 100)

        x = np.arange(len(x_labels))
        ax.plot(x, ctx_fid, "o-", color=COLORS["ctxpack"], linewidth=2, markersize=7, label="CtxPack L2", zorder=3)
        ax.plot(x, raw_fid, "s--", color=COLORS["raw"], linewidth=1.5, markersize=6, label="Raw stuffing", zorder=2)
        ax.plot(x, min_fid, "^:", color=COLORS["minified"], linewidth=1.5, markersize=6, label="Minified", zorder=2)

        ax.set_title(label, fontweight="bold")
        ax.set_xlabel("Source tokens")
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels)
        ax.set_ylim(0, 105)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter())

        # Highlight GPT-4o crossover
        if "gpt" in model_id.lower():
            for xi, (c, r) in enumerate(zip(ctx_fid, raw_fid)):
                if r > c:
                    ax.annotate("raw > ctx", xy=(xi, r), xytext=(xi + 0.3, r + 5),
                                fontsize=7, color=COLORS["raw"], fontstyle="italic",
                                arrowprops=dict(arrowstyle="->", color=COLORS["raw"], lw=0.8))
                    break

    axes[0].set_ylabel("Rule-based fidelity")
    axes[0].legend(loc="lower left", framealpha=0.9)

    fig.suptitle("Figure 1. Controlled Cross-Scale Evaluation (same 25 questions at every scale)",
                 fontsize=11, y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, "fig1_controlled_scaling.png"), dpi=300)
    plt.savefig(os.path.join(FIG_DIR, "fig1_controlled_scaling.pdf"))
    plt.close()
    print("  fig1_controlled_scaling.png/pdf")


# ─────────────────────────────────────────────────────────────
# Figure 2: BPE Token Landscape
# ─────────────────────────────────────────────────────────────
def fig_bpe_landscape():
    """Grouped bar chart: word count vs BPE tokens per method."""
    bpe_path = os.path.join(PROJECT_DIR, "ctxpack", "benchmarks", "results", "bpe_cost_comparison.json")
    data = load_json(bpe_path)

    methods_order = ["ctxpack_default", "ctxpack_bpe_optimized", "minified", "raw_stuffing"]
    labels = ["CtxPack\n(default)", "CtxPack\n(BPE-opt)", "Minified", "Raw\nstuffing"]
    colors_bar = [COLORS["ctxpack"], COLORS["ctxpack_bpe"], COLORS["minified"], COLORS["raw"]]

    word_counts = []
    bpe_counts = []
    for m in methods_order:
        md = data["methods"][m]
        word_counts.append(md["word_count"])
        bpe_counts.append(md["bpe_tokens"]["cl100k_base"])

    fig, ax = plt.subplots(figsize=(8, 5))

    x = np.arange(len(labels))
    w = 0.35

    bars1 = ax.bar(x - w / 2, word_counts, w, label="Word count", color=[c + "80" for c in colors_bar],
                   edgecolor=colors_bar, linewidth=1.5)
    bars2 = ax.bar(x + w / 2, bpe_counts, w, label="BPE tokens (cl100k)", color=colors_bar,
                   edgecolor=[c for c in colors_bar], linewidth=1.5)

    # Value labels
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 20,
                f"{int(bar.get_height())}", ha="center", va="bottom", fontsize=8, color="#666")
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 20,
                f"{int(bar.get_height())}", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax.set_ylabel("Token count")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(loc="upper left")
    ax.set_title("Figure 2. Word Count vs BPE Tokens — Golden Set", fontweight="bold")

    # Annotation: "10x gap"
    ax.annotate("~10x gap", xy=(0 - w / 2, 139), xytext=(0.5, 600),
                fontsize=9, fontstyle="italic", color="#666",
                arrowprops=dict(arrowstyle="->", color="#999", lw=0.8))

    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, "fig2_bpe_landscape.png"), dpi=300)
    plt.savefig(os.path.join(FIG_DIR, "fig2_bpe_landscape.pdf"))
    plt.close()
    print("  fig2_bpe_landscape.png/pdf")


# ─────────────────────────────────────────────────────────────
# Figure 3: Baseline Comparison (fidelity bar chart)
# ─────────────────────────────────────────────────────────────
def fig_baseline_comparison():
    """Grouped bar: fidelity across all baselines on Sonnet 4.5."""
    # Hardcoded from paper results — these are the definitive numbers
    methods = ["CtxPack L2", "Structured\nprompt", "LLM\nsummary", "Minified", "Raw\nstuffing"]
    rule_fid = [100, 84, 80, 96, 96]
    judge_fid = [100, 96, None, 100, 100]  # LLM summary judge not available

    colors_bar = [COLORS["ctxpack"], COLORS["structured"], COLORS["llm_summary"],
                  COLORS["minified"], COLORS["raw"]]

    fig, ax = plt.subplots(figsize=(9, 5))

    x = np.arange(len(methods))
    w = 0.35

    bars1 = ax.bar(x - w / 2, rule_fid, w, label="Rule-based", color=colors_bar, edgecolor="white", linewidth=1)

    # Judge bars — handle None
    judge_vals = [v if v is not None else 0 for v in judge_fid]
    judge_colors = [c if v is not None else "#FFFFFF00" for c, v in zip(colors_bar, judge_fid)]
    bars2 = ax.bar(x + w / 2, judge_vals, w, label="LLM-judge", color=judge_colors,
                   edgecolor=colors_bar, linewidth=1.5, alpha=0.5)

    # Value labels
    for bar, val in zip(bars1, rule_fid):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{val}%", ha="center", va="bottom", fontsize=9, fontweight="bold")
    for bar, val in zip(bars2, judge_fid):
        if val is not None:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"{val}%", ha="center", va="bottom", fontsize=8, color="#666")

    # Token count annotations below bars
    tokens = ["139 words\n1,368 BPE", "41 words\n565 BPE", "~139 words", "431 words\n1,273 BPE", "720 words\n1,430 BPE"]
    for xi, tok in enumerate(tokens):
        ax.text(xi, -8, tok, ha="center", va="top", fontsize=7, color="#888")

    ax.set_ylabel("Fidelity (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(methods)
    ax.set_ylim(0, 115)
    ax.legend(loc="upper right")
    ax.set_title("Figure 3. Baseline Comparison — Golden Set, Sonnet 4.5", fontweight="bold")

    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, "fig3_baseline_comparison.png"), dpi=300)
    plt.savefig(os.path.join(FIG_DIR, "fig3_baseline_comparison.pdf"))
    plt.close()
    print("  fig3_baseline_comparison.png/pdf")


# ─────────────────────────────────────────────────────────────
# Figure 4: Packer Pipeline Architecture
# ─────────────────────────────────────────────────────────────
def fig_architecture():
    """Clean pipeline diagram showing packer stages."""
    fig, ax = plt.subplots(figsize=(12, 3.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 3.5)
    ax.axis("off")

    # Pipeline stages
    stages = [
        ("YAML\nMarkdown\nJSON", 0.5, "#E8EEF4", "Source\nCorpus"),
        ("Entity\nExtraction", 2.5, "#DBEAFE", "Parse &\nClassify"),
        ("Entity\nResolution", 4.5, "#BFDBFE", "Dedup &\nMerge"),
        ("Conflict\nDetection", 6.5, "#93C5FD", "Multi-source\nValidation"),
        ("Salience\nScoring", 8.5, "#60A5FA", "Heuristic\nRanking"),
        (".ctx L2\nOutput", 10.5, "#2563EB", "Serialise"),
    ]

    box_w = 1.6
    box_h = 1.8
    y_center = 1.8

    for i, (label, x, color, subtitle) in enumerate(stages):
        # Box
        rect = plt.Rectangle((x - box_w / 2, y_center - box_h / 2), box_w, box_h,
                              facecolor=color, edgecolor="#1E40AF", linewidth=1.5,
                              joinstyle="round", zorder=2)
        ax.add_patch(rect)

        # Text colour — white for dark boxes
        text_color = "white" if i >= 4 else "#1A1A2E"

        ax.text(x, y_center + 0.15, label, ha="center", va="center",
                fontsize=8.5, fontweight="bold", color=text_color, zorder=3)
        ax.text(x, y_center - box_h / 2 - 0.2, subtitle, ha="center", va="top",
                fontsize=7, color="#666", fontstyle="italic")

        # Arrow
        if i < len(stages) - 1:
            ax.annotate("", xy=(stages[i + 1][1] - box_w / 2 - 0.05, y_center),
                        xytext=(x + box_w / 2 + 0.05, y_center),
                        arrowprops=dict(arrowstyle="-|>", color="#1E40AF", lw=2))

    # Compression ratio annotation
    ax.annotate("5–93x\ncompression", xy=(10.5, y_center + box_h / 2 + 0.1),
                fontsize=8, ha="center", va="bottom", color=COLORS["ctxpack"],
                fontweight="bold")

    ax.set_title("Figure 4. CtxPack Packer Pipeline", fontsize=12, fontweight="bold", pad=20)

    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, "fig4_architecture.png"), dpi=300)
    plt.savefig(os.path.join(FIG_DIR, "fig4_architecture.pdf"))
    plt.close()
    print("  fig4_architecture.png/pdf")


# ─────────────────────────────────────────────────────────────
# Figure 5: Cost-Fidelity Trade-off (BPE-corrected)
# ─────────────────────────────────────────────────────────────
def fig_cost_fidelity():
    """Scatter plot: BPE cost vs fidelity for all methods on Sonnet 4.5."""
    # Data points: (BPE cost $, rule fidelity %, label)
    points = [
        (0.0036, 100, "CtxPack L2", COLORS["ctxpack"], "o", 10),
        (0.0036, 100, "CtxPack BPE-opt", COLORS["ctxpack_bpe"], "D", 9),
        (0.0045, 96, "Raw stuffing", COLORS["raw"], "s", 9),
        (0.0044, 96, "Minified", COLORS["minified"], "^", 9),
        (0.0017, 84, "Structured prompt", COLORS["structured"], "P", 9),  # 565 BPE * $3/M
        (0.0036, 80, "LLM summary", COLORS["llm_summary"], "X", 9),
    ]

    fig, ax = plt.subplots(figsize=(8, 5.5))

    for cost, fid, label, color, marker, size in points:
        ax.scatter(cost * 1000, fid, c=color, marker=marker, s=size * 15, zorder=3,
                   edgecolors="white", linewidths=0.5)
        # Offset labels to avoid overlap
        x_off = 0.15
        y_off = -3 if fid > 85 else 3
        if "Struct" in label:
            x_off = 0.15
            y_off = 3
        if "Raw" in label:
            x_off = 0.15
            y_off = -3
        if "Min" in label:
            x_off = -0.8
            y_off = -3
        ax.annotate(label, (cost * 1000, fid), xytext=(cost * 1000 + x_off, fid + y_off),
                    fontsize=8, color=color, fontweight="bold")

    ax.set_xlabel("Cost per query ($ × 10⁻³, BPE-corrected, Sonnet 4.5)")
    ax.set_ylabel("Rule-based fidelity (%)")
    ax.set_ylim(70, 105)
    ax.set_title("Figure 5. Cost-Fidelity Trade-off — Golden Set (BPE-corrected)", fontweight="bold")

    # Ideal corner annotation
    ax.annotate("← Ideal\n(low cost,\nhigh fidelity)", xy=(1.5, 102), fontsize=8,
                color="#999", fontstyle="italic")

    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, "fig5_cost_fidelity.png"), dpi=300)
    plt.savefig(os.path.join(FIG_DIR, "fig5_cost_fidelity.pdf"))
    plt.close()
    print("  fig5_cost_fidelity.png/pdf")


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    print("Generating figures...")
    fig_controlled_scaling()
    fig_bpe_landscape()
    fig_baseline_comparison()
    fig_architecture()
    fig_cost_fidelity()
    print(f"\nAll figures saved to: {FIG_DIR}/")


if __name__ == "__main__":
    main()
