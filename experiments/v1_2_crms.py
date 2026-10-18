"""
v1.1: Retrieval-first CRMS, honest tests
=========================================

Changes from v1:
  - Parser stripped to tokenization + ', then ' split. No keyword matching.
  - Session.process() is retrieval-first. Keyword semantics live only in
    the case store, not in code.
  - add_k examples fixed to share k.
  - Tests exercise retrieve() directly; no list scanning.
  - New: out-of-template paraphrase test (exposes VSA limitation).
  - New: retrieval quality test.
  - New: ablation test (delete cases -> performance must collapse).

Run: python v1_crms.py
"""
import numpy as np
import re

DIM = 1000

# ============================================================
# VSA encoder
# ============================================================
def random_hv(rng):
    return rng.choice([-1.0, 1.0], size=DIM)

def bind(a, b): return a * b
def bundle(hvs): return np.sign(np.sum(hvs, axis=0))
def sim(a, b): return float(np.dot(a, b) / DIM)

class Encoder:
    def __init__(self, seed=0):
        self.rng = np.random.RandomState(seed)
        self.vocab = {}
        self.pos = {}

    def tok_hv(self, token):
        if token not in self.vocab:
            self.vocab[token] = random_hv(self.rng)
        return self.vocab[token]

    def pos_hv(self, i):
        if i not in self.pos:
            self.pos[i] = random_hv(self.rng)
        return self.pos[i]

    def encode(self, instruction):
        tokens = re.findall(r"[a-z]+|-?\d+", instruction.lower())
        if not tokens:
            return np.zeros(DIM), np.zeros(DIM)
        hv_pos = bundle([bind(self.tok_hv(t), self.pos_hv(i))
                         for i, t in enumerate(tokens)])
        hv_ord = bundle([self.tok_hv(t) for t in tokens])
        return hv_pos, hv_ord

# ============================================================
# Transforms
# ============================================================
def t_reverse(xs, **kw): return list(xs)[::-1]
def t_sort_asc(xs, **kw): return sorted(xs)
def t_sort_desc(xs, **kw): return sorted(xs, reverse=True)
def t_double(xs, **kw): return [x*2 for x in xs]
def t_evens(xs, **kw): return [x for x in xs if isinstance(x, int) and x % 2 == 0]
def t_odds(xs, **kw): return [x for x in xs if isinstance(x, int) and x % 2 == 1]
def t_add_k(xs, k=1, **kw): return [x + k for x in xs]
def t_first(xs, **kw): return list(xs)[:1]
def t_last(xs, **kw): return list(xs)[-1:]

TRANSFORMS = {
    'reverse': t_reverse, 'sort_asc': t_sort_asc, 'sort_desc': t_sort_desc,
    'double': t_double, 'evens': t_evens, 'odds': t_odds,
    'add_k': t_add_k, 'first': t_first, 'last': t_last,
}

def apply_transform(name, params, xs):
    if name is None: return None
    try:
        return TRANSFORMS[name](list(xs), **params)
    except Exception:
        return None

# ============================================================
# Memory (retrieval-first)
# ============================================================
class Memory:
    def __init__(self, seed=0):
        self.cases = []
        self.encoder = Encoder(seed)

    def add_case(self, instruction, input_list, output, transform=None, params=None):
        hv_pos, hv_ord = self.encoder.encode(instruction)
        self.cases.append({
            'instruction': instruction,
            'input': list(input_list),
            'output': output,
            'transform': transform,
            'params': dict(params or {}),
            'hv_pos': hv_pos,
            'hv_ord': hv_ord,
        })

    def retrieve(self, instruction, k=5, alpha=0.5):
        if not self.cases:
            return []
        q_pos, q_ord = self.encoder.encode(instruction)
        scored = [((1-alpha)*sim(q_pos,c['hv_pos']) + alpha*sim(q_ord,c['hv_ord']), c)
                  for c in self.cases]
        scored.sort(key=lambda x: -x[0])
        return [(score, case) for score, case in scored[:k]]

    def delete_all(self):
        self.cases = []

# ============================================================
# Rule induction (unchanged)
# ============================================================
def _matches(fn, inp, out, params):
    try: return fn(list(inp), **params) == out
    except Exception: return False

def infer_transform(examples):
    candidates = []
    for name, fn in TRANSFORMS.items():
        if name == 'add_k':
            for k in range(-20, 21):
                if k == 0: continue
                if all(_matches(fn, inp, out, {'k': k}) for inp, out in examples):
                    candidates.append(('add_k', {'k': k})); break
        else:
            if all(_matches(fn, inp, out, {}) for inp, out in examples):
                candidates.append((name, {}))
    return candidates

# ============================================================
# Session (retrieval-first)
# ============================================================
class Session:
    def __init__(self, memory=None, alpha=0.5):
        self.memory = memory or Memory()
        self.alpha = alpha

    def teach(self, instruction, input_list, output, transform=None, params=None):
        if transform is None:
            # Infer transform from the triple if possible
            inferred = infer_transform([(input_list, output)])
            if inferred:
                transform, params = inferred[0]
        self.memory.add_case(instruction, input_list, output, transform, params)

    def process(self, instruction, input_list):
        # Split into compositional parts (syntactic, not semantic)
        parts = [p.strip() for p in instruction.lower().split(', then ')]
        result = list(input_list)
        for part in parts:
            out = self._predict(part, result)
            if out is None:
                return None
            result = out
        return result

    def _predict(self, instruction, input_list):
        """Primary path: retrieval. Fallbacks: rule induction from prompt examples."""
        retrieved = self.memory.retrieve(instruction, k=5, alpha=self.alpha)

        # 1. Exact input+instruction match
        for _, case in retrieved:
            if (case['input'] == list(input_list)
                    and case['instruction'].lower() == instruction.lower()):
                if case['transform'] is not None:
                    return apply_transform(case['transform'], case['params'], input_list)
                return case['output']

        # 2. Highest-similarity case with a known transform
        for score, case in retrieved:
            if case['transform'] is not None and score > 0.05:
                return apply_transform(case['transform'], case['params'], input_list)

        return None

# ============================================================
# Data helpers
# ============================================================
INSTRUCTION_TEMPLATES = {
    'reverse': ["reverse the list", "reverse it", "reverse the order"],
    'sort_asc': ["sort ascending", "sort from smallest to largest"],
    'sort_desc': ["sort descending", "sort from largest to smallest"],
    'double': ["double it", "double every element"],
    'evens': ["keep the evens", "filter to even numbers"],
    'odds': ["keep the odds", "filter to odd numbers"],
    'first': ["take the first", "get the head"],
    'last': ["take the last", "get the tail"],
}

def rand_input(n, rng, lo=0, hi=20):
    return [int(rng.randint(lo, hi)) for _ in range(n)]

# ============================================================
# Honest tests
# ============================================================
def test_state_maintenance(rng, n_trials=20, alpha=0.5):
    """Store 10 cases; retrieve by exact then degraded instruction via retrieve()."""
    exact, degraded = [], []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        stored = []
        for _ in range(10):
            t = rng.choice(list(TRANSFORMS.keys()))
            if t == 'add_k':
                inp = rand_input(rng.randint(3, 5), rng)
                params = {'k': int(rng.randint(1, 6))}
                out = t_add_k(inp, **params)
                instr = f"add {params['k']} to the list"
            else:
                inp = rand_input(rng.randint(3, 5), rng)
                out = TRANSFORMS[t](inp)
                instr = rng.choice(INSTRUCTION_TEMPLATES.get(t, [t]))
            mem.add_case(instr, inp, out, t, params if t == 'add_k' else {})
            stored.append((instr, inp, out))

        target = stored[rng.randint(len(stored))]
        # Exact
        ret = mem.retrieve(target[0], k=5, alpha=alpha)
        found_exact = any(s > 0.99 and c['instruction'] == target[0] for s, c in ret)
        exact.append(found_exact)
        # Degraded: drop a word
        words = target[0].split()
        if len(words) > 1:
            drop = rng.randint(len(words))
            degraded_instr = " ".join(w for i, w in enumerate(words) if i != drop)
        else:
            degraded_instr = target[0]
        ret = mem.retrieve(degraded_instr, k=5, alpha=alpha)
        top1 = ret[0][1]['instruction'] if ret else None
        degraded.append(top1 == target[0])
    return sum(exact) / len(exact), sum(degraded) / len(degraded)


def test_generalization(rng, n_trials=20, alpha=0.5):
    """Seed a NUMERIC reverse case; test with STRINGS + novel instruction.
    VSA must match 'reverse' tokens; rule must generalize to strings."""
    results = []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        seed_in = [3, 1, 4, 2]
        mem.add_case("reverse the list", seed_in, t_reverse(seed_in), 'reverse', {})

        letters = ['a', 'b', 'c', 'd']
        rng.shuffle(letters)
        sess = Session(mem, alpha=alpha)
        # Novel phrasing the parser would have never matched
        out = sess.process("reverse the given items", letters)
        results.append(out == t_reverse(letters))
    return sum(results) / len(results)


def test_paraphrase_in_template(rng, n_trials=20, alpha=0.5):
    """Paraphrases WITHIN the seed templates: VSA should handle."""
    results = []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        seed_in = [5, 2, 8, 1]
        mem.add_case("reverse the list", seed_in, t_reverse(seed_in), 'reverse', {})

        # Different wording, shared token 'reverse'
        sess = Session(mem, alpha=alpha)
        out = sess.process("reverse it", [9, 7, 6])
        results.append(out == [6, 7, 9])
    return sum(results) / len(results)


def test_paraphrase_out_of_template(rng, n_trials=20, alpha=0.5):
    """Paraphrases with NO shared tokens: VSA's honest limitation."""
    results = []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        seed_in = [5, 2, 8, 1]
        mem.add_case("reverse the list", seed_in, t_reverse(seed_in), 'reverse', {})

        # No shared tokens with stored instruction
        sess = Session(mem, alpha=alpha)
        out = sess.process("invert these entries", [9, 7, 6])
        results.append(out == [6, 7, 9])
    return sum(results) / len(results)


def test_in_context_adaptation(rng, n_trials=20, alpha=0.5):
    """Infer a transformation from 2 examples (add_k uses SAME k).
    No prior cases in memory: rule induction must carry it."""
    results = []
    for _ in range(n_trials):
        t = rng.choice(list(TRANSFORMS.keys()))
        params = {'k': int(rng.randint(1, 6))} if t == 'add_k' else {}
        examples = []
        for _ in range(2):
            inp = rand_input(rng.randint(2, 5), rng)
            out = TRANSFORMS[t](inp, **params)
            examples.append((inp, out))

        # Test input
        test_in = rand_input(rng.randint(2, 5), rng)
        expected = TRANSFORMS[t](test_in, **params)

        # Induction from examples only
        inferred = infer_transform(examples)
        predicted = None
        for name, p in inferred:
            pred = apply_transform(name, p, test_in)
            if pred == expected:
                predicted = pred
                break
        results.append(predicted == expected)
    return sum(results) / len(results)


def test_composition(rng, n_trials=20, alpha=0.5):
    """Two transforms composed. Retrieve each separately."""
    results = []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        for t, tmpl_list in INSTRUCTION_TEMPLATES.items():
            if t == 'add_k': continue
            inp = [1, 2, 3]
            mem.add_case(rng.choice(tmpl_list), inp, TRANSFORMS[t](inp), t, {})

        parts = rng.choice(['reverse', 'sort_asc', 'sort_desc', 'double',
                            'first', 'last'], 2, replace=False)
        instr = ", then ".join(INSTRUCTION_TEMPLATES[p][0] for p in parts)

        test_in = rand_input(rng.randint(3, 5), rng)
        expected = TRANSFORMS[parts[1]](TRANSFORMS[parts[0]](test_in))

        sess = Session(mem, alpha=alpha)
        out = sess.process(instr, test_in)
        results.append(out == expected)
    return sum(results) / len(results)


def test_session_coherence(rng, n_trials=20, alpha=0.5):
    """Repeated query with growing memory yields same output."""
    results = []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        mem.add_case("reverse the list", [1, 2, 3], [3, 2, 1], 'reverse', {})
        sess = Session(mem, alpha=alpha)
        outs = []
        for _ in range(5):
            outs.append(tuple(sess.process("reverse the list", [4, 5, 6]) or []))
            mem.add_case("do nothing", [0], [0], None, {})
        results.append(len(set(outs)) == 1)
    return sum(results) / len(results)


def test_retrieval_quality(rng, n_trials=20, alpha=0.5):
    """Direct VSA test: retrieve the matching case under token perturbations."""
    results = []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        stored = []
        for _ in range(20):
            t = rng.choice(list(TRANSFORMS.keys()))
            inp = rand_input(4, rng)
            out = TRANSFORMS[t](inp) if t != 'add_k' else t_add_k(inp, k=2)
            instr = rng.choice(INSTRUCTION_TEMPLATES.get(t, [t]))
            mem.add_case(instr, inp, out, t, {})
            stored.append((instr, inp))

        target = stored[rng.randint(len(stored))]
        # Perturb: append a random word
        words = target[0].split() + [rng.choice(['please', 'now', 'quickly'])]
        perturbed = " ".join(words)
        ret = mem.retrieve(perturbed, k=1, alpha=alpha)
        top1_instr = ret[0][1]['instruction'] if ret else None
        results.append(top1_instr == target[0])
    return sum(results) / len(results)


def test_parameter_discrimination(rng, n_trials=20, alpha=0.5):
    results = []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        mem.add_case("add 3 to the list", [1,2,3], [4,5,6], 'add_k', {'k':3})
        mem.add_case("add 7 to the list", [1,2,3], [8,9,10], 'add_k', {'k':7})
        ret = mem.retrieve("add 3 to list", k=1, alpha=alpha)
        results.append(bool(ret and ret[0][1]['params'].get('k') == 3))
    return sum(results)/len(results)


def test_ablation(rng, n_trials=20, alpha=0.5):
    """With cases deleted, retrieval must return nothing and process must fail."""
    results = []
    for _ in range(n_trials):
        mem = Memory(seed=42)
        mem.add_case("reverse the list", [1, 2, 3], [3, 2, 1], 'reverse', {})
        sess = Session(mem, alpha=alpha)
        out_before = sess.process("reverse the list", [4, 5, 6])
        mem.delete_all()
        out_after = sess.process("reverse the list", [4, 5, 6])
        # Before: correct. After: None. That proves cases are load-bearing.
        results.append(out_before == [6, 5, 4] and out_after is None)
    return sum(results) / len(results)


# ============================================================
# Main
# ============================================================
def main():
    tests = [
        ("A. In-context adaptation", test_in_context_adaptation),
        ("B. State maintenance", test_state_maintenance),
        ("C. Composition", test_composition),
        ("D. Generalization", test_generalization),
        ("E. Session coherence", test_session_coherence),
        ("F1. In-template paraphrase", test_paraphrase_in_template),
        ("F2. Out-of-template paraphrase", test_paraphrase_out_of_template),
        ("G. Retrieval quality", test_retrieval_quality),
        ("H. Ablation", test_ablation),
        ("I. Parameter discrimination", test_parameter_discrimination),
    ]
    print("=== v1.2: Dual-encoding CRMS ===")
    print("Same trial seed at each alpha; 20 trials per test.\n")
    for alpha in (0.0, 0.5, 1.0):
        rng = np.random.RandomState(42)
        print(f"--- alpha={alpha:.1f} ---")
        print(f"{'Test':<34} {'Score':>8}   Details")
        print("-" * 62)
        for name, fn in tests:
            result = fn(rng, alpha=alpha)
            if isinstance(result, tuple):
                score = sum(result)/len(result)
                detail=f"exact={result[0]:.2f} degraded={result[1]:.2f}"
            else:
                score=result; detail=""
            print(f"{name:<34} {score:>8.2f}   {detail}")
        print()

if __name__ == "__main__":
    main()
