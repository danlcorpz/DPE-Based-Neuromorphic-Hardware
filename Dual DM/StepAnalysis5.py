"""
StepAnalysis5.py -- quantitative delta-modulator step-size chooser (V5, two-DM).

For a grid of candidate DM step sizes, this runs the SAME DeltaMod the mirror and
hardware use over the DS1 training beats and reports, PER AAMI CLASS, how many
spikes each step produces -- overall and split into ECG regions (pre/P, QRS, T,
baseline) using the R-centered 200-sample window. It also scores how well each
step SEPARATES the minority classes from N by spike count (Cohen's d).

Why this exists: the step size decides what the DM can see.
  * too SMALL -> it fires on baseline noise: dense, near the dead-cycle ceiling,
    low information -- this is what made the single-DM run collapse.
  * too LARGE -> it only catches the QRS and misses the P/T detail that
    distinguishes S and F from N.
The two DMs are INDEPENDENT, so you analyze each candidate step once and read off
the table: pick a COARSE step where a big-amplitude class (V) separates from N,
and a FINE step where the subtle classes (S, F) separate while baseline stays low.

This does NOT need torch. It needs numpy, DataPrep5 (for the beats) and
RTLPythonMirror5 (for DeltaMod). Runs in seconds.

Run:
    python StepAnalysis5.py /path/to/mitbih
    # or set DATA_DIR below. Add a second arg 'test' to test on DS2 instead of DS1.
"""
import sys
import csv
import numpy as np

from DataPrep5 import load_dataset, DS1_TRAIN, DS2_TEST, AAMI_CLASSES, class_distribution
from RTLPythonMirror5 import DeltaMod

DATA_DIR = None   # set to your mitbih folder, or pass as argv[1]

# ---- candidate steps to evaluate (edit freely) ------------------------------
# spans the noisy/dense regime (small) up to QRS-only (large).
STEPS = [4, 6, 8, 12, 16, 20, 30, 40, 60, 80, 100, 120]

# ---- ECG regions inside the R-centered 200-sample window --------------------
# Beats are cut +/- 100 samples around the R-peak (DataPrep5 BEAT_WINDOW=200,
# HALF=100), so the R-peak sits at index ~100. These bounds are HEURISTIC, only
# used for the per-region breakdown -- the per-class TOTAL is the primary signal.
R_INDEX     = 100
P_REGION    = (28, 58)     # atrial P-wave, ~120-200 ms before R
QRS_REGION  = (82, 118)    # the R complex itself
T_REGION    = (150, 195)   # ventricular repolarization, after R
# everything else counts as "baseline" (isoelectric segments + noise)


def region_of(i):
    if P_REGION[0]   <= i < P_REGION[1]:   return "P"
    if QRS_REGION[0] <= i < QRS_REGION[1]: return "QRS"
    if T_REGION[0]   <= i < T_REGION[1]:   return "T"
    return "base"


def beat_spikes(beat, step_size):
    """Run the DM over one beat. Returns (total, up, down, region_counts dict).
    Uses the mirror's DeltaMod so counts match the hardware encoding exactly."""
    dm = DeltaMod()
    dm.reset()
    up = down = 0
    reg = {"P": 0, "QRS": 0, "T": 0, "base": 0}
    for i, s in enumerate(beat):
        u, d = dm.step(int(s), step_size, 1)
        up += u
        down += d
        if u or d:
            reg[region_of(i)] += (u + d)
    return up + down, up, down, reg


def analyze_step(beats, labels, step_size, n_classes=5):
    """Per-class spike statistics for one step size.
    Returns dict: class_idx -> {n, total[], up[], down[], P[], QRS[], T[], base[]}"""
    acc = {c: {"total": [], "up": [], "down": [],
               "P": [], "QRS": [], "T": [], "base": []} for c in range(n_classes)}
    for beat, lab in zip(beats, labels):
        tot, up, dn, reg = beat_spikes(beat, step_size)
        a = acc[lab]
        a["total"].append(tot); a["up"].append(up); a["down"].append(dn)
        a["P"].append(reg["P"]); a["QRS"].append(reg["QRS"])
        a["T"].append(reg["T"]); a["base"].append(reg["base"])
    return acc


def cohens_d(x, y):
    """Standardized mean difference between two samples (separability, unit=pooled std).
    |d| ~ 0.2 small, 0.5 medium, 0.8+ large. Sign: + means x has MORE spikes than y."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 2 or len(y) < 2:
        return 0.0
    nx, ny = len(x), len(y)
    sp2 = ((nx - 1) * x.var(ddof=1) + (ny - 1) * y.var(ddof=1)) / (nx + ny - 2)
    sp = np.sqrt(sp2) if sp2 > 0 else 1e-9
    return float((x.mean() - y.mean()) / sp)


def summarize(step_size, acc, n_index):
    """Print the per-class table for one step + return CSV rows and a separation dict."""
    print(f"\n================ step = {step_size} ================")
    print(f"{'class':>5} {'n':>6} {'mean':>7} {'std':>6} | {'P':>5} {'QRS':>5} {'T':>5} {'base':>6}  {'d_vs_N':>7}")
    n_totals = acc[n_index]["total"]
    csv_rows = []
    seps = {}
    for c in range(len(AAMI_CLASSES)):
        a = acc[c]
        n = len(a["total"])
        if n == 0:
            print(f"{AAMI_CLASSES[c]:>5} {0:>6}   (no samples)")
            csv_rows.append([step_size, AAMI_CLASSES[c], 0, 0, 0, 0, 0, 0, 0, 0.0])
            continue
        mt = np.mean(a["total"]); st = np.std(a["total"])
        mP = np.mean(a["P"]); mQ = np.mean(a["QRS"]); mT = np.mean(a["T"]); mB = np.mean(a["base"])
        d = cohens_d(a["total"], n_totals) if c != n_index else 0.0
        seps[AAMI_CLASSES[c]] = d
        print(f"{AAMI_CLASSES[c]:>5} {n:>6} {mt:>7.1f} {st:>6.1f} | "
              f"{mP:>5.1f} {mQ:>5.1f} {mT:>5.1f} {mB:>6.1f}  {d:>7.2f}")
        csv_rows.append([step_size, AAMI_CLASSES[c], n, round(mt, 2), round(st, 2),
                         round(mP, 2), round(mQ, 2), round(mT, 2), round(mB, 2), round(d, 3)])
    # saturation hint: high baseline mean OR mean total near the ~100 dead-cycle ceiling
    n_mean_total = np.mean(n_totals) if n_totals else 0.0
    n_mean_base = np.mean(acc[n_index]["base"]) if n_totals else 0.0
    flag = ""
    if n_mean_total > 80:  flag = "  <- SATURATING (near dead-cycle ceiling)"
    elif n_mean_base > 0.30 * n_mean_total and n_mean_total > 0: flag = "  <- noisy baseline (small step)"
    print(f"   N mean total={n_mean_total:.1f}  N baseline={n_mean_base:.1f}{flag}")
    return csv_rows, seps


def main():
    args = [a for a in sys.argv[1:]]
    data_dir = args[0] if args else DATA_DIR
    use_test = (len(args) > 1 and args[1].lower() == "test")
    if not data_dir:
        print("No data folder. Set DATA_DIR at the top, or: python StepAnalysis5.py /path/to/mitbih")
        sys.exit(1)

    records = DS2_TEST if use_test else DS1_TRAIN
    print(f"Loading {'DS2 (test)' if use_test else 'DS1 (train)'} beats...")
    beats, labels = load_dataset(data_dir, records)
    class_distribution(labels)
    if len(beats) == 0:
        print("No beats loaded -- check the data path."); sys.exit(1)

    n_index = AAMI_CLASSES.index("N")

    all_rows = []
    sep_by_step = {}   # step -> {class: d_vs_N}
    for step in STEPS:
        acc = analyze_step(beats, labels, step)
        rows, seps = summarize(step, acc, n_index)
        all_rows.extend(rows)
        sep_by_step[step] = seps

    # ---- write CSV for plotting ----
    with open("step_analysis5.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["step", "class", "n", "mean_total", "std_total",
                    "mean_P", "mean_QRS", "mean_T", "mean_base", "cohens_d_vs_N"])
        w.writerows(all_rows)

    # ---- recommendation summary ----
    print("\n" + "=" * 64)
    print("SEPARATION FROM N (|Cohen's d| of total spikes, higher = more separable)")
    print(f"{'step':>5} | " + "  ".join(f"{c:>6}" for c in ["S", "V", "F", "Q"]))
    for step in STEPS:
        s = sep_by_step[step]
        print(f"{step:>5} | " + "  ".join(f"{abs(s.get(c, 0.0)):>6.2f}" for c in ["S", "V", "F", "Q"]))

    def best_for(cls):
        return max(STEPS, key=lambda st: abs(sep_by_step[st].get(cls, 0.0)))
    print("\nSuggested reads (confirm against the confusion sweep):")
    print(f"  COARSE candidate  -> step {best_for('V')}  (max V-vs-N separation; V is amplitude-driven)")
    sf = {st: (abs(sep_by_step[st].get('S', 0)) + abs(sep_by_step[st].get('F', 0))) / 2 for st in STEPS}
    best_sf = max(STEPS, key=lambda st: sf[st])
    print(f"  FINE candidate    -> step {best_sf}  (max mean S/F-vs-N separation; those need P/T detail)")
    print("\nWrote step_analysis5.csv (one row per step x class).")


if __name__ == "__main__":
    main()