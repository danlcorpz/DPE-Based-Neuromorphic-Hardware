"""
quantize.py -- map trained float weights to signed integer hardware weights,
and flatten them into the scan-chain order HW_Net3 / the RTL expect.
Works for any number of input rows (2 for V2, 4 for V3). float_w shape
(n_neurons, n_inputs): row j = neuron j, col r = input row r.
"""
import numpy as np


def quantize_weights(float_w, weight_bits=6, verbose=False):
    float_w = np.asarray(float_w, dtype=np.float64)
    qmax = (1 << (weight_bits - 1)) - 1     # 6-bit -> +31
    qmin = -(1 << (weight_bits - 1))        # 6-bit -> -32
    max_abs = np.max(np.abs(float_w))
    scale = qmax / max_abs if max_abs > 0 else 1.0
    q = np.clip(np.round(float_w * scale), qmin, qmax).astype(int)
    if verbose:
        print(f"quantize: scale={scale:.4f}  int range=[{q.min()},{q.max()}]  shape={q.shape}")
    return q


def to_hw_weight_list(q, n_neurons=5):
    """Flatten (n_neurons, n_inputs) into weights[row*n_neurons + j].
    V3 row order: 0=coarse-up 1=coarse-down 2=fine-up 3=fine-down."""
    q = np.asarray(q)
    n_inputs = q.shape[1]
    flat = []
    for r in range(n_inputs):
        for j in range(n_neurons):
            flat.append(int(q[j, r]))
    return flat