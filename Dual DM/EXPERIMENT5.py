"""
experiment4.py -- V4 iteration cockpit (per-class threshold / param sweep).

Loads the weights train_dpe3.py trained + quantized (trained_weights_v3.npz) and
sweeps HARDWARE parameters (per-neuron thresholds, leak_rate, refractory) through
HW_Net3 on the DS2 test set. No torch, no retraining -- runs in seconds.

V3 vs V2: HW_Net3 has TWO delta modulators, so weights are 4 rows per neuron
(coarse_up, coarse_down, fine_up, fine_down) = a flat vector of length 20, and
the DM step sizes are (coarse, fine). Keep the DM steps FIXED at the values the
weights were TRAINED with (train_dpe3.py: coarse=12, fine=1) -- changing them
re-encodes the input away from what the weights expect.

EVERY run appends to results_v3.csv.

Run:
    python experiment3.py /path/to/mitbih         (or set DATA_DIR below)
"""
import sys
import csv
import os
import itertools
import numpy as np

from DataPrep5 import load_dataset, DS2_TEST, AAMI_CLASSES, class_distribution
from RTLPythonMirror5 import Net

DATA_DIR = r"C:\Users\sidew\OneDrive\Desktop\LAB\RESEARCH\mitbih"     # set to your mitbih folder, or pass as argv[1]

N_NEURONS = 5
N_INPUTS  = 4

# The DM step sizes the weights were trained with -- keep these fixed.
DM_STEP_COARSE = 80
DM_STEP_FINE = 12


# ---- THRESHOLD UNITS --------------------------------------------------------
# "raw"    : thresholds are literal membrane-potential counts (scan-chain values).
# "spikes" : thresholds as "how many input spikes of evidence" -> converted to raw
#            using each neuron's dominant weight (portable across quantizer rescales).
THRESHOLD_UNITS = "raw"


def spikes_to_raw(threshold_spikes, flat_weights, n_neurons=N_NEURONS, n_inputs=N_INPUTS):
    """Convert per-neuron 'spikes of evidence' thresholds into raw counts, using
    each neuron's strongest of its FOUR synapse weights."""
    raw = []
    for j, ts in enumerate(threshold_spikes):
        drive = max(abs(flat_weights[r * n_neurons + j]) for r in range(n_inputs)) or 1
        raw.append(max(1, int(round(ts * drive))))
    return raw


# ============================================================ CHOOSE YOUR MODE
MODE = "grid"          # "list" (hand-picked configs) or "grid" (auto sweep)

# ---- WEIGHT SOURCE ----------------------------------------------------------
# "file" : load trained weights from trained_weights_v3.npz (normal workflow).
# "list" : use the hand-written WEIGHT_SETS below (design/probe weights yourself).
WEIGHT_SOURCE = "file"

# Hand-written weight sets, per-neuron (coarse_up, coarse_down, fine_up, fine_down).
# Integers in [-32, 31]. Example below is the trained V4 set from a real run.
WEIGHT_SETS = {
    "trained_v4_example": [(0, 0), (1, -1), (-7, 5),
                           (2, 3), (-8, 5)],
}
ACTIVE_WEIGHT_SETS = ["trained_v4_example"]


def weights_to_flat(per_neuron, n_neurons=N_NEURONS):
    """Convert [(cUP,cDN,fUP,fDN), ...] into the flat vector HW_Net3 indexes as
    weights[row*n_neurons + j].  row 0=coarse-up 1=coarse-down 2=fine-up 3=fine-down."""
    n_inputs = len(per_neuron[0])
    assert len(per_neuron) == n_neurons, f"need {n_neurons} tuples"
    flat = [0] * (n_inputs * n_neurons)
    for j, tup in enumerate(per_neuron):
        for r, w in enumerate(tup):
            flat[r * n_neurons + j] = int(w)
    return flat


# ---- LIST MODE: hand-picked configs -----------------------------------------
# thresholds: 5 per-neuron values. DM steps fixed to the training values.
HANDPICKED_CONFIGS = [
    {"thresholds": [50, 50, 50, 10, 50], "leak_rate": 12, "refractory": 2},
    {"thresholds": [50, 50, 50, 20, 50], "leak_rate": 12, "refractory": 2},
    {"thresholds": [50, 50, 50, 30, 50], "leak_rate": 12, "refractory": 2},
    {"thresholds": [50, 50, 50, 40, 50], "leak_rate": 12, "refractory": 2},
    {"thresholds": [50, 50, 50, 50, 50], "leak_rate": 12, "refractory": 2},
    {"thresholds": [50, 50, 50, 60, 50], "leak_rate": 12, "refractory": 2},
    ]

# ---- GRID MODE: sweep ranges -------------------------------------------------
GRID_THRESHOLDS = [20, 30, 40, 60, 70, 80, 90, 100, 110, 120]   # applied to all 5 neurons (coarse pass)
GRID_LEAK       = [4, 8, 12, 16, 20]
GRID_REFRAC     = [2]


# ============================================================ core evaluation
def evaluate_config(net_weights, thresholds, leak_rate, refractory,
                    beats, labels, n_neurons=N_NEURONS):
    net = Net(weights=net_weights, thresholds=thresholds,
                  leak_rate=leak_rate, refractory_period=refractory,
                  dm_step_coarse=DM_STEP_COARSE, dm_step_fine=DM_STEP_FINE, n_neurons=n_neurons, n_inputs=N_INPUTS)
    n_cls = len(AAMI_CLASSES)
    confusion = np.zeros((n_cls, n_cls), dtype=np.int64)
    for beat, true in zip(beats, labels):
        pred, _ = net.classify_beats(list(beat))
        confusion[true, pred] += 1
    return confusion


def summarize(confusion):
    n = len(AAMI_CLASSES)
    total = confusion.sum()
    correct = sum(confusion[i, i] for i in range(n))
    per_class = {}
    for i, c in enumerate(AAMI_CLASSES):
        row = confusion[i].sum()
        per_class[c] = (confusion[i, i] / row) if row > 0 else 0.0
    return (correct / max(1, total)), per_class


def print_confusion(confusion, config_label):
    n = len(AAMI_CLASSES)
    print(f"\n--- {config_label} ---")
    print("Confusion (rows=true, cols=pred):")
    print("      " + "".join(f"{c:>8}" for c in AAMI_CLASSES))
    for i, c in enumerate(AAMI_CLASSES):
        print(f"  {c:>3} " + "".join(f"{confusion[i,j]:>8d}" for j in range(n)))
    overall, per_class = summarize(confusion)
    print("per-class TP: " + "  ".join(f"{c}={per_class[c]:.3f}" for c in AAMI_CLASSES))
    print(f"overall: {overall:.4f}")
    return overall, per_class


def build_configs():
    if MODE == "list":
        return HANDPICKED_CONFIGS
    elif MODE == "grid":
        configs = []
        for thr, leak, refrac in itertools.product(GRID_THRESHOLDS, GRID_LEAK, GRID_REFRAC):
            configs.append({"thresholds": [thr] * N_NEURONS, "leak_rate": leak, "refractory": refrac})
        return configs
    raise ValueError(f"MODE must be 'list' or 'grid', got {MODE!r}")


def weight_angles_report(flat_weights, n_neurons=N_NEURONS, n_inputs=N_INPUTS, label=""):
    """Angular spread of the weight set in 4-D (cosine-based). Higher min pairwise
    angle = more distinct detectors (in 4-D, up to 90 deg for orthogonal)."""
    import math
    w = np.array([[flat_weights[r * n_neurons + j] for r in range(n_inputs)]
                  for j in range(n_neurons)], dtype=float)
    norms = np.linalg.norm(w, axis=1, keepdims=True); norms[norms == 0] = 1e-8
    wn = w / norms
    min_ang = 180.0
    for i in range(n_neurons):
        for j in range(i + 1, n_neurons):
            c = float(np.clip(np.dot(wn[i], wn[j]), -1.0, 1.0))
            min_ang = min(min_ang, math.degrees(math.acos(abs(c))))
    print(f"  [{label}] min pairwise angle = {min_ang:.1f} deg (higher = more distinct)")
    return min_ang


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    if not data_dir:
        print("No data folder. Set DATA_DIR at the top, or:  python experiment3.py /path/to/mitbih")
        sys.exit(1)

    # ---- assemble weight sets ----
    weight_variants = []
    if WEIGHT_SOURCE == "file":
        if not os.path.exists("trained_weights_v5.npz"):
            print("trained_weights_v5.npz not found -- run train_dpe5.py first, "
                  "or set WEIGHT_SOURCE='list'.")
            sys.exit(1)
        data = np.load("trained_weights_v5.npz")
        flat = [int(x) for x in data["hw_weights"]]
        weight_variants.append(("from_file", flat))
        print("Loaded trained V4 weights (len %d): %s" % (len(flat), flat))
    elif WEIGHT_SOURCE == "list":
        for name in ACTIVE_WEIGHT_SETS:
            if name in WEIGHT_SETS:
                weight_variants.append((name, weights_to_flat(WEIGHT_SETS[name])))
        print(f"Using {len(weight_variants)} hand-written weight set(s).")
    else:
        raise ValueError(f"WEIGHT_SOURCE must be 'file' or 'list', got {WEIGHT_SOURCE!r}")

    print("\nAngular spread of each weight set:")
    for name, flat in weight_variants:
        weight_angles_report(flat, label=name)

    print("\nLoading DS2 test set...")
    test_beats, test_labels = load_dataset(data_dir, DS2_TEST)
    class_distribution(test_labels)
    if len(test_beats) == 0:
        print("No test beats loaded -- check data path."); sys.exit(1)

    configs = build_configs()
    total_runs = len(weight_variants) * len(configs)
    print(f"\nMODE={MODE}, WEIGHT_SOURCE={WEIGHT_SOURCE}: "
          f"{len(weight_variants)} weight set(s) x {len(configs)} config(s) = {total_runs} run(s)\n")

    log_exists = os.path.exists("results_v5.csv")
    logf = open("results_v5.csv", "a", newline="")
    writer = csv.writer(logf)
    if not log_exists:
        writer.writerow(["weight_set", "weights", "thresholds", "leak_rate", "refractory",
                         "dm_c", "dm_f", "overall", "TP_N", "TP_S", "TP_V", "TP_F", "TP_Q"])

    best = None; run = 0
    for wname, flat in weight_variants:
        for cfg in configs:
            run += 1
            raw_thr = spikes_to_raw(cfg["thresholds"], flat) if THRESHOLD_UNITS == "spikes" else list(cfg["thresholds"])
            label = (f"run {run}/{total_runs} | weights={wname} | thr={cfg['thresholds']}"
                     f"{'sp' if THRESHOLD_UNITS=='spikes' else ''}->raw{raw_thr} "
                     f"leak={cfg['leak_rate']} refrac={cfg['refractory']}")
            confusion = evaluate_config(flat, raw_thr, cfg["leak_rate"], cfg["refractory"],
                                        test_beats, test_labels)
            overall, per_class = print_confusion(confusion, label)
            writer.writerow([wname, "|".join(map(str, flat)), "|".join(map(str, raw_thr)),
                             cfg["leak_rate"], cfg["refractory"], DM_STEP_COARSE, DM_STEP_FINE,
                             f"{overall:.4f}"] + [f"{per_class[c]:.4f}" for c in AAMI_CLASSES])
            minority_score = (per_class["S"] + per_class["V"] + per_class["F"]) / 3
            if best is None or minority_score > best[0]:
                best = (minority_score, label, overall)

    logf.close()
    print("\n" + "=" * 60)
    print(f"Best minority-class run:\n  {best[1]}")
    print(f"  (mean S/V/F TP = {best[0]:.3f}, overall = {best[2]:.3f})")
    print("All runs appended to results_v5.csv")


if __name__ == "__main__":
    main()