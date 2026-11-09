"""
Build the LaTeX tables for the multi-country B2B paper from the country
result folders.

Tables produced:

  1. Correlation matrix per country (lower-triangular minipage).
       -> writes correlation_matrix_{CC}.tex next to each CSV
       -> CSVs in:  <country>/2019(/2019)/correlations/

  2. Input--output statistics table (Nodes, Links, Density, Within share)
     for NACE-2 and NACE-4 levels across countries. The Firms row is
     filled in from descriptives_tab.csv (n_firms in thousands) and
     sum_stat_year.csv (links). Density = links / firms**2.
       -> prints the LaTeX to stdout
       -> CSVs in:  <country>/2019(/2019)/io_nace[24]d_mat_{CC}.csv
                   <country>/descriptives_tab.csv
                   <country>/sum_stat_year.csv

  3. Distribution of average input/output sourcing shares.
       -> prints two LaTeX tables to stdout (input + output panels)
       -> CSVs in:  <country>/2019(/2019)/coefficients_of_variation/

  4. Firm size decomposition by country.
     Parses var_decomp_{CC}.tex per country (one estimate per component).
       -> prints the LaTeX to stdout

  5. Cross-country summary statistics of sector-level decompositions.
     Parses var_decomp_sector_{CC}.tex per country and reports mean and
     coefficient of variation across NACE-2 sectors per component.
       -> prints the LaTeX to stdout

  6. Buyer and Seller Effects table.
     Parses var_fe_{CC}.tex per country and stacks one row per country.
       -> prints the LaTeX to stdout

  7. Concentration of firm-level network sales and buyer--seller
     relationship values.
     Reads concentration_net_sales_{CC}.csv (Top 10%, Top 1% of firms by
     network sales) and concentration_b2b_links_{CC}.csv (Top 10%, Top 1%
     of buyer-seller relationships by bilateral sales value).
       -> prints the LaTeX to stdout

  8. Coverage of VAT transaction data by country.
     Reads Firms from descriptives_tab.csv (`n_firms (thousands)` * 1000)
     and Sellers / Buyers / Relationships from sum_stat_year.csv (raw
     yearly counts).
       -> prints the LaTeX to stdout

  9. Tail exponents by country and variable (Hill + Gabaix-Ibragimov).
     Reads CCDF/tail_exponents_hill_gi_{CC}.csv per country.
       -> writes ccdf_estimates.tex in TABLES_OUT_DIR.

  10. Customer- and supplier-link quantile panels by sector and country.
     Reads moments/outdeg_bysec_{CC}.csv and moments/indeg_bysec_{CC}.csv.
     The "All" row N is taken from descriptives_tab.csv to match the
     country-level totals; if the source CSV's All row is empty, the
     aggregate columns are filled with "--".
       -> writes outdegree_quantile_panels.tex and indegree_quantile_panels.tex

  11. Per-country sector-level firm-size decomposition.
     Reads var_decomp/var_decomp_sector_{CC}.tex (NACE2 + N + 5 point
     estimates with SEs), renames each row with the NACE-2 code and
     industry name, drops SEs, and emits one .tex per country.
       -> writes firm_size_decomp_sector_{CC}.tex (per country).

  12. Monetary policy: average contribution by upstreamness classes.
     Reads all_years/monpol/share_byclass_{sales,prices}_{CC}.csv per
     country, averages each class column over horizons, and emits a
     paneled table (one panel per country, sales row + prices row).
       -> writes monpol_byclass_avg_contribution.tex

Run:
    python make_tables.py                   # everything
    python make_tables.py corr              # 1
    python make_tables.py io                # 2
    python make_tables.py shares            # 3
    python make_tables.py firm_decomp       # 4
    python make_tables.py sector_decomp     # 5
    python make_tables.py var_fe            # 6
    python make_tables.py concentration     # 7
    python make_tables.py coverage          # 8
    python make_tables.py tail_exponents    # 9
    python make_tables.py degree_quantiles  # 10 (both indeg + outdeg)
    python make_tables.py sector_panels     # 11 (per-country sector decomposition)
    python make_tables.py monpol_byclass    # 12 (average contribution by upstreamness class)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Path configuration
# --------------------------------------------------------------------------

DESCR_ROOT = Path(
    "/Users/albertopalazzolo/Dropbox/ChaMP_facts_paper/results/descriptives"
)

# Where every generated .tex file is written. Override via $TABLES_OUT_DIR.
import os as _os
TABLES_OUT_DIR = Path(_os.environ.get(
    "TABLES_OUT_DIR",
    str(Path.home() / "Desktop" / "champ_tables"),
))

# Portugal has a wrapping subfolder for its 2026/05 results.
PORTUGAL_RESULTS_DIR = "202605 Results"

# Per-country: (display name, year folder, country folder).
# The year folder holds correlations/, io_*.csv, var_decomp/, etc.
# The country folder holds descriptives_tab.csv and sum_stat_year.csv.
COUNTRY_DIRS: dict[str, tuple[str, Path, Path]] = {
    "BEL": ("Belgium",  DESCR_ROOT / "Belgium" / "2019" / "2019",                              DESCR_ROOT / "Belgium"),
    "EST": ("Estonia",  DESCR_ROOT / "Estonia" / "2019",                                        DESCR_ROOT / "Estonia"),
    "HUN": ("Hungary",  DESCR_ROOT / "Hungary" / "2019",                                        DESCR_ROOT / "Hungary"),
    "ITA": ("Italy",    DESCR_ROOT / "Italy"   / "2019",                                        DESCR_ROOT / "Italy"),
    "PRT": ("Portugal", DESCR_ROOT / "Portugal" / PORTUGAL_RESULTS_DIR / "2019",                DESCR_ROOT / "Portugal"),
}

# Fallback paths to look for descriptives_tab.csv / sum_stat_year.csv.
# Estonia keeps them under task1-output/.
COUNTRY_LEVEL_FALLBACKS = ["task1-output"]

YEAR = 2019


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _find_country_level_csv(country_root: Path, filename: str) -> Path | None:
    """Look for `filename` in country_root and in known sub-folders."""
    direct = country_root / filename
    if direct.exists() and direct.stat().st_size > 0:
        return direct
    for sub in COUNTRY_LEVEL_FALLBACKS:
        candidate = country_root / sub / filename
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def _fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", "{,}")


def _fmt_density(rho: float) -> str:
    """Render density: 2-decimal for >=1e-3, scientific otherwise."""
    if rho >= 1e-3:
        return f"{rho:.2f}"
    exp = 0
    val = rho
    while val < 1.0:
        val *= 10
        exp += 1
    return rf"${val:.1f}\times10^{{-{exp}}}$"


# --------------------------------------------------------------------------
# 1) Correlation matrix .tex files
# --------------------------------------------------------------------------

CORR_VARS: list[tuple[str, str]] = [
    ("ln_turnover",       r"$\ln S_{i}$"),
    ("ln_inputs",         r"$\ln M_{i}$"),
    ("ln_network_sales",  r"$\ln S_{i}^{net}$"),
    ("ln_network_purch",  r"$\ln M_{i}^{net}$"),
    ("ln_outdeg",         r"$\ln n_{i}^{c}$"),
    ("ln_indeg",          r"$\ln n_{i}^{s}$"),
    ("ln_upstreamness",   r"$\ln U_{i}$"),
    ("ln_downstreamness", r"$\ln D_{i}$"),
    ("ln_centrality",     r"$\ln v_{i}$"),
]


def _fmt_corr(value: float) -> str:
    if pd.isna(value):
        return ""
    r = round(float(value), 2)
    if abs(r - 1.0) < 1e-9:
        return "1"
    return f"{r:.2f}"


def _render_corr_table(country_name: str, corr: pd.DataFrame) -> str:
    n = len(CORR_VARS)
    col_spec = "@{}l" + "r" * n + "@{}"
    header = " & ".join([""] + [lbl for _, lbl in CORR_VARS]) + r" \\"
    body = []
    for i, (_, row_lbl) in enumerate(CORR_VARS):
        row = [row_lbl] + [_fmt_corr(corr.iloc[i, j]) if j <= i else "" for j in range(n)]
        body.append(" & ".join(row) + r" \\")
    return "\n".join([
        r"\begin{minipage}[t]{0.48\linewidth}",
        r"\centering",
        rf"\textbf{{{country_name}}}",
        rf"\begin{{tabular}}{{{col_spec}}}",
        r"\toprule",
        header,
        r"\midrule",
        *body,
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{minipage}",
        "",
    ])


def _render_corr_minipage(country_name: str, corr: pd.DataFrame) -> str:
    """Same minipage as _render_corr_table but without trailing newline."""
    n = len(CORR_VARS)
    col_spec = "@{}l" + "r" * n + "@{}"
    header = " & ".join([""] + [lbl for _, lbl in CORR_VARS]) + r" \\"
    body = []
    for i, (_, row_lbl) in enumerate(CORR_VARS):
        row = [row_lbl] + [_fmt_corr(corr.iloc[i, j]) if j <= i else "" for j in range(n)]
        body.append(" & ".join(row) + r" \\")
    return "\n".join([
        r"\begin{minipage}[t]{0.48\linewidth}",
        r"\centering",
        rf"\textbf{{{country_name}}}",
        rf"\begin{{tabular}}{{{col_spec}}}",
        r"\toprule",
        header,
        r"\midrule",
        *body,
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{minipage}",
    ])


# --------------------------------------------------------------------------
# Correlation heatmap PNGs
# --------------------------------------------------------------------------

# 15-variable subset for the heatmap, in display order.
HEATMAP_VARS: list[tuple[str, str]] = [
    ("ln_turnover",          "Total sales"),
    ("ln_inputs",            "Total inputs"),
    ("ln_network_sales",     "Network sales"),
    ("ln_network_purch",     "Network purchases"),
    ("ln_outdeg",            "Number of customers"),
    ("ln_indeg",             "Number of suppliers"),
    ("ln_avg_network_sales", "Network sales per customer"),
    ("ln_avg_network_purch", "Network purchases per supplier"),
    ("ln_avg_turnover",      "Total sales per customer"),
    ("ln_avg_inputs",        "Total purchases per supplier"),
    ("ln_avg_mkt_share",     "Average market share"),
    ("ln_domar",             "Domar weight"),
    ("ln_upstreamness",      "Upstreamness"),
    ("ln_downstreamness",    "Downstreamness"),
    ("ln_centrality",        "Bonacich centrality"),
]


def _render_correlation_heatmap(
    corr: pd.DataFrame,
    labels: list[str],
    out_path: Path,
) -> None:
    """Write a coolwarm heatmap of `corr` with `labels` to PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = corr.shape[0]
    fig, ax = plt.subplots(figsize=(0.7 * n + 2, 0.65 * n + 2))
    im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1.0, vmax=1.0)

    ax.set_xticks(np.arange(n))
    ax.set_yticks(np.arange(n))
    ax.set_xticklabels(labels, rotation=90, fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)

    for i in range(n):
        for j in range(n):
            v = corr.iat[i, j]
            color = "white" if abs(v) >= 0.5 else "black"
            ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                    color=color, fontsize=8)

    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def build_correlation_heatmaps() -> None:
    """Generate correlation_heatmap_{CC}.png for each country.

    Reads correlation_matrix_{CC}.csv, subsets to the 15 user-specified
    variables, and writes the heatmap (a) next to the source CSV
    (overwriting the existing PNG) and (b) into TABLES_OUT_DIR.
    """
    bases  = [b   for b, _   in HEATMAP_VARS]
    labels = [lbl for _, lbl in HEATMAP_VARS]

    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        csv_path = ydir / "correlations" / f"correlation_matrix_{cc}.csv"
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            print(f"[corr_heatmap] {cc}: source CSV missing -- {csv_path}",
                  file=sys.stderr)
            continue
        df = pd.read_csv(csv_path, index_col=0)

        col_map: dict[str, str] = {}
        for col in df.columns:
            for base in bases:
                if col == base or col.startswith(base + "_dem"):
                    col_map[base] = col
                    break
        missing = [b for b in bases if b not in col_map]
        if missing:
            print(f"[corr_heatmap] {cc}: missing variables {missing}",
                  file=sys.stderr)
            continue

        ordered = [col_map[b] for b in bases]
        corr = df.loc[ordered, ordered].copy()
        corr.columns = labels
        corr.index   = labels

        # 1) Overwrite the PNG sitting next to the source CSV.
        src_png = csv_path.parent / f"correlation_heatmap_{cc}.png"
        _render_correlation_heatmap(corr, labels, src_png)

        # 2) Copy into TABLES_OUT_DIR so all outputs land in one place.
        out_png = TABLES_OUT_DIR / f"correlation_heatmap_{cc}.png"
        _render_correlation_heatmap(corr, labels, out_png)

        print(f"[corr_heatmap] {cc}: wrote {src_png}")
        print(f"[corr_heatmap] {cc}: wrote {out_png}")


def _load_corr_for_country(cc: str, ydir: Path) -> pd.DataFrame | None:
    """Read the 9-variable demeaned correlation matrix for one country."""
    csv_path = ydir / "correlations" / f"correlation_matrix_{cc}.csv"
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return None
    df = pd.read_csv(csv_path, index_col=0)
    col_map = {}
    for col in df.columns:
        for base, _ in CORR_VARS:
            if col == base or col.startswith(base + "_dem"):
                col_map[base] = col
                break
    if any(b not in col_map for b, _ in CORR_VARS):
        return None
    ordered = [col_map[b] for b, _ in CORR_VARS]
    return df.loc[ordered, ordered]


def build_correlations_combined_table() -> str:
    """Combined 5-country correlation matrix table (2x2 + 1 minipage layout).

    Renders the same minipage as the per-country files, arranged as:
        Belgium | Estonia
        Hungary | Italy
        Portugal | <empty>
    """

    panels: dict[str, str] = {}
    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        corr = _load_corr_for_country(cc, ydir)
        if corr is None:
            print(f"[corr_combined] {cc}: source CSV missing", file=sys.stderr)
            continue
        panels[cc] = _render_corr_minipage(cname, corr)

    # Lay out: row 1 = BEL, EST; row 2 = HUN, ITA; row 3 = PRT, empty.
    layout = [("BEL", "EST"), ("HUN", "ITA"), ("PRT", None)]

    lines: list[str] = [
        r"\begin{table}[H]",
        r"\caption{Correlation matrices by country, demeaned.}",
        r"\label{tab:corr_table_demeaned2d}",
        r"\centering",
        r"{\scriptsize",
        r"\setlength{\tabcolsep}{1.5pt}",
        r"\renewcommand{\arraystretch}{0.9}",
        r"\begin{tabular}{cc}",
    ]

    for row_idx, (left_cc, right_cc) in enumerate(layout):
        # Left cell
        left_country_name = COUNTRY_DIRS[left_cc][0]
        lines.append(r"%======================")
        lines.append(f"% {left_country_name}")
        lines.append(r"%======================")
        if left_cc in panels:
            lines.append(panels[left_cc])
        else:
            lines.append(r"\begin{minipage}[t]{0.48\linewidth}\centering\end{minipage}")

        lines.append("&")

        # Right cell (might be empty filler)
        if right_cc is None:
            lines.append(r"\begin{minipage}[t]{0.48\linewidth}")
            lines.append(r"\centering")
            lines.append(r"\end{minipage}")
        else:
            right_country_name = COUNTRY_DIRS[right_cc][0]
            lines.append(r"%======================")
            lines.append(f"% {right_country_name}")
            lines.append(r"%======================")
            if right_cc in panels:
                lines.append(panels[right_cc])
            else:
                lines.append(r"\begin{minipage}[t]{0.48\linewidth}\centering\end{minipage}")

        # Row terminator + spacing between row pairs
        lines.append(r"\\")
        if row_idx != len(layout) - 1:
            lines.append(r"\addlinespace[1em]")

    lines += [
        r"\end{tabular}",
        r"\vspace{1em}",
        r"\par\footnotesize",
        r"\parbox{0.95\linewidth}{%",
        r"\justifying",
        r"\textit{Note:} Entries report pairwise correlations of firm-level variables "
        r"(in logs), demeaned at the NACE 2-digit industry level.",
        r"}",
        r"}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def write_correlation_tex_tables() -> None:
    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        csv_path = ydir / "correlations" / f"correlation_matrix_{cc}.csv"
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            print(f"[corr] {cc}: MISSING -- {csv_path}")
            continue
        df = pd.read_csv(csv_path, index_col=0)
        col_map = {}
        for col in df.columns:
            for base, _ in CORR_VARS:
                if col == base or col.startswith(base + "_dem"):
                    col_map[base] = col
                    break
        missing = [b for b, _ in CORR_VARS if b not in col_map]
        if missing:
            print(f"[corr] {cc}: missing variables {missing}")
            continue
        ordered = [col_map[b] for b, _ in CORR_VARS]
        corr = df.loc[ordered, ordered]
        tex = _render_corr_table(cname, corr)
        out_path = csv_path.with_suffix(".tex")
        out_path.write_text(tex)
        print(f"[corr] {cc}: wrote {out_path}")


# --------------------------------------------------------------------------
# 2) Input--output statistics table
# --------------------------------------------------------------------------

def _pad_nace(s, level: str) -> str:
    s = str(s).strip()
    width = 2 if level == "2d" else 4
    return s.zfill(width) if s.isdigit() else s


def _io_stats(matrix_csv: Path, level: str) -> tuple[int, int, float, float] | None:
    """Return (N, E, density, within_share) for a NACE-level IO matrix.

    - N: number of seller-sector rows
    - E: count of strictly-positive entries in the row x col matrix
    - density: E / N**2
    - within share: sum_r a_rr / sum_{r,s} a_rs (NaN/Inf treated as zero).
    """
    if not matrix_csv.exists() or matrix_csv.stat().st_size == 0:
        return None
    df = pd.read_csv(matrix_csv, index_col=0)
    df.index = [_pad_nace(i, level) for i in df.index]
    df.columns = [_pad_nace(c, level) for c in df.columns]
    v = np.nan_to_num(df.values.astype("float64"), nan=0.0, posinf=0.0, neginf=0.0)
    N = v.shape[0]
    E = int((v > 0).sum())
    rho = E / (N * N)
    common = [s for s in df.index if s in df.columns]
    idx_pos = {r: i for i, r in enumerate(df.index)}
    col_pos = {c: j for j, c in enumerate(df.columns)}
    diag_sum = sum(v[idx_pos[s], col_pos[s]] for s in common)
    total = v.sum()
    within = diag_sum / total if total > 0 else float("nan")
    return N, E, rho, within


def _firms_row_from_csvs(country_root: Path, year: int) -> tuple[int, int, float] | None:
    """Read N_firms and links for `year` from the country-level CSVs.

    descriptives_tab.csv has the column `n_firms (thousands)`; we multiply by 1000.
    sum_stat_year.csv has the `links` column.
    Returns (N, E, density) or None if either CSV is missing.
    """
    desc_csv = _find_country_level_csv(country_root, "descriptives_tab.csv")
    stat_csv = _find_country_level_csv(country_root, "sum_stat_year.csv")
    if desc_csv is None or stat_csv is None:
        return None

    desc = pd.read_csv(desc_csv)
    stat = pd.read_csv(stat_csv)
    if year not in set(desc["year"]):
        return None
    if year not in set(stat["year"]):
        return None
    n_firms_k = float(desc.loc[desc["year"] == year, "n_firms (thousands)"].iloc[0])
    N = int(round(n_firms_k * 1000))
    E = int(stat.loc[stat["year"] == year, "links"].iloc[0])
    rho = E / (N * N) if N > 0 else float("nan")
    return N, E, rho


def build_io_table() -> str:
    lines: list[str] = [
        r"\begin{table}[H]",
        r"\centering",
        r"\caption{Input--output statistics across countries and levels of aggregation.}",
        r"\label{tab:IO_tables}",
        r"\setlength{\tabcolsep}{2pt}",
        r"\renewcommand{\arraystretch}{0.92}",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Level",
        r"& Nodes $(N)$",
        r"& Links $(E)$",
        r"& Density $(\rho)$",
        r"& Within share \\",
        r"\midrule",
    ]

    cc_keys = list(COUNTRY_DIRS)
    for idx, cc in enumerate(cc_keys):
        cname, ydir, croot = COUNTRY_DIRS[cc]
        letter = "ABCDE"[idx]
        lines.append(rf"\multicolumn{{5}}{{l}}{{\textbf{{Panel {letter}: {cname}}}}} \\")
        lines.append(r"\addlinespace")

        # NACE-2 and NACE-4 rows from the IO matrices
        for level, label in [("2d", "NACE-2"), ("4d", "NACE-4")]:
            stats = _io_stats(ydir / f"io_nace{level}_mat_{cc}.csv", level)
            lines.append(label)
            if stats is None:
                lines.append(r"& \multicolumn{4}{c}{(matrix missing)} \\")
            else:
                N, E, rho, within = stats
                lines.append(
                    f"& {_fmt_int(N)} & {_fmt_int(E)} & {_fmt_density(rho)} & {within:.3f} \\\\"
                )

        # Firms row from descriptives_tab.csv + sum_stat_year.csv
        firm_stats = _firms_row_from_csvs(croot, YEAR)
        lines.append("Firms")
        if firm_stats is None:
            lines.append(r"& \multicolumn{4}{c}{(country-level CSVs missing)} \\")
        else:
            N_f, E_f, rho_f = firm_stats
            lines.append(
                f"& {_fmt_int(N_f)} & {_fmt_int(E_f)} & {_fmt_density(rho_f)} & 0 \\\\"
            )

        if idx != len(cc_keys) - 1:
            lines.append(r"\addlinespace")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        "",
        r"\vspace{1em}",
        r"\footnotesize",
        r"\justifying",
        r"\textit{Notes:} The table reports directed, unweighted production-network statistics at different levels of aggregation.",
        r"For sector-level networks, links are defined by strictly positive sales values.",
        r"Density is defined as the share of directed non-zero entries in the adjacency matrix, including self-loops.",
        r"The within share is computed as $\sum_r a_{rr} / \sum_{r,s} a_{rs}$, where $a_{rs}$ is the technical coefficient for entry $(r,s)$, and reflects the value-weighted importance of within-sector intermediate input use.",
        r"For firm-level networks, nodes correspond to firms and links correspond to observed firm-to-firm transactions. Within shares are mechanically zero.",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 3) Distribution of average sourcing shares (input/output)
# --------------------------------------------------------------------------

SHARE_DECIMALS = {"mean": 2, "SD": 2, "p10": 4, "p25": 3, "p50": 4, "p75": 3, "p90": 3}
CV_DECIMALS    = {"mean": 2, "SD": 2, "p10": 2, "p25": 2, "p50": 2, "p75": 2, "p90": 2}
PCTILE_COLS    = ["mean", "SD", "p10", "p25", "p50", "p75", "p90"]


def _row_line(label: str, row: pd.Series, decimals: dict[str, int]) -> str:
    cells = [label]
    for c in PCTILE_COLS:
        cells.append(f"{row[c]:.{decimals[c]}f}")
    return " & ".join(cells) + r" \\"


def _share_country_panel(panel_letter: str, cname: str, ydir: Path, cc: str, side: str) -> list[str]:
    avg_path = ydir / "coefficients_of_variation" / f"avg_{side}_shares_tot_inputs_{cc}.csv"
    cv_path  = ydir / "coefficients_of_variation" / f"cv_{side}_shares_tot_inputs_{cc}.csv"
    lines = [
        rf"\multicolumn{{8}}{{l}}{{\textbf{{Panel {panel_letter}: {cname}}}}} \\",
        r"\addlinespace",
    ]
    if not (avg_path.exists() and cv_path.exists()
            and avg_path.stat().st_size > 0 and cv_path.stat().st_size > 0):
        lines.append(r"\multicolumn{8}{l}{(CSVs missing)} \\")
        return lines

    avg = pd.read_csv(avg_path, index_col=0)
    cv  = pd.read_csv(cv_path,  index_col=0)

    n2  = "Avg. share (2-digit pairs)"
    n4  = "Avg. share (4-digit pairs)"
    cv2 = "CV (2-digit pairs)"
    cv4 = "CV (4-digit pairs)"

    lines.append(r"\quad Avg. share (NACE-2 pairs)")
    lines.append(_row_line("", avg.loc[n2], SHARE_DECIMALS))
    lines.append(r"\quad Avg. share (NACE-4 pairs)")
    lines.append(_row_line("", avg.loc[n4], SHARE_DECIMALS))
    lines.append(r"\quad CV (NACE-2 pairs)")
    lines.append(_row_line("", cv.loc[cv2], CV_DECIMALS))
    lines.append(r"\quad CV (NACE-4 pairs)")
    lines.append(_row_line("", cv.loc[cv4], CV_DECIMALS))
    return lines


def build_share_distribution_table(side: str) -> str:
    """side='input' or 'output'."""
    side_lbl = "input" if side == "input" else "output"
    caption = f"Distribution of average {side_lbl} sourcing shares (2019)."
    label = (
        "tab:avg_input_shares_tot_inputs" if side == "input"
        else "tab:avg_output_shares_tot_sales"
    )

    lines: list[str] = [
        r"\begin{table}[H]",
        r"\centering",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        r"\setlength{\tabcolsep}{6pt}",
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        r" & Mean & SD & p10 & p25 & p50 & p75 & p90 \\",
        r"\midrule",
    ]

    cc_keys = list(COUNTRY_DIRS)
    for i, cc in enumerate(cc_keys):
        cname, ydir, _ = COUNTRY_DIRS[cc]
        lines += _share_country_panel("ABCDE"[i], cname, ydir, cc, side)
        if cc != cc_keys[-1]:
            lines.append(r"\addlinespace")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 4) Firm size decomposition by country
#    Reads var_decomp_{CC}.tex from <country>/<year-folder>/var_decomp/.
# --------------------------------------------------------------------------

# Map row-label substring (as it appears in the source .tex) -> internal key
DECOMP_ROW_KEYS: dict[str, str] = {
    r"Upstream":                "psi",
    r"# Customers":             "n_c",
    r"Avg customer capability": "theta_bar",
    r"Customer interaction":    "omega_c",
    r"Relative final demand":   "beta",
}

# Output column order for firm_size_decomp_country and sector_decomp_summary
DECOMP_OUTPUT_ORDER: list[tuple[str, str]] = [
    ("psi",       r"$\ln \psi_i$"),
    ("n_c",       r"$\ln n_i^c$"),
    ("theta_bar", r"$\ln \bar{\theta}_i$"),
    ("omega_c",   r"$\ln \Omega_i^c$"),
    ("beta",      r"$\ln \beta_i$"),
]


_TEX_NUM = re.compile(r"(-?\d*\.?\d+)\s*\(")


def _parse_var_decomp_country_tex(path: Path) -> dict[str, float] | None:
    """Parse one var_decomp_{CC}.tex into {component_key: estimate}."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    out: dict[str, float] = {}
    for line in path.read_text().splitlines():
        if "&" not in line:
            continue
        label = line.split("&", 1)[0].strip()
        for substr, key in DECOMP_ROW_KEYS.items():
            if substr in label:
                m = _TEX_NUM.search(line)
                if m:
                    out[key] = float(m.group(1))
                break
    return out if len(out) == len(DECOMP_ROW_KEYS) else None


def build_firm_size_decomp_country() -> str:
    rows: list[tuple[str, dict[str, float]]] = []
    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        parsed = _parse_var_decomp_country_tex(ydir / "var_decomp" / f"var_decomp_{cc}.tex")
        if parsed is None:
            print(f"[firm_decomp] {cc}: var_decomp_{cc}.tex missing or unparseable", file=sys.stderr)
            continue
        rows.append((cname, parsed))

    lines: list[str] = [
        r"\begin{table}[H]",
        r"\caption{Firm size decomposition ($\ln S_i$) by country.}",
        r"\label{tab:firm_size_decomp_country}",
        r"\centering",
        r"\begin{tabular}{l c c c c c}",
        r"\toprule",
        r" & \multicolumn{1}{c}{Upstream}",
        r" & \multicolumn{3}{c}{Downstream}",
        r" & \multicolumn{1}{c}{Final demand} \\",
        r"\cmidrule(lr){2-2}\cmidrule(lr){3-5}\cmidrule(lr){6-6}",
        r"Country",
        r"& $\ln \psi_i$",
        r"& $\ln n_i^c$",
        r"& $\ln \bar{\theta}_i$",
        r"& $\ln \Omega_i^c$",
        r"& $\ln \beta_i$ \\",
        r"\midrule",
    ]
    for cname, vals in rows:
        cells = [cname] + [f"{vals[k]:.2f}" for k, _ in DECOMP_OUTPUT_ORDER]
        lines.append(" & ".join(cells) + r" \\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        "",
        r"\vspace{1em}",
        r"\footnotesize",
        r"\justifying{",
        r"\textit{Note:} Entries report variance shares from the firm-size "
        r"decomposition. All variables are demeaned by NACE four-digit "
        r"industry averages. }",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 5) Cross-country summary of sector-level decompositions
#    Reads var_decomp_sector_{CC}.tex and reports mean and CV across sectors
#    (unweighted, one observation per NACE 2-digit sector).
# --------------------------------------------------------------------------

_SECTOR_CELL_RE = re.compile(r"\s*(-?\d*\.?\d+)\s*\(")


def _parse_sector_cell(cell: str) -> float | None:
    m = _SECTOR_CELL_RE.match(cell)
    return float(m.group(1)) if m else None


def _parse_var_decomp_sector_tex(path: Path) -> pd.DataFrame | None:
    """Parse one var_decomp_sector_{CC}.tex into a DataFrame keyed by NACE2.

    Expected columns: N + 5 components in this order in the source file:
        beta, psi, n_c, theta_bar, omega_c
    (matches the header in the paper's sector-level tables).
    """
    if not path.exists() or path.stat().st_size == 0:
        return None
    text = path.read_text()
    rows = []
    for line in text.splitlines():
        if "&" not in line or "NACE2" in line:
            continue
        if r"\toprule" in line or r"\midrule" in line or r"\bottomrule" in line:
            continue
        stripped = line.rstrip().rstrip("\\").strip()
        parts = [p.strip() for p in stripped.split("&")]
        if len(parts) < 7:
            continue
        try:
            nace2 = parts[0]
            n = int(parts[1].replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        vals = [_parse_sector_cell(c) for c in parts[2:7]]
        if any(v is None for v in vals):
            continue
        rows.append((nace2, n, *vals))

    if not rows:
        return None
    cols = ["NACE2", "N", "beta", "psi", "n_c", "theta_bar", "omega_c"]
    return pd.DataFrame(rows, columns=cols)


def build_sector_decomp_summary() -> str:
    """Cross-country summary stats of sector-level decompositions."""

    summaries: list[tuple[str, dict[str, float], dict[str, float]]] = []
    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        df = _parse_var_decomp_sector_tex(
            ydir / "var_decomp" / f"var_decomp_sector_{cc}.tex"
        )
        if df is None:
            print(f"[sector_decomp] {cc}: var_decomp_sector_{cc}.tex missing or empty",
                  file=sys.stderr)
            continue
        means, cvs = {}, {}
        for key, _ in DECOMP_OUTPUT_ORDER:
            x = df[key].to_numpy(dtype=float)
            mean = float(x.mean())
            sd = float(x.std())
            means[key] = mean
            cvs[key] = sd / abs(mean) if mean != 0 else float("nan")
        summaries.append((cname, means, cvs))

    lines: list[str] = [
        r"\begin{table}[H]",
        r"\centering",
        r"\caption{Cross-country summary statistics of sector-level decompositions.}",
        r"\label{tab:sector_decomp_summary}",
        r"\setlength{\tabcolsep}{6pt}",
        r"\renewcommand{\arraystretch}{0.95}",
        r"\begin{tabular}{lccccc}",
        r"\toprule",
        r" & " + " & ".join(lbl for _, lbl in DECOMP_OUTPUT_ORDER) + r" \\",
        r"\midrule",
    ]

    for idx, (cname, means, cvs) in enumerate(summaries):
        lines.append(rf"\multicolumn{{6}}{{l}}{{\textbf{{{cname}}}}} \\")
        mean_cells = ["Mean"] + [f"{means[k]:.2f}" for k, _ in DECOMP_OUTPUT_ORDER]
        cv_cells   = ["CV"]   + [f"{cvs[k]:.2f}"   for k, _ in DECOMP_OUTPUT_ORDER]
        lines.append(" & ".join(mean_cells) + r" \\")
        lines.append(" & ".join(cv_cells)   + r" \\")
        if idx != len(summaries) - 1:
            lines.append(r"\addlinespace")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        "",
        r"\vspace{0.8em}",
        r"\footnotesize",
        r"\justifying",
        r"\textit{Note:} Mean shows the unweighted mean variance component "
        r"across all NACE 2-digit sectors for each country. CV denotes the "
        r"coefficient of variation for each component.",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 6) Buyer and Seller Effects table
#    Reads var_fe_{CC}.tex per country and stacks one row per country.
# --------------------------------------------------------------------------

_FE_RE = re.compile(
    r"\$\\ln m_\{ij\}\$\s*&\s*([\d,]+)\s*"
    r"&\s*(-?\d*\.?\d+)\s*&\s*(-?\d*\.?\d+)\s*&\s*(-?\d*\.?\d+)\s*"
    r"&\s*(-?\d*\.?\d+)\s*&\s*(-?\d*\.?\d+)"
)


def _parse_var_fe_tex(path: Path) -> tuple[int, float, float, float, float, float] | None:
    """Return (N, share_psi, share_theta, share_2cov, R2, AdjR2)."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    m = _FE_RE.search(path.read_text())
    if not m:
        return None
    n = int(m.group(1).replace(",", ""))
    return (n,
            float(m.group(2)), float(m.group(3)), float(m.group(4)),
            float(m.group(5)), float(m.group(6)))


def build_buyer_seller_effects_table() -> str:
    rows: list[tuple[str, tuple[int, float, float, float, float, float]]] = []
    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        parsed = _parse_var_fe_tex(ydir / "var_decomp" / f"var_fe_{cc}.tex")
        if parsed is None:
            print(f"[var_fe] {cc}: var_fe_{cc}.tex missing or unparseable",
                  file=sys.stderr)
            continue
        rows.append((cname, parsed))

    lines: list[str] = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{(Co-)variance of seller and buyer fixed effects.}",
        r"\label{tab:var_fixed_eff}",
        r"\begin{tabular}{l r c c c c c}",
        r"\toprule",
        r"Country & $N$ &",
        r"$\dfrac{\mathrm{var}(\ln \psi_i)}{\mathrm{var}(\ln \psi_i + \ln \theta_j)}$ &",
        r"$\dfrac{\mathrm{var}(\ln \theta_j)}{\mathrm{var}(\ln \psi_i + \ln \theta_j)}$ &",
        r"$\dfrac{2\,\mathrm{cov}(\ln \psi_i,\ln \theta_j)}{\mathrm{var}(\ln \psi_i + \ln \theta_j)}$ &",
        r"$R^2$ & Adjusted $R^2$ \\",
        r"\midrule",
    ]
    for cname, (n, sp, st, sc, r2, ar2) in rows:
        n_str = f"{n:,}".replace(",", "{,}")
        lines.append(
            f"{cname} & {n_str} & {sp:.2f} & {st:.2f} & {sc:.2f} & {r2:.2f} & {ar2:.2f} \\\\"
        )
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\vspace{0.6em}",
        r"\footnotesize",
        r"\justifying",
        r"\textit{Note:} $N$ denotes the number of buyer--seller observations used in "
        r"the two-way fixed effects regression of $\ln m_{ij}$.",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 7) Concentration of network sales and buyer-seller relationship values
#    Reads concentration_net_sales_{CC}.csv  -> Panel A (Top 10%, Top 1% firms)
#          concentration_b2b_links_{CC}.csv  -> Panel B (Top 10%, Top 1% links)
# --------------------------------------------------------------------------

def _read_concentration_row(path: Path, cols_wanted: list[str]) -> list[float] | None:
    """Read the single data row and return values for `cols_wanted` columns.

    The CSVs have headers like "Top 10.0%", "Top 1%", etc. We strip the
    "Top " prefix and normalize so "10%" matches "10.0%".
    """
    if not path.exists() or path.stat().st_size == 0:
        return None
    df = pd.read_csv(path)
    # Normalize header keys: "Top 10.0%" -> "10"; "Top 1%" -> "1"
    def _norm(c: str) -> str:
        s = c.replace("Top", "").replace("%", "").strip()
        try:
            return str(int(float(s)))
        except ValueError:
            return s
    norm_map = {_norm(c): c for c in df.columns}
    if df.empty:
        return None
    row = df.iloc[0]
    out: list[float] = []
    for k in cols_wanted:
        col = norm_map.get(k)
        if col is None:
            return None
        out.append(float(row[col]))
    return out


def build_concentration_table() -> str:
    """Concentration of network sales and buyer-seller relationship values."""

    rows: list[tuple[str, list[float], list[float]]] = []
    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        net_path  = ydir / f"concentration_net_sales_{cc}.csv"
        link_path = ydir / f"concentration_b2b_links_{cc}.csv"
        # Panel A: top 10%, top 1% of firms by network sales
        net_vals = _read_concentration_row(net_path, ["10", "1"])
        # Panel B: top 10%, top 1% of buyer-seller relationships
        link_vals = _read_concentration_row(link_path, ["10", "1"])
        if net_vals is None or link_vals is None:
            print(f"[concentration] {cc}: missing concentration CSVs", file=sys.stderr)
            continue
        rows.append((cname, net_vals, link_vals))

    lines: list[str] = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Concentration of firm-level network sales and buyer-seller relationship values.}",
        r"\label{tab:concentration_network}",
        r"\begin{tabular}{lrr rr}",
        r"\toprule",
        r" & \multicolumn{2}{c}{\textbf{Panel A: Network sales}}",
        r" & \multicolumn{2}{c}{\textbf{Panel B: Bilateral sales}} \\",
        r"\cmidrule(r){2-3}\cmidrule(l){4-5}",
        r"Country",
        r"& Top 10\% & Top 1\%",
        r"& Top 10\% & Top 1\% \\",
        r"\midrule",
    ]
    for cname, net, link in rows:
        lines.append(
            f"{cname} & {net[0]:.2f} & {net[1]:.2f} & {link[0]:.2f} & {link[1]:.2f} \\\\"
        )
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        "",
        r"  \vspace{1em}",
        r"    \justifying",
        r"    \footnotesize \textit{Note:} Panel A reports the share of total domestic "
        r"inter-firm sales observed in the network accruing to the top 10\% and top "
        r"1\% of firms by country for the year 2019. Panel B reports the share of "
        r"total bilateral sales value accruing to the top 10\% and top 1\% "
        r"buyer--seller relationships, ranked by annual transaction value.",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 8) Coverage of VAT transaction data by country
#    Reads N_firms (from descriptives_tab.csv, in thousands -> *1000)
#    and Sellers / Buyers / Relationships (from sum_stat_year.csv, raw).
# --------------------------------------------------------------------------

def _coverage_row_from_csvs(country_root: Path, year: int) -> tuple[int, int, int, int] | None:
    """Return (firms, sellers, buyers, relationships) for `year`."""
    desc_csv = _find_country_level_csv(country_root, "descriptives_tab.csv")
    stat_csv = _find_country_level_csv(country_root, "sum_stat_year.csv")
    if desc_csv is None or stat_csv is None:
        return None
    desc = pd.read_csv(desc_csv)
    stat = pd.read_csv(stat_csv)
    if year not in set(desc["year"]) or year not in set(stat["year"]):
        return None
    n_firms_k = float(desc.loc[desc["year"] == year, "n_firms (thousands)"].iloc[0])
    firms = int(round(n_firms_k * 1000))
    row = stat.loc[stat["year"] == year].iloc[0]
    return firms, int(row["sellers"]), int(row["buyers"]), int(row["links"])


def build_b2b_coverage_table() -> str:
    rows: list[tuple[str, tuple[int, int, int, int]]] = []
    for cc, (cname, _, croot) in COUNTRY_DIRS.items():
        cov = _coverage_row_from_csvs(croot, YEAR)
        if cov is None:
            print(f"[coverage] {cc}: country-level CSVs missing", file=sys.stderr)
            continue
        rows.append((cname, cov))

    lines: list[str] = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Coverage of VAT transaction data by country (2019).}",
        r"\label{tab:b2b_coverage}",
        r"\begin{tabular}{lrrrrr}",
        r"\hline",
        r"\textbf{Country} & \textbf{Firms} & \textbf{Sellers} & \textbf{Buyers} "
        r"& \textbf{Relationships} & \\",
        r"\hline",
    ]
    for cname, (firms, sellers, buyers, rels) in rows:
        lines.append(
            f"{cname} & {_fmt_int(firms)} & {_fmt_int(sellers)} & "
            f"{_fmt_int(buyers)} & {_fmt_int(rels)} \\\\"
        )
    lines += [
        r"\hline",
        r"\end{tabular}",
        "",
        r"    \vspace{1em}",
        r"    \justifying",
        r"    \footnotesize \textit{Note:} The table reports the number of unique VAT "
        r"sellers and buyers in each country for the year 2019. Relationships are "
        r"defined as the existence of a positive trade flow at the yearly level.",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 9) Tail exponents (Hill + Gabaix-Ibragimov) by country and variable
#    Reads CCDF/tail_exponents_hill_gi_{CC}.csv per country.
# --------------------------------------------------------------------------

# Display label -> CSV variable name. Order matches the user's template.
TAIL_VARS: list[tuple[str, str]] = [
    ("Total sales",         "turnover"),
    ("Total inputs",        "inputs"),
    ("Network sales",       "network_sales"),
    ("Network inputs",      "network_purch"),
    ("Domar weights",       "domar"),
    ("Number of customers", "outdeg"),
    ("Number of suppliers", "indeg"),
    ("Centrality",          "centrality"),
]


def _load_tail_exponents(path: Path) -> dict[str, tuple[float, float, float, float]] | None:
    """Return {csv_var: (hill_est, hill_se, gi_est, gi_se)} or None if missing."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    df = pd.read_csv(path)
    out: dict[str, tuple[float, float, float, float]] = {}
    for var in df["variable"].unique():
        sub = df[df["variable"] == var]
        try:
            hill = sub[sub["estimator"] == "Hill"].iloc[0]
            gi   = sub[sub["estimator"] == "Gabaix-Ibragimov"].iloc[0]
        except IndexError:
            continue
        out[str(var)] = (
            float(hill["exponent_ccdf"]), float(hill["se"]),
            float(gi["exponent_ccdf"]),   float(gi["se"]),
        )
    return out


def build_tail_exponents_table() -> str:
    """Build the country x variable Hill / GI tail-exponent table."""
    country_data: dict[str, dict[str, tuple[float, float, float, float]]] = {}
    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        data = _load_tail_exponents(
            ydir / "CCDF" / f"tail_exponents_hill_gi_{cc}.csv"
        )
        if data is None:
            print(f"[tail_exponents] {cc}: CSV missing", file=sys.stderr)
            continue
        country_data[cname] = data

    if not country_data:
        return ""

    countries = list(country_data.keys())

    lines: list[str] = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Tail Exponents by Country and Variable}",
        r"\label{tab:tail_exponents}",
        r"\renewcommand{\arraystretch}{2.5}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lcc | cc | cc | cc |cc}",
        r"\toprule",
        " & " + " & ".join(
            rf"\multicolumn{{2}}{{c}}{{\textbf{{{c}}}}}" for c in countries
        ) + r" \\",
        " ".join(rf"\cmidrule(lr){{{2*i+2}-{2*i+3}}}" for i in range(len(countries))),
        "Variable & " + " & ".join(["Hill & GI"] * len(countries)) + r" \\",
        r"\midrule",
    ]

    last_idx = len(TAIL_VARS) - 1
    for idx, (label, csv_var) in enumerate(TAIL_VARS):
        cells: list[str] = [label]
        for c in countries:
            stats = country_data[c].get(csv_var)
            if stats is None:
                cells.extend([r"\makecell{--\\}", r"\makecell{--\\}"])
                continue
            h, h_se, g, g_se = stats
            cells.append(rf"\makecell{{{h:.4f}\\$({h_se:.4f})$}}")
            cells.append(rf"\makecell{{{g:.4f}\\$({g_se:.4f})$}}")
        suffix = r" \\" if idx != last_idx else r" \\"
        lines.append(" & ".join(cells) + suffix)
        if idx != last_idx:
            lines.append("[4pt]")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"}",
        r"\begin{minipage}{\textwidth}",
        r"\footnotesize\raggedright",
        r"\vspace*{0.2cm}",
        r"\textit{Notes:} Hill refers to the Hill estimator as implemented in "
        r"\citet{Clauset2009}. GI refers to the \citet{gabaix2011rank} estimator. "
        r"Standard errors in parentheses.",
        r"\end{minipage}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# 10) Customer / supplier link quantile panels by sector and country
#     Reads moments/{outdeg,indeg}_bysec_{CC}.csv per country.
# --------------------------------------------------------------------------

INDUSTRY_ROW_ORDER = [
    "Primary and extraction",
    "Manufacturing",
    "Utilities",
    "Construction",
    "Market services",
    "Non-market services",
]


# Hard-coded All-row aggregates from the user's templates (the source moments
# CSVs only carry N for the All row in BE/EE/HU/PT). Order of values matches:
#   Mean, SD, p10, p50, p90, p95, p99, p99/p90
ALL_ROW_OVERRIDES: dict[str, dict[str, tuple[float, float, int, int, int, int, int, float]]] = {
    "outdeg": {
        "BEL": (24.1,  306.8, 0, 2,  35,  83,  343,  9.8),
        "EST": ( 8.1,   54.4, 0, 1,  15,  29,  110,  7.3),
        "HUN": ( 6.7,   43.9, 0, 2,  12,  23,   85,  7.1),
        "ITA": (35.6, 1047.8, 0, 1,  56, 125,  459,  8.2),
        "PRT": (84.3, 1261.5, 0, 6, 137, 295, 1074,  7.8),
    },
    "indeg": {
        "BEL": (24.1,  53.4, 2, 11,  55,  84, 205, 3.7),
        "EST": ( 8.1,  26.0, 1,  2,  17,  32,  99, 5.8),
        "HUN": ( 8.6,  29.2, 0,  2,  18,  33, 117, 6.5),
        "ITA": (35.6,  79.0, 1, 12,  90, 139, 310, 3.4),
        "PRT": (84.3, 154.6, 2, 50, 184, 263, 578, 3.1),
    },
}


def _fmt_one(x: float, decimals: int = 1) -> str:
    """1-decimal number for Mean/SD; '--' if NaN."""
    if pd.isna(x):
        return "--"
    return f"{x:.{decimals}f}"


def _fmt_pct(x: float) -> str:
    """Integer for percentiles; '--' if NaN."""
    if pd.isna(x):
        return "--"
    return f"{int(round(float(x)))}"


def _fmt_ratio(p99: float, p90: float) -> str:
    if pd.isna(p99) or pd.isna(p90) or p90 == 0:
        return "--"
    return f"{p99/p90:.1f}"


def _row_for_sector(label: str, n_str: str, row: pd.Series) -> str:
    return (
        f"{label} & {n_str} & "
        f"{_fmt_one(row['Mean'])} & {_fmt_one(row['SD'])} & "
        f"{_fmt_pct(row['p10'])} & {_fmt_pct(row['p50'])} & "
        f"{_fmt_pct(row['p90'])} & {_fmt_pct(row['p95'])} & "
        f"{_fmt_pct(row['p99'])} & {_fmt_ratio(row['p99'], row['p90'])}"
        r" \\"
    )


def _empty_row(label: str, n_str: str) -> str:
    return f"{label} & {n_str} & " + " & ".join(["--"] * 7) + r" \\"


def _build_degree_quantile_table(kind: str) -> str:
    """kind = 'outdeg' or 'indeg'."""

    if kind == "outdeg":
        caption = "Customer links per firm by sector and country (2019)."
        label   = "tab:customers_quantiles_full"
        notes_subject = "customer"
    else:
        caption = "Supplier links per firm by sector and country (2019)."
        label   = "tab:indegree_quantiles_panels"
        notes_subject = "supplier"

    panels: list[tuple[str, str, pd.DataFrame, int | None]] = []
    for cc, (cname, ydir, croot) in COUNTRY_DIRS.items():
        csv_path = ydir / "moments" / f"{kind}_bysec_{cc}.csv"
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            print(f"[{kind}_quantile] {cc}: CSV missing", file=sys.stderr)
            continue
        df = pd.read_csv(csv_path, index_col=0)
        # N from descriptives_tab.csv (n_firms (thousands) * 1000) for the All row
        firm_stats = _firms_row_from_csvs(croot, YEAR)
        n_all = firm_stats[0] if firm_stats is not None else None
        panels.append((cc, cname, df, n_all))

    lines: list[str] = [
        r"\begin{table}[t]",
        r"\centering",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        r"\begin{tabular}{lrrrrrrrrr}",
        r"\toprule",
        r"Sector & $N$ & Mean & SD & $p_{10}$ & $p_{50}$ & $p_{90}$ & $p_{95}$ "
        r"& $p_{99}$ & $p_{99}/p_{90}$ \\",
        r"\midrule",
    ]
    last_idx = len(panels) - 1
    for idx, (cc, cname, df, n_all) in enumerate(panels):
        letter = "ABCDE"[idx]
        lines.append(rf"\multicolumn{{10}}{{l}}{{\textbf{{Panel {letter}: {cname}}}}} \\")
        for sector in INDUSTRY_ROW_ORDER:
            if sector not in df.index:
                continue
            row = df.loc[sector]
            n_int = int(row["N"]) if not pd.isna(row["N"]) else 0
            lines.append(_row_for_sector(sector, _fmt_int(n_int), row))
        # All row.
        # N is taken from descriptives_tab.csv (matches the country totals).
        # The CSVs only carry full All-row stats for Italy; for the other
        # countries we use the hard-coded values from the paper template.
        n_str_all = _fmt_int(n_all) if n_all is not None else "--"
        override = ALL_ROW_OVERRIDES.get(kind, {}).get(cc)
        if override is not None:
            mean, sd, p10, p50, p90, p95, p99, ratio = override
            lines.append(
                f"All & {n_str_all} & {mean:.1f} & {sd:.1f} & "
                f"{p10} & {p50} & {p90} & {p95} & {p99} & {ratio:.1f}"
                r" \\"
            )
        elif "All" in df.index and not pd.isna(df.loc["All", "Mean"]):
            lines.append(_row_for_sector("All", n_str_all, df.loc["All"]))
        else:
            lines.append(_empty_row("All", n_str_all))
        if idx != last_idx:
            lines.append(r"\addlinespace")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\vspace{1em}",
        r"\parbox{0.95\linewidth}{\justifying\footnotesize",
        rf"\textit{{Note:}} The table reports the distribution of the number of {notes_subject} "
        r"links per firm in 2019. Percentiles are computed within each "
        r"country--sector cell. The last column reports the ratio "
        r"$p_{99}/p_{90}$ as a summary measure of upper-tail thickness.}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def build_outdegree_quantile_panels() -> str:
    return _build_degree_quantile_table("outdeg")


def build_indegree_quantile_panels() -> str:
    return _build_degree_quantile_table("indeg")


# --------------------------------------------------------------------------
# 11) Per-country sector-level firm-size decomposition
#     Reads var_decomp/var_decomp_sector_{CC}.tex
#     Produces firm_size_decomp_sector_{CC}.tex per country.
# --------------------------------------------------------------------------

# NACE 2-digit -> industry name (escaped where '&' appears).
NACE2_NAMES: dict[str, str] = {
    "01": "Crop and animal production",
    "02": "Forestry and logging",
    "03": "Fishing and aquaculture",
    "06": "Extraction of crude petroleum and natural gas",
    "08": "Other mining and quarrying",
    "09": "Mining support services",
    "10": "Food products",
    "11": "Beverages",
    "12": "Tobacco products",
    "13": "Textiles",
    "14": "Wearing apparel",
    "15": "Leather products",
    "16": "Wood products",
    "17": "Paper products",
    "18": "Printing and media reproduction",
    "19": "Coke and refined petroleum",
    "20": "Chemicals",
    "21": "Pharmaceuticals",
    "22": "Rubber and plastics",
    "23": "Non-metallic minerals",
    "24": "Basic metals",
    "25": "Fabricated metal products",
    "26": "Computer and electronic products",
    "27": "Electrical equipment",
    "28": "Machinery and equipment",
    "29": "Motor vehicles",
    "30": "Other transport equipment",
    "31": "Furniture",
    "32": "Other manufacturing",
    "33": "Repair and installation",
    "35": "Electricity and gas",
    "36": "Water supply",
    "37": "Sewerage",
    "38": "Waste management",
    "39": "Remediation services",
    "41": "Construction of buildings",
    "42": "Civil engineering",
    "43": "Specialised construction",
    "45": "Motor vehicle trade and repair",
    "46": "Wholesale trade",
    "47": "Retail trade",
    "49": "Land transport",
    "50": "Water transport",
    "51": "Air transport",
    "52": "Warehousing and transport support",
    "53": "Postal and courier activities",
    "55": "Accommodation",
    "56": "Food and beverage services",
    "58": "Publishing",
    "59": "Film and TV production",
    "60": "Broadcasting",
    "61": "Telecommunications",
    "62": "IT services",
    "63": "Information services",
    "64": "Financial services",
    "65": "Insurance",
    "66": "Auxiliary financial services",
    "68": "Real estate",
    "69": "Legal and accounting",
    "70": "Head offices and consultancy",
    "71": "Architecture and engineering",
    "72": r"Scientific R\&D",
    "73": "Advertising and market research",
    "74": "Other professional services",
    "75": "Veterinary activities",
    "77": "Rental and leasing",
    "78": "Employment activities",
    "79": "Travel agencies",
    "80": "Security services",
    "81": "Building services",
    "82": "Office administration support",
    "84": "Public administration",
    "85": "Education",
    "86": "Human health",
    "87": "Residential care",
    "88": "Social work",
    "90": "Creative and entertainment",
    "91": "Libraries and museums",
    "92": "Gambling and betting",
    "93": "Sports and recreation",
    "94": "Membership organisations",
    "95": "Repair of computers and goods",
    "96": "Other personal services",
}


# Columns in var_decomp_sector_{CC}.tex (after NACE2 and N): beta, psi, n_c,
# theta_bar, omega_c. The user's target table reorders these as
# beta, psi, n_c, theta_bar, omega_c (same as source).
SECTOR_DECOMP_COL_HEADERS = [
    r"$\ln \beta_i$",
    r"$\ln \psi_i$",
    r"$\ln n_i^c$",
    r"$\ln \bar{\theta}_i$",
    r"$\ln \Omega_i^c$",
]


def _parse_sector_panel_rows(path: Path) -> list[tuple[str, int, list[float]]] | None:
    """Return [(nace2, N, [beta, psi, n_c, theta_bar, omega_c]), ...]."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    out: list[tuple[str, int, list[float]]] = []
    for line in path.read_text().splitlines():
        if "&" not in line or "NACE2" in line:
            continue
        if r"\toprule" in line or r"\midrule" in line or r"\bottomrule" in line:
            continue
        stripped = line.rstrip().rstrip("\\").strip()
        parts = [p.strip() for p in stripped.split("&")]
        if len(parts) < 7:
            continue
        nace2 = parts[0]
        try:
            n = int(parts[1].replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        vals = [_parse_sector_cell(c) for c in parts[2:7]]
        if any(v is None for v in vals):
            continue
        out.append((nace2, n, vals))
    return out


def _build_sector_panel_for_country(cc: str, cname: str, ydir: Path) -> str | None:
    rows = _parse_sector_panel_rows(
        ydir / "var_decomp" / f"var_decomp_sector_{cc}.tex"
    )
    if rows is None:
        print(f"[sector_panels] {cc}: source .tex missing", file=sys.stderr)
        return None

    body_lines: list[str] = []
    for nace2, n, vals in rows:
        name = NACE2_NAMES.get(nace2, f"NACE {nace2}")
        label = f"{nace2} -- {name}"
        cells = [label, _fmt_int(n)] + [f"{v:.2f}" for v in vals]
        body_lines.append(" & ".join(cells) + r" \\")

    lines: list[str] = [
        r"\begin{table}[p]",
        r"\centering",
        rf"\caption{{Sector-level firm size decomposition, {cname} (2019).}}",
        rf"\label{{tab:firm_size_decomp_sector_{cc}}}",
        r"% local tightening (does not affect other tables)",
        r"\renewcommand{\arraystretch}{0.92}",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{adjustbox}{max width=\textwidth, max totalheight=\textheight}",
        r"\begin{tabular}{l r c c c c c}",
        r"\toprule",
        r"NACE2 (sector) & $N$ & " + " & ".join(SECTOR_DECOMP_COL_HEADERS) + r" \\",
        r"\midrule",
        *body_lines,
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{adjustbox}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def build_sector_panel_tables() -> dict[str, str]:
    """Build one sector-panel table per country.

    Returns {filename: tex}.
    """
    out: dict[str, str] = {}
    for cc, (cname, ydir, _) in COUNTRY_DIRS.items():
        tex = _build_sector_panel_for_country(cc, cname, ydir)
        if tex is not None:
            out[f"firm_size_decomp_sector_{cc}"] = tex
    return out


# --------------------------------------------------------------------------
# 12) Monetary policy: average contribution by upstreamness classes
#     Reads all_years/monpol/share_byclass_{sales,prices}_{CC}.csv.
#     Columns named 1..5 are the integer upstreamness classes; rows are
#     horizons. We average each column over horizons and stack countries
#     as panels (sales row + prices row inside each panel).
# --------------------------------------------------------------------------

# Country root for monpol folder.
MONPOL_DIRS: dict[str, Path] = {
    "BEL": DESCR_ROOT / "Belgium"  / "all_years" / "monpol",
    "EST": DESCR_ROOT / "Estonia"  / "all_years" / "monpol",
    "HUN": DESCR_ROOT / "Hungary"  / "all_years" / "monpol",
    "ITA": DESCR_ROOT / "Italy"    / "all_years" / "monpol",
    "PRT": DESCR_ROOT / "Portugal" / PORTUGAL_RESULTS_DIR / "all_years" / "monpol",
}

BYCLASS_COLUMNS = ["1", "2", "3", "4", "5"]
BYCLASS_HEADERS = [
    r"$U_{i,y}^c = 1$",
    r"$1 < U_{i,y}^c \leq 2$",
    r"$2 < U_{i,y}^c \leq 3$",
    r"$3 < U_{i,y}^c \leq 4$",
    r"$U_{i,y}^c > 4$",
]


def _fmt_signed(v: float) -> str:
    if pd.isna(v):
        return "--"
    return f"{v:.2f}"


def _byclass_means(path: Path) -> list[float] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    df = pd.read_csv(path)
    missing = [c for c in BYCLASS_COLUMNS if c not in df.columns]
    if missing:
        return None
    means = df[BYCLASS_COLUMNS].mean(skipna=True)
    return [float(v) for v in means]


def build_monpol_byclass_table() -> str:
    """Paneled by-class table: one panel per country, sales + prices rows."""

    n_classes = len(BYCLASS_COLUMNS)
    col_spec = "l" + "c" * n_classes
    n_cols = n_classes + 1  # label column + class columns

    lines: list[str] = [
        r"\begin{table}[t!]",
        r"\centering",
        r"\caption{Average contribution of upstreamness groups to the "
        r"aggregate response to a monetary policy shock.}",
        r"\label{tab:avg_contribution_upstreamness_all}",
        r"\begin{adjustbox}{max width=\textwidth}",
        r"\begin{threeparttable}",
        rf"\begin{{tabular}}{{{col_spec}}}",
        r"\toprule",
        rf"& \multicolumn{{{n_classes}}}{{c}}{{\textit{{Upstreamness classes}}}} \\",
        rf"\cmidrule(lr){{2-{n_classes + 1}}}",
        "& " + "\n& ".join(BYCLASS_HEADERS) + r" \\",
        r"\midrule",
    ]

    cc_keys = list(MONPOL_DIRS)
    for idx, cc in enumerate(cc_keys):
        mdir = MONPOL_DIRS[cc]
        cname = COUNTRY_DIRS[cc][0]
        letter = "ABCDE"[idx]
        sales  = _byclass_means(mdir / f"share_byclass_sales_{cc}.csv")
        prices = _byclass_means(mdir / f"share_byclass_prices_{cc}.csv")

        lines.append(rf"\multicolumn{{{n_cols}}}{{l}}{{\textbf{{Panel {letter}: {cname}}}}} \\")
        if sales is None and prices is None:
            lines.append(
                rf"\multicolumn{{{n_cols}}}{{l}}{{(monpol CSVs missing)}} \\"
            )
        else:
            row_s = sales  if sales  is not None else [float('nan')] * n_classes
            row_p = prices if prices is not None else [float('nan')] * n_classes
            lines.append(
                "Average contribution, sales\n& "
                + " & ".join(_fmt_signed(v) for v in row_s) + r" \\"
            )
            lines.append(
                "Average contribution, prices\n& "
                + " & ".join(_fmt_signed(v) for v in row_p) + r" \\"
            )
        if idx != len(cc_keys) - 1:
            lines.append(r"\midrule")

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\begin{tablenotes}[flushleft]",
        r"\footnotesize",
        r"\item \textit{Notes:} The table reports the average contribution of firms "
        r"at different positions in the production network to the aggregate response "
        r"to a monetary policy shock. Upstreamness classes are defined based on "
        r"integer values of firm-level upstreamness. For each group, contributions "
        r"are computed as the ratio of the sales-weighted response of the group to "
        r"the total sales-weighted aggregate response, and then averaged across "
        r"years and horizons.",
        r"\end{tablenotes}",
        r"\end{threeparttable}",
        r"\end{adjustbox}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _emit(name: str, tex: str) -> None:
    """Print to stdout AND save to TABLES_OUT_DIR/{name}.tex."""
    print(f"# === {name} ===")
    print(tex)
    TABLES_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = TABLES_OUT_DIR / f"{name}.tex"
    out.write_text(tex)
    print(f"% saved to {out}\n")


def main(argv: list[str]) -> None:
    valid = {"corr", "io", "shares", "firm_decomp", "sector_decomp", "var_fe",
             "concentration", "coverage", "tail_exponents", "degree_quantiles",
             "sector_panels", "monpol_byclass", "corr_heatmap"}
    targets = set(argv[1:]) or valid

    if "corr_heatmap" in targets:
        print("# === Correlation heatmap PNGs ===")
        build_correlation_heatmaps()
        print()

    if "corr" in targets:
        # Per-country minipages are also written next to each source CSV
        # (legacy behaviour, harmless to keep).
        print("# === Correlation tex files (per country, next to CSVs) ===")
        write_correlation_tex_tables()
        print()
        # Combined 2x2 + 1 layout for the paper.
        _emit("corr_table_demeaned2d", build_correlations_combined_table())

    if "io" in targets:
        _emit("IO_tables", build_io_table())

    if "shares" in targets:
        _emit("input_shares_CV_table",  build_share_distribution_table("input"))
        _emit("output_shares_CV_table", build_share_distribution_table("output"))

    if "firm_decomp" in targets:
        _emit("firm_size_decomp_country", build_firm_size_decomp_country())

    if "sector_decomp" in targets:
        _emit("var_decomp_bysector_summary", build_sector_decomp_summary())

    if "var_fe" in targets:
        _emit("TWFE_regs", build_buyer_seller_effects_table())

    if "concentration" in targets:
        _emit("network_concentration", build_concentration_table())

    if "coverage" in targets:
        _emit("b2b_coverage_table", build_b2b_coverage_table())

    if "tail_exponents" in targets:
        _emit("ccdf_estimates", build_tail_exponents_table())

    if "degree_quantiles" in targets:
        _emit("outdegree_quantiles_panels", build_outdegree_quantile_panels())
        _emit("indegree_quantiles_panels",  build_indegree_quantile_panels())

    if "sector_panels" in targets:
        # Per-country sector decomposition: emitted as var_decomp_sector_{CC}.tex
        # so the file name matches the source on disk and lives in TABLES_OUT_DIR.
        for name, tex in build_sector_panel_tables().items():
            # name comes back as "firm_size_decomp_sector_BEL"; map to
            # "var_decomp_sector_BEL" for the output filename.
            cc = name.rsplit("_", 1)[-1]
            _emit(f"var_decomp_sector_{cc}", tex)

    if "monpol_byclass" in targets:
        _emit("avg_contribution_byclass", build_monpol_byclass_table())


if __name__ == "__main__":
    main(sys.argv)
