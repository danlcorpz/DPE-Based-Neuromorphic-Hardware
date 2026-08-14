import sys
import numpy as np
import torch
import torch.nn as nn
import snntorch as snn
from snntorch import surrogate

from DataPrep4 import (load_dataset, DS1_TRAIN, DS2_TEST, AAMI_CLASSES,
                       class_distribution)
from Quantize4 import quantize_weights, to_hw_weight_list
from model import Net

# --- pointer to your data (a command-line arg overrides this) ---
DATA_DIR =  r"C:\Users\sidew\OneDrive\Desktop\LAB\RESEARCH\mitbih"    # e.g. r"C:\Users\sidew\OneDrive\Desktop\LAB\RESEARCH\mitbih"

# --- tuning knobs ---
EPOCHS           = 30
LEARNING_RATE    = 1e-3
BATCH_SIZE       = 128
CLASS_WEIGHT_CAP = 50.0
WEIGHT_DECAY     = 0.5
DIVERSITY_WEIGHT = 0.0
BETA             = 0.95
SEED             = 2
DM_STEP          = 12
EVAL_THRESHOLDS  = [50, 50, 50, 50, 50] # None -> auto-scale to weights
EVAL_LEAK_RATE   = 12
EVAL_REFRACTORY  = 4


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
    def __init__(self, beta=0.95):
        super().__init__()
        self.fc = nn.Linear(2, 5, bias=False)   # (5,2): cols=[up, down]
        self.lif = snn.Leaky(beta=beta, spike_grad=surrogate.fast_sigmoid(), init_hidden=False)

    def forward(self, x):                        # x: (batch, T, 2)
        batch, T, _ = x.shape
        mem = self.lif.init_leaky()
        spk_count = torch.zeros(batch, 5, device=x.device)
        for t in range(T):
            cur = self.fc(x[:, t, :])
            spk, mem = self.lif(cur, mem)
            spk_count = spk_count + spk
        return spk_count


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
          weight_decay=0.0, diversity_weight=0.0, verbose=True):
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    loss_fn = nn.CrossEntropyLoss(weight=class_weights)
    N = X.shape[0]
    for epoch in range(epochs):
        perm = torch.randperm(N); total = 0.0
        for i in range(0, N, batch_size):
            idx = perm[i:i + batch_size]; xb, yb = X[idx], y[idx]
            opt.zero_grad()
            out = model(xb)
            loss = loss_fn(out, yb)
            if diversity_weight > 0.0:
                loss = loss + diversity_weight * diversity_loss(model.fc.weight)
            loss.backward(); opt.step()
            total += loss.item() * len(idx)
        if verbose and ((epoch + 1) % 10 == 0 or epoch == 0):
            print(f"  epoch {epoch+1:3d}/{epochs}  loss={total/N:.4f}")
    return model


def evaluate_on_hardware(hw_weights, thresholds, beats, labels,
                         leak_rate, refractory_period, dm_step):
    net = Net(weights=hw_weights, thresholds=thresholds,
                  leak_rate=leak_rate, refractory_period=refractory_period,
                  dm_step=dm_step,n_neurons=5, n_inputs=2)
    confusion = np.zeros((5, 5), dtype=np.int64)
    for beat, true in zip(beats, labels):
        pred, _ = net.classify_beats(list(beat))
        confusion[true, pred] += 1
    return confusion


def diagnose_weights(float_w, quiet=False):
    import math
    n = float_w.shape[0]
    if not quiet:
        print("\nPer-neuron learned weights (row=neuron  [UP,DN):")
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
        print(f"\n   angular spread: min pairwise angle = {min_angle:.1f} deg, mean |cos| = {cos_sum/max(1,pairs):.3f}")
        print("   *** COLLAPSED ***" if min_angle < 5 else ("   PARTIAL collapse." if min_angle < 15 else "   good spread."))
    return min_angle, cos_sum / max(1, pairs)


def print_confusion(confusion):
    n = len(AAMI_CLASSES)
    print("\nConfusion Matrix (rows=true, cols=predicted):")
    print("        " + "".join(f"{c:>8}" for c in AAMI_CLASSES))
    for i, c in enumerate(AAMI_CLASSES):
        print(f"   {c:>3}  " + "".join(f"{confusion[i,j]:>8d}" for j in range(n)))
    print("\nPer-class accuracy (true positive rate):")
    total_correct, total, recs = 0, confusion.sum(), []
    for i, c in enumerate(AAMI_CLASSES):
        row = confusion[i].sum(); tp = confusion[i, i]; total_correct += tp
        if row > 0:
            recs.append(tp/row); print(f"   {c}: {tp}/{row} = {tp/row:.4f}")
        else:
            print(f"   {c}: (no samples)")
    print(f"\nOverall: {total_correct}/{total} = {total_correct/max(1,total):.4f}")
    print(f"Macro-recall (class-balanced): {np.mean(recs):.4f}")


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    if not data_dir:
        print("No data folder. Set DATA_DIR at the top, or:  python train_dpe3.py /path/to/mitbih")
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

    print(f"\nTraining DPE_Train (2->5)  epochs={EPOCHS} lr={LEARNING_RATE} beta={BETA} seed={SEED}")
    model = train(DPE_Train(beta=BETA), X_train, y_train, class_weights,
                  epochs=EPOCHS, batch_size=BATCH_SIZE, lr=LEARNING_RATE,
                  weight_decay=WEIGHT_DECAY, diversity_weight=DIVERSITY_WEIGHT)

    float_w = model.fc.weight.detach().cpu().numpy()   # (5,2)
    diagnose_weights(float_w)
    q = quantize_weights(float_w, weight_bits=6, verbose=True)
    hw_weights = to_hw_weight_list(q, n_neurons=5)
    print("Flat HW weight list (len 10):", hw_weights)

    if EVAL_THRESHOLDS is None:
        SOE = 4
        thresholds = [max(1, int(round(SOE * (max(abs(q[j,0]),abs(q[j,1])) or 1)))) for j in range(5)]
        print(f"\nAuto-scaled thresholds (~{SOE} spikes each): {thresholds}")
    else:
        thresholds = list(EVAL_THRESHOLDS); print(f"\nUsing configured thresholds: {thresholds}")

    print(f"Evaluating on Net: (leak={EVAL_LEAK_RATE}, refrac={EVAL_REFRACTORY}, dm step={DM_STEP}...")
    confusion = evaluate_on_hardware(hw_weights, thresholds, test_beats, test_labels,
                                     EVAL_LEAK_RATE, EVAL_REFRACTORY, DM_STEP)
    print_confusion(confusion)
    np.savez("trained_weights_v4.npz", float_weights=float_w, quant_weights=q,
             hw_weights=hw_weights, thresholds=thresholds)
    print("\nSaved trained_weights_v4.npz (for the threshold sweep).")


if __name__ == "__main__":
    main()