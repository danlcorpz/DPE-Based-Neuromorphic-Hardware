"""
data_prep.py -- load MIT-BIH, extract beats, map to AAMI 5 classes, and quantize
each beat to the unsigned 11-bit stream our delta modulator expects.
 
This is shared infrastructure: BOTH the snnTorch trainer and HW_Net consume the
beats this produces, so they see identical input.
 
WHAT IT DOES
------------
1. Reads a record (.dat/.hea/.atr) via the `wfdb` package.
2. Takes channel 0 (MLII) -- the conventional lead for arrhythmia work.
3. For each beat annotation, cuts a fixed 200-sample window centered on the
   R-peak (200 samples @ 360 Hz = 0.556 s, covers one P-QRS-T).
4. Maps the MIT-BIH beat symbol to one of the 5 AAMI classes (N/S/V/F/Q).
5. Quantizes each window to unsigned 11-bit (0..2047) -- the DM's input range.
 
DECISIONS (validated against record 222's real header + annotations)
--------------------------------------------------------------------
- 360 Hz, format 212, gain 200, ADC-zero 1024 -- confirmed from the .hea.
- Channel 0 = MLII.
- 200-sample centered window per beat; beats too close to the record edges
  (window would run off either end) are skipped.
- Per-beat normalization to 0..2047: each beat is scaled using its OWN min/max
  so the DM sees the full dynamic range regardless of baseline wander. (This is
  a choice; see normalize_beat for the alternative.)
 
REQUIREMENTS (install locally -- no network here):
    pip install wfdb numpy
"""
 
import os
import numpy as np
 
try:
    import wfdb
except ImportError:
    wfdb = None
 
 
# ---- AAMI class mapping ------------------------------------------------------
# The 5 AAMI classes and the MIT-BIH beat symbols that map into each.
AAMI_CLASSES = ['N', 'S', 'V', 'F', 'Q']
AAMI_INDEX = {c: i for i, c in enumerate(AAMI_CLASSES)}
 
SYMBOL_TO_AAMI = {
    # N -- normal & bundle-branch/escape beats
    'N': 'N', 'L': 'N', 'R': 'N', 'e': 'N', 'j': 'N',
    # S -- supraventricular ectopic
    'A': 'S', 'a': 'S', 'J': 'S', 'S': 'S',
    # V -- ventricular ectopic
    'V': 'V', 'E': 'V',
    # F -- fusion (ventricular + normal)
    'F': 'F',
    # Q -- unknown / paced / unclassifiable
    '/': 'Q', 'f': 'Q', 'Q': 'Q',
}
# annotation symbols that are NOT beats (rhythm/quality markers) -- always skip
NON_BEAT_SYMBOLS = set('+~|!][."=@x()pt`\' ')
 
# The standard "DS1/DS2" division from de Chazal et al. -- the same split the
# literature (and the reference) uses so train/test don't share a patient.
DS1_TRAIN = [101, 106, 108, 109, 112, 114, 115, 116, 118, 119, 122, 124,
             201, 203, 205, 207, 208, 209, 215, 220, 223, 230]
DS2_TEST = [100, 103, 105, 111, 113, 117, 121, 123, 200, 202, 210, 212,
            213, 214, 219, 221, 222, 228, 231, 232, 233, 234]
 
FS = 360               # sampling frequency (Hz)
BEAT_WINDOW = 200      # samples per beat (our fixed timestep count)
HALF = BEAT_WINDOW // 2
 
 
# ---- beat normalization ------------------------------------------------------
# Counts per millivolt for global normalization. Chosen so a large (~4 mV p-p)
# ventricular beat still fits inside 0..2047 without heavy clipping, while a
# typical ~1 mV normal beat still spans ~400 counts (= ~100 delta-modulator
# steps at step_size 4). That headroom is what preserves the AMPLITUDE
# DIFFERENCE between beat classes.
GLOBAL_GAIN_COUNTS_PER_MV = 400.0
MIDSCALE = 1024          # where the per-beat baseline is parked
 
 
def normalize_beat_global(window, gain=GLOBAL_GAIN_COUNTS_PER_MV,
                          midscale=MIDSCALE, out_max=2047):
    """GLOBAL normalization -- the default, and the one you want.
 
    Removes BASELINE WANDER (which is noise) while PRESERVING AMPLITUDE (which is
    signal). Every beat is scaled by the SAME fixed gain, so a tall ventricular
    beat stays tall relative to a small normal beat.
 
    Why this matters: the old per-beat min/max normalization rescaled every beat
    to span the full 0..2047 range using its OWN min/max, which made a 390-unit
    beat and a 79-unit beat come out identical. On record 222 that discarded a
    4.9x amplitude signal. Since large amplitude is a defining feature of
    ventricular (V) beats, per-beat scaling was deleting one of the two cues that
    define the class we most want to detect.
 
    Method: subtract this beat's own MEDIAN (kills slow baseline drift without
    touching peak height), apply a fixed gain, offset to midscale, clip.
    """
    w = np.asarray(window, dtype=np.float64)
    centered = w - np.median(w)              # baseline removal, amplitude intact
    scaled = centered * gain + midscale
    return np.clip(np.round(scaled), 0, out_max).astype(np.int64)
 
 
def normalize_beat_per_beat(window, out_max=2047):
    """LEGACY per-beat min/max scaling. Maps this beat's own min->0 and max->
    out_max, so every beat fills the full range regardless of true amplitude.
 
    Kept for comparison runs only -- it DESTROYS cross-beat amplitude info (see
    normalize_beat_global). Use it if you want to reproduce the earlier results
    or show the ablation in your write-up.
    """
    w = window.astype(np.float64)
    lo, hi = w.min(), w.max()
    if hi <= lo:
        return np.full_like(w, out_max // 2, dtype=np.int64)
    scaled = (w - lo) / (hi - lo) * out_max
    return np.clip(np.round(scaled), 0, out_max).astype(np.int64)
 
 
# Which normalization the loaders use by default. "global" or "per_beat".
#
# SET TO "per_beat" FOR V2 PAPER MATCHING. This is not because per-beat is
# better -- global normalization genuinely preserves amplitude information that
# per-beat destroys (see normalize_beat_global). It's because per-beat is what
# produces weight magnitudes on the SAME SCALE as the reference's Fig 6.4
# weights, which in turn makes the paper's threshold of ~50 meaningful.
#
# Concretely: per_beat -> quantized weights ~9-10, so threshold 50 = ~5 spikes
# of evidence (matches the paper). global -> quantized weights ~15-18, so the
# equivalent thresholds land in the 100-250 range, and nothing is comparable to
# the published numbers any more.
#
# Switch to "global" for V3, where preserving amplitude should HELP -- and where
# the per_beat vs global comparison becomes a legitimate ablation to report.
NORMALIZE_MODE = "global"   # V3 default: amplitude-preserving (pairs with two DMs). "per_beat"=V2/paper, "global"=V3, or edit normalize_beat for raw.
 
 
def normalize_beat(window, out_max=2047):
    """Dispatch to the configured normalization. Both the wfdb path and the
    pure-Python path call this, so they always agree."""
    if NORMALIZE_MODE == "global":
        return normalize_beat_global(window, out_max=out_max)
    elif NORMALIZE_MODE == "per_beat":
        return normalize_beat_per_beat(window, out_max=out_max)
    raise ValueError(f"NORMALIZE_MODE must be 'global' or 'per_beat', got {NORMALIZE_MODE!r}")
 
 
# ---- per-record beat extraction ---------------------------------------------
def load_record_beats(record_path, channel=0, window=BEAT_WINDOW):
    """Return (beats, labels) for one record.
        beats:  list of np.int64 arrays, each length `window`, values 0..2047
        labels: list of ints 0..4 (AAMI class index)
 
    record_path: path WITHOUT extension, e.g. '/data/mitbih/222'
    """
    if wfdb is None:
        raise ImportError("wfdb not installed. Run: pip install wfdb numpy")
 
    rec = wfdb.rdrecord(record_path)             # reads .dat + .hea
    ann = wfdb.rdann(record_path, 'atr')         # reads .atr
 
    sig = rec.p_signal[:, channel]               # physical units, channel 0 = MLII
    n = len(sig)
 
    beats, labels = [], []
    half = window // 2
    for samp, sym in zip(ann.sample, ann.symbol):
        if sym in NON_BEAT_SYMBOLS:
            continue
        cls = SYMBOL_TO_AAMI.get(sym)
        if cls is None:
            continue                             # unmapped symbol -> skip
        start = samp - half
        stop = samp + (window - half)
        if start < 0 or stop > n:
            continue                             # window runs off the record edge
        win = sig[start:stop]
        beats.append(normalize_beat(win))
        labels.append(AAMI_INDEX[cls])
    return beats, labels
 
 
# ---- dataset assembly --------------------------------------------------------
def load_dataset(data_dir, record_numbers, channel=0):
    """Load and concatenate beats from a list of record numbers.
        returns (beats, labels) across all records.
    data_dir: folder containing the .dat/.hea/.atr files.
    """
    all_beats, all_labels = [], []
    for num in record_numbers:
        path = os.path.join(data_dir, str(num))
        if not os.path.exists(path + '.dat'):
            print(f"  [skip] record {num}: {path}.dat not found")
            continue
        b, l = load_record_beats(path, channel=channel)
        all_beats.extend(b)
        all_labels.extend(l)
        print(f"  record {num}: {len(b)} beats")
    return all_beats, all_labels
 
 
def class_distribution(labels):
    """Print and return the per-class counts + percentages."""
    counts = [0] * len(AAMI_CLASSES)
    for l in labels:
        counts[l] += 1
    total = max(1, sum(counts))
    print("Class distribution:")
    for i, c in enumerate(AAMI_CLASSES):
        print(f"  {c}: {counts[i]:6d} ({100*counts[i]/total:5.2f}%)")
    return counts
 
 
def load_train_test(data_dir):
    """Load the standard DS1 (train) / DS2 (test) inter-patient split."""
    print("=== TRAIN (DS1) ===")
    train_beats, train_labels = load_dataset(data_dir, DS1_TRAIN)
    class_distribution(train_labels)
    print("\n=== TEST (DS2) ===")
    test_beats, test_labels = load_dataset(data_dir, DS2_TEST)
    class_distribution(test_labels)
    return (train_beats, train_labels), (test_beats, test_labels)
 
 
if __name__ == "__main__":
    import sys
    # Usage: python data_prep.py /path/to/mitbih_folder [record_number]
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    if len(sys.argv) > 2:
        # single-record smoke test
        num = sys.argv[2]
        path = os.path.join(data_dir, num)
        beats, labels = load_record_beats(path)
        print(f"Record {num}: {len(beats)} beats extracted")
        class_distribution(labels)
        if beats:
            b = beats[0]
            print(f"\nFirst beat: {len(b)} samples, "
                  f"range [{b.min()}, {b.max()}], first 10: {b[:10].tolist()}")
    else:
        # full DS1/DS2 load
        load_train_test(data_dir)