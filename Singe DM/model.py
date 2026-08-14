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

    def __init__(self, data_w=11, min_val=0,max_val=2047):
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
            return(0,0)
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
        return(up_n, down_n)
#--------------------------------------------------------------SYNAPSE-------------------------
class Synapse:
    """synapse.sv mirror. Phase 1: stateless gated weight. Phase 2 adds the
    constrained-STDP state here (w_base, weight_reg, syn_time, clamp)."""
 
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

        if(not enable) or beat_clear:
            self.mp = 0
            self.leak_counter = 0
            self.refrac_cnt = 0
            self.fire = 0
        elif force_reset:
            self.mp = 0
            self.leak_counter = 0
            self.fire = 0
        elif in_refractory:
            self.refrac_cnt -=1
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
        self.synapses  = [Synapse(weight_w=w.get("weight_w",6)) for _ in range(n_inputs * n_neurons)]
        self.neurons   = [Neuron(**w) for _ in range(n_neurons)]

    def reset(self):
        for nrn in self.neurons:
            nrn.reset()

    def step(self, spikes, weights, thresholds, leak_rate, refractory_period, reset_others, beat_clear = 0, enable = 1):
        fire = [0] * self.N_NEURONS
        for j in range(self.N_NEURONS):
            syn_in = 0
            for r in range(self.N_INPUTS):
                syn_in += self.synapses[r * self.N_NEURONS + j].step(enable,spikes[r], weights[r * self.N_NEURONS + j])
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
# ----------------------------------------------------------DELTA MODULATOR---------------
class Net:

    def __init__(self, weights, thresholds, leak_rate, refractory_period,
                 dm_step, n_neurons=5, n_inputs=2,
                 weight_w=6, mp_w=10, thresh_w=10, leak_w=4, refrac_w=4,
                 data_w=11, max_val=2047, min_val=0):
                self.N_NEURONS = n_neurons
                self.N_INPUTS  = n_inputs
                self.weights = list(weights)
                self.thresholds = list(thresholds)
                self.leak_rate = leak_rate
                self.refractory_period = refractory_period
                self.dm_step = dm_step
                self.dm = DeltaMod(data_w=data_w, min_val=min_val,max_val=max_val)
                self.dpe = DPE(n_neurons=n_neurons, n_inputs=n_inputs, weight_w=weight_w,
                       mp_w=mp_w, thresh_w=thresh_w, leak_w=leak_w, refrac_w=refrac_w)
                self.wta = WTA(n_neurons=n_neurons)
                self.enable = 1
                self._reset_others = [0] * n_neurons

    def reset(self):
        self.dm.reset()
        self.dpe.reset()
        self._reset_others = [0] * self.N_NEURONS

    def beat_clear(self):
        self.dpe.step([0] * self.N_INPUTS, self.weights, self.thresholds, self.leak_rate,
                      self.refractory_period, [0] * self.N_NEURONS, beat_clear=1, enable=self.enable)
        self._reset_others = [0] * self.N_NEURONS

    def step_dpe(self, spikes, reset_others=None, beat_clear=0):
        if reset_others is None:
            reset_others = [0] * self.N_NEURONS
        fire = self.dpe.step(spikes, self.weights, self.thresholds, self.leak_rate,
                             self.refractory_period, reset_others, beat_clear, self.enable)
        winner, valid, _ = self.wta.step(fire, self.enable)
        return {"fire": fire, "mp": [n.mp for n in self.dpe.neurons], "winner": winner, "valid": valid}

    def step_pipeline(self, ecg, beat_clear=0):
        spikes_stale = [self.dm.up, self.dm.down]
        fire = self.dpe.step(spikes_stale, self.weights, self.thresholds, self.leak_rate, self.refractory_period,
                             self._reset_others, beat_clear, self.enable)
        winner, valid, reset_others = self.wta.step(fire, self.enable)
        self._reset_others = reset_others
        up, dn = self.dm.step(ecg, self.dm_step, self.enable)
        return {"fire": fire, "mp": [n.mp for n in self.dpe.neurons],
                "winner": winner, "valid": valid, "spikes": (up, dn)}
    def classify_beats(self, samples, clear_between=True):
        if clear_between:
            self.beat_clear()
            self.dm.reset()
        win = [0] * self.N_NEURONS
        for ecg in samples:
            out = self.step_pipeline(ecg)
            if out["valid"]:
                win[out["winner"]] += 1
        best = 0
        for i in range(1, self.N_NEURONS):
            if win[i] > win[best]:
                best = i
        return best, win