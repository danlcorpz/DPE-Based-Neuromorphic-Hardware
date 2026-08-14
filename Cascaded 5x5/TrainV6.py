import sys
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import snntorch as snn
from snntorch import surrogate

from DataPrep6 import (load_dataset, DS1_TRAIN, DS2_TEST, AAMI_CLASSES,
                       class_distribution)
from Quantize6 import quantize_weights, to_hw_weight_list
from RTLPythonMirror6 import Net

# --- pointer to your data (a command-line arg overrides this) ---
DATA_DIR = r"C:\Users\sidew\OneDrive\Desktop\LAB\RESEARCH\mitbih"

# --- network shape ---
N_INPUTS_1  = 2      # DM up/down
N_NEURONS_1 = 5      # hidden / feature layer
N_NEURONS_2 = 5      # output classes

# --- tuning knobs ---
EPOCHS           = 30
LEARNING_RATE    = 1e-3
BATCH_SIZE       = 128
CLASS_WEIGHT_CAP = 50.0
WEIGHT_DECAY     = 0.5

DIVERSITY_WEIGHT = 0.0
BETA             = 0.95
SEED             = 2
DM_STEP          = 8

# --- layer 1 liveness controls (training-side only) ---
TRAIN_THRESH_1   = 0.5    # snnTorch firing threshold for the hidden layer
TRAIN_THRESH_2   = 1.0    # snnTorch firing threshold for the output layer
INIT_GAIN_1      = 2.0    # scale up fc1 init so layer 1 spikes from epoch 1
L1_RATE_TARGET   = 0.05   # desired mean layer-1 spikes per neuron per timestep
L1_RATE_WEIGHT   = 1.0    # penalty pushing layer 1 UP toward the target (0 = off)

# --- hardware eval parameters (None -> auto-scale from quantized weights) ---
EVAL_THRESHOLDS_1 = None
EVAL_THRESHOLDS_2 = None
SOE_1             = 2      # layer 1: spikes of evidence to fire (keep low)
SOE_2             = 2      # layer 2: spikes of evidence to fire
EVAL_LEAK_1       = 8
EVAL_LEAK_2       = 4
EVAL_REFRAC_1     = 1
EVAL_REFRAC_2     = 1

# Pure-Python mirror is slow: ~200 timesteps x 35 synapses per beat. Cap the
# eval set while iterating, then set to None for the final number.
EVAL_MAX_BEATS   = 4000


def delta_modulate(beat, step_size, max_val=2047, min_val=0):
    n = len(beat)
    up = np.zeros(n, dtype=np.float32); down = np.zeros(n, dtype=np.float32)
    approx = int(beat[0]); last_spike = False
    for t in range(1, n):
        x = int(beat[t])
        if last_spike:
            last_spike = False; continue
        if x > approx + step_size:
            up[t] = 1.0; approx = min(approx + step_size, max_val); last_spike = True
        elif x + step_size < approx:
            down[t] = 1.0; approx = max(approx - step_size, min_val); last_spike = True
    return up, down


def beats_to_spike_tensor(beats, step_coarse=DM_STEP):
    """One DM per beat -> 2 channels [up, down]."""
    T = len(beats[0])
    X = np.zeros((len(beats), T, 2), dtype=np.float32)
    for i, beat in enumerate(beats):
        b = np.asarray(beat)
        u, d = delta_modulate(b, step_coarse)
        X[i, :, 0] = u; X[i, :, 1] = d
    return torch.from_numpy(X)


class DPE_Train(nn.Module):
    """Cascaded 2 -> 5 -> 5 spiking network.

    Two SEPARATE snn.Leaky instances, each with its own membrane state carried
    through the timestep loop. Reusing one Leaky for both layers would share
    state between them and silently break the model.
    """
    def __init__(self, n_in=N_INPUTS_1, n_hid=N_NEURONS_1, n_out=N_NEURONS_2,
                 beta=0.95, thresh1=TRAIN_THRESH_1, thresh2=TRAIN_THRESH_2,
                 init_gain1=INIT_GAIN_1):
        super().__init__()
        self.n_hid, self.n_out = n_hid, n_out
        self.fc1  = nn.Linear(n_in,  n_hid, bias=False)   # (5,2): cols=[up, down]
        self.lif1 = snn.Leaky(beta=beta, threshold=thresh1,
                              spike_grad=surrogate.fast_sigmoid(), init_hidden=False)
        self.fc2  = nn.Linear(n_hid, n_out, bias=False)   # (5,5): cols=layer-1 neurons
        self.lif2 = snn.Leaky(beta=beta, threshold=thresh2,
                              spike_grad=surrogate.fast_sigmoid(), init_hidden=False)
        if init_gain1 != 1.0:
            with torch.no_grad():
                self.fc1.weight.mul_(init_gain1)

    def forward(self, x):                        # x: (batch, T, 2)
        batch, T, _ = x.shape
        mem1 = self.lif1.init_leaky()
        mem2 = self.lif2.init_leaky()
        out_count = torch.zeros(batch, self.n_out, device=x.device)
        hid_count = torch.zeros(batch, self.n_hid, device=x.device)
        for t in range(T):
            cur1 = self.fc1(x[:, t, :])
            spk1, mem1 = self.lif1(cur1, mem1)
            cur2 = self.fc2(spk1)
            spk2, mem2 = self.lif2(cur2, mem2)
            out_count = out_count + spk2
            hid_count = hid_count + spk1
        return out_count, hid_count, T


def inverse_frequency_weights(labels, n_classes=5, cap=50.0, q_index=4, q_weight=0.1):
    counts = np.bincount(labels, minlength=n_classes).astype(np.float64)
    counts[counts == 0] = 1.0
    w = np.clip(counts.sum() / (n_classes * counts), None, cap)
    w[q_index] = q_weight          # Q basically ignored; the other four stay inverse-frequency
    return torch.tensor(w, dtype=torch.float32)


def diversity_loss(weight_matrix):
    w = weight_matrix
    wn = w / torch.norm(w, dim=1, keepdim=True).clamp(min=1e-8)
    gram = wn @ wn.t(); n = gram.shape[0]
    off = gram - torch.diag(torch.diag(gram))
    return (off ** 2).sum() / (n * (n - 1))


def train(model, X, y, class_weights, epochs=30, batch_size=128, lr=1e-3,
          weight_decay=0.0, diversity_weight=0.0,
          l1_rate_target=L1_RATE_TARGET, l1_rate_weight=L1_RATE_WEIGHT,
          verbose=True):
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    loss_fn = nn.CrossEntropyLoss(weight=class_weights)
    N = X.shape[0]
    for epoch in range(epochs):
        perm = torch.randperm(N); total = 0.0; rate_sum = 0.0; seen = 0
        for i in range(0, N, batch_size):
            idx = perm[i:i + batch_size]; xb, yb = X[idx], y[idx]
            opt.zero_grad()
            out, hid, T = model(xb)
            loss = loss_fn(out, yb)
            if diversity_weight > 0.0:
                loss = loss + diversity_weight * diversity_loss(model.fc1.weight)
            # one-sided penalty: pushes layer 1 UP if it is too quiet, and does
            # nothing once it is above target, so it never fights the CE loss
            rate = hid.mean() / T
            if l1_rate_weight > 0.0:
                loss = loss + l1_rate_weight * F.relu(l1_rate_target - rate) ** 2
            loss.backward(); opt.step()
            total += loss.item() * len(idx)
            rate_sum += rate.item() * len(idx); seen += len(idx)
        if verbose and ((epoch + 1) % 5 == 0 or epoch == 0):
            print(f"  epoch {epoch+1:3d}/{epochs}  loss={total/N:.4f}  L1 rate={rate_sum/seen:.4f}")
            if rate_sum / seen < 1e-4:
                print("     *** layer 1 is silent -- lower WEIGHT_DECAY / TRAIN_THRESH_1, "
                      "or raise INIT_GAIN_1 ***")
    return model


def auto_thresholds(q, soe):
    """threshold_j ~ soe spikes of the strongest synapse into neuron j."""
    return [max(1, int(round(soe * max(1, int(np.abs(q[j]).max())))))
            for j in range(q.shape[0])]


def subsample(beats, labels, max_beats, seed=0):
    """Stratified subsample so rare classes survive the cut."""
    if max_beats is None or len(beats) <= max_beats:
        return beats, labels
    rng = np.random.default_rng(seed)
    labels = np.asarray(labels)
    keep = []
    frac = max_beats / len(labels)
    for c in range(len(AAMI_CLASSES)):
        idx = np.flatnonzero(labels == c)
        if len(idx) == 0:
            continue
        n = max(1, int(round(len(idx) * frac)))
        keep.extend(rng.choice(idx, size=min(n, len(idx)), replace=False).tolist())
    keep.sort()
    return [beats[i] for i in keep], [int(labels[i]) for i in keep]


def evaluate_on_hardware(hw_w1, hw_w2, th1, th2, beats, labels,
                         leak1, leak2, refrac1, refrac2, dm_step):
    net = Net(weights_1=hw_w1, weights_2=hw_w2,
              thresholds_1=th1, thresholds_2=th2,
              leak_rate_1=leak1, leak_rate_2=leak2,
              refractory_period_1=refrac1, refractory_period_2=refrac2,
              dm_step=dm_step,
              n_inputs_1=N_INPUTS_1, n_neurons_1=N_NEURONS_1, n_neurons_2=N_NEURONS_2)
    confusion   = np.zeros((5, 5), dtype=np.int64)
    no_decision = np.zeros(5, dtype=np.int64)
    l1_tot = np.zeros(N_NEURONS_1, dtype=np.float64)
    l2_tot = np.zeros(N_NEURONS_2, dtype=np.float64)
    dm_tot = 0.0
    for beat, true in zip(beats, labels):
        pred, _win, diag = net.classify_beats(list(beat))
        if pred is None:
            no_decision[true] += 1
        else:
            confusion[true, pred] += 1
        l1_tot += np.asarray(diag["l1_counts"], dtype=np.float64)
        l2_tot += np.asarray(diag["l2_counts"], dtype=np.float64)
        dm_tot += diag["dm_spikes"]
    n = max(1, len(beats))
    return confusion, no_decision, l1_tot / n, l2_tot / n, dm_tot / n


def diagnose_weights(float_w, label="[UP,DN]", quiet=False):
    import math
    n = float_w.shape[0]
    if not quiet:
        print(f"\nPer-neuron learned weights (row=neuron  {label}):")
        for j in range(n):
            print(f"   neuron {j}: " + " ".join(f"{float_w[j,c]:+.3f}" for c in range(float_w.shape[1])))
    wn = float_w / np.clip(np.linalg.norm(float_w, axis=1, keepdims=True), 1e-8, None)
    min_angle, cos_sum, pairs = 180.0, 0.0, 0
    for i in range(n):
        for j in range(i + 1, n):
            c = float(np.clip(np.dot(wn[i], wn[j]), -1.0, 1.0))
            min_angle = min(min_angle, math.degrees(math.acos(abs(c))))
            cos_sum += abs(c); pairs += 1
    if not quiet:
        print(f"   angular spread: min pairwise angle = {min_angle:.1f} deg, mean |cos| = {cos_sum/max(1,pairs):.3f}")
        print("   *** COLLAPSED ***" if min_angle < 5 else ("   PARTIAL collapse." if min_angle < 15 else "   good spread."))
    return min_angle, cos_sum / max(1, pairs)


def print_confusion(confusion, no_decision=None):
    n = len(AAMI_CLASSES)
    print("\nConfusion Matrix (rows=true, cols=predicted):")
    header = "        " + "".join(f"{c:>8}" for c in AAMI_CLASSES)
    if no_decision is not None:
        header += f"{'silent':>8}"
    print(header)
    for i, c in enumerate(AAMI_CLASSES):
        row = f"   {c:>3}  " + "".join(f"{confusion[i,j]:>8d}" for j in range(n))
        if no_decision is not None:
            row += f"{no_decision[i]:>8d}"
        print(row)
    print("\nPer-class accuracy (true positive rate):")
    total_correct, recs = 0, []
    total = confusion.sum() + (no_decision.sum() if no_decision is not None else 0)
    for i, c in enumerate(AAMI_CLASSES):
        row = confusion[i].sum() + (no_decision[i] if no_decision is not None else 0)
        tp = confusion[i, i]; total_correct += tp
        if row > 0:
            recs.append(tp/row); print(f"   {c}: {tp}/{row} = {tp/row:.4f}")
        else:
            print(f"   {c}: (no samples)")
    print(f"\nOverall: {total_correct}/{total} = {total_correct/max(1,total):.4f}")
    print(f"Macro-recall (class-balanced): {np.mean(recs):.4f}")
    if no_decision is not None and no_decision.sum() > 0:
        print(f"Beats with NO layer-2 spike at all: {no_decision.sum()} "
              f"({100*no_decision.sum()/max(1,total):.2f}%)")


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    if not data_dir:
        print("No data folder. Set DATA_DIR at the top, or:  python TrainV61.py /path/to/mitbih")
        sys.exit(1)
    torch.manual_seed(SEED); np.random.seed(SEED)

    print("Loading TRAIN (DS1)..."); train_beats, train_labels = load_dataset(data_dir, DS1_TRAIN)
    class_distribution(train_labels)
    print("\nLoading TEST (DS2)..."); test_beats, test_labels = load_dataset(data_dir, DS2_TEST)
    class_distribution(test_labels)
    if len(train_beats) == 0 or len(test_beats) == 0:
        print("\nNo beats loaded -- check the records are in", data_dir); sys.exit(1)

    print(f"\nDelta-modulating: {DM_STEP} -> 2 channels...")
    X_train = beats_to_spike_tensor(train_beats)
    y_train = torch.tensor(train_labels, dtype=torch.long)
    class_weights = inverse_frequency_weights(train_labels, cap=CLASS_WEIGHT_CAP)
    print("  class weights:", [round(v, 3) for v in class_weights.tolist()])

    print(f"\nTraining DPE_Train ({N_INPUTS_1}->{N_NEURONS_1}->{N_NEURONS_2})  "
          f"epochs={EPOCHS} lr={LEARNING_RATE} beta={BETA} seed={SEED}")
    model = train(DPE_Train(beta=BETA), X_train, y_train, class_weights,
                  epochs=EPOCHS, batch_size=BATCH_SIZE, lr=LEARNING_RATE,
                  weight_decay=WEIGHT_DECAY, diversity_weight=DIVERSITY_WEIGHT)

    float_w1 = model.fc1.weight.detach().cpu().numpy()   # (5,2)
    float_w2 = model.fc2.weight.detach().cpu().numpy()   # (5,5)
    diagnose_weights(float_w1, label="[UP,DN]")
    diagnose_weights(float_w2, label="[L1 n0..n4]")

    # SEPARATE scale per layer -- the two weight matrices have different
    # distributions, and one shared scale would squash whichever is smaller.
    print("\nlayer 1:", end=" ")
    q1 = quantize_weights(float_w1, weight_bits=6, verbose=True)
    print("layer 2:", end=" ")
    q2 = quantize_weights(float_w2, weight_bits=6, verbose=True)

    hw_w1 = to_hw_weight_list(q1, n_neurons=N_NEURONS_1)
    hw_w2 = to_hw_weight_list(q2, n_neurons=N_NEURONS_2)
    print(f"Flat HW weight list L1 (len {len(hw_w1)}):", hw_w1)
    print(f"Flat HW weight list L2 (len {len(hw_w2)}):", hw_w2)

    th1 = list(EVAL_THRESHOLDS_1) if EVAL_THRESHOLDS_1 is not None else auto_thresholds(q1, SOE_1)
    th2 = list(EVAL_THRESHOLDS_2) if EVAL_THRESHOLDS_2 is not None else auto_thresholds(q2, SOE_2)
    print(f"\nthresholds L1: {th1}")
    print(f"thresholds L2: {th2}")

    eval_beats, eval_labels = subsample(test_beats, test_labels, EVAL_MAX_BEATS, seed=SEED)
    print(f"\nEvaluating on Net over {len(eval_beats)} beats "
          f"(leak={EVAL_LEAK_1}/{EVAL_LEAK_2}, refrac={EVAL_REFRAC_1}/{EVAL_REFRAC_2}, dm step={DM_STEP})...")
    confusion, no_decision, l1_rate, l2_rate, dm_rate = evaluate_on_hardware(
        hw_w1, hw_w2, th1, th2, eval_beats, eval_labels,
        EVAL_LEAK_1, EVAL_LEAK_2, EVAL_REFRAC_1, EVAL_REFRAC_2, DM_STEP)

    print("\n--- spike budget per beat (200 timesteps) ---")
    print(f"   DM spikes      : {dm_rate:.2f}")
    print(f"   layer 1 fires  : " + " ".join(f"{v:.2f}" for v in l1_rate))
    print(f"   layer 2 fires  : " + " ".join(f"{v:.2f}" for v in l2_rate))
    if l1_rate.sum() < 0.5:
        print("   *** layer 1 nearly silent in hardware -- lower th1 (raise SOE_1 divisor) ***")
    elif l2_rate.sum() < 0.5:
        print("   *** layer 1 fires but layer 2 does not -- lower th2 or slow EVAL_LEAK_2 ***")

    print_confusion(confusion, no_decision)
    np.savez("trained_weights_v6.npz",
             float_w1=float_w1, float_w2=float_w2,
             quant_w1=q1, quant_w2=q2,
             hw_w1=hw_w1, hw_w2=hw_w2,
             thresholds_1=th1, thresholds_2=th2,
             leak_1=EVAL_LEAK_1, leak_2=EVAL_LEAK_2,
             refrac_1=EVAL_REFRAC_1, refrac_2=EVAL_REFRAC_2,
             dm_step=DM_STEP)
    print("\nSaved trained_weights_v6.npz")


if __name__ == "__main__":
    main()