import math

def to_twos(value, width):
    mask = (1 << width) - 1
    v = value & mask
    return v - (1 << width) if (v & (1 << (width - 1))) else v

def sat(value, lo, hi):
    if value < lo: return lo
    if value > hi: return hi
    return value

# ----------------------------------------------------------DELTA MODULATOR---------------

class DeltaMod:

    def __init__(self, data_w=11, min_val=0, max_val=2047):
        self.DATA_W = data_w
        self.MIN = min_val
        self.MAX = max_val
        self.reset()

    def reset(self):
        self.up = 0
        self.down = 0
        self.init = 0
        self.approx = 0
        self.last_cycle_spike = 0

    def step(self, ecg, step_size, enable):
        if not enable:
            self.approx = 0
            self.up = 0
            self.down = 0
            self.init = 0
            self.last_cycle_spike = 0
            return (0, 0)
        up_n = down_n = 0
        if not self.init:
            self.approx = ecg
            self.init = 1
        elif self.last_cycle_spike:
            self.last_cycle_spike = 0
        elif ecg > self.approx + step_size:
            up_n = 1
            self.approx = sat(self.approx + step_size, self.MIN, self.MAX)
            self.last_cycle_spike = 1
        elif ecg + step_size < self.approx:
            down_n = 1
            self.approx = sat(self.approx - step_size, self.MIN, self.MAX)
            self.last_cycle_spike = 1
        self.up = up_n
        self.down = down_n
        return (up_n, down_n)

#--------------------------------------------------------------SYNAPSE-------------------------
class Synapse:

    def __init__(self, weight_w=6):
        self.WEIGHT_W = weight_w

    def reset(self):
        pass

    def step(self, enable, spike_in, weight):
        return weight if (enable and spike_in) else 0


# ----------------------------------------------------------NEURON------------------------
class Neuron:

    def __init__(self, weight_w=6, mp_w=10, thresh_w=10, leak_w=4, refrac_w=4):
        self.MP_W = mp_w
        self.reset()

    def _wrap(self, v):
        lo, hi = -(1 << (self.MP_W - 1)), (1 << (self.MP_W - 1)) - 1
        return sat(v, lo, hi)      # saturate at [-512, 511], not wrap

    def reset(self):
        self.mp = 0
        self.leak_counter = 0
        self.refrac_cnt = 0
        self.fire = 0

    def step(self, syn_in, threshold, leak_rate, refractory_period, force_reset=0, beat_clear=0, enable=1):
        in_refractory = (self.refrac_cnt != 0)
        syn_total = self._wrap(syn_in if (enable and not in_refractory) else 0)
        next_accum = self._wrap(self.mp + syn_total)

        leak_tick = (self.leak_counter >= leak_rate)
        if not leak_tick:       mp_next = next_accum
        elif next_accum > 0:    mp_next = next_accum - 1
        elif next_accum < 0:    mp_next = next_accum + 1
        else:                   mp_next = next_accum
        mp_next = self._wrap(mp_next)

        if (not enable) or beat_clear:
            self.mp = 0
            self.leak_counter = 0
            self.refrac_cnt = 0
            self.fire = 0
        elif force_reset:
            self.mp = 0
            self.leak_counter = 0
            self.fire = 0
        elif in_refractory:
            self.refrac_cnt -= 1
            self.mp = mp_next
            self.leak_counter = 0 if leak_tick else self.leak_counter + 1
            self.fire = 0
        elif mp_next >= threshold:
            self.mp = 0
            self.leak_counter = 0
            self.refrac_cnt = refractory_period
            self.fire = 1
        else:
            self.mp = mp_next
            self.leak_counter = 0 if leak_tick else self.leak_counter + 1
            self.fire = 0
        return self.fire

# ----------------------------------------------------------NEURON ARRAY------------------------
class DPE:

    def __init__(self, n_neurons=5, n_inputs=2, **w):
        self.N_NEURONS = n_neurons
        self.N_INPUTS  = n_inputs
        self.synapses  = [Synapse(weight_w=w.get("weight_w", 6)) for _ in range(n_inputs * n_neurons)]
        self.neurons   = [Neuron(**w) for _ in range(n_neurons)]

    def reset(self):
        for nrn in self.neurons:
            nrn.reset()

    def step(self, spikes, weights, thresholds, leak_rate, refractory_period, reset_others, beat_clear=0, enable=1):
        fire = [0] * self.N_NEURONS
        for j in range(self.N_NEURONS):
            syn_in = 0
            for r in range(self.N_INPUTS):
                syn_in += self.synapses[r * self.N_NEURONS + j].step(enable, spikes[r], weights[r * self.N_NEURONS + j])
            fire[j] = self.neurons[j].step(syn_in=syn_in, threshold=thresholds[j], leak_rate=leak_rate,
                refractory_period=refractory_period, force_reset=reset_others[j],
                beat_clear=beat_clear, enable=enable)
        return fire

# ----------------------------------------------------------WTA--------------------------------
class WTA:

    def __init__(self, n_neurons=5):
        self.N_NEURONS = n_neurons
        self.CLS_W = math.ceil(math.log2(n_neurons + 1))
        self.sentinel = (1 << self.CLS_W) - 1

    def step(self, fire, enable=1):
        winner_class = self.sentinel
        valid = 0
        reset_others = [0] * self.N_NEURONS
        if enable:
            for i in range(self.N_NEURONS):
                if fire[i]:
                    winner_class = i
                    valid = 1
                    break
            if valid:
                reset_others = [0 if i == winner_class else 1 for i in range(self.N_NEURONS)]
        return winner_class, valid, reset_others

# ----------------------------------------------------------TOP LEVEL---------------------------
class Net:
    def __init__(self, weights_1, weights_2, thresholds_1, thresholds_2,
                 leak_rate_1, leak_rate_2, refractory_period_1, refractory_period_2,
                 dm_step, n_neurons_1=5, n_inputs_1=2, n_neurons_2=5,
                 weight_w=6, mp_w=10, thresh_w=10, leak_w=4, refrac_w=4,
                 data_w=11, max_val=2047, min_val=0):
        self.N_NEURONS_1 = n_neurons_1
        self.N_NEURONS_2 = n_neurons_2
        self.N_INPUTS_1 = n_inputs_1
        self.N_INPUTS_2 = n_neurons_1          # layer 2's rows ARE layer 1's neurons
        self.weights_1 = list(weights_1)
        self.weights_2 = list(weights_2)
        self.thresholds_1 = list(thresholds_1)
        self.thresholds_2 = list(thresholds_2)
        self.leak_rate_1 = leak_rate_1
        self.leak_rate_2 = leak_rate_2
        self.refractory_period_1 = refractory_period_1
        self.refractory_period_2 = refractory_period_2
        self.dm_step = dm_step

        expect_1 = self.N_INPUTS_1 * self.N_NEURONS_1
        expect_2 = self.N_INPUTS_2 * self.N_NEURONS_2
        if len(self.weights_1) != expect_1:
            raise ValueError(f"weights_1 has {len(self.weights_1)} entries, expected {expect_1}")
        if len(self.weights_2) != expect_2:
            raise ValueError(f"weights_2 has {len(self.weights_2)} entries, expected {expect_2}")
        if len(self.thresholds_1) != self.N_NEURONS_1:
            raise ValueError(f"thresholds_1 has {len(self.thresholds_1)} entries, expected {self.N_NEURONS_1}")
        if len(self.thresholds_2) != self.N_NEURONS_2:
            raise ValueError(f"thresholds_2 has {len(self.thresholds_2)} entries, expected {self.N_NEURONS_2}")

        self.dm = DeltaMod(data_w=data_w, min_val=min_val, max_val=max_val)
        self.dpe1 = DPE(n_neurons=n_neurons_1, n_inputs=n_inputs_1, weight_w=weight_w,
                        mp_w=mp_w, thresh_w=thresh_w, leak_w=leak_w, refrac_w=refrac_w)
        self.dpe2 = DPE(n_neurons=n_neurons_2, n_inputs=self.N_INPUTS_2, weight_w=weight_w,
                        mp_w=mp_w, thresh_w=thresh_w, leak_w=leak_w, refrac_w=refrac_w)
        self.wta = WTA(n_neurons=n_neurons_2)
        self.enable = 1
        self._fire1 = [0] * n_neurons_1
        self._reset_others = [0] * n_neurons_2

    def reset(self):
        self.dm.reset()
        self.dpe1.reset()
        self.dpe2.reset()
        self._fire1 = [0] * self.N_NEURONS_1
        self._reset_others = [0] * self.N_NEURONS_2

    def beat_clear(self):
        self.dpe1.step([0] * self.N_INPUTS_1, self.weights_1, self.thresholds_1, self.leak_rate_1,
                       self.refractory_period_1, [0] * self.N_NEURONS_1, beat_clear=1, enable=self.enable)
        self.dpe2.step([0] * self.N_INPUTS_2, self.weights_2, self.thresholds_2, self.leak_rate_2,
                       self.refractory_period_2, [0] * self.N_NEURONS_2, beat_clear=1, enable=self.enable)
        self._fire1 = [0] * self.N_NEURONS_1
        self._reset_others = [0] * self.N_NEURONS_2

    def step_pipeline(self, ecg, beat_clear=0):
     
        spikes_stale = [self.dm.up, self.dm.down]
        fire1_stale  = list(self._fire1)
        reset_stale  = list(self._reset_others)

        fire2 = self.dpe2.step(fire1_stale, self.weights_2, self.thresholds_2,
                               self.leak_rate_2, self.refractory_period_2,
                               reset_stale, beat_clear, self.enable)

        fire1 = self.dpe1.step(spikes_stale, self.weights_1, self.thresholds_1,
                               self.leak_rate_1, self.refractory_period_1,
                               [0] * self.N_NEURONS_1, beat_clear, self.enable)

        winner, valid, reset_others = self.wta.step(fire2, self.enable)

        up, dn = self.dm.step(ecg, self.dm_step, self.enable)

        self._fire1 = fire1
        self._reset_others = reset_others

        return {"fire_l1": fire1,
                "fire": fire2,
                "mp1": [n.mp for n in self.dpe1.neurons],
                "mp2": [n.mp for n in self.dpe2.neurons],
                "winner": winner,
                "valid": valid,
                "spikes": (up, dn)}

    def classify_beats(self, samples, clear_between=True):
        """Run one beat and return the majority-vote class.

        Returns (best, win, diag) where diag carries the per-layer fire counts.
        best is None when nothing in layer 2 ever fired -- distinguish that from
        a genuine vote for class 0, or a silent network reads as 89% normal.
        """
        if clear_between:
            self.beat_clear()
            self.dm.reset()

        win = [0] * self.N_NEURONS_2
        l1_counts = [0] * self.N_NEURONS_1
        l2_counts = [0] * self.N_NEURONS_2
        dm_spikes = 0

        for ecg in samples:
            out = self.step_pipeline(ecg)
            for i in range(self.N_NEURONS_1):
                l1_counts[i] += out["fire_l1"][i]
            for i in range(self.N_NEURONS_2):
                l2_counts[i] += out["fire"][i]
            dm_spikes += out["spikes"][0] + out["spikes"][1]
            if out["valid"]:
                win[out["winner"]] += 1

        if sum(win) == 0:
            best = None
        else:
            best = 0
            for i in range(1, self.N_NEURONS_2):
                if win[i] > win[best]:
                    best = i

        diag = {"l1_counts": l1_counts, "l2_counts": l2_counts, "dm_spikes": dm_spikes}
        return best, win, diag