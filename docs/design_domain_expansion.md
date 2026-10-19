# Roadmap: natural-language math, coding, and translation

**Status:** staged, with a first checked math→code composition implemented.
CRMS has working, bounded natural-language paths for exact arithmetic and
simple equations (`crms_math.py`), example-grounded translation and rewriting
(`crms_translation.py`), and Python rendering for learned list procedures
(`crms_codegen.py`). `generate_mapped_math_python` now composes one licensed
exact scalar expression over each integer in a bounded list, and chat accepts
a natural-language code request for that task. These remain domain-specific
prototypes, not broad competence; the shared evaluation and cross-domain
coverage work below remains open.

**Goal:** users should reach each capability through the same natural-language
chat interface used for knowledge and reasoning. A command or structured form
may remain available for teaching and inspection, but it must not be the only
way to ask for ordinary supported work. The domain engines must preserve CRMS's
core contract: explicit learned structures, inspectable evidence, bounded
execution, correction or retraction, and honest abstention.

## 1. Shared contract

Each domain follows the same observable path:

1. **Understand:** identify the requested operation, operands or slots, output
   form, and any required constraints from ordinary phrasing.
2. **Check support:** use the exact arithmetic grammar, accepted rule, licensed
   frame, or source evidence appropriate to the task. Unknown wording or
   ambiguous roles must not be silently guessed.
3. **Produce:** return a result, translation, or code artifact only when the
   selected operation is supported and its checks pass.
4. **Explain:** show the expression/proof, aligned examples and provenance, or
   generated operation steps on request. The short answer remains uncluttered.
5. **Learn under review:** examples can propose or license explicit reusable
   operators and frames through the existing validation paths. A successful
   output alone is not evidence that a new rule is correct.

Natural-language variation is measured separately from domain correctness.
Every evaluation records correct, incorrect, abstained, incomplete, and
unsupported requests; it also records the route and evidence used. A correct
answer reached by exact syntax is not counted as transfer to a new wording.
Repeated runs on the same stored model and input must be deterministic.

## 2. Domain roadmap

### 2.1 Mathematics

**Current boundary:** exact arithmetic and a bounded set of equations and unit
operations are available through explicit natural-language frames. Operator
phrases are learned from examples; this is not a general symbolic algebra or
proof system.

**Next work:** broaden question and instruction phrasing while preserving exact
expression parsing; add multi-step derivations only when each step has a
verifiable rule; distinguish unsupported notation, ambiguous precedence, and
resource limits from a mathematical contradiction. Expand property-based and
adversarial cases for signs, fractions, units, large values, and malformed
expressions.

**Measure:** exact result accuracy, derivation validity, supported-phrasing
coverage, abstention on malformed or unsupported inputs, and runtime/memory
bounds. Compare against a 70B-class model on the same answerable and
must-abstain set, scoring exactness separately from explanation quality.

### 2.2 Coding

**Current boundary:** CRMS renders Python for a bounded set of learned list
procedures. It is an inspectable code artifact renderer, not an open-ended
programming assistant, and it does not establish correctness merely by
producing syntactically valid code.

**Next work:** make supported requests discoverable in ordinary language;
improve role-safe composition of learned procedures; check generated artifacts
against the learned procedure and input/output examples; report unsupported
control flow, types, libraries, or side effects plainly. Any execution used for
validation must run in a bounded isolated environment and retain the input,
expected behavior, and result as evidence. Do not broaden the executable
surface without a threat and correctness review.

**Measure:** held-out functional cases, test-passing rate, semantic equivalence
to the learned procedure, wording transfer, and false-positive rate on
unsupported requests. Compare with a 70B-class model on identical prompts and
tests; score runnable correctness separately from explanation and code style.

### 2.3 Language translation

**Current boundary:** translation uses reviewed aligned examples and named
template slots. Copied slots and explicitly mapped values can transfer within a
licensed frame. It does not provide an open bilingual lexicon or general
translation for unseen vocabulary.

**Next work:** improve natural-language request handling, clarify source and
target language or register when missing, test slot alignment and agreement,
and add reviewable vocabulary or morphology records only when their evidence
supports the transfer. Preserve source sentence, aligned target sentence,
language pair, register, and the exact evidence used to license each frame.
Conflicting translations should be shown as alternatives or trigger
clarification, not silently ranked as truth.

**Measure:** held-out sentence adequacy, exact slot preservation, register
compliance, ambiguity handling, and abstention for unseen translated slots.
Compare against a 70B-class model using the same bilingual examples and test
sentences, with human review for meaning and fluency; exact-match alone is not
a sufficient translation metric.

## 3. Cross-domain composition

After each domain has stable individual checks, evaluate bounded compositions:

- translate a request, then apply a licensed math or coding operation only if
  the translated slots are unambiguous;
- use a verified calculation inside a generated code artifact only when the
  operation and types are explicit;
- explain a computed or generated result using the underlying proof or
  operation trace.

The first math→code slice is implemented in
`generate_mapped_math_python` and checked by
`experiments/v1_356_grounded_math_list_composition.py`. It parses a scalar
expression with the existing exact math grammar, requires exactly one integer
variable (`x`), refuses units and unsupported operators, then applies the
verified scalar function to each item of a bounded integer list. Its
standalone artifact carries the scalar expression's evidence and artifact ID,
an outer composition record, exact-rational list probes, and input bounds.
The CLI exposes the task through “Write Python code to apply x times x plus 3
to each value in the list”, then supports the existing code explanation and
evidence follow-ups. This establishes only an elementwise map composition;
translation→math/code and other cross-domain task structures remain untested.

Each composition must retain the lineage of every contributing frame, rule,
fact, and intermediate result. If one stage is unsupported, the whole result
must disclose the incomplete stage rather than presenting a complete-looking
answer. Start with two-stage tasks and held-out combinations; do not infer
general composability from success on isolated domains.

## 4. Evaluation against large-model comparators

Use pinned, versioned task sets and record model name/version, prompt, settings,
date, and scoring method for every external comparison. Give the CRMS and
70B-class systems the same task information and allowed tools. Separate:

- capability coverage: which tasks each system can attempt;
- correctness on shared answerable cases;
- uncertainty quality on unsupported and ambiguous cases;
- evidence or explanation quality;
- latency and memory/resource use.

Report per-domain and aggregate results, including sample size and confidence
intervals where applicable. A strength in transparent evidence or resource
use does not imply answer-quality parity. State a parity claim only for a
defined task distribution where the measured results support it; otherwise
publish the specific gaps and retain the roadmap status as incomplete.

## 5. Delivery order

1. Add a small, held-out natural-language benchmark for each existing domain,
   with positive, ambiguous, malformed, and unsupported cases.
2. Establish route, correctness, abstention, provenance, and resource
   baselines before expanding accepted language.
3. Improve math phrasing and exactness, code composition and functional
   validation, and translation alignment as independent workstreams.
4. Re-run cross-domain compositions only after their component contracts pass.
5. Compare with pinned 70B-class systems on shared tasks and publish measured
   gaps. Do not use the comparator as a source of unreviewed training targets.

The existing focused experiments (`v1_206`, `v1_207`, `v1_217`, and `v1_268`)
are useful component checks, but do not yet constitute the domain-wide or
cross-domain evaluation described here.
