# CRMS prototype

## Distributing learned CRMS memories

Documents, websites, and chats are inputs from which CRMS can learn. They are
not required to distribute the resulting learned stores. Create one portable
SQLite model database from learned knowledge and rule memories, with optional
math, translation memories, and extracted searchable source text:

```sh
python3 crms_package.py export --output crms-model.sqlite \
  --knowledge crms_knowledge.json --rules crms_rules.json \
  --math crms_math.json --translations crms_translations.json \
  --research-index crms_research.sqlite
python3 crms_package.py inspect crms-model.sqlite
python3 crms_chat.py --model-db crms-model.sqlite
```

After using the chat to learn facts, rules, math, translations, or new sources,
close the session so its sidecar is saved, then fold that state into a new
single-file model:

```sh
python3 crms_package.py repack crms-model.sqlite \
  --memory-dir crms-model.sqlite.memories \
  --output crms-model-updated.sqlite
python3 crms_package.py inspect crms-model-updated.sqlite
```

Repacking preserves embedded sources, includes updated sidecar memories and
research text when present, and validates the new database. The input model
is left intact; the output can be copied as the next distributable model.
`experiments/v1_278_portable_model_repack.py` checks that a learned fact,
operation phrase, translation frame, and newly indexed source all survive a
repack and work through the chat CLI.

The optional `--research-index` copies extracted readable text, page
boundaries, titles, and locations into the model database; it does not copy
the original files. On first run, `crms_chat.py --model-db` rebuilds a local
SQLite FTS index from embedded source text in a neighboring `.memories/`
working sidecar. The model database can therefore be distributed and searched
without the input files or a separately supplied index. Without
`--research-index`, the portable database contains learned memories only.
SQLite research indexes are exported and installed in batches to bound working
memory as the corpus grows. `crms_package.py inspect` reports embedded source
document count, UTF-8 bytes, and CRMS word-unit count so local corpus growth can
be measured; word units are not an LLM tokenizer count and do not establish
knowledge equivalence to a model by parameter count. Model v3 installs
`knowledge.sqlite` and `rules.sqlite` into the neighboring `.memories/` working
sidecar and chat writes learned changes back into the portable model. Older
v1/v2 models still rebuild the indexed fact sidecar from their JSON knowledge
payload. Pass `--fact-db PATH` only when using a standalone knowledge JSON file.
Direct fact lookups use subject/relation and
object/relation indexes, while source facts and citations remain alongside the
portable knowledge memory. Backward-chaining queries against these SQL tables fetch
only facts for the relations reachable through the query's declared rules,
plus the schema and entity-kind facts needed to verify that proof. The
independent proof checker validates against that same scoped snapshot. This
avoids materializing the full fact corpus for each inference query. Derived
proof reuse uses a fingerprint of the query's reachable relations, exact
qualifier scope, relevant schema/type facts, and applicable rules, so unrelated
corpus additions do not invalidate a verified case. Relevant positive or
negative evidence and rule changes do invalidate it.

An expanded open-academic package is available at
`data/crms_project_model_academic_expanded_pmc.sqlite`. It embeds 2,933 existing
documents and 20 redistributable PMC full-text articles, for 2,953 documents
and about 9.9 MB of extracted source text. The PMC records are CC BY or CC0 and
retain their license attribution and source revision notice. Start the
portable model directly with:

```sh
python3 crms_chat.py --model-db data/crms_project_model_academic_expanded_pmc.sqlite
```

A broad encyclopedia-backed package is also available at
`data/crms_project_model_academic_simplewiki.sqlite`. It embeds the existing
academic corpus plus 285,478 Simple English Wikipedia articles (288,431
documents total; about 602 MB of extracted source text). The source pages retain
their Wikipedia page URL, revision ID, and the importer-supplied CC BY-SA 4.0
license notice, so the SQLite model database is self-contained for search and
distribution. The original dump is not needed at runtime. See
`experiments/large_corpus_chat_audit.md` for a natural-language chat evaluation
on this corpus and the gaps it exposed. Start it with:

```sh
python3 crms_chat.py --model-db data/crms_project_model_academic_simplewiki.sqlite
```

For direct `What is X?` questions, chat can quote an exact-title source page
when its opening text gives a definition. For `Why ...?` questions, it returns
only a retrieved sentence with a nearby causal cue; otherwise it says the
indexed sources do not establish a reason. Both routes label quotations as
evidence rather than accepted facts. These are bounded retrieval rules, not
general paraphrase understanding. `Who ...?` questions can surface one
source sentence with all question content terms and a complete named subject;
recognized work, live, born, located, and based questions are scoped to an
exact-title entity page. “Where can I find information about X?” lists indexed
source titles containing the topic. These routes also preserve the
evidence/accepted-fact distinction.

For a simple active `Who VERB OBJECT?` question, if a source sentence yields
one matching subject–relation–object claim, CRMS can offer it as a review-only
candidate. Accepting it stores the cited fact and records the observed
sentence/question frame through the existing fact-learning path; retrieved
claims are not auto-accepted.

Learned stores can include evidence snippets, source identifiers, and
provenance needed to explain or audit what was learned. When learned memories
or indexed source text change during a session, CRMS repacks them into the
model database on `/quit` and refreshes the sidecar fingerprint. Rule search
and VSA retrieval settings travel with the model database and load at startup.

## Current status

CRMS is a deterministic, evidence-grounded prototype, not a general language
model. Its strongest demonstrated mechanisms are example-based procedure
learning over a bounded integer-list grammar; evidence-gated language and fact
retrieval; explicit provenance and proof checks for selected inference and
derived-case paths; and abstention when evidence is ambiguous or incomplete.
The system is designed to make its stored evidence and derivations inspectable.
For novel instructions, direct candidates from the grounded retrieval routes
are checked for behavioral disagreement before one is selected; a conflict
requests a contrastive example.
The terminal also has narrow exact-math and teacher-aligned translation-frame
prototypes; neither establishes general mathematical or translation
competence. A bounded question-frame trainer can also derive and retain
source-backed relation analogies after source-separated holdout checks, while
keeping those frames separate from teacher-provided examples.

The active grammar and language layer are still substantially hand-specified.
Primitive discovery is at an early, bounded stage: binary-window and local
arithmetic-expression proposals are report-only unless a caller explicitly
accepts one into that model's operation grammar. Acceptance adds no phrase
rule; stored examples must still pass ordinary procedure synthesis. The
retrieval-route ablation currently covers 320
controlled held-out cases, not the full experiment corpus; 304 predictions
depend on their designated route, while half of the lexical-feature cases still
resolve through other routes. The semantic canonicalizer contains many operation-specific
rewrite laws and remains a measured search hot spot; scaling beyond the current
grammar has not yet been established. These limits mean CRMS should be described as a
bounded symbolic learning and retrieval system, not as an alternative to
general-purpose language models.

### Initial exact arithmetic through learned language

The terminal routes arithmetic questions in bounded forms such as
`What is EXPR?`, `How much is EXPR?`, `Calculate EXPR`, and `Compute EXPR` to
`crms_math.py`. These wordings share the same expression grammar and learned
operator evidence; they do not add built-in meanings for words such as “plus.”
Teach each binary phrase with
`/teach-math QUESTION|ANSWER`; examples are matched against the declared exact
operation set (addition, subtraction, multiplication, rational division, and
integer modulo). A phrase is usable only after at least two distinct operand
pairs leave one operation consistent. Queries can compose learned phrases;
multiplication, division, and modulo bind more tightly than addition and
subtraction, equal-precedence operations associate left-to-right, and
parentheses override precedence.
Conventional arithmetic notation (`+`, `-`, `*`, `×`, `/`, `÷`, and `%`) is also
part of the explicit math grammar and composes with learned word operators;
signed integer literals are supported. These symbols have their standard
formal meanings. `%` follows Python's exact integer remainder convention,
including for negative operands, and rejects a zero divisor. A learned phrase
such as “remainder” uses the same operation only after aligned examples. Modulo
is supported in expressions with exact constant operands; symbolic remainder
expressions abstain. Words such as “plus” still require example-based
licensing. Equations accept either `equals` or `=` as the equality connective,
so `Solve 2 * x + 3 = 11 for x.` uses the same bounded exact solver and
substitution check as its word-operator form. A number or single-letter
variable adjacent to another variable or parenthesized factor means
multiplication, supporting forms such as `2x` and `(x + 1)(x + 1)`; unknown
multiword phrases are never treated as implicit multiplication. Unary plus and
minus also apply to numeric literals, variables, and parenthesized expressions,
so `-x` and `-(x + 1)` are represented and evaluated exactly.
Finite decimal and scientific-notation literals are converted directly to
exact rational values (`0.1 + 0.2` is `3/10`); CRMS does not route them through
binary floating-point arithmetic. The decimal grammar bounds significand and
exponent length, and the existing exact-result bit limit still applies.
Expressions may also use single-letter symbolic variables. Addition,
subtraction, multiplication, and division by a nonzero constant operate on
exact rational-coefficient polynomials; like terms combine and products
expand. Division by a variable expression is outside this grammar and
abstains. Symbolic expressions are bounded to 512 terms and 4,096 coefficient
bits. CRMS shows the learned phrase-to-operation mappings and supporting
examples.
Unknown phrases, unresolved ambiguity, division or remainder by zero, and
results beyond the arithmetic size bound abstain. These are learned surface
alignments; no operator synonyms are built in.
When a question fits the exact binary math frame but uses an unknown operator
phrase, CRMS now identifies the missing phrase and shows the bounded example
form needed to teach it instead of treating the request as an unrelated
unanswered fact question.

The same learning step is available in ordinary CRMS language with 2 to 8
explicit examples: `Teach math from examples: "What is 2 glorp 3?" -> 5;
"What is 5 glorp 3?" -> 8.` CRMS checks every example against the same exact
operation candidates and commits the batch only if all examples are
consistent. This bounded teaching form does not infer answers from unlabeled
arithmetic prose. When examples leave multiple operations, CRMS searches a
small bounded operand range for a pair on which candidate answers differ,
shows those alternatives, and accepts a natural-language numeric reply such as
`The result is -1`. The pending operands and phrase survive restart, and an
answer inconsistent with every remaining operation leaves the pending question
intact. `/cancel-math` stops that interaction without deleting examples.

CRMS also accepts the bounded equation frame `Solve EXPR equals EXPR for x.`
Here `equals` and `=` are reserved grammar connectives; arithmetic words still
need learned phrase evidence, while conventional operator symbols use their
fixed exact meanings. It solves univariate linear equations and
quadratics with rational roots, verifies every exact solution with a separate
exact evaluator over the original expression trees, and returns both distinct
roots when present. It abstains for irrational or
complex roots, degree above two, inconsistent or non-unique equations, and
unsupported variable structures. The equation result exposes the reduced
polynomial terms and exact solution tuple.

Word-form operands are available only when the existing rule learner has
grounded the cardinal phrase against digit-form instructions. The math route
consumes that public value-and-source mapping and includes those sources in its
answer explanation; ungrounded number phrases remain unknown. Ordinals such as
`third` are excluded from cardinal arithmetic. This transfer is bounded by the
rule learner's configured parameter ranges, not by a built-in number-word
dictionary.

The math route also supports exact unit conversion in natural forms such as
`What is 2 meters in centimeters?` and `Convert 2 meters to centimeters.`
Teach a conversion with
`/teach-unit-equivalence QUANTITY|QUANTITY`, for example
`/teach-unit-equivalence 2 meters|200 centimeters`, then provide a second
distinct quantity pair with the same ratio. A batch can also be taught in
ordinary CRMS conversation: `Teach unit conversions from examples: "2 meters"
-> "200 centimeters"; "5 meters" -> "500 centimeters".` Batches of 2 to 8
aligned quantity pairs are committed together; a conflicting pair rejects the
whole batch. Until two examples agree, CRMS abstains. Unit labels have no
built-in meanings: a conversion is possible only along a path licensed by
these examples, and the answer reports the examples used. Conversion questions can use a digit or a cardinal phrase already
grounded by CRMS's rule learner; its source examples are included in the
answer. Digit queries may use zero or negative integer amounts through the same
verified multiplicative ratio; teaching examples remain positive integers.
Conflicting ratios are rejected. Once units are grounded, expressions
can add or subtract compatible quantities (the result uses the leftmost unit)
and multiply or divide a quantity by a scalar. Adding different learned unit
components, multiplying two quantities, and dividing by a quantity abstain.
This prototype handles positive integer conversion examples and exact
multiplicative ratios; it does not model offsets such as temperature scales,
infer physical dimensions independently, or combine unitful quantities in
general algebra.

`experiments/v1_206_grounded_math_language.py` checks held-out arithmetic,
example-learned remainder and standard `%`, negative operands and zero-divisor
abstention, contrastive disambiguation, exact rational output, rejection of conflicting
examples, unknown-phrase and unsupported-frame handling, persistence, and
ordinary terminal-chat routing, standard operator notation and its composition
with learned phrases, implicit factors, unary signs, precedence, grouping, bounded linear and
rational-quadratic equation solving with substitution, and bounded exact
composition, learned word-form cardinal operands, numeral source lineage, and
ordinal/cardinal separation, symbolic polynomial expansion, like-term
combination against an independent exact substitution check, persistence, and
unsupported symbolic-division abstention. Unit checks cover two-example
licensing, exact and transitive conversion, unit-aware addition and scalar
arithmetic, dimensional abstention, evidence rendering, conflicting and
disconnected unit rejection, persistence, and natural-chat routing.
`MathResult.symbolic_terms`
exposes the exact monomial powers and rational coefficients for polynomial
checks. This remains a narrow math prototype, not a general solver: it does
not support equations above degree two, irrational or complex roots,
functions, unconstrained natural-language syntax, or unconstrained
mathematical prose.

### Initial aligned translation frames

CRMS can apply a teacher-declared sentence-frame pair through ordinary
language input. Teach with
`/teach-translation SOURCE-LANGUAGE|TARGET-LANGUAGE|REGISTER|SOURCE-TEMPLATE|TARGET-TEMPLATE|SOURCE-1|TARGET-1|SOURCE-2|TARGET-2`.
The same bounded teaching input is also available conversationally, for
example: `Teach a translation frame from English to French in formal register:
"Hello, {name}." => "Bonjour, {name}."; "Hello, Ada." -> "Bonjour, Ada.";
"Hello, Malik." -> "Bonjour, Malik."`. This makes the frame accessible in
CRMS language while keeping templates and all aligned examples explicit;
they are checked by the same licensing rules as the command form. The natural
template form accepts two to eight aligned pairs in one turn, so additional
source-to-target slot values can be licensed together.
For a simpler copied-slot case, teach only parallel pairs with
`Teach translation examples from English to French in formal register:
"Hello, Ada." -> "Bonjour, Ada."; "Hello, Malik." -> "Bonjour, Malik."`.
CRMS infers one or more slots only when token-aligned varying source and target
spans are exactly the same text, validates every supplied pair against that
frame, and prints the inferred templates. This can transfer copied names,
items, and other shared text while keeping fixed language structure separate.
If the differing spans are translated, inserted, deleted, or otherwise
misaligned, it refuses this inference and requires explicit templates.
Templates use matching named slots, such as `{name}`, and both parallel
examples must fit the templates and use distinct source bindings. Each slot
learns its exact source-to-target value mapping; for example, a teacher can
license `{food}` with `tea` → `thé` and `coffee` → `café`. After a frame has
been licensed with multiple pairs, the user can add one exact mapping in an
ordinary turn: `Teach an additional translation example from English to French
in neutral register: "I like sugar." -> "J'aime le sucre."`. CRMS accepts this
only when the language pair, register, and source sentence identify exactly
one existing frame; conflicting mappings or ambiguous frames are rejected
without changing the memory. Initial frame licensing still requires multiple
aligned pairs. A request such as
`Translate from English to French in formal register: Hello, Rowan.` or
`Could you please translate from English to French in formal register: Hello,
Rowan?` matches the learned frame and substitutes `Rowan` into its target
template. A template's final punctuation may be omitted from the input, while
substituting a different final mark does not match. CRMS keeps the language
direction and register separate, reports the matched template and
supporting pairs, and abstains on missing or conflicting matches. A request may
omit the register when matching frames identify one output; if different
registers produce different outputs, CRMS shows the supported candidate
translation for each register and asks the user to specify one.
A short reply naming one of the displayed registers, such as “formal register”
or “go with the informal one,” continues that translation request. The choice
must match an offered register. This pending clarification is held only for the
current terminal session and a small `--translation-session` file. `/quit`
preserves a register or source-language choice for the next launch; the source
text and offered choices are restored only when the translation memory's
content fingerprint is unchanged. A new unrelated turn clears the pending
choice. Editing the translation memory invalidates it so a stale choice cannot
be applied.
The sentence may also come first, for example “Please translate ‘Hello, Rowan.’
from English into French.” Polite sentence-first requests use the same explicit
language-pair and frame lookup. When the quoted source sentence matches frames
for exactly one licensed source language, CRMS also accepts the common shorter
form “Translate ‘Hello, Rowan.’ into French.” It infers that source language
from the matching frame and retains the same evidence and register checks. If
multiple source languages match, it asks for the source language; a reply such
as “I mean Spanish” resumes the original request only if Spanish is one of the
offered choices. Each offered source language must have a matching frame whose
slot values can actually be translated, and unresolved overlapping frames
remain grounds to abstain; CRMS shows the resulting candidate sentences beside
the language labels. An unsupported explicit choice keeps the clarification
open.
The natural question “How do you say Hello, Rowan. in French?” (or the quoted
form “How do you say ‘Hello, Rowan.’ in French?”) uses that same target-only
path, including source-language clarification when multiple
licensed source frames match; “in formal register” can be stated in the same
request. It does not introduce a separate translation model or bypass the
frame evidence. For unquoted requests, the final target-language label is
matched against stored translation frames, so a source sentence such as “I
live in Rome” is not split at its own word “in”.
If no frame matches, CRMS abstains. This inference uses licensed frame coverage
rather than a general language detector. Named slots can cover multiple roles
and appear in a different order in the target template; two aligned examples
license held-out role values while preserving the declared slot mapping.

This is bounded frame transfer, not open-ended translation. Explicit templates
may map different source and target slot values, but the source value must have
an exact aligned example; unseen translated values abstain. Automatically
inferred templates still require copied spans. Examples mechanically check
frame and value alignment but do not independently establish that the fixed
words preserve meaning. The system does not infer an open-ended lexicon, inflect
words, or verify tense, polarity, modality, or semantic roles. The
translation-memory diagnostic covers copied and translated slots, incremental
single-pair learning, rejection of conflicting updates, multi-slot reordering,
register and source-language inference with one-turn conversational
clarification (including preservation after an unsupported choice and across
restart when the translation memory is unchanged), stale-session invalidation
after a memory edit, direction boundaries, ambiguity, persistence, and chat
routing;
held-out parallel corpora and independent semantic-role checks remain needed
before claiming language-pair coverage.

Near-term work should measure retrieval contributions on broader fixed
corpora, test the canonicalizer's cost as the operation grammar grows, and
evaluate primitive proposals on independent failure clusters with held-out
utility and complexity gates. Automatic promotion of proposed primitives is
disabled; derived-case write-back remains gated by proof validation, provenance,
correction propagation, and bounded storage. The experiment history below
records the evidence and limits behind these statements.

`crms_model.py` is a self-contained, deterministic CRMS model for integer-list
transformations. It stores examples by exact instruction string, searches a
finite operation library, learns procedures up to four steps, and abstains
when the evidence has multiple fits or no fit. Repeated words, aligned phrase
positions, grounded positional analogy frames, learned affix and token-span
edits, numeric slots, grounded sequence-connective composition, and a gated
VSA fallback can retrieve
procedures from examples. The model has no built-in word meanings or synonym
list.

## Use

Start with the terminal chat:

```sh
python3 crms_chat.py
```

Ask about a stored fact, add evidence with `/source PATH`, or teach a cited
fact with `/teach-fact`. The first `/help` shows a short quick start; `/help all`
lists every command. CRMS explains when a fact or question wording is missing
and abstains when stored evidence does not support an answer. Use scratch paths
for `--knowledge`, `--index`, and other state options when you want to keep
runtime state separate from the source tree.

### Python API

```python
from crms_model import CRMSModel

model = CRMSModel("crms_memory.json")  # loads memory if the file exists
instruction = "apply doubling twice"

print(model.predict(instruction, [1, 2]))  # asks for examples initially
learn = model.teach(instruction, [
    ([1, 2], [4, 8]),
    ([3, -1], [12, -4]),
])
print(learn.status, learn.procedure)
print(model.predict(instruction, [5, 2]).output)  # [20, 8]
```

Rule memories can be stored as JSON or as a versioned SQLite database. In chat,
pass a `.sqlite` path to `--rules`; examples, accepted procedures, and supporting
rule artifacts are stored in separate rows. JSON remains available for import,
export, and existing workflows. Portable model v3 files include normalized
knowledge and rule tables, verify them against compatibility payloads, and
install writable SQLite sidecars for chat. Existing v1 and v2 model files
remain readable.

The parameterized rule family can also discover multipliers beyond doubling:

```python
model = CRMSModel(max_composition_depth=1)
learn = model.teach("triple every value", [([1, 2], [3, 6]),
                                           ([2, -1], [6, -3])])
print(learn.status, learn.procedure)  # learned; scale_k with k=3
```

Repetition count is also a grounded parameter rather than a fixed primitive:

```python
model = CRMSModel(max_composition_depth=1, max_repeat=5)
model.teach("repeat each value 3 times", [([1, 2], [1, 1, 1, 2, 2, 2])])
model.teach("repeat each value 4 times", [([2, 1], [2, 2, 2, 2, 1, 1, 1, 1])])
print(model.predict("repeat each value 5 times", [3, 1]).output)
# [3, 3, 3, 3, 3, 1, 1, 1, 1, 1]
```

The operation is inferred from list examples, and the number slot transfers
only because two distinct counts ground the same phrase frame. Counts are
bounded by `max_repeat`; no built-in meaning for “repeat” or the count is
assumed by the learner.

The same family can learn sign reversal from examples:

```python
model = CRMSModel(max_composition_depth=1)
learn = model.teach("negate every value", [([1, -2], [-1, 2]),
                                           ([-3, 4], [3, -4])])
print(learn.status, learn.procedure)  # learned; scale_k with k=-1
```

Identity is also a learnable rule when examples show that values should remain
unchanged:

```python
model = CRMSModel(max_composition_depth=1)
learn = model.teach("keep the list as is", [([3, 1, 2], [3, 1, 2]),
                                            ([5, 2, 4], [5, 2, 4])])
print(learn.status, learn.procedure)  # learned; identity
```

`add_position` is an opt-in position-dependent rule: it adds each item's
one-based position to its value (the first item receives `+1`). Enable it with
`CRMSModel(enable_position_arithmetic=True)`; keeping it opt-in avoids
expanding the default depth-three/four search space. The mapping is learned
from examples like other operations; words such as “position” have no built-in
rule meaning. Programs containing this operation keep a conservative syntax
key, and composition with positional filters is gated until their
order-dependent interaction has an exact summary.
`experiments/v1_166_position_value_rule_discovery.py` checks unique learning,
held-out transfer, empty/singleton behavior, and persistence.

Stable duplicate removal is another example-discovered primitive. The
`stable_unique` operation keeps the first occurrence of each integer and
preserves the order of those first occurrences. To distinguish it from
identity, examples must include repeated values; unique-only examples remain
ambiguous. Its current semantic canonicalizer conservatively treats programs
containing this operation as distinct by syntax except for proven first-
selection identities; it does not claim unverified equivalence between other
compositions around deduplication.
`experiments/v1_97_stable_unique_learning.py` checks discovery, held-out order,
identity ambiguity, and persistence.
`experiments/v1_100_endpoint_deletion_learning.py` checks learning first/last
deletion, empty and singleton behavior, persistence, exact repeated-run
and rotation/reversal canonicalization, and composition after a first-relative
filter.
`experiments/v1_98_relational_affine_canonicalization.py` checks exact semantic
grouping for affine transforms and uniform repetition around first-relative
filters, including negative-scale relation reversal. It also checks 82
same-key program pairs against 781 exhaustive short integer lists each, in
addition to seeded wider probes; no output disagreement was found.

The operation library also includes `absolute_values`, which maps each signed
integer to its magnitude. It is learned from input/output demonstrations; the
phrase has no built-in meaning. Its canonicalizer collapses only the exact
idempotence and commutation with reversal/rotation, repetition, positional or
endpoint selection, and value filters that preserve divisibility. It also
normalizes magnitude across signed scale operations while retaining syntax for
unproved interactions.
`experiments/v1_133_absolute_value_discovery.py`
checks unique learning, held-out lists, composition with reversal, persistence,
and a non-equivalent sorting-order control. It also checks that the
canonicalizer merges no behaviorally different programs across 2,379 generated
one-to-three-step cases and 781 exhaustive short lists.

The operation library also includes `sort_by_magnitude`, a stable ascending
sort by absolute value. The learner must distinguish it from numeric
ascending/descending order using mixed-sign demonstrations; equal-magnitude
values retain their input order. Its canonicalizer uses a conservative syntax
key with exact identity removal, repeated-sort idempotence, proven commutation
with repetition and stable uniqueness, and removal when immediately followed
by a numeric sort. Instruction words have no built-in mapping to the
operation. `experiments/v1_141_magnitude_sort_discovery.py`
checks unique discovery, held-out values and tie order, composition with
reversal, persistence, terminal teaching, and abstention for an unseen phrase.

The operation library also includes `sum_values`, which reduces an integer
list to a one-item list containing its sum; the empty list maps to `[0]`.
The operation name is not attached to any built-in instruction meaning: CRMS
learns a phrase-to-sum rule only from input/output examples. Programs
containing aggregation retain a conservative syntax key until the semantic
canonicalizer can prove interactions with other operations. The composed
search's length bound accounts for reduction and the empty-sum result.
`experiments/v1_121_sum_rule_discovery.py` checks ambiguity on singleton-only
evidence, empty and multi-value demonstrations, held-out prediction, explicit
language composition with a learned doubling rule, and persistence.

Prefix accumulation is a separate operation: `cumulative_sum` returns every
running total while preserving the input length, so the empty list maps to an
empty list and a singleton remains unchanged. As with aggregation, the rule is
learned only from demonstrations, and compositions containing it retain a
conservative syntax key until exact interaction laws are established.
`experiments/v1_127_cumulative_sum_discovery.py` checks singleton ambiguity,
mixed-sign and empty-input evidence, held-out prediction, composition with a
learned doubling rule, and persistence.

Neighbor differences are available as `adjacent_difference`: each output is
the next input value minus its immediate predecessor, so empty and singleton
inputs both produce an empty list. This is a learned operation, not an
instruction keyword. Its compositions use a conservative syntax key until
their interaction laws are established. `experiments/v1_129_adjacent_difference_discovery.py`
checks ambiguity, edge cases, mixed-sign transfer, composition with learned
prefix accumulation, and persistence.

The rule library also includes a parameterized divisibility filter:

```python
model = CRMSModel(max_composition_depth=1, max_modulus=6)
learn = model.teach("keep multiples of 3", [([3, 4, 6, 8], [3, 6]),
                                             ([9, 10, 12], [9, 12])])
print(learn.status, learn.procedure)  # learned; keep_multiples_k with k=3
```

All operations run on CPUs. For sufficiently large two-step searches the
model uses Python worker processes, capped to CPUs available to the process;
small searches stay serial to avoid process startup cost. Set `max_workers=1`
to force serial search, or set `max_workers=N` to cap worker count. Programs
that trigger multiprocessing should start model work under the normal Python
main guard (`if __name__ == "__main__":`) on platforms that use spawn workers.

`teach` returns `learned`, `need_more_examples`, or `no_fit`, with a request
that can be shown to the user; when no examples are supplied it returns
`need_examples`. `predict` returns `ok` with an output or an abstention status
and request. Successful predictions include `evidence_phrases` and
`matched_tokens`, `matched_bigrams`, and `matched_templates` so callers can see
whether a result came from an exact taught phrase, repeated lexical grounding,
an aligned phrase pattern, a learned numeric or categorical slot, or a
positional analogy. For derived word forms,
`evidence_phrases` includes the phrases that grounded the affix edit. Supplying more examples uses the same instruction
association; pass `replace=True` to discard its old evidence first. Configured
memory is saved to JSON after learning and deletion.
After a complete search, CRMS keeps that instruction's candidate version
space in memory and filters it when more examples are appended. This avoids
re-enumerating the same bounded program grammar during a teaching exchange.
The transient least-recently-used cache keeps at most 16 instruction spaces
and skips spaces larger than 10,000 candidate procedures. It is discarded on
replacement or forgetting and is never persisted. `experiments/v1_112_incremental_candidate_space.py`
checks parity with fresh batch search and cache invalidation.
When teaching leaves multiple exact procedures, `predict()` can reuse the
contrastive input computed during that teaching exchange to ask a focused
follow-up. The transient probe is tied to the exact demonstration snapshot and
search bounds, cleared when the evidence resolves or changes, and is not
persisted; after reload CRMS safely asks for a new contrastive example.
`list_rules()` inspects committed procedures; `forget(instruction)` removes an
association.
Abstentions also report `language_gaps` when the missing evidence can be
identified deterministically: `unknown_tokens` have no taught phrase
association, `under_supported_tokens` occur in fewer than two distinct taught
phrases, and `weak_bigrams` lack repeated adjacent-pair evidence. The request
names these gaps and asks for an input/output example. `conflicting_tokens`
and `conflicting_bigrams` identify query features that point to multiple
learned procedures; when a contrastive probe is available, the request shows
those alternatives alongside the probe. This is an evidence diagnosis only;
CRMS does not infer a token's meaning from the diagnostic.
When learned phrase evidence narrows an otherwise ambiguous `teach` search,
`LearnResult.evidence_phrases` reports the supporting instruction cases. The
language prior is applied only if its procedure still fits every supplied
input/output example.

## VSA retrieval

After exact, numeric, aligned, and repeated-token retrieval have no grounded
answer, CRMS can compare the query with stored instruction cases using two
deterministic 1000-dimensional bipolar hypervectors: position-bound token
vectors and an order-invariant token bundle. `vsa_alpha` weights the
order-invariant score; defaults are `0.5`, with a minimum similarity of `0.30`
and a top-candidate margin of `0.10`. Predictions report the supporting case
and score in `evidence_phrases` and `matched_templates`.

The vectors come from stable hashes and require no trained model or neural
network. They represent token overlap, not word meaning. To keep this fallback
conservative, query tokens must form an in-order subsequence of the supporting
phrase: omitted words can be tolerated, while added or reordered words need
other grounded evidence. An unknown synonym still has no case token to match.
If VSA retrieval abstains because its best candidate has low similarity or too
little separation from the runner-up, `Prediction` exposes the `retrieval_score`
and `retrieval_margin`, plus a `contrastive_input` and aligned `candidate_outputs`
when the bounded probe search finds a real separator. These scores are
similarities and margins, not calibrated probabilities. The probe is a request
for teacher feedback; it does not resolve the ambiguity by itself. Other
abstentions may also expose a VSA score and margin when eligible grounded cases
were found.
The VSA settings are persisted with memory and must match when it is loaded.
The encoder retains the same 1,000-dimensional bipolar score, while cached
phrase vectors use integer bit masks and `bit_count()` similarity. Bundling uses
bit-sliced counters, preserving the coordinate-wise majority and tie behavior.
An inverted token index intersects the postings for every distinct query token
before scoring; exact multiplicity and in-order checks still gate every
candidate. This avoids Python-side visits to phrases missing any required
token, including when each individual posting is dense. Queries whose tokens
co-occur in most phrases can still scan most of the memory, so worst-case
retrieval remains linear. `experiments/v1_19_retrieval_scaling_diagnostic.py`
checks retrieval on common, selective, and unique-token workloads.

When `teach` returns `need_more_examples`, it searches short lists for an input
that makes the remaining procedures predict different outputs. The result
includes `contrastive_input`, aligned `candidate_outputs`, and
`candidate_procedures`. The interactive request groups identical predicted
outputs and bounds the displayed list, while the result object retains every
candidate output for inspection. A suggested input is a real separating
example, while no suggestion only means the bounded probe search found none.
`experiments/v1_106_contrastive_output_summary.py` checks that large ambiguity
sets remain readable without discarding the underlying candidate data.

Composed rule search is bounded by `max_search_expansions` (default 250,000)
per teaching attempt. If that limit is reached, `teach` returns
`search_incomplete`, preserves the examples, reports the expansion count, and
does not commit a procedure from the partial candidate set. Raise the
configured limit for a larger search or add examples to narrow the candidate
space. The setting is persisted with model memory so reloads use the same
search budget. For composed search, the count is newly visited semantic
behaviors that survive exact canonicalization and the sound length-reachability
bound, rather than syntactic extensions or prefixes already proved unable to
match the demonstrated output lengths. Search prefixes carry an incremental
signature for relational and positional-filter constraints, avoiding repeated
full-prefix scans while preserving the same extension gates. The availability
of sum operations is computed once per search. `experiments/v1_140_search_gate_parity.py`
compares the incremental gates with the original predicates over every
configured operation and 2,000 seeded prefixes.

The deterministic semantic canonicalizer uses a process-local LRU cache of
exact procedure keys (131,072 entries). It is bounded, is not written to model
memory, and does not change which programs are considered equivalent; it
avoids repeating canonicalization work when bounded search revisits the same
program. A cache miss still runs the full canonicalizer.
`experiments/v1_142_semantic_key_cache.py` checks cached/uncached parity across
12,111 generated programs, recursive canonicalization, runtime reuse, and
parameter mutation.

The corresponding prediction-time active-learning path is checked by
`experiments/v1_22_metacognitive_retrieval.py`: an ambiguous retrieval abstains,
requests the intended output for a separating input, and can learn the answer
after the teacher supplies confirming examples.

Instructions can also be composed with the explicit separator `, then `:

```python
# Learn each phrase as a primitive, then compose them at prediction time.
compose_model = CRMSModel(max_composition_depth=1)
compose_model.teach("reverse the list", [([1, 2, 3], [3, 2, 1]),
                                        ([4, 1, 2], [2, 1, 4])])
compose_model.teach("double every element", [([1, 2], [2, 4]),
                                            ([3, -1], [6, -2])])
print(compose_model.predict("reverse the list, then double every element", [5, 1, 3]).output)
# [6, 2, 10]
```

Each part must have a uniquely learned procedure, unless the entire compound
instruction has itself been taught. The explicit separator is parsed literally.
When learning individual primitives, `max_composition_depth=1` avoids ambiguity
from longer candidate programs that happen to fit the same examples.

CRMS can also learn a sequential connective from examples. It requires two
distinct grounded component-phrase pairs whose concatenated procedures match
their demonstrated compound behavior. It can then compose a new combination of
grounded components through that observed connective. A single compound
context or an unseen connective is insufficient. The learned route has no
prebuilt connective or synonym list.

At every search depth, candidate procedures are compared by behavior, not
spelling. The model summarizes the current operation library's effects on
values, modular residues, ordering, and selection. Programs with identical behavior on
every finite integer list count as one candidate. It reports a deterministic
shortest representative. Procedures with different behavior that still fit the
examples remain ambiguous and require more evidence.

Language transfer is learned from examples. A word constrains possible
procedures only after it appears in at least two distinct taught phrases. An
adjacent word pair can also constrain retrieval after it appears in at least
two distinct phrases. The model intersects these candidate sets and answers
only when one procedure remains. Bigrams preserve some word-order evidence;
they do not provide general syntax or meaning. In lexical transfer, an
unobserved or weakly supported adjacent word pair also causes abstention;
familiar individual words in a new order are not enough to identify a rule.
Token and bigram postings are cached and rebuilt after teaching, forgetting,
or loading memory, so repeated lexical lookups do not reconstruct the index.
The separate aligned-position route can still combine independently grounded
word substitutions. Unknown query words cause abstention because they may
change the instruction, except for a number in a numeric phrase frame learned
as described below. For example, teaching both
“reverse the list” and “reverse the order” with demonstrations grounds the
shared word “reverse”; a new phrase using known words and an adjacent pair
repeated across taught phrases can reuse the procedure. Unseen synonyms and phrases with unknown
words still require examples. Conflicting word or bigram associations cause
abstention.

The model can also combine observed word substitutions by position. If separate
example sets ground `"reverse the list"`, `"reverse the array"`, and
`"flip the list"` to the same procedure, it can retrieve that procedure for
`"flip the array"`. Every word must have appeared at its query position in a
phrase grounded to that same behavior. Each changed position also needs a
same-rule phrase pair that differs only there, including the queried word;
at least two phrases are required. The aligner can also infer a short prefix
or ending edit, such as adding `re-`, adding `s`, or changing `y` to `ies`,
when the same edit appears with at least two different stems in independently
contrasted phrase pairs whose two phrases each ground to the same rule. It may
apply that edit to another stem already grounded at that position.

CRMS also has a stricter positional analogy route for combinations that lack a
one-word-at-a-time contrast. It requires at least two distinct, independently
taught phrases with the same learned behavior and token count, at least two
varying positions, and every query token grounded at its position in two
distinct phrases. For example, `"reverse the list"`, `"reverse the values"`,
`"turn the array"`, and `"flip the array"` can support `"reverse the array"`.
This is a discrete role-frame completion derived from demonstrated procedures;
it does not infer that arbitrary words are synonyms. Competing frames or an
ungrounded role value cause abstention. Successful predictions return the
evidence phrases and an `analogy_frame:` template.
`experiments/v1_23_positional_analogy.py` checks
transfer, persistence and forgetting, missing evidence, unknown role values,
competing frames, and whether a grounded analogy can narrow an ambiguous rule
search without overriding contradictory examples.

For categorical contrasts that select different rules, CRMS can learn a
position-specific token-to-procedure mapping across independent phrase
contexts. A value is used only when it maps to one rule in at least two
distinct phrases, another value at that position maps to a different rule,
and every other query token is grounded at its position for the selected rule.
For example, `"remove the first item"` / `"remove the last item"` and
`"delete the first element"` / `"delete the last element"` support the held-out
combination `"remove the first element"`. This learns a local categorical
slot relation; it does not assign a universal meaning to `first`, `last`, or
the verbs. Unknown words and conflicting mappings still make the model abstain.
`experiments/v1_101_contrastive_instruction_slots.py` checks this transfer,
evidence attribution, persistence, terminal use, and abstention for unknown or
conflicting evidence.

The same route can learn an optional contiguous token span from at least two
distinct phrase-pair contexts that ground to the same rule, at the same token
position. It can then combine either deletion or insertion of that span with
independently grounded substitutions. For example, demonstrations for
`"reverse the list"` / `"reverse list"`, `"reverse the values"` /
`"reverse values"`, `"turn list"`, and `"turn the list"` can support both
`"turn values"` and `"turn the values"` without a prebuilt stop-word list.
A single span pair is insufficient, and retracting enough donor examples
removes both transfers.
`evidence_phrases` includes the phrases that ground the span edit and
substitutions; `matched_templates` reports the aligned pattern. These edits do
not infer general grammar or unseen stems. `experiments/v1_15_learned_optional_word_diagnostic.py`
checks both directions, evidence retraction, ambiguity, persistence, and
unknown-modifier abstention.

Numeric parameters can transfer through an exact phrase frame. For example,
teaching `"add 3 to every value"` and `"add 5 to every value"` with examples
that infer the matching `add_k` rules lets the model apply the same frame to
`"add 7 to every value"`. Frames can contain multiple numbers, aligned in
order with varying parameterized steps of the inferred procedure. A composed
procedure may also contain fixed parameters, which must remain identical across
the grounded examples. Each numeric slot must map consistently and uniquely to
a varying parameter, directly or by sign reversal, across at least two
distinct phrases. New mapped values must be within configured operation
ranges. For example, examples for `"set every value to 3"` and
`"set every value to 7"` can teach the composition `scale_k(0)` followed by
`add_k(k)`; a separately grounded number word `five` can then transfer into
that frame as `set every value to five`. The zero-scale parameter stays fixed
while the addition parameter varies. `experiments/v1_147_fixed_parameter_numeric_slots.py`
checks this transfer, fixed-parameter retention, bounds, abstention, and
persistence. `keep_multiples_k` is searched from 3 through `max_modulus`;
the even and odd filters cover divisibility by two. Two relational primitives
also retain values strictly greater than or less than the current first value;
they preserve order, exclude values equal to that reference, and return an
empty list for empty input. They can be learned compositionally from examples.
The bounded learner can identify each as a one-step rule from examples. In
multi-step search they may follow ordinary operations and may be followed by
`first`/`last` selection or `drop_first`/`drop_last` deletion. The canonicalizer
recognizes the exact relational-filter-plus-endpoint form, preserves any
preceding affine value transform in that equivalence, and treats uniform
repetition as irrelevant to the selected value. Endpoint deletion compositions
use conservative syntax keys except for proven repeated-run identities. More
complex reference-changing interactions remain syntactically distinct and may
require additional examples. The words in a
numeric frame are matched literally. This does not
teach a new operation or infer a different paraphrase of the frame.
When a query matches a grounded numeric frame but has too little slot evidence
or requests an out-of-range value, the model abstains instead of letting
weaker lexical or VSA retrieval silently reuse another parameter value. The
abstention includes the phrases that grounded the frame in `evidence_phrases`
and reports the frame in `matched_templates`.

This also supports a grounded subtraction frame: if examples for
`"subtract 3 from every value"` and `"subtract 5 from every value"` infer
`add_k` parameters -3 and -5, respectively, the consistent sign mapping lets
the model apply `"subtract 7 from every value"` as `add_k(-7)`. The mapping is
induced from the demonstrated frame and parameters; no subtraction keyword
rule is built into the language retriever.

Number words are not built into a dictionary. CRMS can bind a contiguous
number phrase such as `"twenty one"` to the digit `21` when committed phrases
differ only at that numeric span, share the same inferred procedure, and the
literal matches the procedure's parameter magnitude. Hyphenated forms such as
`"twenty-one"` use the same grounded token sequence. Conflicting values remove
the phrase from the learned number mapping. Once grounded, the phrase can fill
numeric slots in another parameterized rule family; `evidence_phrases` retains
the examples that established the mapping. The
`experiments/v1_109_multiword_numeric_slots.py` diagnostic checks cross-family
transfer, unknown-phrase abstention, and persistence.

Number phrases can also compose when CRMS has direct evidence for their parts.
For example, if `"twenty"`, `"one"`, and `"two"` are grounded and both
`"twenty one" → 21` and `"twenty two" → 22` are taught against digit forms,
the repeated additive structure can license `"twenty three" → 23` when
`"three"` is separately grounded. One compound example is not enough. The
composed phrase retains the part and pattern examples as provenance, and an
unknown component still causes abstention. This is a narrow learned
compositional rule, not a built-in English number parser.
`experiments/v1_111_compositional_number_words.py` checks two-example schema
support, held-out and hyphenated composition, provenance, abstention,
withdrawal after forgetting a supporting example, and persistence.

Grounded number phrases can also support a multiplicative suffix pattern. For
example, after separately grounding `two` as 2, `three` as 3, `four` as 4,
`two hundred` as 200, and `three hundred` as 300, CRMS can derive `four
hundred` as 400. The suffix factor must agree across at least two distinct
grounded prefixes and compounds; the result must remain within configured rule
parameter bounds. A single compound, unknown prefix, or ambiguous mapping does
not license transfer. This is example-induced composition, not a built-in
English numeral grammar. `experiments/v1_143_grounded_multiplicative_number_words.py`
checks held-out transfer, lineage, persistence, insufficient support, and
unknown-prefix abstention.

Longer additive compounds can transfer after CRMS sees a complete 2×2 grid
of grounded prefix/suffix combinations whose outputs equal the sum of the
separately grounded parts. Examples for 200 + 21, 200 + 22, 300 + 21, and
300 + 22 can support the held-out phrase `four hundred twenty three` when
`four hundred` and `twenty three` are separately grounded. Sparse grids do not
license composition, and ambiguous or out-of-range results remain unavailable.
`experiments/v1_144_grounded_compound_numerals.py` checks held-out transfer,
complete-grid gating, provenance, persistence, hyphenated tokenization, and
abstention when an ungrounded connective is inserted. It also learns optional
`and` placement from two directly grounded number-phrase pairs with distinct
values and the same insertion boundary; forgetting one supporting pair
withdraws that transfer. Other connective positions still require evidence.

The same complete-grid rule now supports a second grounded composition level:
thousand-scale prefixes can combine with hundred-scale compounds when their
independently observed grids support the same token-boundary pattern. Inferred
splits must have strictly descending component magnitude, preventing the
additive learner from treating reversed or repeated pieces such as `twenty one
two hundred` or `two hundred two hundred` as licensed merely because their
values sum correctly. Directly taught phrases remain available.
`experiments/v1_148_hierarchical_numeral_composition.py` checks the held-out
phrase `four thousand two hundred twenty three`, sparse-grid and unknown-prefix
abstention, reverse-order rejection, provenance, and persistence. This remains
bounded example-based composition, not a general English numeral parser.
Optional `and` can also transfer at a deeper boundary when two distinct
thousand-scale numeral pairs directly demonstrate the same insertion position.
`experiments/v1_149_hierarchical_numeral_connective.py` checks transfer into the
held-out phrase above, exact boundary grounding, provenance, persistence, and
abstention with one supporting pair or a different insertion position.

Signed digit/word pairs retain their sign during alignment. A one-token prefix
can be learned as a negation marker when at least two directly grounded
negative phrases agree with their separately grounded positive remainders.
For example, `minus three` and `minus four` can support `minus twenty three`
once `twenty three` is grounded. The prefix is learned from those pairs rather
than assigned a built-in meaning. `experiments/v1_145_grounded_negative_number_words.py`
checks signed alignment, transfer, provenance, persistence, and abstention
with insufficient or unknown prefix evidence.

The parameterized scale family now includes `scale_k(0)`, which maps every
input value to zero. This gives the learner a nontrivial zero-valued rule and
lets it ground `zero` against digit examples, while `add_k(0)` remains excluded
because it is identical to list identity. `experiments/v1_146_zero_scale_learning.py`
checks discovery, grounded-word transfer to a different phrase frame, unknown
word abstention, and persistence.

The current primitives are identity, reverse, ascending/descending sort,
stable magnitude sort, stable duplicate removal, double, elementwise squaring,
repeating every element a bounded number of times, scaling
by integers from -`max_scale` through 0 or from 3 through `max_scale`, even
and odd filtering, divisibility filters from 3 through `max_modulus`, adding a
constant from -`max_add` through `max_add`, first/last selection, first/last
deletion, and left rotation by a nonzero offset from -`max_rotation` through
`max_rotation`. `add_first` adds
the input's first value to every value, and `subtract_first` subtracts it from
every value; both are data-dependent rules, not fixed numeric parameters.
Empty lists remain empty under rotation and these two input-relative rules.
`repeat_each_k` emits `k` adjacent copies of every value,
with `k` from 2 through `max_repeat` (default 4). The older `duplicate_each`
procedure remains loadable for stored memories and migrates in memory to a
repeat count of two. Positional filtering keeps ordinal positions 1, 3, 5, ...
or 2, 4, 6, ... (one-based); these operations are separate from filtering by
the values' evenness or oddness. Interactions with affine value transforms
have an exact canonical form. General composition search currently combines
these filters with other positional selectors and affine value changes. Search
also permits positional selection to compose with reversal and ascending or
descending sort, bounded rotation, and stable duplicate removal, retaining
syntax when an interaction has no exact semantic normal form. Selection can
also precede or follow `sum_values`; summation followed by a position filter
uses exact singleton semantics. A small fallback
separately checks two-step combinations of `keep_multiples_k`
with a positional filter when at least one demonstrated output is non-empty.
Other mixed ordering and value-filter interactions remain outside the current
search gate. `experiments/v1_113_mixed_filter_search.py` checks candidate
retention and abstention for the fallback family.
`keep_every_kth_position` learns one-based positions `k, 2k, 3k, ...` from
examples, including ordinal instructions such as “keep every 3rd item.” The
stride is bounded by `max_position_stride` (default 6). Search can compose
strides with other positional selectors and value-preserving affine operations
(`double`, `scale_k`, and `add_k`) using an exact residue-class summary. Other
interactions remain gated until their laws are modeled. `v1_156` checks repeated
stride composition and transfer, plus composition with a value map.
`experiments/v1_156_positional_stride_rule.py` checks distinction from
value-divisibility filters, held-out numeric ordinal parameter transfer,
learning a spelled ordinal such as “third” from paired numeral and word
phrases, transfer into a separately grounded instruction template, abstention
when that ordinal word is ungrounded, inference of regular ordinal suffixes
from two distinct grounded pairs, one-pair abstention, irregular-word
conservatism, reconstruction after persistence, affine/stride composition,
bounds, and persistence.
`experiments/v1_157_grounded_ordinal_morphology.py` checks the same learned
suffix rule through the terminal chat commands, including displayed grounding
phrases and abstention with only one ordinal correspondence.
`experiments/v1_158_positional_reversal_composition.py` checks both orders of
positional selection and reversal, preserving their distinct held-out behavior
through persistence.
`experiments/v1_159_positional_sort_composition.py` checks that positional
selection before and after sorting remains distinct on held-out lists and
through persistence.
`experiments/v1_160_positional_rotation_composition.py` checks both orders of
positional selection and bounded rotation, preserving their distinct outputs
through persistence.
`experiments/v1_163_positional_deduplication_composition.py` checks that
positional selection before and after stable duplicate removal remains distinct
on held-out lists and through persistence.
`experiments/v1_164_positional_aggregation_composition.py` checks aggregation
over selected positions, held-out transfer, singleton canonicalization, and
persistence.
`experiments/v1_139_square_rule_discovery.py` checks ambiguity retention,
learning `square_values` from examples, held-out and composed application,
persistence, terminal teaching, and conservative semantic-key behavior for
this nonlinear rule.
At default settings the one-step search contains 72 candidate steps; enabling
position arithmetic adds one candidate.
`v1_104_position_filter_rule_discovery.py`
checks learning, parity distinction, composition, persistence, and held-out
behavior. Rule search supports depths 1 through 4; depths 3 and 4 use
breadth-first expansion over distinct behaviors, so equivalent programs are
expanded once. Depth 4 is
opt-in because its search uses more CPU and memory. Explicitly separated
instruction parts can compose longer learned sequences. Adjust
`max_composition_depth`, `max_add`, `max_scale`, `max_modulus`, `max_rotation`,
`max_repeat`, or `max_position_stride` when constructing the model;
persisted memory requires matching settings.

## Grounded factual question answering

`crms_knowledge.py` adds a separate symbolic fact store for question-answering
experiments. Facts are explicit subject/relation/object triples with one or
more source labels. Direct fact lookup indexes both subject/relation and
object/relation directions; adding evidence merges source labels, while
retracting the last source removes the fact from both indexes. The indexes are
rebuilt when knowledge is loaded and preserve qualifier filtering. Knowledge
serialization writes fact rows incrementally instead of materializing a second
full list and encoded JSON string; loading streams the positive and negative
fact arrays one record at a time while retaining the existing provenance
checks. A `.sqlite` path supplied to `--knowledge` stores facts, inference
rules, and derived proofs as indexed SQL rows, with acquired language frames
retained as typed memory payloads. The optional `--fact-db` backend stores
positive and negative facts in indexed SQLite tables for a standalone JSON
knowledge file; it is rebuilt from that JSON at startup. Rule inference and
backward inference fetches only facts in the reachable relation closure and
exact qualifier scope. Corpus-wide discovery retains its current search
bounds. `v1_248` checks indexed lookup with 10,000 unrelated facts, both
directions, source retraction, qualifiers, selective inference snapshots,
SQLite derived-case reuse and invalidation, streaming persistence, and malformed
input rejection. An initial relation and answer
direction are licensed by two distinct bound entities tied to stored facts.

Convert an existing JSON knowledge memory while preserving its facts, learned
frames, provenance, and proof cases with:

```python
from crms_knowledge import CRMSKnowledgeBase

knowledge = CRMSKnowledgeBase.load("knowledge.json")
knowledge.save("knowledge.sqlite")
```
After that, one additional
fact-backed example can license a new exact wording frame for that same
relation and answer direction. For example, grounded examples of "Who designed
the Engine?" and "Who designed the Compiler?" establish `designed`; one
grounded "Who built the Trajectory Table?" example then licenses that exact
wording for `designed`. Held-out answers still require matching stored facts.
`experiments/v1_58_grounded_question_paraphrase_transfer.py` checks transfer,
unseen-wording abstention, persistence, and CLI behavior. Questions using a
licensed frame return fact-backed answers and their sources; missing facts
return `unknown`, and competing answers return `ambiguous`. Unseen wording is
not inferred without a teaching example except for the bounded direct-relation
question forms described below. A leading `a`, `an`, or `the` can be
removed from a bound entity only when the exact surface is not itself known
and the article-free entity is present in the fact store. Separately, the
question matcher now records a one-token frame variation when two taught
frames share at least two bound entities, and the stored facts give the same
unique answer in both frames for each entity. The trace names both frames and
the fact sources; it is recomputed from persisted examples and current facts,
so it disappears when the aligned evidence is retracted. This is evidence for
that exact token/frame relation, not a part-of-speech model or general optional
word grammar. Relation-word equivalence, tense/inflection transfer, and
cross-frame composition remain later proposal-and-holdout work. Keep each
domain's frame matcher separate until at least two domains demonstrate the
same evidence and uniqueness contract. `ask_path(start, relations)` also
supports explicit forward composition across one to three relation edges,
returning each complete proof chain and its sources; competing endpoints remain
ambiguous. `ask_path_between(start, target, relations)` searches from both
endpoints and joins at the midpoint over the supplied one-to-three relation
sequence, with a configurable expansion limit and reported expansion count. It returns a proof-backed yes or abstains when the path is
missing or the limit is reached, and reports ambiguity if explicit negative
evidence contradicts a positive path edge. The terminal exposes it as
`/ask-path-between START|TARGET|RELATION1>RELATION2[|KEY=VALUE...]`.
Path-question wording can also transfer after a relation sequence is licensed
by two distinct entities: one additional fact-backed example teaches a new
exact frame for that same path. `v1_59_path_question_paraphrase_transfer.py`
checks held-out transfer, proof production, abstention, persistence, and CLI.
Python callers can run `counterfactual_path_between(..., excluded_fact=...)`
or `counterfactual_path_without_source(..., source=...)` to check whether a
proven path survives fact or citation exclusion. A fixed-endpoint frame with a
variable source slot can be taught through
`/teach-counterfactual-source-question QUESTION|RELATION1>RELATION2|START|TARGET|SOURCE[|KEY=VALUE...]`.
For transfer across endpoints, `/teach-counterfactual-path-question` learns
start, target, and source slots from examples while holding the relation path
and qualifiers fixed. Both use exact literal frame matching and grounded path
checks; ambiguous bindings abstain. `v1_56` checks the fixed-endpoint frame and
`v1_57` checks multi-slot transfer, qualifier binding, proof validity,
ambiguous-frame abstention, dialogue routing, and persistence. The explicit
terminal form remains available as
`/counterfactual-path-without-source START|TARGET|RELATION1>RELATION2|SOURCE[|KEY=VALUE...]`.
`respond(question)` and `render(result)` provide controlled text templates for
answers, uncertainty, abstention, and proof chains. A path-question frame can
be taught from two grounded question/path-answer pairs, with one-example exact
wording transfer available after that relation path is licensed.

This is a bounded first Q&A layer, not general chat or research: it has no
broad natural-language parser, open-ended path planner, or free-form response
writer. Research supports explicitly supplied pages and bounded same-origin
crawls, not open-ended web search. `experiments/v1_29_grounded_question_answering.py`
checks frame acquisition, controlled response rendering, one explicit two-hop
proof, learned path-question transfer, source preservation, ambiguity,
abstention, and save/load behavior.

Research retrieval filters common function words when content terms remain
and returns the best matching complete source sentence with exact offsets in
both in-memory and SQLite indexes. Queries containing only function words fall
back to literal matching. This reduces broad passage noise but is still lexical
retrieval; it does not resolve paraphrases. A bounded `Where do/does/did …
VERB?` route adds transparent regular present, past, and progressive spellings
for the final question verb, so `Where does Alan Turing work?` can retrieve a
sentence containing “worked.” The expansion is shown with its spelling rule
and changes retrieval only; it neither infers a relation nor stores a fact.
When an exact, unique article title returns a metadata snippet instead of a
sentence, the locative lookup scans sentence boundaries in that one article.
It accepts a surname-only subject only within that exact-title article, and a
bounded fronted time phrase such as “During World War II,” does not get parsed
as part of the subject. The answer remains a quoted source sentence. The
SimpleWiki chat check for `Where did Alan Turing work?` is covered by
`experiments/v1_303_exact_title_locative_chat.py` and returns the Bletchley
Park sentence from the 2 GB index.
For code corpora, explicit programming cues, a programming language paired
with a code construct, or an identifier containing `_` makes code files rank
ahead of prose. A generic question such as “What is the function of a feedback
loop?” stays on the prose route. This changes source ranking only; it does not
parse code or extract executable facts. The direct and SQLite ranking checks
are included in `experiments/v1_242_sentence_focused_retrieval.py`.
Common irregular verbs are excluded. Review status is surfaced only when
a proposed claim shares content words with the question, while other extracted
claims remain visible as review-only candidates. A narrow copular contrastive
correction such as “Canberra is the capital of Australia, not Sydney” now
produces a positive claim for Canberra and a separate negative claim for
Sydney, both marked for review. An object-slot correction such as “Guido
created Python, not Linux” is proposed only when the affirmative clause has
one unambiguous bounded parse. The nominal parser is limited to “X is the R
of Y, not Z” and inverted “The R of Y is X, not Z” shapes; other unsupported
negation and disjunction still abstain. Sentence boundaries preserve
dotted numeric identifiers such as `PMC101.2`; unpunctuated spans longer than
1,000 characters use a bounded matching window instead of being returned as an
oversized snippet. `v1_238` and `v1_234` cover those citation paths.
`experiments/v1_242_sentence_focused_retrieval.py` checks both search
backends, stopword filtering, exact sentence citations, the regular-verb
retrieval route, review-only locative extraction, two-example acceptance,
where-question transfer, the contrastive correction guard, and a focus term in
a later SQLite chunk. SQLite uses chunk ranking to find candidate documents,
then retains all matching terms from each selected document so sentence-level
ranking can choose evidence from a different chunk. The project-document chat
evaluation in `experiments/v1_252_project_document_chat_eval.py` checks five
queries against the current README and requires every expected evidence
sentence. A reviewed
pattern such as “Alan Turing worked at Bletchley Park” preserves `worked at`
as the relation. After two varied accepted examples license that surface frame,
`Where does Alan Turing work?` can return the stored place using the regular
`work` → `worked` alignment and its fact provenance. One reviewed example is
not enough to license transfer. `experiments/v1_251_large_corpus_chat_stress.py`
generates and indexes 1,200 synthetic source files (7,200 sentences), drives
direct and paraphrase queries through the chat CLI, checks abstention and
reviewed held-out fact transfer, then packages the searchable source corpus in
a portable SQLite model and retrieves from it with the original sources and
index unavailable. This validates corpus-scale plumbing, not broad semantic
coverage over real-world literature. Sentence extraction now joins soft-wrapped
lines within a paragraph while retaining the original source text and stops at
blank paragraph boundaries. `experiments/v1_252_project_document_chat_eval.py`
drives five questions over a 284 KB README corpus with paragraphs describing
this diagnostic removed to prevent evaluation leakage. Both direct-wording
probes and all three paraphrase probes retrieve an acceptable source sentence.
For the distribution question, the selected passage describes packaging the
searchable corpus in a portable SQLite model. Sentence ranking removes common
auxiliaries and complementizers such as “can” and “that” and weighs rare terms,
adjacent phrases, and a conservative predicate focus in “What can SUBJECT
VERB?” questions; citations still quote the unchanged source. The evaluation
checks acceptable source sentences, not generated answer text.

Licensed question frames also guide research retrieval. If two grounded
examples teach “Who was the designer of {object}?” as a question about the
`designed` relation, the same frame can expand a later research query with that
relation wording and retrieve a sentence such as “Cy designed the Vela
instrument C.” The expansion is labeled with its teaching sources, remains
retrieval evidence only, and does not write the held-out claim into the fact
store. Person-question sentence coverage counts content terms rather than
function words, so “who”, “was” and “of” do not block a cited paraphrase.
`experiments/v1_257_learned_question_frame_research.py` checks two-example
licensing, held-out retrieval, provenance, no automatic write-back, and parity
between the in-memory and SQLite indexes.

When no licensed sentence frame matches a retrieved sentence, research also
offers a narrow surface-relation hypothesis for adjacent capitalized spans
when the intervening phrase has a bounded predicate-morphology cue. The
candidate records the heuristic and must be reviewed against its exact source;
it never enters the fact store automatically. This can surface a claim such as
“Charles Babbage designed the Analytical Engine” without first teaching the
relation frame. Explicit acceptance stores the fact and records the reviewed
sentence as one labeled frame example. The existing varied-example licensing
gate must still pass before the frame can transfer to another sentence. It is
intentionally only an exploratory proposal: capitalization is not named-entity
recognition and morphology is not syntax. Accepted examples also induce the
exact subject-answer wording “Who/What [observed predicate] [object]?” once two
distinct bound entities license the frame. This supports that surface form; it
also induces a passive inverse form such as “What was designed by Ada?” for
observed regular past predicates. Active do-support such as “What did Ada
design?” is induced only when a cross-relation spelling rule supports the
surface-to-base change and the indexed corpus independently supplies at least
two uses of the base form after an infinitive cue. Ambiguous stems remain
surface-labeled. Alternate wording such as “made” for “created” must be found
with repeated source support and explicitly aligned by a reviewer.
`v1_243` checks citation review, no-auto-commit, held-out extraction and QA,
persistence, corpus-supported lemma resolution, active/passive inversion,
hyphen handling, and contrastive-negation abstention.
Review-candidate matching also recognizes one regular base-form change inside
a compound predicate, so “What did Ken Thompson co-create?” can review the
source candidate extracted from “Ken Thompson co-created Unix.” This affects
candidate relevance only; it does not add a new relation or bypass acceptance.
The review candidate retains the source spelling `co-created` while indexed
tokens still align it with `co create`. Sentence coverage also counts a
question predicate as supported by another surface form only when reviewed
predicate frames align both forms to the same relation; entity terms must still
match the cited sentence. This lets “Who made Python?” retrieve “Guido van
Rossum created Python.” without treating an arbitrary word overlap as a
paraphrase.
`experiments/v1_259_compound_predicate_review.py` checks this route alongside
full multiword-object extraction, separated positive/negative claims, and
review-only storage.

`ask()` can compose up to three independently learned question clauses joined
uniformly by `and`/commas or `or`, such as “Who designed the Engine and built
the Compiler?” or “Which thing did Ada design and build?”. It tries bounded
reconstructions of omitted wording against existing question frames and
accepts only a unique supported parse. Wh-question conjunction intersects
answers; disjunction unions them. Multiple resulting answers remain
ambiguous. Fully grounded polar clauses use Boolean AND/OR; unknown clauses,
conflicts, mixed operators, and competing parses are not silently resolved.
Mixed operators require explicit grouping, and clause reconstruction is
bounded to three clauses of at most 32 tokens each. Unsupported clauses and
empty conjunction intersections abstain. This
composes logical operators over existing learned frames; it does not learn
new predicates or broaden wording.
`experiments/v1_165_conjunctive_question_composition.py` checks held-out
subject/object AND/OR and two/three-clause composition, polar truth combination
and conflict, evidence retention, a rule-derived conjunct, retrieval coverage
for each research clause without auto-committing facts, unsupported and
disjoint abstention, ambiguity, persistence, and terminal chat.
Compound reconstruction now evaluates its invariant first clause once and
reuses the result across candidate prefixes. The small in-memory check in
`experiments/v1_304_compound_question_reuse.py` verifies one evaluation,
answer/provenance stability, and both conjunction and disjunction. At larger
scales, indexed connector-phrase checks and fast exits for unused question
frames avoid loading all facts during routine composition. The profile in
`experiments/v1_305_compound_question_scaling.py` returned the same answer and
provenance with 1,002, 100,002, and 1,000,002 SQLite facts; warm medians on the
development runtime were approximately 0.4 ms, 10 ms, and 108 ms respectively.
This is evidence for the serial indexed path, not a claim that all query work
is constant-time or that parallel dispatch would help. Research sharding and
persistent worker pools should remain benchmark-gated, with SQLite shards
using separate read-only connections and deterministic merge order.
An explicit named-subject form such as “What did Ada and Grace each build?”
reuses the learned question frame once per stored subject and combines answers
only when both queries are answered uniquely. Boolean forms use AND: each
subject must have positive evidence for “yes,” and an explicit negative can
make the aggregate “no.” Unknowns and ambiguity prevent partial answers.
Research returns the combined grounded response while retaining its retrieved
passages. The parser requires “each”; without it, CRMS does not assume that a
coordinated subject distributes over the predicate. `v1_171_distributive_named_subject_questions.py`
checks frame reuse, evidence aggregation, research, Boolean semantics,
abstention, and the distributivity gate.

Grounded sentence frames can be learned from source-backed fact examples with
`teach_fact_pattern_from_hit()`. A literal structure supported by varied
subject and object pairs can produce candidates through
`propose_facts_from_hit()`. A new structure can also transfer from one
source-backed example when that canonical relation and polarity already have
an independently varied frame. This is conservative structural transfer: the
teacher still labels subject, relation, object, and predicate phrase, and
contrastive frame evidence prevents known structure words from being absorbed
into entity slots. Proposals remain outside the fact store until
`accept_fact_candidate()` verifies the current citation and exact cited
sentence. Each candidate retains and renders the example frames and source
labels that licensed its language match. CRMS does not decide whether a passage
entails a claim or parse arbitrary sentence structure. The writer can realize
stored facts with the observed surface variants. After `/teach-fact`, the
terminal reports the exact frame's distinct subject/object pair, subject,
object, and source-document counts, along with the unmet variation thresholds
when the frame remains unlicensed.
`experiments/v1_32_grounded_fact_pattern_learning.py`
checks the original two-example path; `v1_70_grounded_sentence_structure_transfer.py`
checks one-example passive transfer, relation gating, unique role parsing,
review-only proposals, visible language evidence, citation acceptance, and
persistence.

For a narrow zero-frame path, research can also suggest review-only claims from
capitalized spans and predicate morphology. A bounded copular nominal pattern
such as “The capital of France is Paris” is mapped to `Paris — capital of →
France`; an agentless passive such as “The C language was created at Bell
Labs” abstains instead of treating the location as an agent or a positive
claim. These heuristics do not establish entailment and never write directly
to the fact store. Every proposal still requires inspection and explicit
acceptance. Zero-frame discovery abstains on unlicensed negation, so it cannot
recast a negative clause as a positive predicate such as `is not`. It preserves
two narrow explicit negative forms as review-only evidence: negative class
membership (“Ada is not a mathematician”) and active auxiliary negation (“Ada
did not create Python”). The latter rejects coordination and prepositional
attachments, and rejects lowercase trailing words after a named object rather
than guessing whether they begin an adjunct or another clause. It accepts a
single lowercase object such as “radium” and bounded multiword proper names.
It also handles a narrow explicit-agent passive negative such as “Python was
not created by Guido,” reusing the passive role parser and any source-backed
predicate alignment. Attached adverbs or prepositional phrases make it abstain.
All candidates remain review-only. Explicitly taught negative frames remain
handled by the structured pattern learner.
`experiments/v1_243_reviewed_surface_relation_discovery.py`
covers the role-order case, agentless-passive abstention, simple and
contrastive negation, and hyphenated predicates alongside held-out review and
question transfer. During review, a candidate naming an entity from the
question takes precedence over unrelated claims that only share its relation;
this keeps candidate numbering actionable in multi-source retrieval.

Zero-frame extraction also handles one bounded noun-phrase appositive when
removing the descriptive phrase leaves a unique supported core parse, as in
“Python, a high-level language, was created by Guido.” and “Guido, a
programmer, created Python.” The original source sentence remains the cited
evidence and the appositive parse remains review-only. Other comma or
semicolon attachments abstain instead of being absorbed into the subject,
predicate, or object. `experiments/v1_262_appositive_fact_extraction.py`
checks active, passive, and trailing appositives, cited acceptance, question
answering, and ambiguous-comma abstention.

`/suggest-corpus-frames` scans 1,000 indexed sources and 20,000 sentences per
request by default, grouping zero-frame parses only when their template repeats with
distinct subjects, distinct objects, and independent source documents. When
the model has cross-relation, source-backed morphology rules, discovery applies
those rules to compatible sentence predicates and can group variants such as
“creates” and “created” under the licensed relation “create”; each row keeps
its exact wording and rule support for review. It does not merge inflections
whose spelling rule or base relation remains ambiguous. The
zero-frame parser also normalizes a bounded explicit-agent passive form such
as “Python was created by Guido” into the same agent/relation/patient slots as
“Guido created Python.” Agentless passives remain unassigned. Both routes keep
the source wording and review provenance. The
parser also proposes a narrow named-subject, lowercase-object form such as
“Marie Curie discovered radium.” It abstains when the object boundary appears
to include a prepositional attachment, coordination, or negation. This route
is also report-only and prints the exact cited sentences. The explicit
copular pattern “Engine is a machine” proposes an `is-a` type fact, which can
serve as a proof guard for typed rules after review. It does not guess whether
the type should be asked with “Who” or “What.” A source sentence such as
“Ada is not a mathematician” yields a separate review-only
negative `is-a` fact. Accepting contradictory positive and negative evidence
preserves the conflict so inference returns ambiguity.
For a question such as “Which river flows through Paris?”, a source-licensed
positive relation frame can identify the relation and bound object, while an
explicit positive `is-a` fact must establish that the answer is a river.
Missing type support remains unknown, and contradictory type evidence returns
ambiguity. An untyped “What flows through Paris?” uses the same licensed frame
without claiming a class. `v1_245_zero_frame_corpus_learning.py` covers both
question forms and their evidence requirements.
Questions in the bounded `What did/does SUBJECT VERB?` form can retrieve
objects directly from accepted facts when the predicate matches a licensed
source frame or a single-token relation stored in the fact database. Regular
past and third-person forms are reduced mechanically; multiword relations
still need a learned frame. The bounded `Who PREDICATE OBJECT?` form can also
answer from a stored single-token relation or a source-licensed predicate
form. Both routes use exact stored entities and relations, report multiple
supported answers as ambiguous, leave missing positive evidence unknown, and
do not treat an explicit negative fact as an answer. They do not infer
synonyms. `v1_242_sentence_focused_retrieval.py` checks the direct-relation
routes, regular forms, synonym abstention, and ambiguity.
Repeated, explicitly negated passive claims can also form a separate
review-only corpus relation proposal when their normalized roles, distinct
entities, and independent-source support meet the same gates. Acceptance stores
them as negative facts and does not assert the denied relation. The
`v1_245_zero_frame_corpus_learning.py` diagnostic covers this source-separated
grouping, polarity-preserving acceptance, and ambiguity when independent
positive evidence conflicts with an accepted negative.
Add a document offset, such as `/suggest-corpus-frames 1000`, to scan the next
source batch;
accept with `/accept-corpus-frame SELECTOR|1000` so the same proposal page is
revalidated. After reviewing the evidence, acceptance
transactionally stores its cited example facts and the shared sentence and
question frames. This is a practical route from corpus repetition to learned
language without first hand-teaching each relation. The discovery remains
limited by its capitalized-span and predicate heuristics; acceptance means the
user reviewed these examples, not that CRMS independently proved entailment.
The heuristic now rejects Markdown/title metadata and weak sentence-initial
subjects such as “Such”, “Both”, “There”, and ordinal labels before proposing
claims; it still accepts a bounded copular type pattern and repeated authored
frames. `experiments/v1_267_corpus_rule_proposal_quality.py` checks these gates.
On the current 2,006-document local corpus, the wider review-only scan yields
23 relation-frame proposals and no repeated-pair predicate alignments. The
remaining proposals still include noisy nominal and copular parses, so corpus
discovery is not yet safe for unattended learning.
An audit of the bounded `v1_274_corpus_relation_learning.py` scan found six of
nine proposals came from comma-bearing discourse openings or loose appositives
(for example, “Finally, the quality of ...” and “one of ...”). Corpus mining
now skips comma/semicolon sentences unless the extractor marks a unique,
bounded appositive parse. The same 2,006-document diagnostic now retains three
review-only frames (`achieves`, `is-a`, and `returns`); the dedicated appositive
diagnostic still passes. This removes the observed false structures, but the
remaining type and return claims still require source review.
`experiments/v1_245_zero_frame_corpus_learning.py` checks the evidence gates,
no-mutation-before-acceptance, stale proposal protection, transaction staging,
question transfer, provenance, both index backends, later-page discovery,
acceptance revalidation, lowercase-object extraction, source-backed inflection
grouping, and the interactive path. `v1_243_reviewed_surface_relation_discovery.py`
also checks explicit passive role ordering, agentless-passive abstention,
prepositional-boundary abstention, and the separate teacher-aligned route for
learning a second surface predicate from two cited examples. Its chat-runtime
probe verifies that the new wording retrieves and realizes a fact stored under
the original predicate, and that the alignment survives reload.

`/suggest-corpus-alignments` adds a corpus-only path for alternate predicate
wording. It proposes an alignment only when the same distinct subject/object
pairs are independently parsed under both predicates in separate documents.
The more frequently attested relation supplies the proposed canonical label;
the proposal is still report-only and displays both cited sentences for each
pair. `/accept-corpus-alignment SELECTOR` rechecks the citations and unique
surface parses before storing the facts and reusable predicate frame under the
reviewed canonical relation. One shared pair is insufficient, and the feature
does not use an external synonym list. `experiments/v1_260_corpus_only_predicate_alignment.py`
checks sparse-overlap rejection, report-only behavior, explicit acceptance,
chat routing, question transfer, a held-out source sentence that becomes a
reviewed fact and answer through the accepted alternate predicate, provenance,
and loss of the alternate wording when its source supports are retracted.
`experiments/v1_261_large_corpus_alignment.py`
checks the same path in a 1,200-document SQLite corpus with 599 aligned
training pairs, then reviews a source-backed candidate and answers a question
about a previously unseen entity pair.

CRMS can also discover alternate predicate wording from already accepted facts.
`/suggest-predicate-forms` scans the first 100 accepted facts and searches up
to 100 indexed hits per fact by default. Use
`/suggest-predicate-forms FACT_OFFSET|MAX_HITS_PER_FACT` to scan later batches
of 100 facts or change the per-fact hit bound (1 to 1,000). It reports an
alignment only when the same alternate phrase occurs across distinct fact
pairs and independent source documents. Proposals are report-only;
`/accept-predicate-form SELECTOR` accepts the displayed number or proposal ID
and revalidates the cited sentences. For nondefault bounds, append
`|FACT_OFFSET|MAX_HITS_PER_FACT` on acceptance. Acceptance adds source
provenance to the facts and teaches the phrase as another surface form for
that relation. Question frames can then transfer
to the observed wording, such as “Who made Python?” after “made” has been
reviewed as a form of “create.” Source-backed nominal forms ending in “of”
also transfer into the corresponding copular question frame; for example,
“Who created Python?” can extend to “Who is the creator of Python?” after
the nominal wording has repeated across distinct fact pairs and been reviewed.
The copula and article are restored as question structure; CRMS does not add an
unobserved synonym. Users can say “Review alternate predicate
forms” and “Accept predicate-form proposal ID” in ordinary chat; acceptance
revalidates the source evidence and remains explicit. This learns from source
co-occurrence and human review, not from a synonym list or automatic fact
promotion. `experiments/v1_244_corpus_predicate_alignment.py` checks varied
fact support, source separation, no mutation before acceptance,
natural-language review and acceptance, held-out fact review, question
transfer for verb and nominal wording, provenance, restart, and abstention on
an unobserved synonym.

The terminal accepts two to eight examples conversationally in one batch;
they must all use the same canonical relation and polarity:
`Teach a sourced fact pattern from examples: "Ada Lovelace designed the
Analytical Engine." => "Ada Lovelace" | "designed" | "the Analytical
Engine"; "Grace Hopper designed the Compiler." => "Grace Hopper" |
"designed" | "the Compiler"`. Each sentence must occur exactly once in one
indexed source, and the teacher explicitly labels its subject, relation, and
object. CRMS stores each labeled fact with its citation and learns from the
batch atomically; if any source lookup fails, it saves none of them. Additional
varied examples can strengthen the frame beyond the minimum pair. A
citation establishes where the example came from, not that the source entails
the teacher's labels. Subsequent pattern extraction remains a review-only
proposal until explicitly accepted against its cited sentence.
Once a sentence frame is licensed, a teacher can add a fact in ordinary
conversation with `Remember that "Alice likes tea." as a fact from source
"teacher:conversation".` CRMS stores it only when exactly one learned pattern
matches; an unknown or ambiguous sentence is not guessed. This is explicit
teacher input and attribution, not an independently verified external source
or a new language-pattern lesson.
To teach a new sentence frame without indexed passages, provide explicit
slot labels in multiple varied examples: `Teach a fact pattern from labeled
examples: "Ada mentors Bo." => "Ada" | "mentors" | "Bo"; "Cara mentors
Dee." => "Cara" | "mentors" | "Dee"`. These examples are stored under the
single `teacher:conversation` source and do not count as independent sources
for rule-discovery validation. The frame is learned only from the teacher's
explicit subject, relation, object, and polarity labels; this route does not
claim citation verification or automatic semantic parsing.
When source wording differs from canonical labels, add explicit surface spans
to each example in brackets: `["SUBJECT PHRASE" | "PREDICATE PHRASE" |
"OBJECT PHRASE"]`. For example, the teacher can label “A. Lovelace developed
the engine” as subject “Ada Lovelace,” relation “designed,” and object
“Analytical Engine,” while showing exactly which words fill each slot. These
are teacher-declared alignments; CRMS does not infer that “developed” means
“designed.”
An example can also explicitly label polarity before the optional spans:
`"Ada did not design the Engine." => "Ada" | "designed" | "the Engine" |
"negative" ["Ada" | "did not design" | "the Engine"]`. Negative examples
enter the negative evidence store, and later extracted candidates remain
negative through review. Missing positive evidence is still unknown; it is
never converted into a negative claim. `experiments/v1_216_conversational_negative_fact_learning.py`
checks negative teaching, citation retention, polarity-preserving transfer,
and separation from positive facts. It then teaches a yes/no frame from
explicit truth labels, reviews and accepts a held-out negative candidate, and
checks that the accepted citation supports “No” while a different unsupported
entity remains unknown; it also writes the accepted negative fact using the
learned negated sentence form and its source citation. Dialogue treats both `it` and the clause marker
`that` in “Is it true that …?” as nonreferential words, including when the
entity in the proposition is not yet known.
`experiments/v1_215_conversational_fact_pattern_learning.py` checks CLI
three-example licensing, mixed-relation rejection, transactional source
validation, held-out extraction, explicit surface alignment, transfer of the
teacher-aligned predicate into stored-fact question answering and source
retrieval, and review-only handling when a held-out source supplies the new
fact. Its CLI
workflow then explicitly accepts that proposal and checks that `write_about`
uses the learned sentence wording while citing both the accepted fact and the
examples that licensed the wording. It also retracts all teaching sources
and verifies that the accepted fact remains while predicate transfer,
held-out extraction, and source-grounded writing lose their now-insufficient
language support.

Review-only research can also decompose a bounded sentence with independently
licensed assertions joined by “and,” “but,” or a semicolon. Each resulting claim keeps the original
sentence citation and remains uncommitted until accepted; ambiguous analyses
or sentences with more than eight coordinator tokens abstain. Sentences with
“or” abstain because neither branch is asserted individually. Ellipsis recovery
is limited to “and” and “but”; each semicolon clause must match on its own.
This composes existing learned frames rather than inferring new relation
meanings. A later coordinated clause may omit a repeated subject or predicate
when restoring it from the preceding candidate produces a match to an already
learned frame.
`experiments/v1_134_coordinated_fact_frames.py` checks two- and three-clause
extraction, shared-subject and shared-predicate recovery, research integration,
attribution, selective acceptance, no auto-commit, and the coordination bound.
`experiments/v1_136_contrastive_fact_frames.py` checks “but” and semicolon
coordination, gated shared-subject recovery, review-only behavior, and
abstention on disjunction.
One coordinated subject pair can also share a learned predicate frame, as in
“Ada and Grace designed the Rotor.” CRMS reconstructs one candidate per
subject only when both clauses independently match the same learned relation,
object, and polarity. The first subject must be a known entity; the second may
be a new source-mentioned name and remains a review candidate. “Both” is an
optional surface cue. An unsupported predicate or ambiguous split abstains.
This first version handles two subjects only; longer coordinated lists
abstain rather than treating the whole list as one entity.
These structural candidates are not proof that the passage entails each
individual claim: source-backed research keeps them uncommitted for explicit
review. `experiments/v1_169_coordinated_subject_fact_frames.py` checks
multiword subjects, unseen-name proposals, unsupported-predicate abstention,
citation retention, and no auto-commit.
One comma-delimited subject-relative clause using “who” or “which” can also
be decomposed when both the relative clause and main clause independently
match learned fact frames. Both proposals retain the complete source sentence;
missing embedded evidence, multiple relative clauses, and partial parses
abstain. This does not infer a relation from the relative marker.
`experiments/v1_137_grounded_relative_clauses.py` checks held-out extraction,
research citations, no automatic fact commitment, and partial/multiple-clause
abstention.
The same bounded composition supports one restrictive, unpunctuated subject-
or object-relative clause (“Ada who designed the Engine built the Compiler”;
“the Engine that Ada designed passed testing”). Since neither clause boundary
nor antecedent role is marked uniformly, the parser tries token boundaries and
both role assignments, accepting only a unique claim set for which each
clause matches learned fact frames and the antecedent fills the tested role.
An unsupported or ambiguous parse abstains; proposals retain the whole source
sentence and remain review-only. This still handles only one restrictive
relative clause with “who”, “whom”, “which”, or “that”; it is not general
relative-clause parsing.
`experiments/v1_167_restrictive_relative_clauses.py` checks boundary selection,
subject/object role resolution, research citations, complete attribution, no
partial extraction, review-only behavior, and regression coverage for the
comma-delimited form.
Entity variants can be learned explicitly with `/teach-alias ALIAS|ENTITY|SOURCE QUERY`
in the terminal shell. The cited passage must contain both the alias and an
entity already in stored facts; conflicting mappings are rejected. Question
and path lookup canonicalize the learned alias, while unseen names remain
unresolved unless independent alias examples license a productive form. For
aligned entity names, examples for at least two distinct entities from at least
two source documents can license only the observed regular plural classes
(`-s`, sibilant `-es`, and consonant `y → ies`). The alias and canonical name
must have the same token prefix; only the final token can inflect, allowing
forms such as `Analytical Engine → Analytical Engines` without changing the
name's modifier. Donors must also share a fact relation and argument role, and
the target must occur in that same role; support is evaluated separately for
each relation-role scope so subject and object examples do not cancel each
other out. An object-name rule therefore cannot pluralize an agent just because
its spelling fits. Generated plurals are
query-time mappings with donor citations; they do not create facts or persisted
aliases. Irregular forms, changed prefixes, final-`o` forms, collisions with
another stored entity, and under-supported patterns remain unresolved.
`/aliases` displays explicit mappings and their citations. `/alias-rules` lists
active productive plural classes, their shared fact-role scope, donor forms and
citations, and the query-time forms currently licensed with the source evidence
for each target's role. If a mapping needs correction,
`/forget-alias ALIAS` removes it so a new cited mapping can be taught;
`/forget-alias ALIAS|SOURCE` retracts one citation and preserves any other
citations for that mapping. Productive plural rules are recomputed from the
remaining aliases, so withdrawing a donor can disable a transfer.
Fact-pattern teaching can also label a surface entity phrase directly in its
cited sentence with `/teach-fact SUBJECT|RELATION|OBJECT|QUERY|PREDICATE|POLARITY|SUBJECT SURFACE|OBJECT SURFACE`.
The canonical fact must already have matching source evidence, and each
surface phrase must occur exactly once without overlapping the predicate or
other entity phrase. This explicit alignment records the source citation as
alias evidence, allowing observed forms such as `sculptures` to contribute to
the same bounded plural rules without rewriting the fact or guessing from
sentence similarity. Retracting the supporting fact citation also retracts
that aligned alias contribution; a separately taught alias support is kept.
`experiments/v1_155_fact_aligned_entity_surfaces.py`
checks cited alignment, held-out plural transfer, absent-span rejection,
subject- and object-role transfer, multiword names with distinct prefixes,
terminal teaching, persistence, and dependency-aware retraction.
Fact-backed question answers, bounded path answers, direct inference results,
and review-only fact proposals expose the explicit alias or induced plural
rule and its source lineage in `language_evidence`. Resemblance alone does not
merge entities. Proposals canonicalize the entity but are not committed
automatically. Research queries containing an explicit or licensed plural
alias expand retrieval with the canonical entity; aliases absent from the query
do not affect retrieval. Dialogue follow-ups and explicit corrections recognize
the same licensed forms, preserve the user's surface form when rerunning a
question, and keep the canonical entity in short-term referent state.
`experiments/v1_44_alias_research_expansion.py` checks this against an unlearned
control query. `experiments/v1_152_entity_alias_qa_provenance.py` checks
unknown-form abstention, explicitly taught alias transfer, source visibility
in QA, persistence, and rejection when the alias already names another stored
entity. `experiments/v1_153_grounded_entity_plural_transfer.py` checks
independent support for all three regular plural classes, single- and
multiword-name transfer, prefix alignment, QA, direct inference and path APIs,
review-only fact transfer, research expansion, visible lineage, no fact
promotion, fact-role scoping, irregular and collision abstention, citation-level
retraction, and persistence. `experiments/v1_154_dialogue_plural_followup.py` checks multi-turn
replacement, canonical referent tracking, correction with a learned form, and
lineage retention.
`write_fact(subject, relation, object)` also realizes a stored fact using
sentence structures whose shared frame is supported by at least two varied,
fact-backed examples. An individual surface realization must have at least one
explicit teacher-aligned example within that licensed frame; this lets CRMS
retain a second grounded predicate form without pretending that wording had
independent repeated support. Each realization cites its own alignment
examples and the frame's varied evidence. It preserves source wording and punctuation and returns every
licensed form ordered by distinct supporting source documents, then citation
count and a lexical tie-break; it does not invent facts.
`write_about(subject, qualifiers=...)` composes a short digest from the matching
stored facts that have licensed sentence frames and can add rule-derived
relations when a learned positive frame exists. Derived statements carry their
recursive proof, rule identifiers, source leaves, and requested exact context;
they are never promoted to source facts. Every stored-fact sentence carries its
fact record, fact-source labels, selected wording frame, and that frame's
source citations; the API keeps all surface alternatives while the terminal
selects the most independently supported frame. Facts
with conflicting positive and negative evidence are reported with both source
sets and omitted from the asserted sentences. `Write about ENTITY` and requests
such as `Write a short sourced summary about ENTITY` expose the same bounded
composition in ordinary chat; `/write-about ENTITY|KEY=VALUE` remains available
for exact qualifier selection. Facts without a learned writing frame are
reported as omitted rather than silently left out; with no writeable facts, it
reports that it cannot write the requested digest. This is sourced fact
composition, not open-ended prose generation. A successful natural-language
digest becomes the current writing context, so `Why?` can rebuild it from
current evidence and `What about Grace?` can reuse the same request form for a
different known entity. Dialogue state preserves this context across restarts.
An about-request frame can also be taught in ordinary CRMS language with two
to eight explicit request/entity pairs, for example `Teach an about-request frame from
examples: "Tell me about Ada" => "Ada"; "Tell me about Grace" => "Grace".`
Every entity must already have stored subject facts, the entities must be
distinct, and the requests must share the same token frame around their entity
spans. CRMS applies the examples to a temporary knowledge copy and saves them
only after they license one shared frame; the resulting request still writes
only from sourced facts and learned sentence frames.
`write_about` can coordinate up to eight claims with a shared subject and exact
polarity, inference status, and qualifier scope. For one relation, it can join
the object phrases; for distinct relations, it can share the subject only
when both learned frames use the minimal `<subject> <predicate> <object>`
surface skeleton. Each structured statement keeps its own fact/proof and
frame evidence; the composed line cites their union. Lists of three or more
items use an Oxford comma. More complex frames, conflicting scopes, duplicate
claims, or groups larger than eight remain separate.
`experiments/v1_135_coordinated_fact_writing.py` checks same-relation object
composition and shared-subject composition across three distinct predicates,
scope separation, dialogue explanations, and source attribution.
`experiments/v1_50_grounded_fact_writing.py` checks multi-fact composition,
natural-language request routing, citations, qualifier filtering, conflict
handling, persistence, and the CLI.
Two to eight explicitly named stored subjects can receive separate grounded
digests through `write_about` or `/write-about`, using conjunctions or
comma-separated names. A learned about-request frame can route requests such
as “Tell me about Ada, Grace, and Kai” to the same operation. Each member's
digest stays labeled separately;
the response keeps its fact sources, wording citations, conflicts, and
omissions. Unknown members are not silently dropped. `Why?`, persistence, and
“What about [member]?” follow-ups rebuild or narrow the same grounded writing
context. This is a bounded composition of existing digests, not a newly
inferred joint fact. `experiments/v1_170_multi_entity_about_writing.py` checks
the API, dialogue routing, source retention, explanation refresh, persistence,
unknown-member handling, and entity follow-up.
`write_timeline(subject, order_by="year")` composes positive fact sentences
only when each has a stored, consistently formatted `YYYY` or `YYYY-MM-DD`
qualifier and a learned sentence frame. Natural requests such as “Tell me the
story of Ada ordered by year” use this path. Mixed date precision, invalid
dates, missing frames, and conflicts are reported or omitted; the output does
not infer causality or add connective claims between events. The integrated
`v1_228_natural_domain_router_integration.py` checks chronological ordering and
natural-language routing, omission of a conflicting event, and abstention when
year-only and full-date values cannot be safely ordered together.
`experiments/v1_68_writing_over_inference.py` checks proof-backed unqualified
writing. `experiments/v1_88_contextual_writing_over_inference.py` checks exact-
scope derived writing, preserved context and lineage, mismatched-context
abstention, and conflicting-premise handling.
`experiments/v1_79_supported_writing_frame_selection.py` checks source-document
ranking across active and passive realizations, retention of alternatives,
digest selection, and persistence.
An about-request frame can be taught with `/teach-about REQUEST|ENTITY` after
the entity has stored facts. Two distinct entities are needed to license the
literal request pattern; a held-out entity can then be summarized from its own
stored, licensed facts. Dialogue routes matching requests such as “Tell me
about Ada Lovelace” through `write_about()`, preserves the described entity for
a grounded pronoun follow-up, and abstains when no facts are available.
`experiments/v1_51_learned_about_requests.py` checks frame acquisition,
held-out entity binding, cited writing, pronouns, persistence, and CLI use.

Facts can carry explicit context such as a year or region. The API accepts
`add_fact(..., qualifiers={"year": "2024"})`; qualifiers remain part of the
fact identity and provenance. Unfiltered questions retain open-world behavior
and can be ambiguous across contexts. `ask(question, qualifiers={...})` and
`ask_path(start, relations, qualifiers={...})` apply exact, case-insensitive
filters to every matching fact edge. The terminal exposes cited acquisition
through `/teach-context-fact SUBJECT|RELATION|OBJECT|SOURCE QUERY|KEY=VALUE`
and filtered answering through `/ask-context QUESTION|KEY=VALUE`. `/facts`
prints stored context. Language can also be taught with
`/teach-qualified-question QUESTION|RELATION|subject/object|BOUND ENTITY|ANSWER|KEY=VALUE[|KEY=VALUE...]`.
Single-context frames need two examples that vary both entity and context
value; multi-context frames require distinct entities and evidence that varies
each qualifier slot. The learned frame transfers to held-out combinations only
when every slot has grounded variation. Ambiguous variable-span parses,
unsupported values, and conflicts with explicitly requested context abstain.
Frames and their examples persist separately from facts. Controlled answers
show the recorded context alongside their source evidence; multi-hop proofs
show context on each fact. `experiments/v1_45_qualified_facts.py` checks
single-context question orders, filtered direct and multi-hop answers, CLI
use, and persistence. `experiments/v1_125_multi_qualifier_question_frames.py`
checks grounded multi-context licensing, held-out combinations, conflict and
unknown-scope abstention, persistence, and CLI use.

Source-backed sentence frames can extract qualifiers from cited statements,
for example learning that “in 2024” fills a `year` slot. Teach examples only
after storing the matching qualified fact from the same citation, using
`/teach-context-frame SUBJECT|RELATION|OBJECT|QUERY|PREDICATE|SENTENCE|KEY=VALUE[|KEY=VALUE...]`.
Transfer requires varied subjects, objects, qualifier values, and independent
source documents; ambiguous parses abstain. Extraction returns reviewable
fact candidates and never commits them automatically. Context sentence frames
persist with their source lineage. This learns a bounded language pattern; it
does not verify that an arbitrary generated output is true and therefore does
not authorize generic self-write-back.

Qualified question frames can also be taught from complete verified rule proofs,
then transferred to a new entity and context value. The answer retains the
recursive inference proof and its contextual fact leaves; it is not promoted
into the source fact store. This route uses the same exact-scope inference
contract and abstains on conflicting or incomplete searches.
`v1_86_qualified_language_over_inference.py` checks proof-backed frame
acquisition, held-out entity/context transfer, natural-language chat,
persistence, and conflict abstention.

Explicit rule inference accepts `qualifiers={...}` and uses only facts and
negative evidence whose qualifier set exactly matches that request. Both
premises in a rule proof therefore share one scope; evidence from different
years or regions cannot be joined. `/infer-relation SUBJECT|RELATION|OBJECT`
accepts an optional fourth `name=value,...` field for this query scope. The
independent recursive proof checker validates leaf scopes and premise-scope
agreement. Unqualified evidence is not implicitly promoted into a contextual
proof. Rule candidate discovery and held-out validation also accept contextual
examples when both premises and their positive or negative label have the exact
same scope. Support still counts distinct endpoint pairs and independent
source documents; accepted rules remain context-independent, while queries
must name the exact context used by their proof. `v1_85_contextual_rule_inference.py`
checks exact-scope proofs, cross-context abstention, scoped contradiction,
proof tampering, CLI access, and persistence. `v1_87_contextual_rule_discovery.py`
checks scope-matched candidate support, source-separated held-out validation,
counterexamples, visible context labels in terminal review, and use of an
accepted rule in a new context.
`experiments/v1_297_large_scale_rule_learning.py` adds an end-to-end 1,162-fact
diagnostic over 180 indexed sentences: two cited examples per relation license
the sentence frames, later claims enter through reviewable extraction, 40
labeled chains form the training partition, 12 are held out by source, and 12
premise-only chains test transfer. It discovers the parent-parent-to-ancestor
candidate, validates it on independent sources, requires explicit acceptance,
and independently verifies each of the 12 inferred proofs. The graph also
contains a linked `member-of` / `located-in` pattern with a plausible
`has-region` conclusion. A held-out negative example marks that candidate as
contradicted, blocks its installation, and keeps runtime inference unknown.
The linked decoy triples are symbolic fixtures; the language frames and main
rule chain use cited generated sentences. The entities are generated and the
800 background facts are disconnected, so this does not establish performance
on noisy natural-language corpora. The next discovery evaluation should use
linked distractors extracted from natural-language sources, then measure
runtime and candidate precision as graph size and relation diversity increase.

`CRMSKnowledgeBase.research(question, index)` connects retrieval to the
knowledge layer. It searches supplied documents, answers from existing facts
when a learned question frame applies, and proposes source-bound facts when a
learned sentence pattern matches. Research never commits those candidates;
they require `accept_fact_candidate()` before they can support an answer.
`render_research()` shows cited excerpts, candidate status, or a grounded
answer. `experiments/v1_33_grounded_research_workflow.py` checks this complete
review-and-accept loop and abstention for unsupported questions.
For list questions, research can extract a matching Markdown table into a
cited row list. For how/why questions, it can return the complete source
paragraph around the best matching passage when that paragraph independently
matches multiple content terms. These are bounded extractive paths: the text
remains quoted evidence, and the paragraph path abstains when the match is too
weak. `experiments/v1_266_large_corpus_chat_followups.py` exercises these
responses against the portable 2,006-document corpus.
For an acronym-anchored topic summary, `/summarize` now selects one best
matching prose source when that source covers the topic terms, keeping
unrelated papers and code fixtures out of the summary. Explicit comparison
requests remain multi-source. The same diagnostic checks source scoping.
When a research query has a direct accepted answer, unrelated review-only
fact proposals are omitted from that reply. The sentence-level source evidence
may still be shown independently. Rule conclusions also support the bounded
natural-language form `Who is a [conclusion relation] of ENTITY?` and its
`Is SUBJECT a [conclusion relation] of OBJECT?` truth-question form without a
separately taught question frame; these answers use the same proof search and
abstain when a complete proof is unavailable. A missing-premise response lists
the proposed missing facts and offers to derive the conclusion if the user
confirms one. These forms do not generalize to arbitrary paraphrases.
`experiments/v1_34_grounded_predicate_learning.py` checks supervised alignment
of distinct surface predicates to one canonical relation, held-out transfer,
unseen-phrase abstention, controlled realization, and persistence.
The learner can also induce a limited predicate spelling rule from at least
two independently licensed canonical-relation/surface-predicate alignments
across distinct relations, the same ending class, and at least two source
documents. Citation fragments from one document count as one source. For
example, non-final-e forms can support `paint → painted`, final-e forms can
support `bake → baked`, and consonant-y forms can support `study → studied` by
replacing `y` with `ied`. These forms expand retrieval, can vary an already
learned question frame, and can support review-only fact proposals; each
proposal exposes the supporting relations and source citations, and no
candidate is committed automatically. This small rule family does not cover
irregular forms or general spelling and phonology.
`experiments/v1_73_grounded_predicate_morphology.py` checks held-out transfer
of `-ed` and `-d` into question answering and research, persistence,
review-only extraction, terminal dialogue, visible rule evidence, and
abstention when support is insufficient.
`experiments/v1_76_consonant_y_morphology.py` adds the `consonant-y → -ied`
spelling change. It checks cross-relation evidence, base-relation grounding,
review-only extraction, QA and research transfer, persistence, and abstention
with only one donor relation. Question results and controlled rendering expose
the induced spelling rule, supporting relation forms, and source citations used
for a transfer. `experiments/v1_124_consonant_y_ies_morphology.py` checks the
same evidence gate for third-person `-ies` transfer, including vowel-`y`
controls (`play → plays`, not `plaies`), QA, research, proposal review, and
persistence.
This remains a small example-learned rule family, not a general morphological
analyzer; it does not induce irregular forms or general spelling and
phonology. An irregular surface form can be reused as a relation-specific
observation only after a fact-backed sentence aligns it to that exact relation.
Its sources are exposed as language evidence; it does not transfer to another
relation or count as a productive spelling rule. A grounded unaligned form such
as `go → went` also blocks guessing generic `goed` for that same relation while
leaving independently supported forms such as `going` available; it does not
block ordinary `-ed` transfer to unrelated regular predicates.
`v1_130_grounded_irregular_predicate_forms.py` checks `go → went` as this kind
of lexical observation across QA, research,
persistence, direct and dialogue answer rendering, rendered review proposals,
unrelated-relation controls, and
source retraction. It also checks loading a legacy store and retraction of a
negative-frame example. Sentence frames now retain source links per predicate form and surface template, so
retracting one citation removes only that training contribution; other cited
examples continue to license the frame or form. Generated writing requires
two varied examples for each specific surface, preventing one observed
irregular sentence from being reused as an unverified writing template.
`experiments/v1_77_morphology_source_independence.py` checks that fragments
from one document cannot by themselves license a productive rule, while the
same grounded examples across distinct documents still transfer.
`experiments/v1_132_morphology_source_retraction.py` checks that retracting
one donor relation removes its support from productive -ed transfer across
question answering, review-only parsing, and research expansion, including
corrections applied after saving and reloading the knowledge base.
`experiments/v1_78_cvc_doubling_morphology.py` adds a bounded CVC final
consonant-doubling class, requiring cross-relation and cross-document support;
it checks held-out proposal, no automatic commit, plain third-person `-s`,
preference for doubling over plain `-ed` on CVC targets, abstention on CVC
past tense without CVC-specific support, and controls for two-vowel words and
excluded final consonants. The orthographic heuristic is restricted to short,
one-vowel-group forms and is not a complete account of English stress or
syllabification.
Final-c predicates have a separate, evidence-gated `c + k + {ed, ing}` class
for forms such as `panic → panicked` and `picnic → picnicking`. Support must
come from different canonical relations and source documents. Generic `-ed`
evidence cannot guess a `c-k` form, and ordinary third-person `-s` remains a
separate rule. `experiments/v1_138_final_c_morphology.py` checks transfer,
source independence, review-only proposals, and abstention without `c-k`
evidence.
For progressive forms, aligned examples such as `die → dying` and
`lie → lying` license a separate `ie → y + ing` spelling class for `tie →
tying`. Generic `-ing` evidence cannot create `tieing`, and one donor relation
is insufficient. `experiments/v1_151_ie_to_y_progressive_morphology.py` checks
transfer, controls, review-only proposals, progressive QA, research retrieval,
persistence, and abstention with one donor family.
`experiments/v1_120_sibilant_es_morphology.py` adds a distinct learned
`sibilant-es` class for canonical predicates ending in `s`, `x`, `ch`, or `sh`.
It requires support from multiple relations and source documents, transfers
`passes`/`watches`/`fixes` to `mixes`, rejects `walkes`, and checks review-only
fact proposals, QA, research retrieval, persistence, and one-family abstention.
Final-`o` third-person `-es` is a separate learned class: `go → goes` and
`do → does` can support `echo → echoes`, while the class does not create
`talkes` or override grounded ordinary `-s` forms. `experiments/v1_150_final_o_es_morphology.py`
checks cross-relation and source support, review-only proposals, QA and
research transfer, persistence, and one-family abstention. The form remains
evidence-induced; no final-`o` exception is assumed without examples.
`experiments/v1_123_single_z_verb_morphology.py` adds a separately licensed
single-`z`-after-vowel class (`quiz` → `quizzes`), requiring independent
relation and source support. It checks held-out proposal, QA and research
transfer, persistence, one-family abstention, and that the rule does not
transfer to consonant+`z` spellings such as `waltz`.
`experiments/v1_81_multiword_predicate_morphology.py` extends the same
evidence-gated changes to one aligned token inside a multiword predicate. It
requires the remaining predicate tokens to match exactly, and checks transfer,
particle-context abstention, research expansion, and persistence. This does
not parse general phrasal verbs or irregular multiword predicates.
`experiments/v1_90_progressive_predicate_morphology.py` checks held-out `-ing`
transfer in both research retrieval and QA across ordinary endings, final-e
deletion, CVC doubling, and consonant-y retention. A licensed question frame
can realize an induced progressive as “is + predicate” when the predicate
precedes the bound entity, while retaining its spelling-rule evidence. The
syntax also requires an exact `aspect=progressive` fact scope; an unqualified
fact cannot answer a progressive query. The diagnostic rejects insertion
after the bound entity in a frame with different word order. It also checks
that one relation family cannot license productive transfer by itself. In
particular, `-ing` retains final `y` (`copy → copying`); this is distinct from
endings such as `-ed` that can license `y → i` (`study → studied`). These remain
small, cross-relation spelling rules, not a general morphology system.
`experiments/v1_95_multiword_progressive_transfer.py` extends this check to
multiword predicates: independent `working through` and `talking through`
examples license `walked through` → `is walking through`, with held-out QA,
research expansion, exact progressive scope, and a particle-change abstention
control.
The same subject/object placeholders can appear in different sentence orders:
source-backed passive frames such as “The Engine was designed by Ada” can
learn which phrase denotes the agent and which denotes the patient. The
held-out passive extraction and “Who was the Engine designed by?” transfer are
checked by `experiments/v1_35_passive_fact_frames.py`.

Yes/no questions use `teach_polar_question()` after explicit positive facts or
negative facts have been recorded with `add_fact()` or
`add_negative_fact()`. Two examples that vary both subject and object establish
the canonical relation frame. Once established, one additional fact-backed
example can teach a different exact syntax for the same relation, including a
passive form. Every answer still requires explicit positive or negative
evidence. Absence of a positive fact is not interpreted as “no”; it remains
unknown. If both positive and negative evidence are stored for the same
proposition, the answer is ambiguous and both evidence sets are retained. The
`*_from_hit()` variants can attach exact retrieval citations. This is an
open-world evidence policy, not a closed-world database assumption.
`v1_36_polar_question_answering.py` checks the evidence policy;
`v1_60_polar_question_paraphrase_transfer.py` checks passive wording transfer,
abstention, persistence, and CLI behavior.
For narrowly formed `Is/Are/Was/Were SUBJECT [ARTICLE] RELATION OBJECT?` and
`Do/Does/Did SUBJECT PREDICATE OBJECT?` questions, an exact stored relation
label can ground the parse without a separately taught yes/no frame. The
subject and object still have to match the stored proposition; only explicit
positive evidence or a verified rule proof answers “Yes,” explicit negative
evidence answers “No,” and missing evidence stays unknown. Unobserved predicate
synonyms are not guessed. `experiments/v1_253_unframed_polar_questions.py`
checks the natural chat path, positive and negative answers, open-world
abstention, and unseen-synonym abstention.
When a polar question names contextual values, the same API learns those as
separate qualifier slots rather than freezing them as literal words. Transfer
requires multiple grounded examples that vary subject, object, and every
qualifier slot. Matching is bounded and abstains on ambiguous parses, explicit
context mismatch, unsupported scopes, or positive/negative conflict. Values
still resolve only against positive/negative facts or a verified inference
proof; the language frame itself never supplies truth. Qualified frames persist
separately from ordinary polar frames. `experiments/v1_126_contextual_polar_question_frames.py`
checks held-out context transfer, yes/no evidence, conflicts and unknowns,
persistence, and CLI use.

Sentence frames also retain polarity: `teach_fact_pattern_from_hit(...,
polarity=False)` can learn a source-backed negated construction, and the
resulting `FactCandidate` remains negative through review and acceptance.
Negative writing uses the learned negated surface form. This prevents a
matching negative sentence from being inserted as a positive triple.
`experiments/v1_37_negative_fact_extraction.py` checks negated pattern learning,
review, acceptance, yes/no answering, writing, conflict handling, and
persistence.
When overlapping grounded frames propose the same canonical triple with
opposite polarities, extraction and research preserve both candidates for
review instead of letting one overwrite the other. Same-polarity duplicate
frames merge their language evidence. `experiments/v1_80_conflicting_fact_frame_candidates.py`
checks this with article aliases and source-backed positive and negative frames.

`CRMSDialogue` in `crms_dialogue.py` adds one-turn conversational context.
After an unambiguous entity answer, it can resolve up to four occurrences of
`he`, `she`, `they`, `it`, `him`, `her`, or `them` in a follow-up and route the
expanded question through the same grounded QA or research layer. It tests
bounded combinations of recent grounded subject/object entities and selects
one only when exactly one substitution produces a supported answer. It does
not infer gender or long-range coreference; unresolved or multiple bindings
trigger clarification. Standalone “this” and “that” now use the same grounded
resolution; when followed by a known entity surface, they remain determiners
and are not substituted. Pronoun resolution tries bounded canonical and
definite-article entity forms to match learned question frames, collapsing
surface variants only when they return the same supported reading.
`experiments/v1_161_dialogue_demonstratives.py` checks this/that resolution,
article transfer, the determiner guard, and clarification without a referent.
Explicit distributive forms “they each” and “each of them” can run a follow-up
once for each of the two entities grounded in the preceding answer. CRMS
combines results only when every individual query has one supported answer,
retaining each answer's evidence and research passages. If either query is
unknown or ambiguous, it returns no partial group answer and asks the user to
name the entities or ask separately. Ordinary “they” remains subject to the
existing binding ambiguity checks. `v1_168_distributive_plural_dialogue.py`
checks complete aggregation, individual evidence, research citations, and
abstention on partial or singular/plural-ambiguous readings.
Elliptical “What about it/that?” follow-ups also try recent
grounded entity candidates against the previous question frame, proceeding
only when exactly one replacement is supported; otherwise CRMS asks for
clarification. The same diagnostic checks unique and ambiguous bindings.
When these paths use a research index, the returned dialogue turn preserves
the `ResearchResult` and its source passages as well as answer citations.
After a source-backed research question explicitly names one acronym present
in its evidence, a short pronoun follow-up may reuse that acronym as its focus.
The focus is cleared by a new unrelated source query; the latest-research
route also clears dialogue focus while keeping its separate paper-list context.
`experiments/v1_38_dialogue_reference.py` checks research-topic focus across
save/load, pronoun resolution, and clearing stale focus.
An ambiguous answer counts as supported evidence for its candidate referent;
it cannot be discarded in favor of a different referent that happens to have
one answer. `experiments/v1_162_ambiguous_pronoun_binding.py` checks that this
case asks for clarification rather than silently selecting a less ambiguous
antecedent.
The active referent can be saved separately from the knowledge base. An
unanswered or ambiguous turn clears the referent so an unrelated question
cannot silently reuse stale context. The same routing can run through
`CRMSKnowledgeBase.research()` when a research index is supplied.
When an answer has multiple grounded candidates, the dialogue keeps a pending
clarification and accepts an ordinal (“the second one”) or an exact candidate
name. Invalid ordinals leave the clarification open; selecting a candidate
retains only the selected candidate's direct citations, complete fact-path
proofs, and matching inference proofs, then makes that entity the next
referent. Evidence belonging only to another candidate is not carried into
the selected answer.
`experiments/v1_38_dialogue_reference.py` checks context abstention,
subject/object follow-ups, clarification selection, and state persistence.
After a grounded answer, an explicit “I meant [entity]” correction can replace
one entity in the previous question and rerun it against current evidence.
Unknown entities abstain without changing dialogue state; if more than one
replacement yields a grounded answer, the system asks the user to restate the
question. The previous question is persisted with dialogue state.
`experiments/v1_91_dialogue_entity_repair.py` checks correction, re-answering,
persistence, terminal routing, unknown-entity abstention, and ambiguous-role
abstention. This does not repair arbitrary statements or infer which role to
correct when multiple substitutions fit.
`experiments/v1_92_dialogue_pronoun_case.py` checks subject and object pronouns,
including a follow-up where the antecedent changes grammatical role between
turns. `experiments/v1_93_multi_pronoun_dialogue.py` checks a two-pronoun
question with one supported binding and clarification when several bindings
are supported. Dialogue also tests bounded expansions of selected apostrophe-s
contractions (`who's` → `who is` or `who has`, for example) and uses a reading
only when exactly one produces a grounded answer or complete query-term
coverage in a supplied source. Proper-name possessives are not expanded.
For a narrow property-query form, “What is its size?” is rewritten as a
candidate question such as “What is the size of the Engine?” and answered only
when current dialogue evidence leaves one supported entity. If multiple
entities support the property, CRMS asks the user to name one; an unsupported
property abstains. `experiments/v1_233_possessive_dialogue.py` checks unique
resolution, ambiguity, abstention, and source-backed research provenance. This
does not resolve possessives in arbitrary sentence forms.
`experiments/v1_94_grounded_contraction_resolution.py` checks evidence-selected
QA and research, retained exact aspect scope, and the possessive guard.
Common auxiliary forms (`'re`, `'ve`, `'ll`, `'d`, and `'m`) and a bounded set
of negative contractions (`isn't`, `don't`, `can't`, and related forms) use the
same evidence-selected path. Negative expansions preserve `not`; they never
turn absence of a positive fact into a negative answer. The `'d` reading is
kept ambiguous (`did`, `would`, or `had` for interrogative stems; `would` or
`had` for pronouns), and `ain't` retains its possible auxiliary readings, until
grounded QA or complete source-term coverage selects one. Multiple supported
readings cause abstention. This is a bounded contraction grammar, not general
parsing.
`experiments/v1_128_auxiliary_contraction_resolution.py` checks the supported
forms, negative-polarity preservation, ambiguous-reading abstention, and
possessive protection.
After an answered turn, `Why?`, `Why is that?`, `How do you know that?`, and
`What supports that?` recompute the previous question against current stored
evidence and render its fact citations or verified rule proof with premise
sources, including explicit negative-fact citations for a grounded “No” answer.
Absence of a positive fact alone never supports “No”. If evidence was retracted, the explanation abstains and clears the
stale context. An unresolved answer choice remains pending until selected;
CRMS does not invent a rationale for an ambiguous result. After a user selects
one candidate, the next explanation is filtered to that candidate's current
evidence; if it loses support, CRMS abstains rather than switching to another
candidate. After a grounded “tell me about” digest, an explanation request
rebuilds that digest from current facts and verified inferences, preserving its
source and rule citations. “What about [known entity]?” can also reuse that
learned about-frame for another entity; the follow-up and its explanation stay
bound to the new entity's current evidence.
`experiments/v1_131_grounded_explanation_followup.py` checks direct QA and
research citations, explicit negative-answer support, rule-premise lineage, persistence, stale-evidence
revalidation, pending ambiguity, digest refresh, entity follow-up after a
digest, and the terminal chat loop.

Run the standalone regression experiments through `python3 run_experiments.py`.
Use `--match 241` for a focused diagnostic or `--list` to inspect the selected
files. Each experiment gets a fresh temporary working directory, reports its
status and runtime, and returns a failing exit code when a diagnostic fails.
The default suite includes numbered `v1_*.py` experiments;
`--include-legacy` also includes the earlier `v1_crms.py` prototype.
`experiments/v1_242_grounded_recombination_benchmark.py` measures held-out
phrase recombination as the number of taught examples grows, records wrong
answers separately from abstentions, and exercises controlled negatives. On
its generated 4-by-4 phrase grid, coverage rose from 0/24 held-out cases at four
taught phrases to 16/16 at eight, with no wrong unique answers; all five
controlled negatives abstained. This is evidence for that bounded synthetic
grammar, not a general language benchmark. Its ten authored paraphrase probes
currently abstain, showing the remaining open-vocabulary gap.
`experiments/v1_241_chat_usability_diagnostics.py` checks that an optional
question word or contiguous phrase (up to three tokens) is inferred only from
two aligned, fact-backed examples, carries its source trace through chat and
save/load, and loses word-level evidence when support is retracted. The phrase
variant must occur in its learned position and order; reordered variants
abstain. Two independently grounded phrases at different positions can compose
for a held-out entity. This remains a narrow exact-frame comparison: the
question layer does not yet learn a general function-word class or infer
arbitrary paraphrases.

Run `python3 crms_chat.py` to use these layers from a terminal. The shell can
load or create the knowledge and research-index JSON files, add local UTF-8
text, searchable PDF, or explicitly requested HTTP(S) page sources with
`/source PATH|URL`, teach source-backed fact
patterns with `/teach-fact SUBJECT|RELATION|OBJECT|SOURCE QUERY|PREDICATE PHRASE|positive/negative` (optionally followed by labeled subject and object surface phrases),
and teach question frames with `/teach-question QUESTION|RELATION|subject/object|BOUND ENTITY|ANSWER`.
Question frames can also be taught conversationally with two to eight explicit
question/answer examples, such as `Teach a question frame from examples:
"Who designed the Analytical Engine?" => "Ada Lovelace"; "Who designed the
Compiler?" => "Grace Hopper".` CRMS derives the relation and answer slot only
when every pair matches one direct stored fact and all examples agree on the
same relation and answer slot. It commits the frame only after distinct bound
entities license one shared wording pattern; unresolved or ambiguous examples
are not saved. Once a frame is licensed, one directly supported new entity can
be added conversationally with `Teach an additional question example:
"Who designed the trajectory table?" => "Katherine Johnson"`. CRMS accepts it
only when its exact wording pattern identifies one existing licensed frame,
the entity is new to that frame, and the answer matches one stored fact or a
complete verified inference proof.
Unsupported examples and attempts to create a frame from one example leave
memory unchanged. `experiments/v1_218_incremental_question_frame_learning.py`
checks transfer, grounding, rejection, and persistence.
Each question frame also licenses only its learned answer direction. To ask in
the opposite direction, teach that wording from its own fact-backed examples,
for example `"What did Ada Lovelace design?" => "the Analytical Engine"` and
`"What did Grace Hopper design?" => "the Compiler"`. Once both directions are
licensed, a follow-up such as `"What did she design?"` can resolve against the
prior grounded answer. `experiments/v1_40_cli_language_learning.py` checks this
complete conversational path and its source citation.
Both directions can be taught in one transaction with `Teach paired question
frames from examples:` followed by four or more question/answer pairs. CRMS
requires at least two distinct, directly supported examples for each direction
and one shared relation; if either group fails, no frame is saved.
Single-qualifier frames can be extended in the same way with `Teach an
additional contextual question example: "Who designed the trajectory table
in 1969?" => "Katherine Johnson"`. CRMS requires the exact existing
entity-and-qualifier slot pattern, a previously licensed frame, and a directly
supported fact for the new entity/context pair. Multi-qualifier frames still
use the same command only when every qualifier slot matches the existing
template and varies in the licensed examples. The
`experiments/v1_219_incremental_qualified_question_learning.py`
and `experiments/v1_220_incremental_multi_qualified_question_learning.py`
diagnostics check grounded transfer, exact slot alignment, rejection, and
persistence for one and multiple qualifier slots.
The same teaching form supports qualified questions when examples map to
stored facts with the same qualifier names and different values. CRMS learns
the qualifier slots from those facts, requires distinct entities and variation
in every qualifier slot across the batch, and leaves a question unanswered
when the requested context has no matching evidence.
Path questions can be taught conversationally with two to eight
question/answer examples when each question names a distinct starting entity
and the stored facts expose one unique forward path of at most three relations
to its answer. Every example must resolve to the same relation sequence. If
the facts admit multiple paths or no complete path, CRMS leaves the frame
unlearned. The question frame does not add graph edges; later answers still
require the complete fact path.
Truth-question frames also accept two to eight conversational examples, such as
`Teach a yes/no frame from examples: "Is it true that Ada designed Engine?"
=> yes; "Is it true that Grace designed Compiler?" => no.` Each label must
match explicit positive/negative evidence or a verified positive rule proof:
`yes` may come from a stored positive fact or an independently checked
inference, while `no` still requires an explicit negative fact. CRMS derives
one shared relation and requires all examples to use distinct subjects and
objects before retaining the frame. Candidate alignment is bounded; if it
cannot identify one supported triple, the frame is not learned. Missing
propositions stay unknown rather than becoming false by default.
For bounded active do-support questions (`Did SUBJECT VERB OBJECT?` and
`Does SUBJECT VERB OBJECT?`) and copular questions
(`Is SUBJECT the RELATION OBJECT?`), a separately taught polar template is
not required when the predicate matches a licensed source-backed fact frame.
Regular third-person `-s/-es` forms can be reduced to the bare predicate under
`do/does`; the relation meaning still comes from the accepted frame. The route
requires a unique parse; it answers yes only from a positive fact or verified
proof, no only from an explicit negative fact, and otherwise returns unknown.
It does not infer that an unrecorded object is false.
`experiments/v1_36_polar_question_answering.py` and
`experiments/v1_245_zero_frame_corpus_learning.py` check these routes alongside
the taught-frame, contradiction, citation, and persistence cases.
Typed object questions of the form “Which TYPE did SUBJECT VERB?” use a
separate explicit type gate. CRMS answers only when the stored relation matches
the question's regular `did` form and the candidate object has positive
`is-a` evidence for TYPE. Unsupported types remain unknown; multiple matches
or positive/negative conflicts remain ambiguous. The answer is realized from
the supporting relation fact. `v1_258_typed_object_did_questions.py` checks
type gating, sentence output, ambiguity, and conflict handling.
`/retract-fact POS/NEG|SUBJECT|RELATION|OBJECT|SOURCE[|KEY=VALUE]` removes one
source's support while preserving other citations; derived proofs revalidate
when next retrieved. The ordinary-language form `Retract the positive fact
"Alice likes tea." from source "alice".` resolves only sentences CRMS can
already realize from licensed fact frames and requires the exact supporting
source. Add `in context "year=2024"` (multiple `KEY=VALUE` pairs may be
separated by semicolons) to select an exact qualifier scope; ambiguous scoped
matches without that scope abstain.
The shell can also teach yes/no frames with `/teach-polar`, multi-hop question
frames with `/teach-path-question`, write stored facts with `/write-fact`, and
inspect memory through `/facts` and `/sources`. Relation reasoning uses
`/teach-inference-rule` for bounded two- or three-premise rules and
`/teach-relation-type RELATION|transitive|SOURCE` or
`/teach-relation-type RELATION|symmetric|SOURCE` to license the corresponding
fixed relation schema. In ordinary conversation, an explicit instruction
such as `Teach CRMS that the relation "precedes" is transitive.` or
`Teach CRMS that the relation "collaborates with" is symmetric.` records the
same scoped schema declaration with user-teaching provenance;
`v1_226_natural_relation_schema_teaching.py` checks both types through the
terminal, persistence, provenance, and independent proof verification.
`/infer-relation SUBJECT|RELATION|OBJECT` renders the independently checked
proof and its relation-type provenance. The shell also
exposes the integer-list rule learner with `/teach-rule INSTRUCTION|INPUT CSV|OUTPUT CSV`,
`/apply-rule INSTRUCTION|INPUT CSV`, `/explain-rule INSTRUCTION|INPUT CSV`,
and `/rules`. `/explain-rule` shows the selected procedure, grounding phrases,
and up to three stored demonstrations for each reported phrase, alongside any
retrieval score and matched pattern. Parameterized scaffold transfers also show
which phrase examples support each positional word role and how each numeric
slot maps to an operation parameter, including its source values. A natural request such as
`Reverse the list [7, 1, -4]` also routes the text before a bracketed integer
list through the same learned rule memory. One request can apply the same
instruction to several lists, for example `Reverse the list [1,2,3] and
[5,0,-2]`; CRMS prints results only if every input has a grounded prediction.
Otherwise it asks for clarification without returning partial outputs.
Unresolved rule examples return the model's contrastive request and do not
commit a procedure.
Rules can also be taught conversationally with the explicit demonstration
forms `reverse the list [1,2,3] -> [3,2,1]`, `For input [1,2,3], reverse the
list produces [3,2,1]`, and `Applying reverse the list to [1,2,3] yields
[3,2,1]`. Multiple examples can be supplied in one bounded batch, for example
`reverse the list: [1,2,3] -> [3,2,1]; [5,0,-2] -> [-2,0,5]`. Each turn adds
the exact grounded input/output pairs to the same learner; unresolved
demonstrations remain
uncommitted, and the learner's contrastive request guides the next example.
When CRMS requests the output for a specific contrastive input, a reply such as
`The output is [3,2,1]` or `For that input, the result is [3,2,1]` supplies
that exact pair; the pending input survives a chat restart and can be dismissed
with `/cancel-rule`. `[]` represents an empty list. These are bounded,
explicit forms, not free-form instruction or example extraction.
When natural-language retrieval is ambiguous and CRMS requests an output for a
separating input, the chat keeps that input pending and attaches an output-only
reply to the queried instruction. `/apply-rule` also saves an available
contrastive probe, so the same output-only feedback works after an explicit
rule query. Repeated answers continue the same bounded teaching interaction
until one rule fits or CRMS asks for a new demonstration.
The chat accepts `--rule-depth 1|2|3|4` to set the maximum composition depth,
plus `--rule-max-add`, `--rule-max-scale`, `--rule-max-modulus`,
`--rule-max-rotation`, and `--rule-max-repeat` to set each operation family's
search bound (defaults: 10, 5, 6, 4, and 4). A saved rule memory can be opened
with the same or wider depth, parameter bounds, and `--rule-search-expansions`
(default 250,000); narrower settings are rejected. This lets a teacher reopen
accumulated `no_fit` or incomplete searches with wider bounds after reviewing
an advisory proposal or a search-limit response. `/retry-rule INSTRUCTION`
reruns that instruction's stored examples under the current configuration
without adding duplicates. If the configured-depth search returns `no_fit`, CRMS
may print exact procedures found by a complete search one level deeper. These
are labeled advisory and are not committed; review them by repeating the
demonstrations with a greater depth or parameter bound. A small, behaviorally
distinct proposal set also triggers a contrastive input request; the teacher's
reply filters proposals but does not commit one. An incomplete deeper search
produces no proposals.
It answers natural-language questions, preserves dialogue context, and accepts
a reviewed extraction with `/accept N`. Accepted knowledge and the index save
to the configured paths; `/skip`, `/reset`, and `/quit` manage review and
session state. Research candidates remain uncommitted unless accepted.
An answered question can also establish a frame for the explicit entity-only
follow-ups “What about the Compiler?” or “And the Engine?”. CRMS tries known
entity substitutions in the previous question and carries one forward only
when exactly one revised question has a supported answer. Unknown entities and
ambiguous substitutions do not alter the previous dialogue context. This is a
bounded follow-up form, not general ellipsis resolution;
`experiments/v1_96_dialogue_entity_followup.py` checks the API and terminal
flow, research-backed answers, state persistence, and unknown-entity abstention.
`experiments/v1_39_terminal_chat.py` drives ingestion, review, acceptance,
follow-up, and persistence; `experiments/v1_40_cli_language_learning.py`
bootstraps sentence and question frames from cited examples, exercises
conversational unqualified and polar question-frame learning, then checks
held-out extraction through the same terminal interface.
`experiments/v1_213_conversational_contextual_question_learning.py` checks
conversational qualified-frame teaching, rejection of context-mismatched
examples, held-out entity/context transfer, abstention on a wrong context, and
persistence.
`experiments/v1_214_conversational_path_question_learning.py` checks unique
path derivation from direct facts, held-out path-frame transfer, unknown-path
abstention, and persistence.
`experiments/v1_41_cli_path_learning.py` checks multi-hop frame teaching,
fact/source inspection, held-out path composition, and proof output.
`experiments/v1_42_cli_rule_learning.py` checks ambiguous rule acquisition,
contrastive example accumulation, held-out application, inspection, and
persistence from the terminal shell. `experiments/v1_49_natural_rule_demonstrations.py`
checks conversational teaching, empty-list examples, contrastive requests,
held-out application, persisted no-fit proposal feedback, retry after widening
parameter and work bounds, and persistence. It also checks the atomic shared-
phrase form (`Teach both "reverse the list" and "invert the sequence" using
the same examples: ...`). Each phrase is learned independently against the
same demonstrations, and the batch is saved only when both searches return the
same unique procedure. A mismatch or unresolved search leaves the active model
unchanged. This grounds two phrase associations to one demonstrated behavior;
it does not infer a general synonym relation or license unseen procedures.
`experiments/v1_103_contrastive_chat_learning.py`
checks that an output-only chat reply is attached to the exact separating input
requested by ambiguous retrieval, including repeated probes and held-out use.

## Source retrieval for research

`crms_research.py` indexes supplied UTF-8 text files, CSV/TSV tables, XLSX
workbooks, PPTX slide text, ChatGPT conversation exports, HTML, DOCX/ODT
documents, EPUB books, searchable PDFs, and explicitly supplied HTTP(S) pages
with deterministic lexical ranking.
For large local encyclopedic corpora, `crms_import_wikidump.py` streams plain,
bzip2, or gzip MediaWiki XML exports into a SQLite research index, one page per
citable source. It indexes the latest revision of readable main-namespace
pages, excluding redirects and non-main namespaces, without loading the dump
into memory. Common links, headings, table separators, formatting markers, and
reference tags are converted or removed; citations point exactly into this
indexed readable rendering. Package the index into the distributable model with
`crms_package.py export --research-index wikidump.sqlite`; after export, the
dump and intermediate index are no longer required at runtime. For example:

```sh
python crms_import_wikidump.py enwiki-pages-articles.xml.bz2 \
  --output wikidump.sqlite \
  --license-name "CC BY-SA 4.0" \
  --license-url https://creativecommons.org/licenses/by-sa/4.0/
python crms_package.py export --output crms-model.sqlite \
  --knowledge crms_knowledge.json --rules crms_rules.json \
  --research-index wikidump.sqlite
```

The importer does not determine a dump's license. Verify the source terms and
provide the applicable license name and URL. Each indexed page records the
dump, revision, article revision link when site metadata provides a base URL,
supplied license, and wikitext normalization notice in its source location.

Separate encyclopedic, academic, and project indexes can be combined before
packaging. `crms_merge_research.py` streams source documents into one FTS-backed
SQLite index, retaining document IDs, source locations, page boundaries, and
exact-text citations. Identical IDs with identical content are skipped;
conflicting content fails by default so a refreshed source cannot silently
replace an earlier citation. Resolve such conflicts explicitly with
`--conflict keep-first` or `--conflict replace-later`. Use `--append` to add
new indexes to an existing merged corpus; it rebuilds through a temporary file
and only replaces the target after validation. It commits bounded batches
(256 documents by default; tune with `--batch-size`) so large merges do not
hold one transaction across the entire corpus.

```sh
python crms_merge_research.py --output broad-corpus.sqlite \
  wikidump.sqlite openalex.sqlite arxiv.sqlite pmc.sqlite
python crms_merge_research.py --append --output broad-corpus.sqlite \
  new-papers.sqlite
python crms_package.py export --output crms-model.sqlite \
  --knowledge crms_knowledge.json --rules crms_rules.json \
  --research-index broad-corpus.sqlite
```

`experiments/v1_255_research_corpus_merge.py` checks multi-source merge,
deduplication, citation and page preservation, resumable append, and explicit
conflict handling. The merge utility combines indexes already acquired
locally; it does not download or grant reuse rights to source material.

For local academic article corpora in JATS XML, `crms_import_jats.py` creates
a searchable SQLite index. It requires explicit CC0 or CC BY evidence in each
article's license statement and excludes noncommercial, no-derivatives,
share-alike, unlicensed, and malformed files. The indexed article includes
title, authors, license statement, DOI/PMC provenance, abstract, and readable
body text. This is a conservative first redistribution policy; it is not a
general license classifier. Example:

```sh
python crms_import_jats.py ./pmc-article-xml --output papers.sqlite
python crms_package.py export --output crms-model.sqlite \
  --knowledge crms_knowledge.json --rules crms_rules.json \
  --research-index papers.sqlite
```

`crms_import_pmc.py` can discover and download a bounded set of PMC records
from the current PMC Article Datasets on AWS. It searches only the CC0/CC BY
filters, checks the version's JSON license class against the XML rights,
verifies the XML MD5 from its dataset URL, and excludes retracted or
unsupported-license versions. It retains every eligible version as a separate
document rather than choosing one from the version number or manuscript flag;
the current PMC dataset documentation says the version sequence alone does
not establish which copy is preferred. Each indexed paper records its PMC
version and XML revision in a version-specific document ID, NLM source
acknowledgment, and a notice that the stored snapshot may be stale.
For example:

```sh
python crms_import_pmc.py "symbolic reasoning" --max-articles 200 \
  --output pmc.sqlite
python crms_import_pmc.py "program synthesis" --max-articles 200 \
  --append --output pmc.sqlite
python crms_package.py export --output crms-model.sqlite \
  --knowledge crms_knowledge.json --rules crms_rules.json \
  --research-index pmc.sqlite
```

The adapter is query-bounded (100 articles by default, at most 10,000 search
records). `--append` adds distinct article versions and stores changed XML
revisions as additional immutable records, preserving citations to earlier
snapshots; identical revisions are skipped. This can increase index size over
repeated refreshes. It does not remove records that disappear from a later
search or are retracted upstream. Removal and review policies are still needed
before treating an accumulated database as a synchronized corpus. Re-export
when current source data is required. Its offline API diagnostic is
`experiments/v1_238_pmc_dataset_import.py`.

For larger local libraries, start the chat with a SQLite index path such as
`--index research.sqlite`; the FTS5-backed `CRMSSQLiteResearchIndex` keeps
source text and overlapping 400-token search chunks on disk and loads matching
documents to construct exact-offset citations. Results rank the best chunk per
document, so a long book or PDF can be retrieved by its relevant section rather
than one whole-document score. Version-1 SQLite indexes rebuild their FTS table
into chunked form on first open while preserving stored documents and citations.
`/source-dir PATH` recursively indexes UTF-8
`.txt`, `.md`, `.markdown`, `.rst`, `.csv`, and `.tsv` files, `.xlsx`
workbooks, `.pptx` presentations, readable `.html`/`.htm`/`.xhtml`,
`.docx` and `.odt` documents, EPUB books, searchable `.pdf` files, and
`conversations.json` ChatGPT exports beneath an explicitly selected local directory.
It also accepts `.chat.json` and `.chatgpt.json` exports; unrelated JSON files
are skipped. Chat export ingestion follows the selected current message branch,
keeps user and assistant turns, and excludes system messages, analysis-channel
messages, and unselected branches. Text markup is retained as supplied so
citation offsets remain exact; HTML, office document, spreadsheet, EPUB, and
chat citations resolve against their extracted readable text. XLSX worksheets
are rendered with sheet names, column headers, and row labels to keep retrieved
cell values in context. PPTX slide text is extracted in presentation order and
rendered with slide numbers; citations resolve against that extracted text.
`/source-dir PATH --replace` refreshes existing paths. Directory traversal is
deterministic, skips symlinks and unsupported file types, and reports per-file
failures. SQLite directory ingestion commits batches of at most 256 supported
files and isolates each document with a savepoint, so a malformed file does not
discard other successful imports and very large imports release the database
write lock between batches. It records each imported file's size and nanosecond
modification time; a later scan refreshes files whose metadata changed and skips
unchanged files. It also stores a SHA-256 digest of each raw imported file.
`/source-dir PATH --verify` rechecks every supported file to find changes that
kept the same size and timestamp; SQLite indexes compare stored raw-file hashes,
while the JSON index reprocesses the source text. This adds a full read of every
indexed file.
`/source-dir PATH --replace` forces reprocessing of every supported file.
This provides
disk-backed access to user-supplied local knowledge; it does not supply or
claim a preloaded corpus, and it does not make the independent symbolic fact
store itself disk-backed. `/sources [PAGE]` reports the indexed document count
and source-text size and lists 50 sources per page. URL ingestion can capture
one page with `/source URL`
or explicitly crawl a
bounded same-origin set with `/crawl URL|MAX_PAGES|MAX_DEPTH`. Crawling follows
only HTTP(S) links on the starting origin, records every page as a separate
source, and reports individual failures. It extracts readable HTML text
without executing page code; each page URL remains attached as the snapshot
location, while exact citations resolve against the captured text. Captures
are limited to 2 MB per page by default. PDF ingestion uses `pypdf` and retains page boundaries; scanned
image-only PDFs are not OCR'd. Each hit includes the
document identifier, location, matched terms, score, and an exact text slice
with character offsets; PDF hits also include the page number. Search considers
both body and title terms, so a title-only match can retrieve a document while
its citation still points to an exact body excerpt. `render_hits()`
prints these as attributable excerpts. Replacing a document updates its
postings, and indexes can be saved and reloaded. A small IDF-scaled bonus
favors adjacent query terms and a complete ordered match within one sentence,
with the full-match bonus decreasing as the span grows. It affects ranking
only and does not change citations or license extracted
facts. `v1_122_ordered_proximity_retrieval.py` checks ranking against an equal
term-frequency control, sentence-boundary handling, exact citations, and
no-match behavior. This is a source retrieval foundation, not a claim
synthesizer: research returns exact matching sentences and cited passages for
a person or a later grounded rule to inspect. `/source https://...` captures one page;
`/crawl https://...|10|1` captures a bounded same-origin set. Retrieved
passages remain uncommitted until reviewed and accepted as facts.
`CRMSResearchIndex.summarize(query)` and the chat forms `/summarize QUERY` or
“Summarize …” provide a bounded extractive summary: they select complete source
sentences that overlap query terms and cite each sentence at its exact
character span, including the PDF page when available. Selection prefers
sentences that add query terms not covered by earlier selections, then uses
the existing relevance score; it remains bounded by the result and
per-document limits. The wording is copied unchanged; this does not paraphrase,
infer facts, or guarantee coverage of every important point. Sentence
boundaries use a deterministic punctuation heuristic, so abbreviations can
still fragment a sentence. In terminal chat, the summary route first obtains
the query expansions already licensed by source-cited entity aliases and
predicate frames or verified inference proofs. It uses only expansions that
matched summary hits, and the summary reports each such expansion with its
evidence and source or rule lineage. Licensed expansions are retained
independently of the initial research passage limit, so a low-ranked passage
does not hide the expansion from summary retrieval. The same records are
available as `ResearchResult.query_expansions`, separate from returned
passages. A sentence must match an
original query term or one of those licensed expansion terms. Direct calls to
`CRMSResearchIndex.summarize()` can supply such terms and licenses explicitly.
After a terminal summary, “Show more sentences”, “Show fewer sentences”, and
“Show only the first two sentences” refine the same query and reuse its
licensed expansion records; sentence selection and citations are regenerated
from the current source index.
The `/research` route also carries its best complete matching sentences in
`ResearchResult.source_sentences` and renders them before passage metadata.
Each sentence keeps its exact citation and is clearly presented as source
evidence; it is not promoted to an accepted fact or treated as a verified
interpretation. This keeps ordinary research useful before a relation frame
has been taught, while preserving the distinction between retrieval and
learned fact reasoning.
For question retrieval, terminal chat also applies a narrow regular verb
spelling correspondence from a progressive query form to its regular past
form (for example, “designing” can retrieve a sentence containing “designed”).
The generated term is recorded in `ResearchResult.query_expansions` with the
input word and spelling rule. It only helps locate source sentences; it does
not establish that a source claim is true or equate surrounding phrases such
as “responsible for” with the predicate. Common irregular past stems are
excluded from this rule.
`experiments/v1_212_extractive_research_summary.py` checks exact wording and
citations, page retention, no-match behavior, query-term coverage under a
result cap, expansion availability without initial passage hits, source-cited
alias expansion and lineage, and the natural-language
terminal route and summary-count follow-ups, decimal-punctuation handling,
stable output after index
persistence, and invalidation of citations when a source revision changes.
`v1_71_grounded_predicate_research_expansion.py` and
`v1_69_research_with_derived_context.py` also check that learned predicate and
proof-derived licenses are exposed separately from passage results.
Summary generation is read-only. This adds source-grounded writing for research
without claiming abstractive summarization.
Each citation includes a content hash, page when available, and character
offsets; `resolve_citation()` rejects it if the document has since changed.
`CRMSKnowledgeBase.add_fact_from_hit()`
can attach a verified hit to an explicit fact. That step records provenance but
does not decide whether the passage entails the asserted relation.
`experiments/v1_30_research_source_retrieval.py` checks body and title-only
ranking, exact source spans, deterministic no-match behavior, body/title
replacement invalidation, file ingestion, persistence, and
passage-to-fact-to-answer provenance.
`experiments/v1_31_pdf_source_retrieval.py` checks multi-page PDF extraction,
exact excerpts, page citations, and persistence using the bundled runtime with
`pypdf` installed.
`experiments/v1_99_explicit_url_research.py` checks readable HTML extraction,
script removal, exact snapshot citations, persistence, terminal ingestion,
redirect metadata, URL/content validation, and the capture-size bound using a
mocked HTTP response.
`experiments/v1_107_bounded_site_research.py` checks same-origin link traversal,
page and depth limits, redirect rejection, per-page citations, and CLI
persistence with mocked responses.
When learned sentence patterns extract the same candidate claim from multiple
retrieved passages, `render_research()` groups the claim, counts distinct
indexed sources, and lists the exact supporting sentences and citations.
Each returned passage also separates matched terms from the literal question
from terms added by licensed alias, predicate, or verified-inference query
expansion. Each matched expansion retains its license type, originating phrase,
source evidence, and inference rule IDs where applicable. The renderer labels
these beside the cited source so a reader can see why it was retrieved; query
matches and expansion licenses explain retrieval, not whether the passage
supports an answer.
Different candidate objects or polarities for the same subject and relation
are marked as competing claims. These remain review-only extractions, not
verified facts or a general natural-language summary. The
`experiments/v1_108_review_only_evidence_synthesis.py` diagnostic checks
cross-source grouping, exact attribution, and the no-auto-commit gate.
Research candidates can be accepted or rejected conversationally with phrases
such as `Accept that candidate` or `Reject candidate 2`, while `/accept N`,
`/reject N`, and `/skip` remain available. Acceptance uses the same citation
and sentence revalidation as the command path. If several candidates are
pending, a decision without a number requests clarification; rejection removes
only the selected proposal and never adds it to memory. The remaining queue is
shown with refreshed candidate numbers so the user can continue the review.
`experiments/v1_217_natural_candidate_review.py` checks cited acceptance,
explicit rejection, ambiguous-choice clarification, persistence, and the
no-unreviewed-write invariant, including restoring a pending candidate after a
chat restart and continuing after one of several candidates is rejected. If a
queued citation or learned-frame license becomes invalid, CRMS retains the
candidate and reason in an inspect-only invalidation history rather than
discarding its details. Use `/invalidated-candidates` to inspect and
`/clear-invalidated-candidates` to clear that history; invalidated proposals
cannot be accepted until research produces a currently licensed candidate.

Rotation is an explicit parameterized primitive. For example, with
`max_rotation=4`, demonstrations showing `[1, 2, 3, 4] -> [2, 3, 4, 1]`
identify a one-place left rotation when the examples distinguish it from other
offsets. Numeric phrase frames can transfer a demonstrated "rotate the list
left N" pattern to another in-range offset after two distinct values have
grounded the same frame. The semantic summary canonicalizes consecutive
rotations and reorder-only interactions exactly. Uniform repetition
canonicalizes with reverse, sorting, filters, and a following endpoint
selection. Repetition after an endpoint selection is also summarized exactly
as a selected value with a copy count. A rotation that crosses a filter or
splits repeated runs uses a conservative syntax key unless a later sort
discards the ordering interaction; this may leave equivalent composed
programs ambiguous, but it does not merge them without proof.

### Academic paper sources (roadmap)

Academic platforms are a high-value source family for the research path, but
discovery, retrieval, and redistribution must be treated as separate steps.
OpenAlex is a candidate discovery/catalog adapter: its work records expose
multiple locations, versions, and location-level license metadata. A paper
being marked open access is not by itself sufficient permission to copy its
full text into a distributable model. The adapter should preserve the DOI or
stable platform identifier, authors, title, publication/version metadata,
retrieval URL, and the license statement for the exact copy selected.

Searchable article text may be embedded in the model database
only when the specific article's license permits that redistribution; otherwise
retain bibliographic metadata and a link to the source, and do not package its
full text. Preserve source attribution and license alongside each document,
and make retrieval citations point into the stored text with section/page
context when the format provides it. Facts or rules learned from a paper remain
separately derived CRMS knowledge and should retain a citation back to the
passage that supports them.

Remaining candidate source adapters, in order:

1. OpenAlex for topic/DOI discovery and alternate-copy metadata, never as a
   blanket license grant.
2. arXiv for preprints through its documented interfaces and permitted
   download routes, recording the paper version and its declared license.
3. Additional repositories such as institutional repositories, DOAJ-listed
   journals, and subject archives through their own documented interfaces and
   per-copy reuse terms.

The OpenAlex adapter is implemented in `crms_import_openalex.py`. It performs
bounded cursor-paged work discovery and indexes searchable bibliographic
metadata (title, reconstructed abstract, authors, year, type, DOI, and stable
OpenAlex ID) in the CRMS SQLite research database. OpenAlex supplies abstracts
as word-position inverted indexes rather than plaintext; the importer rebuilds
their order and punctuation under explicit size and validity bounds. It retains
the best and primary copy's reported version, license, repository, landing
page, and PDF URL. It does not download paper full text. OpenAlex's metadata is
CC0, but a work's open-access flag is not a license for its article copy;
full-text acquisition must pass the license check of the specific location. Create an index with
`python3 crms_import_openalex.py --query "formal verification" --output research.sqlite`
or add records with `--append`; result count is capped at 1,000 per run. OpenAlex
permits initial keyless API use, but cursor paging beyond the first page
requires an API key; set `CRMS_OPENALEX_API_KEY` or pass `--api-key` for larger
searches. For catalog-scale imports, OpenAlex recommends its downloadable
snapshot rather than cursor-paging all works. Download the works JSONL parts
from the [OpenAlex snapshot](https://help.openalex.org/access/snapshot/) and
stream them into a new index:

```sh
python3 crms_import_openalex.py \
  --snapshot-jsonl ./openalex/data/jsonl/works \
  --output research.sqlite --batch-size 500
```

Snapshot import keeps one bounded batch in memory, commits batches separately,
recursively reads OpenAlex `part_*.gz` or JSONL files in the supplied directory,
and deduplicates by stable work ID. Once a part is read to completion, its
path, size, modification time, and import counts are checkpointed in the
research database. If interrupted, rerun with `--append`; completed unchanged
parts are skipped, while an incomplete or changed part is scanned again and
committed records are deduplicated; works whose stable ID now has revised
metadata or abstract are refreshed in place. The importer does not remove
works that disappeared from a changed part, so build a fresh index when
reconciling deletions across snapshot releases. The checkpoint uses size and
modification time rather than a full content hash, so preserve source-part
metadata when copying snapshots. Use `--max-records N` for a bounded trial;
limited runs do not create completion checkpoints. The
snapshot bulk workflow is designed for user-provided local files; it does not
download the multi-hundred-gigabyte snapshot itself.
`experiments/v1_246_openalex_metadata_import.py` checks cursor paging, abstract
reconstruction and retrieval, the metadata/full-text boundary, per-copy
license/version retention, SQLite search, snapshot JSONL streaming, bounded
batch commits, interruption/resume deduplication, unchanged-part skipping,
changed-part invalidation, and append handling. OpenAlex
supports field selection at the top level, so the adapter requests the abstract,
location, and access objects intact.

The arXiv adapter is implemented in `crms_import_arxiv.py`. It uses one
bounded Atom API page per invocation (up to 100 records), with an explicit
zero-based `--start` offset for resumable paging across append runs. It indexes CC0
bibliographic metadata including abstracts, records versioned arXiv IDs and
links, and deduplicates repeated records. Metadata-only import is the default.
With explicit `--full-text`, the adapter checks the current `arXivRaw` OAI
record, confirms that the latest OAI version still matches the searched
version, and downloads a bounded PDF only for recognized CC0 and CC BY license
URIs. The allowlist is limited to the canonical CC0 1.0 URI and CC BY versions
1.0, 2.0, 2.5, 3.0, and 4.0; other licenses and unknown URIs remain
metadata-only. Indexed paper text carries title, authors, version, declared
license URI, OAI datestamp, PDF URL, and PDF checksum in its attribution text.
Page boundaries remain intact for citations. Records first imported as
metadata can be upgraded with `--append --full-text` when their license is
eligible. This follows arXiv's [license guidance](https://github.com/arXiv/arxiv-docs/blob/develop/source/help/license/index.md)
and [OAI metadata behavior](https://github.com/arXiv/arxiv-docs/blob/develop/source/help/oa/index.md): article versions can have different licenses, and
the API's open-access status alone does not grant full-text reuse. The
metadata-only command is
`python3 crms_import_arxiv.py --query "all:formal verification" --output research.sqlite`;
to fetch the next page, repeat it with `--append --start 100`; advance the
offset by the requested page size. To add eligible article text, use the same
page offset with `--append --full-text`.
To license-check metadata already indexed and fetch eligible papers in
resumable batches, run
`python3 crms_import_arxiv.py --upgrade-existing-full-text --output research.sqlite --append --max-records 100`.
The sweep records exact-version license outcomes in each source record, skips
restricted licenses and completed records on later runs, and downloads only
CC0/CC BY PDFs. It waits three seconds between records by default;
`--retry-failed-license-checks` retries prior OAI failures. The offline
`experiments/v1_247_arxiv_metadata_import.py` diagnostic checks batch resume,
restricted-record persistence, eligible full-text upgrade, and citation
preservation.
The indexed source text can be embedded in a distributable SQLite model with
`python3 crms_package.py export --output crms-model.sqlite --knowledge knowledge.json --rules crms_rules.json --research-index research.sqlite`.
The `experiments/v1_247_arxiv_metadata_import.py` diagnostic checks API bounds,
explicit page offsets and append paging,
Atom parsing, abstract search, version identity, exact-version OAI license
verification, CC0/CC BY acceptance, restricted-license/version rejection,
metadata upgrade, PDF attribution/page citations, repeated-frame discovery and
review from separate papers, portable-model installation, and deduplication.

The current local academic starter is `data/crms_arxiv_cc0_ccby.sqlite`: 1,697
arXiv records across AI, software engineering, language technology,
combinatorics, statistical learning, and physics. All include metadata and
abstracts; 8 papers whose exact versions passed the CC0/CC BY check include
full text. It is merged with the
project source corpus into `data/crms_project_and_arxiv.sqlite`, then packaged
as `data/crms_project_model_academic.sqlite` (2,006 documents; about 7.5 MB of
source text and 0.93 million CRMS word units). At this snapshot, 92 arXiv
records have a recorded license check that did not permit full-text import,
8 eligible papers include full text, and 1,597 records have not yet had their
exact-version license checked. The bounded upgrade sweep advances those
unchecked records in resumable batches. The model retrieves cited papers across
these topics when copied away from both source indexes. These corpus counts describe this
local starter set and do not establish equivalence to an LLM's knowledge.

An expanded portable model is also available as
`data/crms_project_model_academic_expanded.sqlite`. It contains 2,933
searchable documents (2,624 arXiv records plus 309 project sources), 8.85 MB
of extracted source text, and 1.15 million CRMS word units. It adds 927 unique
arXiv records selected from Programming Languages (`cs.PL`), Logic (`math.LO`),
Number Theory (`math.NT`), Computational Complexity (`cs.CC`), and Formal
Languages and Automata Theory (`cs.FL`). Each category was imported from both
the relevance-ranked page and a current `submittedDate` page. Duplicate
versions were deduplicated; on two conflicting IDs, the already-indexed
baseline copy was retained. These additional records contain arXiv metadata
and abstracts only; they do not add paper full text. The model is built as one
portable SQLite file with the extracted corpus embedded. Verify its SQLite
integrity, source-text digests, and memory payloads with:

```sh
python3 crms_package.py inspect data/crms_project_model_academic_expanded.sqlite
```

The chat maps a bounded set of natural topic names to their explicit arXiv
primary-category metadata, so requests such as “Which papers discuss
mathematical logic?” can find `math.LO` records without assuming that the
phrase appears in every title or abstract. The category names and descriptions
follow arXiv's [category taxonomy](https://arxiv.org/category_taxonomy).
`experiments/v1_277_arxiv_category_topic_routes.py` tests these routes through
the packaged model and verifies that recent computational-complexity records
remain searchable.

This expanded corpus materially improves local academic coverage but is still
not equivalent to a 70B-parameter model's available knowledge. Most new
records are abstracts and the added categories are a bounded sample. The
bundle includes empty math and translation memory slots, ready to receive
examples; it does not ship with learned math-operation phrases or translation
frames.
The importer supports recent-source acquisition with `--sort-by submittedDate`
and `--sort-order descending`; relevance paging remains available as the
default. Continue recent topic pages with `--start 100 --max-results 100
--sort-by submittedDate --append`; continue the separate relevance pages with
`--start 200 --max-results 100 --append`. Merge and package commands above
rebuild the portable database. Full-text import still requires the exact-version
CC0/CC BY check. In chat, “What is the latest research in TOPIC?” requires
all topic terms in a dated record, puts papers with all topic terms in the
title or first abstract sentence first, and orders within each relevance group
by the explicit `Published:` date. A newer broad mention can appear separately;
code files are excluded even if they contain a `Published:` string. Metadata-only
results retain their arXiv source link. An immediate “explain
the result” follow-up quotes the same source and states when no verified
paraphrase rule is available. A same-language rewrite frame can be taught from
two or more aligned examples, then applied only when its sentence pattern
matches; copied slots retain their values and mapped slots require an observed
target. A named-paper summary is constrained to a unique title match; ambiguous
titles prompt for clarification. Validate the research routes with
`python3 experiments/v1_264_latest_dated_research.py` and same-language rewrite
learning with `python3 experiments/v1_265_grounded_plain_rewrite.py`.
The diagnostic verifies the learned frame is embedded back into the portable
SQLite model after a chat teaching session.
Validate topical ranking with `python3 experiments/v1_271_latest_topic_relevance.py`.
Follow-ups such as “Why does this method work?” stay bound to the previous
source. CRMS quotes an explicit causal sentence when the source contains one;
procedural descriptions are labeled as such, and missing explanations are
reported without inventing a mechanism. Validate this with
`python3 experiments/v1_272_research_method_followups.py`.

Curated snapshots under `data/curated_sources/` are included by
`crms_build_project_corpus.py` and embedded with their source URL and license
metadata. The Python history seed is taken from the Python 3.12.15
documentation's “History of the software” section. That page states that
Guido van Rossum created Python and identifies the page's PSF License Version
2; see the [official source](https://docs.python.org/3.12/license.html).
This factual assertion lets chat distinguish the answer from parser examples
in the CRMS README. A source-backed “creator” question can use the bounded
agent-noun-to-verb spelling rule to retrieve that sentence; the morphology
only improves retrieval. Bounded `Who VERB OBJECT?` and `What did AGENT VERB?`
questions can realize matching active clauses and explicit-agent passive
sentences, such as `Python was created by Guido` → `Guido created Python`.
Both require the same object/agent and predicate; passive clauses require an
explicit `by` agent. Assertion context is required; examples, direct negatives,
and corrections are rejected. Predicate morphology helps only with spelling; it does not equate
unobserved synonyms such as “invent” and “create.” The answer retains its source
citation; asking “why?” or “show source” reveals the exact source wording and
citation. It is not stored as an accepted fact. Validate this path with
`python3 experiments/v1_266_large_corpus_chat_followups.py`. This is one
curated source, not broad computing coverage.

Large-corpus chat probes also found that yes/no questions could retrieve
matching examples from code and that ordinal paper references could drift to
lexical matches such as “second quantization.” Natural questions now require
at least two of their content terms in the same source sentence (unless a
licensed predicate-focus term is the evidence). Factual wh and yes/no
questions exclude example-only matches; explicit requests for examples can
still retrieve them. Yes/no questions prefer prose. Immediately after a
latest-research list, “the second paper” resolves to that list and summarizes
the selected paper. A request for what listed papers agree on now states that
CRMS has not established a comparison instead of searching unrelated sources.
Run `python3 experiments/v1_266_large_corpus_chat_followups.py` to drive these
cases against a scratch copy of the 2,006-document portable model. It also
checks acronym identity and definition questions against the local corpus. The probe
does not establish broad paraphrase coverage, full-text research coverage, or
reliable cross-paper synthesis.

Direct paper-list questions such as “Which papers discuss TOPIC?” now have a
separate route from single-answer fact retrieval. The route separates title
matches from related term matches, shows the topic-term coverage and one
supporting abstract sentence for each result, and abstains when a candidate
shares too few topic terms. It remains lexical topic matching rather than a
claim that CRMS has semantically compared the papers. The ordered list remains
available for the next-turn “What does the second paper say?” follow-up.
Validate these routes with `python3 experiments/v1_269_topic_paper_lists.py`.
Explicit “difference between X and Y” questions use a separate evidence check:
CRMS quotes only a source sentence that contains both concepts and an explicit
contrast marker. When the source merely co-mentions them, CRMS says the
difference is not established by that evidence. This bounded route does not
combine definitions across multiple sources. Validate with
`python3 experiments/v1_270_source_grounded_comparisons.py`.

The local JATS importer is implemented in `crms_import_jats.py`; it accepts
explicitly eligible CC0 and CC BY article XML and carries attribution and
license evidence into indexed text. Its runtime diagnostic is
`experiments/v1_237_jats_academic_import.py`. The PMC adapter is implemented
in `crms_import_pmc.py`, with offline API, license, version, checksum,
freshness-notice, source-grounded fact-frame learning, reviewed acceptance,
and citation-backed QA coverage in `experiments/v1_238_pmc_dataset_import.py`. It
follows the current [PMC AWS dataset documentation](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/)
and [dataset README](https://pmc-oa-opendata.s3.amazonaws.com/README.txt).
arXiv full-text import is available only as a bounded, explicit opt-in; broad
bulk synchronization and automatic updates remain future work.

Each future adapter needs bounded acquisition, deduplication across versions and
copies, explicit license allow/deny handling, source provenance, and resumable
indexing. Evaluation should measure exact citation recovery, version/duplicate
handling, license-gate correctness, and whether source passages actually
improve answers on held-out research questions. CRMS does not currently provide
continuous academic-platform synchronization, a general license classifier,
or broad academic-corpus synchronization.

## Composition diagnostic

The historical `experiments/v1_3_diagnostic.py` exercises the earlier VSA
prototype. For the current symbolic model, run
`python3 experiments/v1_9_symbolic_composition_diagnostic.py`. It grounds
six operations from examples, retrieves an unseen phrase assembled from
positionally supported word substitutions, and measures component retrieval
and explicit `, then ` composition over 200 deterministic synthetic trials.

The current diagnostic completed with `p1=1.000`, `p2_marginal=1.000`,
`p2|p1=1.000`, `strict_path=1.000`, `composed_final=1.000`, and
`compose_matches_direct=1.000`. This only establishes behavior for the six
chosen operations, aligned phrase patterns, and generated integer lists. It
does not measure open-ended language understanding or broad paraphrase
coverage.

`python3 experiments/v1_10_language_retrieval_diagnostic.py` checks those
controlled contrasts and verifies that abstentions identify an unknown token
or weak adjacent pair when that is the missing language evidence. Its initial
run found that a reordered phrase could be
accepted from familiar tokens despite its unseen word pairs. Lexical transfer
now abstains on an ungrounded adjacent pair; independently supported aligned
position substitutions remain available.
The updated diagnostic reports five of five expected outcomes, including
successful aligned recombination, retrieval after omitting a grounded filler
word, and abstention on the reordered phrase.
It also enumerates all two-or-more-token in-order omissions from the six
grounded phrases: the model got all 10 uniquely supported omissions right
across three input lists and abstained on both ambiguous fragments.
It also abstained on all 30 non-exact permutations of those phrases and five
queries with added words that were familiar from other learned cases. A final
acquisition probe verifies that the invented token `zorb` is unknown before
examples, then transfers to a new phrase after the teacher grounds it to
reversal, and becomes unknown again after that supporting phrase is forgotten.

`python3 experiments/v1_11_rule_discovery_diagnostic.py` checks example-based
rule discovery. The current model learned `sort_ascending` followed by `first`
from demonstrations for returning the smallest value, then passed a held-out
input. One sorted example remained ambiguous between reversal and descending
sort; an asymmetric contrast resolved it to reversal. It also discovers the
repeat-count-two behavior from input/output examples; length-three examples
initially alias rotations by three places, and the requested contrast resolves
the ambiguity before it generalizes to a held-out list and survives save/load.
The inferred procedure uses `repeat_each_k(k=2)`, behaviorally equivalent to
the legacy `duplicate_each` encoding.
This is bounded search over an explicit operation library, not unrestricted
program synthesis.
Contrastive probes now also include
constants from candidate parameters: the search distinguishes “multiples of 3”
from “multiples of 6” with input `[-3]`, which the former keeps and the latter
rejects. Probe search remains bounded to lists of at most three values. The
diagnostic also confirms that learned language evidence can narrow an
ambiguous one-example rule search, while contradictory examples prevent the
language prior from forcing a procedure. `LearnResult.evidence_phrases` reports
the cases that supported this narrowing.

`python3 experiments/v1_12_primitive_discovery_diagnostic.py` checks all 61
default one-step candidate steps and parameter values using four varied
demonstrations each, including duplicates and non-extreme first values. The
current run inferred all 61 uniquely and matched their behavior on three
held-out lists, including the empty list. This bounded
diagnostic does not establish discovery outside the configured space.
`experiments/v1_74_relational_filter_discovery.py` additionally checks that
two examples uniquely teach each relational filter and that learned procedures
generalize to held-out positive, negative, mixed, and empty lists.

`python3 experiments/v1_24_rotation_rule_discovery.py` adds a parameterized
cyclic-rotation primitive. One example leaves offsets aliased and elicits a
separating probe; the teacher answer identifies the offset and generalizes to
held-out list lengths. Two grounded numeric phrase values transfer the rule to
a third offset. The diagnostic also checks persistence and the boundary where
rotation followed by filtering needs a conservative syntax key.

`python3 experiments/v1_25_parameterized_numeric_guard.py` checks transfer to
a new in-range repetition count, transfer through a number word grounded by an
equivalent digit phrase, abstention when an ungrounded word occupies a numeric
slot, rejection of an out-of-range count, and transfer after save/load. All
five checks passed in the current run.

`python3 experiments/v1_27_input_relative_rules.py` checks discovery of
input-relative addition and subtraction, held-out lists, empty-list behavior,
composition with reversal, modular filtering, and persistence. It verifies
that exact affine and repetition equivalences, filter order, and redundant
filters do not leave the learner stuck with duplicate candidate programs. All
checks pass. The semantic canonicalizer exactly merges affine input-relative
arithmetic and uniform repetition, and handles modular filters when the first
element reference remains stable. Interactions with rotations and endpoint
selection still use syntax keys unless exact equivalence is otherwise known.

`python3 experiments/v1_28_ambiguous_composition_resolution.py` checks a short
contrastive probe against a longer rotation probe, direct discovery of a
scaled endpoint, and iterative reduction of an always-empty rule's candidate
set. When bounded probes no longer separate the remaining programs, CRMS
keeps the rule uncommitted and abstains on held-out inputs rather than treating
finite observations as proof of a constant-empty behavior.

`python3 experiments/v1_13_composed_rule_discovery_diagnostic.py` checks two-
and three-step rule synthesis. It learns minimum selection, shift-then-filter,
and shift/filter/first-selection from demonstrations, then verifies each on
three held-out lists. For the last task, it returns an equivalent canonical
program (`keep_odds`, `first`, `add_k(1)`) instead of the teacher-side
sequence; outputs match on all probes. This tests representative compositions,
not every program in the search space.

`python3 experiments/v1_14_generated_composition_sweep.py` samples 40 distinct
two- and three-step programs that pass the bounded composition gates, supplies
contrastive examples requested by the learner, and checks semantic equivalence
plus held-out behavior. Each trial now has an independent deterministic random
stream for its demonstrations and held-out inputs, so resolving one trial
cannot change the data seen by later trials. The new seed-73 baseline
generalized 35/40 programs within the 40-example cap, using 111 contrastive
examples; 5 programs remained unresolved. This is a bounded, seeded sample,
not exhaustive validation, and its result is not directly comparable to prior
runs that shared a random stream across trials.

The exact semantic normalizations include sign removal around `square_values`
(`abs(x)^2 = x^2` and `(-x)^2 = x^2`), stable-deduplication identities
(`stable_unique` is idempotent and erases uniform repetition immediately
before it), constant translations across positional selectors, and rotation
combination around absolute value. Divisibility filters after a pure scale
reduce to their exact input preimage using the gcd of the scale factor and
filter modulus; redundant filters disappear when every scaled value passes.
The square/divisibility rewrite derives the
exact input preimage (`m | x²` iff the derived modulus divides `x`); for
example, filtering squares by 16 matches filtering inputs by 4, while filtering
inputs by 4 does not match filtering squares by 4. A pre-square filter and a
post-square filter now reduce to the LCM of their input constraints. This
resolved the square/filter case in the independent seed-73 baseline after four
examples.
When a remaining candidate differs only by `stable_unique` after a positional
selector, contrastive search now builds a list with duplicate values at two
selected positions. This identified the stride-six deduplication ambiguity in
the independent baseline. Sum normalization now also crosses order-only
operations and removes redundant sums on guaranteed nonempty singletons, while
preserving empty-input behavior when a prior selector or filter may remove the
item. Scale/filter canonicalization also resolved one generated composition;
together these changes raised coverage to 35/40. Adjacent inverse rotations now
cancel even before a positional filter; this shrank one unresolved trial's
candidate set from three to two but did not resolve it within the example cap.
An earlier run falsely committed one mixed value/position rule; the current
bounded fallback keeps competing rules in the candidate set and causes
abstention.
More mixed operation families still need a representation that preserves
ambiguity without making unrelated searches exceed their work limits.
Focused probes now account for the number of values surviving candidate
filters, so rotation offsets are tested past their aliasing period. Exact
canonicalization also merges cyclic endpoint selections with `first`/`last`,
and redundant filters no longer trigger a fallback.
`python3 experiments/v1_47_empty_filter_composition.py` checks the always-empty
proof against exhaustive lists through length four over values `-5..5`, 500
seeded lists, and a concrete nonempty counterexample. It also checks that
all-empty examples remain uncommitted when the version space is still broad,
that a long contrastive probe reduces the candidate set, that empty input is
tested as a contrastive case, and that scalar no-op operations canonicalize
without erasing the distinct empty-sum behavior.
`python3 experiments/v1_48_rotated_add_first_canonicalization.py` checks exact
equivalence for affine translations around a rotation and `add_first`, while
keeping different anchor positions and offsets distinct. It exhaustively
compares the formerly ambiguous candidate family on lists through length five,
checks 500 seeded lists, and verifies both depth-three and depth-four teaching
plus held-out predictions. A separate one-expansion-budget case confirms that
an incomplete search still abstains without committing a partial fit.
`python3 experiments/v1_114_filtered_extreme_canonicalization.py` checks an
exact normal form for modular filters followed by sorted minimum/maximum
selection, endpoint deletion, repeated runs, and affine output maps. It checks
these rewrites against exhaustive short lists and keeps order-sensitive
controls distinct. `v1_115_length_reachability_pruning.py` checks the search's
over-approximate length bound against all one/two-step paths from representative
lists and 2,500 sampled three-step paths.
`v1_118_semantic_key_collision_audit.py` compares programs that share a
canonical key across depths one through three on 111 short and seeded inputs.
It checked 179,767 same-key collisions and includes regressions for
order-sensitive deduplication and endpoint selection after repetition, plus
exact affine-run normalization inside conservative sequence-sensitive keys
and canonicalization of exact rotation/endpoint-deletion aliases.
The current runtime checked 225,566 same-key collisions with no counterexample;
this remains a broad diagnostic, not a proof for arbitrary-depth programs or
every integer list.

Contrastive probes compare output partitions, prefer a balanced split,
include values from candidate parameters and combined filter periods, and cap
their candidate-evaluation work. For structured filter or rotation candidates,
when the best short probe leaves more than 80% of candidates in one output
class, the learner spends reserved work on period-covering and seeded mixed-
value lists to seek a more useful question. The bounded search can still
return a somewhat skewed split on a large candidate set; every probe must
include the teacher's behavior, and remaining candidates stay uncommitted
unless evidence identifies one behavior. These probes improve separation but
do not prove that remaining candidates behave the same outside the tested
domain.

### ABS-inspired abstraction research direction

CRMS's current primitive discovery is narrower than case-level abstraction:
`propose_primitive_candidates()` learns bounded numeric window operations from
complete no-fit clusters. It does not generalize over the structure of
successful procedures, store abstractions as retrievable cases, or build
hierarchies of abstractions. The proposed ABS comparison is useful as a
direction, while preserving CRMS's stricter evidence gates rather than copying
plausibility-based generalization.

Prioritize this work in stages:

1. **Measure recurring successful structure.** Analyze `_procedures` for
   repeated, aligned operation sequences and propose report-only scaffolds.
   Keep phrase associations and behavioral procedures intact; only generalize
   when an explicit alignment is available. `propose_procedure_scaffolds()`
   now identifies repeated multi-step operation/key structures with varying
   numeric slots and reserves one phrase by a stable SHA-256 ordering as a
   structural holdout; training phrases stay in stable lexical order.
   `python3 experiments/v1_194_success_procedure_scaffolds.py` checks a varying
   `add_k` + `reverse` scaffold, persistence, constant-slot and corrupted-holdout
   negative controls, the `/procedure-scaffolds` review command, and that
   inspection does not change rules or predictions. The command reports support,
   its structural holdout, parameter values, and description-length gain; it
   does not promote scaffolds. The proposal must shorten a two-part Elias-gamma
   code for the learned procedure records, factoring one shared operation
   scaffold plus phrase associations and varying parameter values. Phrase
   labels and demonstrations are common to both encodings and excluded, so this
   is a preliminary procedure-code comparison, not whole-memory compression.
   It instantiates the proposed scaffold using training constants and held-out
   slot values, then reconstructs every held-out demonstration. Transfer and
   retrieval evidence is measured in the following diagnostics. Each proposal
   has a deterministic versioned artifact ID derived from its descriptor,
   split and validation policy, code lengths, and SHA-256 fingerprints of source phrases,
   learned procedures, and demonstrations. `/explain-rule` shows that ID for a
   positional recombination. The ID is recomputed from current evidence; it is
   not a persisted or user-accepted artifact yet. `retrieve_procedure_scaffold(artifact_id)`
   resolves only an exact ID among proposals regenerated from current evidence;
   after a contributing phrase changes or is forgotten, the old ID no longer
   resolves. This is derived retrieval, not a persisted artifact store.
   `v1_194` checks that adding a demonstration to an existing source phrase
   changes the artifact ID and makes the old ID unresolvable, as does forgetting
   a contributing phrase.
   `_retrieve_parameterized_procedure()`
   may combine evidence across distinct taught numeric surface frames when the
   learned procedures share an operation scaffold and all examples agree on one
   varying numeric-slot mapping. The `v1_195` diagnostic checks transfer to a
   new parameter value, independent phrase evidence, conflicting slot mappings,
   and a constant-parameter abstention control. A further route can construct a
   same-length phrase frame not taught verbatim only when its shared scaffold
   also passes the MDL and held-out reconstruction gates above, provided its
   words are supported at their corresponding positions in the scaffold
   evidence.
   `python3 experiments/v1_196_success_scaffold_language_composition.py` checks
   all eight combinations of two taught action words, two quantifiers, and two
   item words, parameter transfer,
   unsupported-word and reordering controls, persistence, and a two-slot
   `add_k`/`keep_multiples_k` composition where each number binds to a distinct
   parameter, and confirms novel-frame transfer abstains when the scaffold
   gate is unavailable. This is bounded positional analogy over learned phrase roles,
   not open-vocabulary synonym recognition, arbitrary sentence parsing, or
   broad language understanding.
   The inference-time scaffold gate currently keys a validated scaffold by
   both its operation signature and the exact set of supporting source
   phrases. It therefore licenses transfer within an already validated group;
   it does not yet establish that the same abstraction transfers to a new
   combination of source phrases. Keep this boundary explicit in claims and
   diagnostics. A later generalization step should validate on an independent
   source-phrase group, report the phrase-to-scaffold association evidence
   separately from the scaffold's MDL and behavioral holdout evidence, and
   abstain when either component is unsupported. In primitive learning,
   contrastive probes labeled by an accepted primitive are mechanical
   supervision for phrase synthesis, not independent evidence that discovered
   the primitive or independently validated the phrase association; preserve
   that provenance distinction in reports and artifact records.
2. **Persist abstractions only after defining lifecycle semantics.** The
   proposal now has a typed descriptor, versioned identity, source fingerprints,
   and MDL/holdout validation record, and current-evidence retrieval by ID.
   Persisted artifact format, user acceptance, and any durable stale-source
   policy still need design before adding an `_abstractions` store. A primitive
   descriptor is a grammar extension, not a case; a procedure is an evidenced
   phrase rule. MDL and reconstruction are evidence gates, not an independent
   verifier for arbitrary conclusions.
3. **Explore composition only after stage 1 and 2 evaluate well.** Composed
   abstractions must reference accepted lower-level artifacts, stay within
   explicit depth and search limits, and pass independent reconstruction and
   held-out checks. Keep proposals advisory until explicitly reviewed.

Frame abstraction over fact patterns is a separate candidate: the existing
licensed-frame transfer already requires varied subjects and objects, but a
stored sentence schema would need its own artifact and validation contract.
Do not combine it with procedure abstraction until each has a concrete task
and separate evaluation. These are roadmap items, not implemented capabilities.

## Discovery research directions

The current development priority is to make the existing bounded synthesis
reliable. The generated sweep now covers the concrete rotation/filter/selection
aliasing cases found so far; continue measuring broader examples before adding
another discovery layer.

The bounded learner now also reports exact, simple parameterized candidates
when examples fit a translation, scale, repetition count, divisibility
modulus, or rotation just outside its configured range. Rotation proposals
search only a bounded neighborhood and preserve periodic alternatives that fit
the demonstrations. Modulus proposals require nonzero retained values and at
least one filtered input value, then search a bounded interval above the
configured limit. These appear only on `no_fit` results, remain uncommitted,
and do not identify the intended rule: small samples can support multiple
explanations. `experiments/v1_26_out_of_range_proposals.py` checks exactness,
rotation periodicity, modulus evidence gates, ambiguity, contradictions,
in-range behavior, and that proposals never enter learned memory. This is a
narrow boundary signal, not a general primitive-discovery mechanism. When a
small proposal set contains behaviorally distinct candidates, CRMS now chooses
a bounded contrastive input and records the teacher's response against that
pending probe, including across a chat restart. The response filters the next
proposal set but cannot commit an out-of-range procedure. `v1_49` checks this
feedback route end to end.

The next broader step is to improve **expression discovery over clustered
`no_fit` demonstrations** and evaluate it on naturally accumulated records.
`experiments/v1_178_failure_cluster_expression_discovery.py` is a report-only
diagnostic over a bounded local expression grammar for two- and three-value
windows, using arithmetic trees and unary absolute value. It requires support
from multiple instruction clusters, validates
held-out examples, excludes one-step pair rules already in the active grammar,
and checks an unrelated negative control. On its synthetic fixture it recovers
`output[i] = x*x + y` from three phrases, gains 406 training bits after a fixed
primitive cost, and validates three held-out examples. Its signed input pattern
includes a zero-left/negative-right case to reject an absolute-value variant.
The diagnostic accepts saved CRMS memories with
`--memory PATH`; without that option it uses a deterministic fixture.
`CRMSModel.propose_primitive_candidates()` includes these expression proposals.
The same fixture currently yields one distinct validated expression schema,
so `propose_shared_expression_subtrees()` reports no reusable subtree grammar;
`v1_178` now checks this negative result at runtime. The separate `v1_197`
constructed pair demonstrates only that positive subtree MDL accounting can
work when repetition exists, not that the current failure clusters justify
another abstraction.
`experiments/v1_224_expression_discovery_near_miss.py` adds an opposing-formula
control: two phrase clusters agree on zero-right training examples but encode
`x*x+y` and `x*x-y`; a varied held-out input separates them, and no shared
expression proposal is admitted. Its positive control reruns the original
three-cluster recovery fixture. This is a targeted false-acceptance check, not
a broad estimate of proposal precision on naturally accumulated failures.
After explicit acceptance, `map_window_expression` enters the bounded search
grammar; ordinary demonstrations then ground each phrase-to-procedure rule.
`experiments/v1_179_expression_primitive_learning.py` uses signed examples,
including zero-left/negative-right windows that distinguish the target from
absolute-value variants. It verifies discovery,
acceptance, synthesis for three phrases, prediction, persistence, and the
revocation guard. It also recombines two independently contrasted phrase slots
to apply the expression to an unseen instruction, with the contributing
phrases and learned template exposed. This is evidence for grounded phrase
transfer in the tested frame, not open-vocabulary synonym understanding. The
result remains generated-data evidence, not general
anti-unification or evidence of discovery from natural failure traffic. The
MDL cost is preliminary and needs calibration against the full active library.
`experiments/v1_180_ternary_expression_discovery.py` additionally recovers
`output[i] = x*x + z` over width-three windows from three independent failure
clusters, validates held-out data, synthesizes the procedure, and reloads the
accepted schema. `experiments/v1_181_expression_grammar_coverage.py` sweeps five
tree shapes over width-two and width-three windows using 15 independently
worded synthetic phrase clusters. All five were uniquely recovered, and
corrupting every phrase's held-out output rejected each proposal. This extends
the measured bounded arithmetic grammar; it does not establish discovery
beyond the tested expression space. The proposer uses the numeric examples,
not the phrase text, to identify arithmetic structure.
`experiments/v1_182_expression_composition.py` uses the same sign-sensitive
expression evidence and confirms a discovered two-position expression can
participate in depth-two synthesis with an
existing operation: CRMS learned `map_window_expression` followed by `reverse`,
executed the result, persisted it, and guarded against revoking its dependency.
The expression is accepted before composition; the composed procedure is
learned through the ordinary bounded synthesizer.
`experiments/v1_183_absolute_expression_discovery.py` adds unary absolute
value to the expression search and runtime representation. It uniquely
recovers `abs(x-y)` from three instruction clusters, rejects corrupted
holdouts, and validates acceptance, procedure synthesis, persistence, and the
dependency guard. The proposal grammar applies exact symmetry/idempotence
canonicalization for absolute differences; more general expression
equivalence remains unsupported.

`CRMSModel.no_fit_cases()` now exposes a bounded archive of the latest 100
complete no-fit searches. It stores the failed instruction, its retained
demonstrations, a content-hashed training/holdout index split when enough
examples exist, the candidate-space signature, and the search bounds that were
tried; records persist with memory and are removed when the phrase is corrected
or forgotten. Primitive proposal search ignores records whose signature does
not match the active grammar, while retaining them for inspection. The fixed
split selects its holdout by SHA-256 of the input/output pair, independent of
demonstration order; old memories with last-example splits are migrated on
load. Reordering demonstrations preserves the proposal; a corrupted holdout is
a negative control. This is a failure index over existing examples, not a record
of incomplete searches or ambiguous version spaces.
`CRMSModel.propose_primitive_candidates()` applies a bounded, report-only
proposal search implemented in `crms_primitive_discovery.py`. It enumerates
binary operations (addition, subtraction, multiplication, minimum, maximum,
and modulo) over two- or three-value windows with bounded offsets and strides,
using the archived split and a two-part training-data description-
length gate. Training examples alone determine the candidate cluster and MDL
score; every held-out example for that cluster must validate before a proposal
is reported. A corrupted holdout rejects the candidate. Candidate-specific
clustering allows unrelated no-fit records to remain in the archive without
suppressing a proposal. `experiments/v1_174_no_fit_primitive_discovery.py`
uses three independently worded synthetic failures to propose an overlapping
adjacent-addition schema while excluding an unrelated append-reverse failure.
The proposal predicts held-out examples for all three phrases and reduces
training description length from 1,467 to 1,043 bits under Elias gamma coding.
Its versioned artifact ID fingerprints the supporting source clusters,
split policy, descriptor, and MDL record. `retrieve_primitive_proposal(id)`
recomputes proposals from current evidence; forgotten or changed sources make
the old ID unresolvable. The CLI displays the ID for review, and ordinary CRMS
conversation supports `Show primitive proposals` and `Accept primitive
proposal ID`. After acceptance, `Try to learn the rule for INSTRUCTION` reruns
that phrase's stored examples against the extended grammar. Acceptance still
requires the exact versioned ID and recomputes validation against current
evidence. The corresponding
training JSON representation falls from 497 to 460 bytes,
but byte size is reported only as a secondary storage comparison. Separate
synthetic clusters also validate non-overlapping pair sums and overlapping
neighbor products on held-out data, checking both stride and operator choice.
Modulo uses Python's exact integer remainder semantics for negative operands;
zero-divisor cases cannot validate a proposal. The new
`experiments/v1_223_modulo_primitive_discovery.py` diagnostic generates an
out-of-grammar target from three distinct phrases, validates it on held-out
examples, learns it transactionally, checks standalone Python parity and
zero-divisor behavior, and reloads the accepted primitive.
All proposals remain advisory until explicitly accepted; proposal generation
does not affect predictions. `CRMSModel.accept_primitive_candidate(descriptor)`
recomputes current proposals, requires the selected descriptor to pass the
training MDL and held-out gates, and adds one instance to that model's bounded
search grammar. Prefer `/accept-primitive ID` to accept the exact reviewed
artifact; the legacy numeric form remains available for the current proposal
list. ID-based acceptance revalidates the artifact against live evidence before
changing the grammar. The complete accepted proposal, including its content ID and
source fingerprints, is persisted beside the descriptor; lineage remains
historical if source examples are later forgotten. The
`/accepted-primitive-artifacts` view reports whether exact source examples are
still present and identifies changed or missing phrases; it does not revoke an
accepted schema. Older memories with accepted descriptors but no artifact
remain loadable. `retry(instruction)` can then synthesize a phrase-specific
procedure from its retained demonstrations. Accepted schemas and learned
procedures persist, while semantic canonicalization treats compositions with
the new operation conservatively by syntax. `experiments/v1_177_accepted_primitive_learning.py`
checks explicit acceptance and conversational rule synthesis for addition and multiplication,
prediction, save/reload, and the actual chat CLI command sequence. It also
learns four aligned instruction frames and correctly predicts the never-taught
combination `sum adjacent values` from repeated slot evidence. That transfer
uses only words grounded by examples; it is not open-vocabulary synonym
understanding. A depth-two search check covers the CLI's default: identity
aliases are collapsed, a distinct competing behavior triggers a contrastive
probe, and the teacher's answer resolves the rule to the accepted primitive.
This is a manual opt-in path; proposal generation never
promotes rules on its own. The chat CLI exposes the flow with
`/primitive-proposals`, `/accept-primitive ID|N`,
`/accepted-primitives`, `/revoke-primitive N`, and `/retry-rule INSTRUCTION`.
Revocation is refused while a committed phrase rule depends on the primitive;
stored examples remain available after removal. The runtime diagnostic checks
both the dependency guard and rollback before rule synthesis. These diagnostics
cover bounded binary-window and local arithmetic-expression grammars, not
general primitive discovery.
`experiments/v1_176_primitive_discovery_grammar_coverage.py`
generates a deterministic sweep of 13 schemas spanning all five operators,
two window widths, offset orientation, and overlapping/non-overlapping stride.
The proposer recovered exactly those 13 schemas, with no extras, from 39
human-authored English phrase clusters and 468 generated examples under both
Elias gamma and delta coding. A separate negative control with three
independently worded clusters for the unsupported append-reversed-list
transformation produced no proposal under either code. This measures recovery
and abstention on generated data inside and outside the declared grammar; it
does not establish natural-language interpretation or generalization to real
demonstrations. The proposal search
does not use phrase text to identify the operator; language-to-rule grounding
from phrase meaning remains untested by this sweep. The code length
encodes the primitive family, operator, width, offsets, and stride with
fixed-width fields; phrases as UTF-8 strings with a gamma-coded byte count;
and list lengths and signed integers
with Elias gamma codes after zigzag mapping. It compares literal training
input/output pairs with the shared schema plus training inputs. Held-out pairs
are excluded from cluster formation and scoring; they only validate predicted
outputs. This is an explicit MDL objective for this encoding, while its values
remain code-dependent. The diagnostic also reruns the adjacent-sum cluster under Elias
delta coding: it selects the same schema and gains 491 bits. That is an initial
sensitivity check over two universal codes, not broad robustness evidence.
Independent naturalistic corpora and an acceptance gate that charges ongoing
grammar complexity and measures held-out utility are still needed before
promoting a proposal. Primitive proposals now also report the unpruned
syntactic sequence-count upper bound before and after adding one step choice
through the configured composition depth. This exposes the combinatorial
trade-off during review; semantic pruning, equivalence collapsing, data-shaped
search work, and the hard expansion limit mean the count is not a runtime
prediction or a substitute for measuring actual learner behavior.

**Version-space search** is already present in a bounded form: `_infer`
maintains the procedures consistent with examples, and `_contrastive_probe`
chooses an input that separates their predicted outputs. Generalizing this to
proposed primitives is a plausible later step, after the current probe
limitations are addressed.

**Equational rewriting** could simplify or derive equivalent programs from a
small, explicitly validated set of operation laws. Completion algorithms do
not in general guarantee termination or confluence, and derived equalities do
not by themselves invent behavior beyond the existing operations. Any future
rewrite system should therefore be bounded and retain exact semantic checks.
Abstract interpretation/type constraints may help if CRMS later introduces
families of operations; relational grammars and coinduction are out of scope
until the data model includes relational or recursive structures. Category,
operad, sheaf, and renormalization theories may be useful vocabulary, but do
not currently provide a concrete implementation advantage for this list
transformation model.

**AST-based discovery and canonicalization** is a research direction, not a
drop-in replacement for the current `Step` sequence. The expression proposer
already represents local arithmetic expressions as bounded trees. Complete
procedures, however, are currently pipelines of unary list transformations;
their sequence structure is meaningful and a general AST would add little
until operations accept nested procedures or branching arguments. A useful
next AST experiment would operate report-only on those local expression trees
or proof trees: mine repeated typed subtrees, charge the shared grammar and
residuals in MDL, validate against held-out cases, and keep the current exact
semantic key as an oracle during evaluation. Procedure rewriting, recursive
tree grammars, and proof-subtree reuse should follow only when a concrete task
needs those structures. This preserves the existing holdout and bounded-search
discipline while avoiding a representation refactor for hierarchy CRMS does not
yet express.

`propose_shared_expression_subtrees()` is the first bounded diagnostic for
that direction. It analyzes only distinct expression proposals that already
passed their own held-out and MDL gates, treats window width as part of the
subtree type, and reports a one-subtree grammar only when its fixed-width
definition-and-reference code is shorter than encoding the expressions
independently. It is report-only and does not alter the operation grammar.
`python3 experiments/v1_197_expression_subtree_grammar.py` checks a controlled
pair with a repeated subtree, a positive 2-bit saving under this diagnostic
code, support and holdout gates, width separation, malformed input rejection,
and immutability. This establishes the accounting path on a constructed
example; it does not show that real proposal corpora contain useful shared
subtrees or that the diagnostic code matches deployed storage costs. Those
measurements are prerequisites before considering subtree abstraction as a
learning feature.

**Lossless compression diagnostics** are a promising, lower-risk experiment
before adding a new discovery mechanism. Measure storage reduction in distinct
stages: duplicate case removal; grouping cases by their exact instruction,
input, and output; grouping behaviorally equivalent procedures where the
semantic canonicalizer proves equivalence; and factoring shared procedure or
instruction structure while retaining a residual that reconstructs every
original record. Verify each encoding by decoding it and comparing the
reconstructed records exactly. Report compression ratio and residual cases;
do not treat the residual as a set of new primitives without a separate
proposal and evaluation step.

This is a diagnostic of structure in the observed store, not a guarantee of
generalization. Exact reconstruction proves only that the encoding preserves
the encoded observations. `_semantic_key` recognizes selected exact
equivalences and deliberately falls back to syntax for interactions it cannot
prove; it is not a complete decision procedure for semantic equivalence.
Likewise, grammar compression of instruction text can suggest recurring
language patterns, but it does not establish that a phrase maps to a
particular operation. Procedure entropy coding is a storage optimization, not
rule discovery. MDL can rank candidate explanations when paired with held-out
evaluation, but shortest encoding alone is not evidence that a candidate
generalizes. Compression-derived procedure grammars or meta-operations can be
considered later, with bounded search and exact behavior checks.

`python3 experiments/v1_46_lossless_rule_compression.py` now measures these
stages on a small learned corpus and decodes each representation back to exact
examples, instruction text, and procedure mappings. In the current run,
deduplicating repeated cases reduced the compact JSON bundle from 985 to 852
bytes; grouping by instruction raised it to 892 bytes, while semantic
procedure sharing reduced the grouped representation to 873 bytes. Factoring
instruction token sequences expanded this small corpus to 953 bytes, so the
diagnostic rejects any assumption that an apparent shared phrase is already a
useful compression. The semantic grouping also checks held-out list probes;
the corpus remains illustrative, not a general compression benchmark.

`python3 experiments/v1_15_learned_optional_word_diagnostic.py` checks whether
deletion of a token learned from multiple grounded phrase pairs can combine
with separately grounded word substitutions. It verifies the unseen
`"turn values"` transfer, confirms an unknown modifier still causes
abstention, checks that one deletion pair is insufficient, confirms forgetting
a supporting case removes the transfer, and checks that competing grounded
rules remain ambiguous. The learned pattern also reconstructs after a memory
save/load cycle. This validates that controlled pattern only; it does not
establish open-ended parsing.

`python3 experiments/v1_18_optional_span_diagnostic.py` checks the same
mechanism for a two-token span. It transfers from examples pairing
`"reverse all the values"` with `"reverse values"` and
`"reverse all the entries"` with `"reverse entries"`, then composes the
learned omission with `"turn all the values"` to answer the unseen phrase
“turn entries”. Unknown modifiers and a single supporting deletion pair still
cause abstention. A competing grounded rule also makes the model abstain. This
covers contiguous span omission at a tested position; it does not establish
broad parsing.

`python3 experiments/v1_19_retrieval_scaling_diagnostic.py` checks exact parity
for packed encoding and similarity, then measures cold and warm VSA retrieval
over 100 to 50,000 synthetic phrases. In the recorded 50,000-phrase run, a
common-token query took 687 ms cold and 116 ms warm. A multiword query built
from common vocabulary took 2.8 ms warm, while a query with a unique word took
about 0.01 ms warm after index creation. Cold timings include lazy index
creation, and all queries selected the grounded procedure. The diagnostic also
checks a dense-posting case where intersecting common token postings retains
the grounded candidate. The results show the unigram index's selectivity
limit; this microbenchmark does not establish million-case throughput.

`python3 experiments/v1_20_parallel_retrieval_diagnostic.py` compares serial
packed-vector scoring with two- and four-process shard scoring over 50,000
cases. The serial score pass took 38 ms; a reused four-worker pool took 74 ms,
including shard transfer. This workload does not benefit from process sharding,
so CRMS keeps retrieval serial pending evidence of a larger workload where
transfer costs amortize.

`python3 experiments/v1_21_learned_sequence_connective.py` grounds component
instructions and two distinct compound instruction patterns using “and then”.
It composes new combinations of grounded rules, including a paraphrased
component and parses up to four query spans at a time; a span may itself be a
previously taught compound, allowing longer grounded chains. Every span must
independently retrieve a grounded procedure. It checks evidence attribution,
save/load, and abstention with one connective context, an unsupported
connective, or an unknown component. This is a bounded learned sequence
operator, not a general parser. The “add one” examples include a negative
output that separates the intended rule from the equally fitting “add one,
then absolute value” alternative. Magnitude sort followed by a numeric sort
now canonicalizes to the numeric sort, since the later total sort discards
the earlier ordering.

`python3 experiments/v1_230_composition_route_conflict.py` checks that a
successful learned sequence composition is compared with independent retrieval
routes before dispatch. Its fixture has a valid sort-then-add composition and
a separate positional analogy that supports reversal for the same phrase.
CRMS now asks for an example and includes both routes' provenance and a
contrastive input instead of silently returning the composition. Five input
shapes verify the disagreement; this covers a concrete route pair, not every
possible composition conflict.

The explicit `, then` route is checked separately by
`python3 experiments/v1_231_explicit_composition_route_conflict.py`. Its
component rules support sort-then-add while a full-phrase positional frame
supports reversal. The explicit syntax now enters the common route comparison;
CRMS asks for an example on five input shapes instead of returning the
component composition unchecked. Together, `v1_230` and `v1_231` cover the two
composition entry paths while broader route-pair coverage remains open.
Clarification results also retain candidate procedures and route-specific
supporting phrases. `/apply-rule` and `/explain-rule` show these alternatives
and pair each procedure with its predicted output on the contrastive input, so
a teacher can inspect which learned rules disagree before providing an output.

`python3 experiments/v1_173_retrieval_route_ablation.py` compares 320 fixed
held-out phrase/input pairs across seven transfer routes with and without the
attributed route: numeric parameter, aligned phrase, contrastive slot,
positional analogy, lexical features, VSA fallback, and learned composition.
Each route uses deterministic varied lists, including empty and singleton
inputs; every baseline prediction is checked for correctness and route
attribution before ablation. Numeric transfer now covers repetition, addition,
and rotation parameter families. Disabling the selected route makes 304/320
predictions fail. For lexical features, VSA recovers 16/32 cases; 16 depend on
lexical evidence assembled across phrases that no single VSA candidate covers.
Exact phrase memory is checked separately by forgetting its teaching
association. The route-specific training fixtures are controlled and the
inputs are generated, so this is broader input coverage but still not an
ablation across the complete experiment suite or a full-corpus contribution
estimate.
Instruction tokens and exact phrase lookup now share Unicode NFC after case
folding. Canonically equivalent spellings reach the same taught association
while retaining its stored surface phrase; if equivalent spellings have
conflicting learned rules, prediction abstains. `python3
experiments/v1_198_unicode_canonical_language.py` checks exact composed/
decomposed lookup, conflict abstention, unknown-word abstention, and
persistence. This handles canonical Unicode equivalence; it does not infer
transliteration, misspellings, or synonymy.
The shared `crms_text.py` tokenizer now keeps combining marks attached while
retaining offsets into the original source. This extends canonical matching
across fact/question frames, inference and independent proof keys, dialogue,
and research retrieval without changing displayed source text. The
`v1_199_unicode_across_language_system.py` runtime diagnostic checks an
accented fact question and dialogue correction, a rule proof whose relation
uses the decomposed form, source retrieval from the composed form, terminal
sentence alignment, exact citation offsets, and learned relative-clause
extraction when subject-relative and object-relative entities use decomposed
accents. Entity comparisons in that parser use the same case-folded NFC form
as token matching while keeping the original sentence text for citation. The scanner supports
canonical Unicode spelling equivalence; it is not a transliteration or
typo-correction system.
`python3 experiments/v1_184_conflicting_retrieval_routes.py` verifies that
novel-phrase prediction evaluates grounded candidates from all retrieval routes
before dispatch. A numeric frame proposes “add five” while independently
aligned phrase evidence proposes reversal; CRMS now asks for a contrastive
example and provides an input that separates those behaviors. Uncontested
numeric transfer still succeeds. Each component of an explicit multi-part
instruction gets the same conflict check before composition. The diagnostic
checks a conflicted component abstains and uncontested components still
compose. This targeted integration diagnostic does not replace the broader
corpus ablation.

`python3 experiments/v1_185_reasoning_contract.py` checks the proof and
abstention contract across direct relation paths, bounded fixed-endpoint paths,
explicit two-premise and typed three-premise rules, and explicitly licensed
transitivity and symmetry schemas. Every positive result is checked by the
separate fact-path or rule-proof verifier.
The diagnostic covers complete no-proof results, incomplete search-limit
results, ambiguity from multiple answers, explicit contradictions, and
malformed or tampered proof rejection for each proof representation. Path query
results expose `complete` and `reason_code`, distinguishing a fully searched
absence (`no_path`) from a bounded search that stopped early (`search_limit`).
Other question families leave `complete` unset until their own completeness
contract is specified and measured.

`python3 experiments/v1_186_symbolic_support_classes.py` exposes a non-
probabilistic support summary on rule-inference results: `unique`, `redundant`,
`contested`, or `none`, plus the number of structurally distinct proof trees
and the number and identifiers of distinct source documents at their fact
leaves. “Lineage” is a distinct proof tree, not a statistical-independence
claim. Contradiction takes precedence as `contested`; incomplete searches still
return `unknown` with no support class. The same summary is computed when a
verified practiced derivation is reused from the derived-case cache.

`python3 experiments/v1_187_middle_kind_index.py` checks typed middle-entity
pruning for explicit two-premise rules. A rule may name a `middle_kind`; only
entities with a scoped, explicit `is-a` fact are enumerated for that rule. The
kind fact is retained in the proof and validated independently. The diagnostic
checks the typed rule succeeds within a two-expansion budget where the
untyped control abstains, then compares their completed search counts. It also
checks missing or altered type evidence is rejected and that typed rules
survive persistence; contradictory kind evidence returns `ambiguous`. Kinds
are exact labels with no inferred subtype relation. The CLI supports
`/teach-inference-rule ID|REL1|REL2|CONCLUSION|middle_kind=KIND`.

`python3 experiments/v1_188_premise_join_index.py` checks goal-directed
candidate pruning for rule premises that cannot be recursively derived. It
intersects indexed direct and verified-cache edges from both endpoints before
enumerating middle entities, retains independent proof verification, and
checks that a one-under-budget search still abstains. This does not prune
premises whose relations have applicable inference rules; those branches keep
the exhaustive bounded candidate search.

`python3 experiments/v1_189_three_premise_rules.py` checks explicit three-edge
chain rules with separate exact kind guards for both interior entities. It
verifies the complete proof tree and all five source leaves, rejects missing
or altered type guards, returns `ambiguous` for contradicted kind evidence,
abstains on search-limit exhaustion, and checks persistence and terminal-chat
teaching. Inference rule arity is capped at three; automatic discovery and
held-out validation remain binary.

`python3 experiments/v1_190_transitivity_schema.py` checks the fixed
`transitivity-v1` schema. A relation generalizes only after an explicit,
source-backed `has relation type=transitive` annotation. Proof steps name the
schema, relation instance, validated schema record, and type assertion; the
independent checker verifies these alongside every fact join. The diagnostic
covers multi-edge inference, no implicit transitivity, schema/provenance
tampering, qualifier scope, contradictions, learned QA, derived-case reuse,
persistence, and CLI.

`python3 experiments/v1_191_bounded_abduction.py` checks minimal fact sets over
explicitly supplied pending research candidates. Terminal chat persists its
review queue separately from accepted facts and binds it to the current
knowledge and research-index paths. On reload it rechecks each citation and
learned fact-pattern license, dropping stale or unsupported candidates.
Candidate subsets are tried under size, subset-count, candidate-count,
proof-expansion, and depth bounds; every successful temporary proof is
independently checked. Incomplete enumeration marks any found sets non-minimal.
The operation does not accept candidates, change the fact store, or write
derived cases. `/abduce SUBJECT|RELATION|OBJECT` prints citations and the
hypothetical proof; `/accept N` remains a separate action and `/skip` dismisses
the saved queue.
Natural relation questions such as “Who is a grandparent of Cara?” and polar
questions such as “Is Ann a grandparent of Cara?” can enter proof search from
the stored rule conclusion without a separately taught question frame.
Missing-link prompts now name a concrete premise only when another direct or
verified premise supports that path; otherwise CRMS says the claim is not
established and abstains from yes/no. The
`experiments/v1_263_grounded_abduction_language.py` diagnostic checks this
behavior and the terminal wording.

`python3 experiments/v1_192_typed_three_premise_discovery.py` searches explicitly
for three-premise rule candidates guarded by two stored `is-a` facts. The
diagnostic checks binary-default isolation, exact discovered kinds, source-
heldout validation, rejection under a held-out counterexample or missing kind
evidence, expansion-limit reporting, independent proof verification, terminal
review/acceptance, and persistence. Three-premise discovery remains opt-in
through `max_arity=3` or `arity=3` in the rule-review commands.

`python3 experiments/v1_16_depth_four_discovery.py` checks a four-step
filter/sort/select/transform rule. It answers requested contrastive probes and
checks any unique fit against the teacher-side target; a three-step model
returns `no_fit` after six examples. With the current 67-step grammar,
including stable magnitude sort, a fresh run learned the four-step target
after seven examples and passed four held-out lists in 95.30 seconds. A
66-step post-search-gate run took 82.72 seconds. Earlier runs took 86.37
seconds with the 66-step grammar, 75.2 seconds with 65 steps (a repeated run
took 77.6 seconds), and 48.6 and 29.9 seconds with 62 and 61 steps
respectively. Timings vary, but the added operation increased measured search
cost in this run; this increase is material and should be tracked as the
operation grammar grows. `_procedure_key` now skips sorting parameter items
for zero- or one-parameter steps, where order is already canonical. Two
isolated four-example searches took 92.45 and 92.30 seconds with the same
149-candidate result; the full discovery diagnostic then learned the target
and passed held-out checks in 93.66 seconds, including the magnitude-sort
rewrite described below. These are modest gains on one
workload, not evidence of general scaling. A cProfile trace of the isolated
four-example search took 184.6 seconds under profiler overhead and recorded
5.36 million `_semantic_key` calls (146.8 seconds cumulative). These profiled timings are
not comparable to normal runs, but they identify canonicalization as the next
search hot spot to optimize. When the
generic bounded probe search returned no separator for two remaining
candidates, the diagnostic's teacher used a deterministic
target-versus-candidate probe. This confirms the tested rule under default
bounds; it does not establish that all depth-four rules are tractable.

`python3 experiments/v1_175_semantic_key_scaling.py` measures the cached
canonicalizer on equal 4,000-procedure deterministic samples drawn from
successively larger slices of the current grammar (8, 16, 24, and all 34
current operation types), including exhaustive one- and two-step combinations
plus seeded longer programs. The benchmark tracks the current count dynamically.
In the latest run, median cold cost per procedure was
8.78, 10.86, 9.95, and 10.59 μs for the four slices; warm cache-hit cost was
0.73, 0.80, 0.63, and 0.71 μs. Cold cost was not monotonic
with operation count, and this single-machine microbenchmark does not isolate
the cost of an individual rewrite or project the effect of new operation
types. It does not show a blow-up within the tested current grammar; larger
search profiling and measurements after genuine grammar growth are still
needed to establish a scaling ceiling.

`python3 experiments/v1_17_generated_depth_four_sweep.py` samples six distinct
four-step behaviors in the configured search grammar with no equivalent
program at depth three or below. In a prior runtime recheck, before the
`absolute_values` addition, it learned and matched all six on four held-out
inputs each. Two generalized
with one example, three with two, and one with six; the learner used eight
contrastive examples overall. The synthetic teacher supplies a real counterexample when the generic
probe search misses one, and the diagnostic checks that each complete candidate
set represents the target. This is a small seeded sample, not exhaustive
coverage of depth-four rules or a guarantee that every target completes within
the default budget. Exact semantic rewrites now collapse tested alias
families: invertible affine scaling around a rotated subtract-first/modular
filter sequence, rotation moved across uniform repetition, and equivalent
rotation/endpoint-deletion forms. The collision audit checked 179,767
same-key collisions over short and seeded lists through depth three.

## Bounded reasoning and research directions

CRMS implements bounded deductive inference over explicit facts, declared
chain rules of two or three premises, and explicitly licensed transitivity and
symmetry relation schemas, alongside a separate direct-fact path query. `ask_path` follows a
caller-specified forward relation sequence of one to three edges, with each
proof step being a stored fact. `infer_relation` backward-chains over two-edge
rules and fixed three-edge chain rules, recursively allowing derived
conclusions to support later rule applications. Three-premise rules require
explicit kinds for both interior entities; their kind assertions are proof
guards, not hidden search hints. A relation explicitly annotated as
`transitive` can use the fixed transitivity schema on direct, verified-cached,
or independently rule-proved same-relation edges. A relation explicitly
annotated as `symmetric` can reverse a direct, verified-cached, or independently
rule-proved edge. Every schema proof cites the relation-type
annotation and its validated schema identity; symmetry does not apply unless
that declaration is explicit in the exact qualifier scope. `v1_190` checks
transitivity and `v1_193` checks symmetry over direct, cached, and rule-proved
edges, including independent proof validation, conflicts, scope, depth limits,
persistence, and language/runtime integration.
Inference defaults to a depth limit of 8
and an expansion limit of 10,000; if a bound prevents a complete search, the
result is `unknown` rather than a partial answer. Both fact-path proofs and
recursive rule proofs have independent checkers, and callers expose inferred
answers only after verification. This is a real, proof-producing deductive
subsystem, but it reasons over explicit symbolic structures rather than
arbitrary text or implicit world knowledge.

Positive/negative evidence conflicts can make supported queries ambiguous,
but this does not make the knowledge base a general paraconsistent reasoner.
Counterfactual path operations remove a fact or source and rerun a query; they
measure proof dependency, not real-world causal effects. Rule discovery is an
inductive process over evidence, separate from the deductive inference engine:
it proposes bounded binary schemas by default and can optionally search typed
three-premise rules, checks candidates on held-out independent sources, and
requires explicit acceptance. Three-premise search is capped at arity three
and requires exact `is-a` guards for both interior entities. Bounded abduction
accepts a caller-supplied
set of pending, citation-backed fact candidates and searches minimal subsets
up to a configured size. It does not generate arbitrary missing facts, rank
open-ended explanations, or accept candidates automatically.
Planning, structural analogy, causal intervention, and probabilistic
reasoning are not implemented. Keep all reasoning claims scoped to those
distinctions.

`crms_proof.py` provides an independent validator for serialized positive
fact-path proofs. It checks path continuity, requested relation order, answer
endpoint, and exact fact membership (including source provenance and
qualifiers). This checker covers paths made only of stored facts.
`crms_rule_proof.py` independently verifies recursive declared-rule and
transitivity-schema proofs.
Neither checker by itself validates every query outcome or the complete
negative-evidence policy.

Treat reasoning as **bounded proof search over explicit structures**: a query
selects a goal, search finds a path through stored facts and declared rules,
each step records a proof obligation, and an independent checker validates the
result. A plausible answer is not enough. The system must also abstain when
search is incomplete or no proof exists, and preserve distinctions among
absence, multiple supported answers, and conflicting evidence wherever the
query type exposes those states. This framing applies to the implemented
backward chaining and counterfactual dependency checks, while keeping their
different semantics explicit.

The original near-term reasoning proposals—goal-directed backward chaining
and bounded fact-store counterfactuals—are implemented below. The following
items record which bounded extensions have landed and their current limits:

1. **Completed: measure the proof and abstention contract.** The `v1_185`
   diagnostic checks independent path, two-premise rule, typed three-premise
   rule, and transitivity-schema proof verification; complete no-proof versus
   incomplete search; multiple path answers; contradictions; and malformed or
   tampered proofs. It also covers the regression where depth exhaustion inside
   a symmetric-schema premise must propagate to the outer search as an
   incomplete `unknown`, rather than complete absence. `ask_path` and
   `ask_path_between` expose structured `complete` and `reason_code` values;
   other language-facing query families still need their own defined
   completeness semantics before those fields can be generalized.
   `v1_249_reasoning_quality_benchmark.py` adds a small seeded seven-node
   recursive ancestor graph: it checks all 49 ordered node pairs, independently
   verifies the 15 expected positive proof answers, requires complete unknowns
   for the other 34, and checks a planted contradiction and a forced depth
   limit. The current implementation scores 1.000 precision and recall on
   this fixture. This is a controlled mechanism check, not a measure of
   real-world reasoning quality or knowledge coverage.
2. **Completed: expose symbolic support classes.** Inference results report
   distinct proof-tree count, distinct leaf source-document count, and
   `unique`/`redundant`/`contested`/`none` support class. `v1_186` covers fresh
   and cached derivations. A proof tree is a structural lineage, not a
   statistical-independence guarantee.
3. **Partially completed: bounded meet-in-the-middle search.** `ask_path_between`
   now searches both endpoints and joins at the middle entity. On the seeded
   624-fact, 576-proof three-edge graph in `v1_54`, it expands 624 edges versus
   1,176 for the prior one-sided traversal, while retaining every proof and
   exact/under-budget abstention behavior. This is a targeted graph shape, not
   a general performance claim. For rule inference, when a premise relation
   has no recursive rule, the reasoner now indexes fact and verified-cache
   edges from both endpoints and intersects their middle entities. `v1_188`
   reduces 51 all-entity candidates to one joined middle while preserving proof
   and budget checks. Premises that can be recursively derived retain exhaustive
   bounded search; an alternating recursive goal-stack design remains future
   work. Describe path lookup as graph search, separate from rule inference.
4. **Completed initial kind-index implementation.** `InferenceRule` can carry
   an optional `middle_kind`; the inference query builds a kind index from
   explicit `entity -is-a-> kind` facts in the exact qualifier scope and tests
   only matching middle entities for that rule. Typed proof trees include the
   kind fact, and the independent verifier checks it against the trusted fact
   snapshot and declared kind. `v1_187` compares bounded typed/untyped search,
   tampers with and removes kind evidence, checks contradictory kind evidence,
   CLI teaching, and save/load. This first implementation is query-local and
   relation-name based; it does not yet provide a separately maintained index
   or type hierarchy/subtyping.
5. **Completed bounded three-premise rules.** A chain rule may include three
   relation premises, but must declare exact kinds for both interior entities.
   The search remains bounded by the existing depth and expansion budgets;
   proof records carry both type facts, which the independent verifier checks.
   `v1_189` covers valid derivation, incorrect/missing guards, contradiction,
   limit abstention, persistence, and CLI teaching. The rule representation
   caps arity at three. Three-premise rule discovery and held-out validation
   are now available as an opt-in mode requiring both interior kinds to be
   explicitly present in training and holdout evidence. `v1_192` checks typed
   candidate discovery, held-out success and rejection, boundedness, CLI
   acceptance, and execution; binary discovery remains the default.
6. **Completed initial relation-schema implementation.** The fixed
   `transitivity-v1` schema generalizes across relation labels only when a
   scoped `RELATION -has relation type-> transitive` fact is explicit. It
   composes direct, verified-cached, or independently rule-proved same-relation
   edges, records the schema
   identity and type declaration in each proof step, and has a separate proof
   verifier branch that checks the schema validation record and every join.
   `v1_190` covers multi-edge inference, absent type declarations, altered
   schema/provenance, qualifier scope, contradictions, learned QA, practice
   cache reuse, persistence, and CLI. `v1_225` checks transitive composition
   over a rule-derived edge, independent mixed-proof verification, complete
   provenance, explicit licensing, limits, and contradiction. Candidate
   targets from nonrecursive rule premises use scoped edge indexes; recursively
   derivable premises remain subject to entity enumeration and the same
   inference bounds. No other relation schemas are implemented.
7. **Completed: try a bounded fact-store counterfactual.** For a query whose answer has a
   proof, `counterfactual_path_between` now excludes one cited fact proposition
   in a temporary view and reruns the same bounded query. It distinguishes
   surviving alternative support from lost support, and reports ambiguous or
   unproven baselines separately. The original store is not mutated. The
   `v1_55` diagnostic checks alternative and necessary facts, invalid baselines,
   source-level exclusion, and restoration. `counterfactual_path_without_source`
   removes one citation across the temporary positive and negative fact views;
   a proposition remains when another citation supports it. This is dependency
   analysis over stored paths; it does not establish real-world causal effects.
   Learned frames now cover both a variable source over fixed endpoints and
   fixed relation sequence, and a multi-slot pattern varying start, target, and
   source while holding relation sequence and qualifiers fixed. `v1_56` and
   `v1_57` check these bounded frames. Broader natural-language access still
   needs evaluation before expanding scope.

`crms_inference.py` implements bounded backward chaining over explicit rules
of the form `x -R1-> y` and
`y -R2-> z` therefore `x -R3-> z`. `infer_relation` checks a specified
conclusion against positive facts and returns premise-carrying rule proofs
without inserting derived facts into the store. The independent
`crms_rule_proof.py` verifier checks rule membership, premise membership,
relation matching, joins, and the requested conclusion; `CRMSKnowledgeBase`
runs this verifier before exposing inferred answers to callers. Results carry
machine-readable `complete` and `reason_code` fields, distinguishing a
complete no-proof search from a depth/expansion limit or verifier rejection.
They also expose `failure_kind`: `no_applicable_rule`, `missing_premise`,
`search_limit`, `proof_rejected`, `integrity_conflict`, or `contradiction`.
For a complete failed search, `missing_premises` lists up to eight explicit
rule premises that could not be proved, with the rule ID and conclusion they
would support. The legacy `reason_code="no_proof"` remains stable; callers
can use `failure_kind` for a more useful diagnosis. Question answering
surfaces a bounded missing-premise explanation when applicable and otherwise
distinguishes no applicable schema from incomplete search;
question answering and writing use those fields to abstain from presenting an
incomplete answer set. The knowledge base persists declarations, and
`/teach-inference-rule` plus `/infer-relation` expose this in terminal chat.
`/teach-relation-type` also accepts explicit `irreflexive`, `asymmetric`, and
`functional` integrity constraints in addition to transitive and symmetric
schemas. A functional relation permits at most one object for each subject;
if a second direct or derived object is provable, inference returns
`ambiguous` with `reason_code="integrity_conflict"`. If checking competing
answers exhausts the expansion budget, it returns incomplete `unknown`. If a
requested positive proof would make an irreflexive relation reflexive, or an
asymmetric relation has proofs in both directions, inference returns
`ambiguous` with `reason_code="integrity_conflict"` and names the schema
source. The reverse check uses the same expansion bound; exhaustion returns
incomplete `unknown`, never a partial answer. These are explicit declarations,
not built-in assumptions about which relations are parenthood, ownership, or
other domain concepts. The declarations currently use the persisted `has
relation type` fact representation; a separate schema store remains future
work.
Two-premise and typed three-premise rules can also be taught in ordinary
language with bounded templates. For the typed form, the user names both
intermediate kinds: `Teach CRMS rule "part-property": if X has relation
"part" to Y, Y is of kind "component", and Y has relation "links" to Z, Z is
of kind "material", and Z has relation "color" to W, then X has relation
"has-property" to W.` These forms store the same declarations as the command
interface; they do not induce rules from unlabelled sentences. `v1_227` checks
both forms, conflicting rule-ID rejection, persistence, direct inference,
independent proof verification, and an ordinary-language yes/no frame taught
from explicit facts and applied to a new entity pair through the rule proof.
It also follows an inference-backed answer with `What about Ada?`, requiring
one grounded substitution and retaining the new rule proof. `v1_227` restarts
the terminal between the answer and follow-up and checks that persisted
dialogue context still produces an answer with a rule proof.
`v1_61` covers derivations, typed no-proof versus search-limit outcomes,
conflict, limits, and tampering;
`v1_62` checks nested-rule persistence and CLI proof rendering; `v1_63` checks
recursive proof verification, depth abstention, cycle termination, and nested
tampering. Learned polar-question frames can now use verified rule proofs as
positive teaching evidence and answer new entity pairs through inference.
Those answers retain the recursive rule proof and source citations. Explicit
negative evidence remains distinct and makes an inferred-positive conflict
ambiguous. `v1_66` checks the learned-language-to-inference route, unknown
wording, contradiction handling, CLI, and persistence. General entity-slot
question frames can also be taught from verified derived answers and retrieve
new answers by bounded search over known entities; `v1_67` checks this path,
including ambiguity, unknown wording, CLI, persistence, completion despite
unrelated entity noise, and abstention without partial candidates when a dense
branching graph exhausts the aggregate inference budget. Entity enumeration is
capped at 256 entities in the exact requested
qualifier scope and inference work at 10,000 expansions by default; callers can
set the validated `max_inference_expansions` bound on `ask()`. The query
abstains if either bound prevents a complete answer set.
For a matched subject-answer question frame, a proof-backed answer is realized
by substituting the inferred subject into the accepted frame wording (for
example, “Who is an ancestor of Pia?” becomes “Nia is an ancestor of Pia.”).
The answer must match a verified proof conclusion; the ordinary reply stays
short, and `Why?` exposes the proof and premise sources. `v1_67` checks this
answer-first wording and the explanation follow-up.
`write_about` can include inferred relations when a positive sentence frame is
licensed for that relation. It marks each sentence as derived and retains the
recursive proof, rule identifiers, and leaf source citations; conflicting
derived statements are reported without being written as facts. `v1_68` checks
this behavior, including no fact-store mutation and CLI output. Writing uses
the same 256-entity-per-scope and 10,000-expansion limits; `v1_88` checks the
contextual path. Research workflows still do
not automatically treat derived relations as source-extracted facts. Instead,
`research` may use an answered rule proof to expand retrieval with its entities
and relation, retaining the derivation separately from exact retrieved
passages and review-only fact candidates. `v1_69` verifies the passage is
retrieved only through the derived entity expansion and remains distinct from
the proof evidence in rendered output. When the answer uses a contextual rule
proof, research also preserves and renders the exact qualifier scope from its
proof leaves; those values can expand retrieval but remain distinct from
passage-extracted facts. `v1_86` checks contextual inferred QA and research
scope retention.
`discover_inference_rules` and `/suggest-inference-rules` now
propose relation-chain schemas from joined positive facts and labeled
conclusions. Candidates require multiple distinct endpoint examples and
distinct conclusion source documents, and show matching explicit negatives;
same-document citation fragments count as one source. Candidates with
insufficient source diversity remain visible but cannot proceed as validated
training rules. An incomplete search labels every partial candidate
incomplete. Discovery does not install rules. `v1_64` checks these gates and
the CLI review output. Two-premise mining indexes facts by subject and exact
qualifier scope before joining, so sparse corpora scale with matching joins
rather than scanning every possible fact pair. The same diagnostic checks this
with a 36,000-fact sparse and multi-context fixture and verifies the reported
join count without mixing conclusions across qualifier scopes.
Rule discovery also memoizes each input fact's normalized triple and context
scope within one search. The sparse scale diagnostic
`experiments/v1_306_rule_discovery_scale.py` checks a labeled rule and stable
candidate status at 10k, 50k, and 100k facts while reporting discovery time.
On the development runtime this reduced the prior 100k sparse fixture from
about 2.05 seconds to roughly 1.0–1.35 seconds. This measures preparation
and sparse joins, not dense-corpus rule enumeration, which remains bounded by
`max_expansions`. `experiments/v1_307_sqlite_rule_discovery_scale.py` repeats
the same evidence and completeness checks through saved and reloaded SQLite
models: warm medians were 233 ms at 20k facts and 1.37 s at 100k. Candidate
status, support, provenance, and expansion counts matched the in-memory
backend; the benchmark excludes database creation and loading from query time.
`/suggest-inference-rules MIN|SOURCE_PREFIX`
excludes matching provenance sources from candidate generation and measures
the candidates against that held-out partition. `/accept-inference-rule
N|ID|SOURCE_PREFIX` installs a rule only when training search completed, the
candidate has no training counterexample, and at least two held-out endpoint
pairs support it without held-out negatives; those positive labels must also
come from at least two distinct source documents (citation fragments from the
same document count once). Acceptance records the validation source prefix,
independent source identities, and evidence in the knowledge file. `v1_65`
checks validation, source independence, overlap rejection, counterexample and
insufficient-support rejection, CLI acceptance, persistence, and use on a new
chain. Held-out review is also available in ordinary language, for example
“Review inference rule candidates against held-out sources with prefix
‘holdout:’.” This request runs the same read-only review; it does not install a
rule. Acceptance remains a separate action and reruns validation before
installation. Acceptance is also available in ordinary language: “Accept rule
candidate 1 as ‘parent-transitivity’ using held-out source prefix ‘holdout:’.”
It reruns the same source-separated validation gate before installation;
`v1_65` checks the natural-language review/accept/use flow, including
persistence and source provenance. Rules remain explicit
declarations after review rather than being inferred automatically from
unlabeled language. `v1_250_source_to_rule_learning.py` exercises the full
bounded route: sourced sentence frames are taught from labeled examples, new
source sentences yield review-only fact candidates, accepted facts feed rule
discovery, independent held-out sources validate a candidate, explicit
acceptance activates it, and the resulting inference is independently
proof-checked with source citations. It also drives the terminal through
ordinary-language candidate review and acceptance, then asks a learned
question about a new pair with only the two premises stored; the answer must
show the accepted rule proof and both source citations. This verifies that the
pieces compose; its small synthetic corpus does not establish automatic rule
discovery from arbitrary documents. Inference now supports learned polar and
entity-slot QA frames, source-grounded writing can verbalize proof-backed derived relations,
and research can use verified conclusions for retrieval expansion while
keeping source passages separate. Other research operations do not yet
consume inferred relations. Contextual rule discovery now requires the two
premises and the labeled conclusion to share an exact qualifier set, and its
held-out evaluation remains source-separated. Accepted rules are not tied to a
single scope; applying them still requires a query with matching exact-scope
facts. Broader semantics for combining unqualified and qualified evidence or
partially overlapping contexts remain open. Preserve bounds, cycle detection,
and distinct absence, ambiguity, and contradiction outcomes as discovery
develops.

### Derived artifacts and practice loop (roadmap)

The architecture has three distinct knowledge routes:

| Route | Input | Stored result | Current status |
|---|---|---|---|
| Teach | Explicit evidence or demonstrations | Facts and procedures | Implemented |
| Induce | Labeled examples | Candidate general rules | Implemented with review and held-out validation |
| Derive | A system-produced result with an independent proof | A separate derived artifact with lineage | Implemented for bounded symbolic inference; explicit practice or session opt-in |

Derivation closes a limited feedback loop: retrieve premises, combine them by
explicit rules, independently verify the proof, and retain the result so it
can be reused. This is useful accumulation of verified work, but it does not
by itself change the rule set or demonstrate general learning from arbitrary
outputs. The stronger claim that practice compounds capability remains a
hypothesis to evaluate against held-out coverage, correctness, and cost.

The current loop does not implement generic overlay of arbitrary cases. Each
kind of output needs a typed representation and a verifier independent of the
generator before it can be admitted. A symbolic proof can be checked against
facts and rules; generated prose, a research summary, or a story cannot be
made reliable merely by checking it against the same material used to produce
it. Verification establishes consistency with the modeled evidence, not the
truth of the underlying sources.

Treat **query-time case overlay** as a separate, representation-specific
research direction. Retrieval similarity can select and attribute candidate
cases, but it does not define how their outputs combine. VSA majority bundling
is defined for token hypervectors; it is not automatically a valid operator on
integer lists, facts, text, or stories. Weighted averaging is meaningful only
for outputs with a justified metric and alignment, and it is generally not a
valid interpolation between categorical procedures. A future overlay must
specify its output algebra, weights, conflict behavior, and exact case-level
attribution, then test held-out utility against selecting the best case.
Structured set or role-map outputs may support deterministic merge operations
with explicit conflict handling. Text continuation distributions and story
overlays would require their own learned representations and independent
checks; neither exists yet. Any resulting artifact remains transient unless
it passes the separate proof-backed or type-appropriate verification gate for
derived memory.

The current bounded form persists an explicitly requested, unambiguous
inference result supported by at least one rule application, with its complete
recursive proof, leaf fact citations, and rule identifiers; direct taught
facts are not copied into derived memory. Reuse independently checks the saved
proof. For the same query, when the scoped fact, negative-evidence, schema,
and applicable-rule snapshot is unchanged and the stored search bounds cover
the request, a fingerprint allows the inference API to return the checked proof
without rerunning bounded search. Unrelated corpus changes do not invalidate
that proof. Such artifacts can also satisfy intermediate relation subgoals in
a different query under the same scope and bounds; the proof tree is expanded
back to its source-fact leaves. Relevant state changes or wider search requests
force fresh inference and proof revalidation. Stale, conflicted, or over-budget
results remain unavailable. The conclusion is not a source-backed fact or an
independent proof leaf.

The general loop to evaluate is **retrieve evidence → combine/derive an output
→ independently verify → record a derived artifact with lineage → retrieve it
again only while its evidence remains valid**. In the current inference path,
the combination is bounded rule chaining over source facts; it is not a generic
overlay of arbitrary cases. Writing, QA, research, and language-learning
outputs must not enter this loop merely because they were generated. Each
needs an independent acceptance check appropriate to its representation.
In particular, proof verification establishes that a conclusion follows from
the current explicit facts and rules; it does not establish that the source
facts are true.

Treat derived memory as a cache of verified work with traceable dependencies,
not as new ground truth. Revalidation already gives it a conservative form of
causal forgetting: after a source fact or rule is removed or contradicted, a
dependent artifact is unavailable if its proof no longer verifies. If several
independent proofs exist, retain and validate each separately so losing one
lineage need not invalidate support from another. Keep taught evidence and
derived artifacts in separate stores; this avoids letting a derived item
outvote teaching or become circular support. If future retrieval combines
both, taught evidence must remain authoritative on conflict and every
derived contribution must expose its provenance and current validity.

Do not automatically store every answer. A later implementation should dedupe
by conclusion and lineage, cap storage, and admit artifacts only under an
explicit novelty/usefulness policy. Novelty must be measured against existing
conclusions and support; usefulness should be based on successful reuse or
measurable saved work, not raw query frequency alone. Keep taught evidence
authoritative on conflict, and measure false derivations and self-reinforcement
on held-out cases. Start with proof-backed symbolic inferences, where CRMS
already has an independent verifier; do not self-train the integer-list
predictor or treat generated prose as verified experience without an
independent correctness check.

Stage the work: (1) retain explicit practice and inspectable lineage; (2) test
revalidation after source/rule deletion, correction, and contradiction,
including survival through alternate valid proofs; (3) measure whether reuse
reduces bounded inference work without changing answer correctness; (4) add
deduplication and a storage cap with deterministic eviction (implemented); (5) only then
consider opt-in or policy-gated automatic write-back. The current system has a
narrow session-scoped opt-in: after the user enables auto-practice, ordinary
question answers are retained only when they pass the existing unique-answer
and independent-proof checks. The toggle defaults off and is not persisted;
verified artifacts themselves are persisted. This implements opt-in write-back
for that bounded question path, not automatic promotion of arbitrary outputs.
Evaluate false
derivations, stale-lineage abstention, ambiguity, search-limit behavior,
storage growth, and reuse benefit at every stage. Do not claim compounding
capability until held-out evaluations show that derived-case reuse improves
coverage or cost without increasing unsupported conclusions.

`CRMSKnowledgeBase.practice_relation()` is the explicit practice operation.
`retrieve_derived_case()` checks the saved proof against current facts and
rules, reusing a matching validated snapshot and rerunning inference whenever
that snapshot, exact qualifier scope, or search bounds do not match. Exact
matching inference queries can also reuse the checked artifact as a result,
and other queries can reuse it as a checked subgoal within the same scope.
`derived_cases()` reports stale or conflicted records without returning them
as verified. `/practice-inference` accepts optional exact context qualifiers;
`Show derived cases` displays each artifact's scope, exposing this feedback
step for explicit user review.
`practice_question()` and `/practice-question QUESTION` connect that route to
language-facing QA: they first run the ordinary read-only `ask()`, then retain
the result only when it is a unique answer with inference proofs for exactly
one conclusion and qualifier scope. The operation independently reruns the
proof through `practice_relation()` before write-back. Directly taught answers,
ambiguous or incomplete results, and composed questions with multiple proof
conclusions do not create artifacts. The separate derived-case cap,
deduplication, proof revalidation, and no-fact-promotion rules still apply.
After an answered question, a user can also say `Practice that answer.` or
`Practice the answer to QUESTION.` in ordinary chat. Both forms use the same
proof gate and report when no derived artifact was retained; they do not
practice arbitrary generated text.
`experiments/v1_202_language_answer_practice.py` checks the language-to-practice
path, exact qualifier retention, no-write behavior for direct and ambiguous
answers, reuse, deduplication, persistence, and the CLI. Terminal chat also
offers `Turn auto-practice on` and `Turn auto-practice off`: this enables the
same gate after ordinary free-form and `/ask-context` questions for the current
process only, defaults off, and is not persisted. Slash forms remain
available. The knowledge API's `ask()` remains read-only. This does not
practice arbitrary generated prose or research summaries.
Serialization keeps artifacts separate, and they never enter `facts()` or
serve as proof leaves. `v1_72_proof_backed_derived_cases.py` checks practice,
deduplication, lineage, persistence, no fact promotion, and conflict
abstention. `v1_82_derived_lineage_revalidation.py` checks that an artifact
survives loss of one premise or rule when an alternate proof remains, and is
marked unavailable when every proof lineage is lost. This confirms dependency
revalidation for the tested positive-proof cases. `remove_fact()` and
`remove_negative_fact()` now retract support from one named source while
preserving independent citations; dependent derived cases are revalidated on
reuse instead of being edited in place. `v1_105_corrected_fact_revalidation.py`
checks that losing one citation preserves a valid derivation, removing the last
outdated support makes its conclusion unavailable, and a corrected fact can
support a newly practiced and reusable conclusion. This is evidence-retraction
and revalidation, not automated source correction or propagation into arbitrary
language and writing memories. `v1_110_cli_fact_correction.py` checks source
retraction from the interactive shell, persisted stale records, and refreshed
lineage after partial retraction.
`v1_83_derived_case_reuse.py` confirms that direct taught facts are not copied,
an exact query reuses its stored proof within validated bounds, wider searches
run again, a changed snapshot triggers revalidation, and a newly added conflict
invalidates reuse.
`v1_84_derived_case_subgoal_reuse.py` checks reuse of a practiced relation as
an intermediate proof in a different query, verifies that the returned proof
expands to source-fact leaves, measures fewer search expansions on a seeded
example, and checks invalidation after negative evidence changes. These are
bounded diagnostics, not broad latency or scaling benchmarks; computing the
snapshot fingerprint still scans the current evidence and rule state.
Automatic write-back beyond the narrow session opt-in described above,
semantic novelty and usefulness scoring, and rule induction from derivations
remain future work and need separate evaluation. The current cap uses
successful reuse as a simple retention signal, not as a complete utility
estimate. Reuse applies only to the same explicitly proved relation and does
not implement generic overlay of arbitrary cases.
`v1_89_contextual_derived_practice.py` checks separate artifacts per exact
scope, persistence, contextual query and subgoal reuse, CLI rendering, and
conflict invalidation isolated to the affected scope.

Derived storage is capped at 1,000 cases by default and can be configured with
`CRMSKnowledgeBase(max_derived_cases=...)`; zero keeps practice inference
available while disabling artifact retention. At capacity, eviction removes
the case with the fewest snapshot-valid cache reuses (a fresh proof search
after state changes does not count), breaking ties by oldest practice order
and then canonical conclusion key. The cap and insertion order
survive persistence. This bounds storage and favors demonstrated reuse, but it
does not implement semantic novelty scoring or estimate saved work. It does not
enable write-back by default; the session opt-in is limited to unique,
proof-backed question results. `v1_119_derived_case_storage_cap.py` checks successful-
reuse priority, deterministic ties, persistence, and zero-cap behavior.

Counterfactual path queries are implemented as bounded fact-store dependency
checks, so evaluate them through proof survival after removing evidence. They
do not establish real-world causality. Keep the broader reasoning taxonomy as
a set of gated research directions, ordered by representation readiness:

- **Planning** needs explicit action preconditions and effects, then bounded
  search with independently checkable action traces.
- **Bounded abduction** needs a finite, reviewable hypothesis space and an
  evidence policy for selecting among explanations; the first bounded API now
  searches only caller-supplied pending research candidates, validates their
  citations and learned fact-frame licenses, and never commits them. A durable
  review queue, accepted-vs-derived candidate policy, and explanation ranking
  remain future work; do not infer arbitrary missing facts.
- **Structural analogy** is a promising bridge from surface-pattern learning
  to relational transfer, but requires explicit relational structures,
  mapping evidence, ambiguity handling, and search-cost controls. Explore it
  after current rule-discovery and proof-evaluation work identifies a concrete
  lexical-transfer failure it could solve.
- **Causal inference** needs causal annotations and intervention semantics in
  the data; dependency under fact removal is not a causal effect.

Full probabilistic inference and open-ended creative reasoning remain outside
the current symbolic evidence model. Bounded confidence labels may be explored
only with a concrete representation and evaluation need. Revisit these
directions when their prerequisites and a testable task exist.

For every reasoning extension, evaluate against an independent proof checker
where possible, plus cases with no proof, invalid near-miss paths, multiple
answers, contradictions, cycles, and search-limit exhaustion. Track proof
validity and false derivations separately from answer coverage; increasing
coverage is not a success if unsupported conclusions are returned. Preserve
provenance, explicit resource bounds, ambiguity reporting, and abstention as
acceptance requirements.

### Case overlay and derivation feedback

The proposed retrieve → overlay → verify → store loop has a partial
implementation in the fact-reasoning subsystem: explicit practice can store
proof-backed derived relations in a separate bounded cache, retain alternative
lineages, validate reuse against current evidence and rules, and revalidate
after source retraction. It does not yet retrieve and combine arbitrary cases
into a new artifact. The existing derived cache is not a general self-training
loop and does not learn new rules from its own outputs.

Treat generic overlay as a research direction. First define typed case
structures and a task-specific combination rule. Prefer discrete structural
composition with source-level attribution; weighted averaging is meaningful
only for output types where that operation is defined. Verification must be
independent of the overlay procedure, and derived artifacts must remain
separate from taught evidence, carry complete lineage, abstain on conflict,
and respect storage bounds. Evaluate held-out correctness, lineage invalidation,
retrieval effects, novelty, retention utility, and error amplification before
expanding write-back beyond the existing session opt-in. Broader write-back and
abstraction or rule induction from overlaid artifacts remain future work.

### Mechanically supervised training loops (roadmap)

Mechanical checks can drive bounded training work without a human labeling
each generated item, but each check applies only to the representation and
claim it validates. Primitive holdout and MDL gates validate a proposal over
their sampled numeric examples; independent proof checkers validate a stated
derivation against the current fact/rule snapshot; citation checks validate
source identity and text offsets. None alone validates an arbitrary generated
sentence, the usefulness of a new rule, or the truth of an unreviewed source
interpretation.

The first useful loop is **self-play as a search diagnostic**. A bounded
explorer can sample supported procedures, generate deterministic examples,
and ask an isolated learner to reconstruct them. Compare the learned behavior
with the target on held-out and separating inputs, and record runtime, search
completeness, and failures. This measures whether the current learner can
recover behaviors already expressible by its grammar; it does not discover a
new primitive or teach natural-language meaning. Generated tasks should stay
outside persistent user memory. To mine primitive proposals from failures,
the task generator must also produce behaviors outside the active grammar,
with an independent target specification and the existing proposal gates.
Sampling targets from `_steps` alone cannot establish that a missing operation
has been found. `python3 experiments/v1_200_self_play_curriculum.py` is the
first isolated pilot: an independent reference interpreter generates five
one- and two-step tasks from a small declared subset, and `teach()` receives
only opaque task labels and input/output examples. It mechanically answers a
contrastive request, then checks each learned behavior over all 781 lists of
length zero through four over `-2..2`, plus 32 seeded longer lists. All five
tasks passed; the odd-filter/sort task needed one teacher round and one extra
example. The 31 examples and six training calls are held in temporary models;
no result enters user memory. This validates the diagnostic loop, not autonomous
curriculum growth, language acquisition, or operation discovery.

`python3 experiments/v1_208_grammar_sampled_selfplay.py` advances the pilot by
sampling one- and two-step targets from the configured model's actual `_steps`
table, restricted to operations with an independent reference interpreter.
The isolated learner searches only depth one: four sampled one-step tasks are
reconstructed and checked on 813 audit inputs, while eight distinguishing
two-step tasks yield complete-search `no_fit` records. Those records are passed
to report-only primitive discovery. The experiment also generates an
out-of-grammar absolute-difference target from a separate reference function,
using three distinct instruction phrases and twelve ephemeral examples per
phrase. The candidate passes the proposal's held-out and description-length
gates. `learn_primitive_proposal()` stages acceptance and phrase synthesis on an
isolated model, replays every retained example, then commits the grammar and
learned language rules together only if all checks pass. A contradictory
demonstration confirms that a failed attempt leaves the active model unchanged.
If phrase synthesis needs a separating example, the learner labels the
contrastive probe by executing the already validated primitive. Those labels
are stored separately in the primitive artifact with their source recorded;
they do not replace or augment the original supplied examples. The best-proposal
route also rechecks up to eight other complete no-fit tasks against the expanded
grammar in the same transaction, so a new primitive can unlock a composed rule.
The same path is available in chat as “Learn from validated primitive proposal
ID.” For a mechanically selected candidate, “Learn the best validated
primitive proposal” ranks current candidates by description-length gain, phrase
support, and estimated grammar growth, then learns at most one. Both routes use
the same held-out, MDL, and replay gates. The no-ID route still depends on
complete no-fit examples already in the model; it does not generate task
labels or candidate-language descriptions. No generated task or result is
saved to user memory by the diagnostic.
This demonstrates one bounded path from mechanically generated examples to a
new primitive and learned phrase rules; the target behavior and instruction
phrases are selected in advance, so this is not autonomous task generation,
natural-language acquisition, or open-ended operation discovery.

The strongest near-term **language** loop is question generation from stored
facts. Generate answerable queries only from licensed question structures and
known facts, run `ask()`, and compare answer and evidence with the fact store.
This can measure frame coverage and identify missing entity or qualifier
transfer. A new frame should remain report-only until its slots are aligned to
source-backed predicate forms, it passes distinct-entity and source-separated
holdouts, and conflicts or unsupported variants abstain. The fact store can
provide answer labels; it cannot by itself justify an arbitrary paraphrase.
`experiments/v1_201_grounded_question_curriculum.py` implements a read-only
diagnostic for licensed one-slot, single-qualifier, and multi-qualifier frames:
it generates questions from stored facts, checks answer sets and source
attribution, and confirms that ambiguous answers remain ambiguous, wrong-scope
or unknown entities remain unknown, and generation does not mutate facts or
frames. Its expected answers are computed from the same fact snapshot passed
to `ask()`, so this measures frame execution and evidence preservation, not
independent source truth or question-language acquisition. Generated items
in that diagnostic remain ephemeral; it does not teach new frames.

`experiments/v1_203_grounded_polar_question_curriculum.py` now adds the polar
slice: it instantiates a licensed yes/no frame over explicit positive and
negative facts, checks source attribution, and confirms that an unrecorded
proposition remains unknown while contradictory evidence is reported as
ambiguous with both sources. The labels come only from explicit evidence, and
the generated questions do not mutate facts or frame examples. This is a
bounded frame-execution diagnostic; it does not measure acquisition of new
polar wording or generalize truth beyond the recorded propositions.

`experiments/v1_204_grounded_path_question_curriculum.py` generates held-out
path questions from a licensed frame and compares `ask()` with an independent
join over the explicit fact triples. It checks answer sets, complete proof
chains and their sources, multiple reachable endpoints, and abstention when a
learned frame has no matching path. It also confirms that generated questions
do not mutate facts or frame examples. This measures bounded path-frame
execution; it does not assess arbitrary path-language acquisition or infer
unstored edges.

`experiments/v1_205_inferred_question_curriculum.py` covers answers licensed
by an explicit two-premise rule. It computes expected conclusions with an
independent join over base facts, compares the complete answer set, and checks
each recursive proof with `crms_rule_proof.verify_inference_proof`. It also
checks source lineage, ambiguous answers, missing-proof abstention, and that
question evaluation does not change facts or learned frames. This validates a
bounded rule and question-frame combination; it does not evaluate arbitrary
rule induction or new natural-language frames. Genuinely new-frame curricula
still need independently held-out language evidence and proof checks.

`crms_question_induction.py` adds analogy proposers for fact-backed question
frames. They can replace a relation phrase in an already licensed question
structure only when the target relation has an exact, source-backed predicate
frame. Contextual proposers handle one or multiple qualifier slots. For a
multi-qualifier frame, every qualifier value and the bound entity must vary
across training and holdout examples. Both require source-separated documents
and direct qualified target facts, test candidates on a temporary
knowledge-base copy, and check held-out answer sets, ambiguity, and source
attribution. Inferred targets remain future work. `Review question frame
proposals` (or `/suggest-question-frames`)
reports lineage-bearing candidates, including the qualifier name, without
changing knowledge. `Accept question frame proposal ID`
reruns those mechanical checks for one exact candidate and retains a passing
frame in the separate induced-frame store. `/train-question-frames` remains
available to accept all currently passing candidates; the same bounded
operation is exposed in conversation as “Learn the current validated question
frame proposals.” `ask()` activates
each induced frame only while its base-frame, predicate, training, and holdout
citations remain present; source retraction disables it, and persistence
revalidates it against the loaded snapshot.

`crms_question_role_induction.py` learns a narrow active-voice role alternation
from paired, source-backed frames: `Who PAST OBJECT?` and
`What did SUBJECT BASE?`. It requires two distinct relation pairs for training,
a third relation pair for held-out validation, and a fourth target relation
with only its subject-answer frame. The current spelling rule is limited to
one-token regular past forms where `BASE + ed = PAST`. Use
`/suggest-question-role-rules` to inspect candidates; they remain report-only
until an exact artifact ID is accepted through the question-frame proposal
workflow. Accepted frames retain the training, held-out, and target-source
lineage, persist across reload, and deactivate when supporting sources change.
This is a bounded learned grammar rule, not a general English voice or verb
inflection model. `experiments/v1_240_active_question_role_alternation.py`
checks the held-out relation, source separation, answer and citation matching,
explicit acceptance, persistence, and invalidation.

`experiments/v1_210_analogical_question_frame_proposals.py` and
`experiments/v1_221_qualified_question_frame_induction.py` and
`experiments/v1_222_multi_qualified_question_frame_induction.py` check proposal
gates, source separation (including shared citations), answer and ambiguity
preservation, explicit and natural-language training, persistence, and
invalidation after retraction across plain, single-qualifier, and
multi-qualifier frames.
These checks show consistency with the recorded facts; they do not
independently prove that a new question is natural or captures its intended
meaning across broader language. The induced frame mechanism is therefore
limited to exact relation substitution over a licensed structure.

Rule conjecture generation is a later extension. In this open-world store,
the absence of a proposition is unknown, not a negative example; negative
labels must come from explicit negative evidence or a separately justified
closed-world domain. Candidate conclusions must still pass independent proof
verification, and unproved candidates are retrieval targets rather than
facts. Active research can target such gaps only within an explicitly selected
corpus or task scope, then retain citation and independent-source checks.

An eventual coordinator may adapt bounded generation when a curriculum
plateaus, but acceptance counts alone are not a quality objective. Track
held-out correctness, false acceptance, coverage, novelty, resource cost, and
the user's selected task before broadening automatic promotion. The explicitly
invoked question-frame trainer is a narrow mechanically gated learning loop;
automatic primitive discovery, arbitrary output write-back, and curriculum
coordination remain future work.

### Additional domains through CRMS natural language (roadmap)

Coding, mathematics, and language translation are roadmap domains for CRMS,
and all three must be supported through the natural language of CRMS. A user
should be able to describe a task, ask a question, teach an example, refine
constraints, correct an interpretation, and inspect the result in ordinary
CRMS conversation, without switching to a domain-specific command language.
Routine use must not depend on memorizing command syntax or on a hidden
synonym list; explicit commands may remain for administration and debugging.
This is a roadmap direction, not a claim that all three domains already have
broad runtime support.

Natural language is the shared interaction layer, not a shared domain model:
CRMS must route a request to a typed coding, math, or translation operation,
then explain the selected operation and its evidence in ordinary CRMS
conversation. Domain-specific examples, constraints, and verification remain
explicit. A capability counts as naturally supported only when a user can
request it, refine or clarify it, receive a grounded result or principled
abstention, and inspect the relevant evidence without needing to know an
internal command syntax. Evaluate this interaction requirement separately for
coding tasks, mathematical tasks, and each translation language pair and
register. Command forms can remain available for precise administration and
debugging.

The coding domain now has an initial runtime slice: requests such as “Write
Python code that reverse the list” render a resolved, learned integer-list
procedure as inspectable Python. Exact associations work directly; learned
language retrieval can also resolve a paraphrase when it consistently selects
the same procedure across distinct inputs, and numeric-slot retrieval can
instantiate a new digit-valued parameter when multiple learned examples
support the same operation scaffold. For example, taught “add 3” and “add 5”
frames can license code for “add 4”; unsupported number-word meanings still
require grounded numeral evidence. For example, paired digit and number-word
rotation instructions can ground “twenty three” to `23`, which can then fill a
learned addition slot. The generated file contains
standalone Python for its supported primitive subset, records the stored
operation descriptors, and embeds `CRMS_PROVENANCE`: a machine-readable record
of the request, resolution route, evidence phrases, per-probe retrieval signals,
procedure, and source-linked examples. Its stable SHA-256 artifact id changes
when this record changes. It preserves source examples separately from
generated-rule parity examples, so a numeric-slot generalization does not
mislabel outputs for other parameter values as direct tests of the new rule.
The standalone file includes a runnable `validate_examples()` check against
recorded CRMS parity outputs. The generated function documents its
list-of-integers contract and comments each operation with its explicit effect
and parameter values. The
generator checks emitted behavior against the learned executor, the saved
demonstrations, and fixed edge probes; the emitted file is also exercised in a
separate Python process without importing CRMS. These checks verify rendering
and parity with CRMS's operation semantics, not general correctness. It
abstains when retrieval is unresolved or the procedure uses an operation not
yet supported by the standalone renderer. A bounded request grammar accepts
common forms such as “Can you write Python code to …?”, “Could you please
write me a Python function to …?”, and “I need you to write Python code that
…”; the task itself still has to resolve through learned CRMS language
evidence. The diagnostic checks every one of
the 72 default learner primitive candidates, including parameterized variants,
against the runtime executor on several edge-case inputs; it also checks
two-step learned procedures end to end. Representative binary and expression
window operations are checked too, including an end-to-end generated
window-expression rule from an explicitly extended grammar. This is code generation for the
existing bounded transformation grammar, not a general-purpose coding
capability or an independent correctness proof;
`experiments/v1_211_grounded_python_generation.py` checks the current slice.

Natural-language Python requests can also render a scalar expression through
the separately learned exact-math vocabulary. For example, after CRMS learns
that `glorp` means addition from distinct examples, “Write Python code to
compute x glorp y” emits a standalone `compute(x, y)` function. The artifact
records its expression tree, learned operator examples, grounded number
evidence, and exact-output probe cases. Division uses `fractions.Fraction` so
the generated function preserves rational results; modulo preserves exact
signed-integer remainder semantics. Its wrapper enforces CRMS's 4096-bit
input and exact-result bounds. A separate natural request
such as “Write Python code to compute x + y” uses the explicit standard math
grammar without requiring a learned word operator; generated provenance lists
standard symbols separately from learned phrases. Implicit multiplication is
also retained in artifacts such as `2x`. Finite decimal literals are emitted as
exact `Fraction` values and recorded as rational numerator/denominator pairs in
the artifact provenance. Unsupported words still need aligned
examples before code can be generated. A separate natural request
such as “Write Python code to convert x meters to centimeters” can render a
standalone exact conversion function when a consistent path is licensed by
aligned unit examples; “convert the amount from meters to centimeters” is also
supported. The generated function retains those examples and checks the same
arithmetic bound as CRMS. Scalar-expression generation accepts only licensed operators
and integer arguments. These code-generation paths do not cover arbitrary
programs or unit-bearing algebra and abstain on unsupported requests.
After generating code in the current chat session, a user can ask “Explain that
code” or “What does it do?” to inspect its learned operation, aligned examples,
and recorded parity checks. The explanation is rendered from the typed artifact
and does not add an interpretation beyond its stored procedure and provenance.
“Show the examples for that code” prints the exact retained training pairs for
the current artifact, including unit-ratio examples or learned math operators.
`experiments/v1_217_grounded_math_code_generation.py` checks exact operations,
rational division and modulo code generation, direct and transitive unit
conversion, arithmetic bounds,
conversational unit-example teaching with transactional rejection and
persistence, provenance inspection through follow-up turns, abstention, and
natural-language chat routing.
`experiments/v1_228_natural_domain_router_integration.py` seeds each bounded
domain from explicit examples, then routes coding, mathematics, translation,
factual question answering, grounded writing, and source-cited research in one
ordinary-language terminal session. It also retracts a fact by its licensed
sentence and exact source, rejects an ambiguous scoped retraction, and then
checks that selecting one exact context leaves other scopes intact. It confirms
the unscoped question no longer has support after its final source is removed,
and a subsequent `Why?` does not reuse the stale answer. Teacher-labeled
sentence examples are also used to learn a new fact frame and transfer it to a
new entity; a contradictory batch confirms transactional rejection.
This checks router coexistence and source-specific correction; it does not
expand the semantic coverage of each domain.

The shared language layer should route learned frames and lexical evidence to
typed domain representations. Each operation must retain its inputs, evidence,
provenance, and verification result. Ambiguous or out-of-grammar requests
should trigger clarification or abstention rather than guessed execution. Do
not force these domains into the current integer-list grammar or ordinary fact
triples.

Recommended staged development:

1. **Mathematics:** add typed expressions, variables, units, and bounded
   transformations with explicit side conditions. Use an independent symbolic
   checker for accepted steps; numeric spot checks are useful diagnostics but
   do not prove identities. Evaluate on held-out expression structures,
   boundary cases, units, and deliberately invalid transformations.
2. **Coding:** extend from the current exact procedure renderer to represent
   broader task contracts, input/output requirements,
   dependencies, and execution constraints; learn bounded code transformations
   from reviewed examples. Validate with compiler, type, static, and sandboxed
   execution checks for the properties they actually establish. Passing tests
   do not prove general correctness. Keep generated code inspectable and
   evaluate held-out and adversarial cases, toolchain versions, and requests
   that need clarification.
3. **Translation:** extend the initial teacher-declared frame prototype by
   learning from aligned examples with language, locale, and register metadata.
   Preserve meaning-bearing structure such as entities,
   predicates, polarity, tense, modality, and qualifiers; allow literal and
   idiomatic candidates to remain distinct. Evaluate on source-separated
   parallel data and semantic-role checks. Round-trip translation is a
   diagnostic, not an independent oracle, and every language pair and register
   needs evidence.

Expose these capabilities through common natural-language routing while
keeping each domain's representation and verifier explicit. Show the matched
frame, supporting evidence, typed operation, and check result where useful.
Treat domain coverage as evidence-specific and bounded; do not imply general
competence from success on a narrow grammar.

Cross-domain roadmap checkpoints:

1. **Natural-language access:** support ordinary requests, follow-up
   constraints, clarification, and teaching examples in each domain. Route by
   learned language evidence and typed task structure; abstain when the route
   or requested operation is unsupported.
2. **Inspectable results:** preserve domain-specific provenance and show the
   resolved procedure or expression, aligned translation frame, and applicable
   validation evidence. Never report a check as proving more than it tests.
3. **Held-out evaluation:** measure request routing, task correctness,
   ambiguity handling, and abstention separately for coding, math, and each
   translation language pair/register. Keep these evaluations distinct from
   general conversation and from command-line-only tests.

### Reasoning and retrieval diagnostics (roadmap)

The reasoning feedback pass found that several reported gaps have since been
addressed in the implementation. Relation declarations can include explicit
`irreflexive`, `asymmetric`, and `functional` integrity constraints, with
conflicts reported instead of silently returning a derivation. Inference results distinguish
`no_applicable_rule`, `missing_premise`, `search_limit`, proof rejection,
integrity conflict, and contradiction; failed searches retain bounded missing
premise details. Learned question frames can target relations supported by
verified rule proofs, including general entity-slot questions. The existing
`v1_185`, `v1_227`, `v1_66`, and `v1_67` diagnostics cover these paths;
`v1_185` now checks direct and derived functional conflicts too. These features
address the first three recommendations in the feedback, though they do not
establish broad natural-language coverage.

The remaining architectural proposals should be staged behind measured needs:

1. **Schema separation:** relation behavior and integrity declarations still
   use persisted `has relation type` facts. Move them to a separately
   validated schema store only when its migration, scope, provenance, and proof
   contracts are specified; preserve compatibility with existing model DBs.
2. **Consequences and closure:** inference is goal-directed. A bounded,
   incremental forward pass could report consequences of a changed fact, but
   needs explicit limits, invalidation rules, and independent proof checking
   before it is used for persisted results.
3. **Rule-language growth:** constants, inverse relations, multiple
   conclusions, negation-as-failure, numeric/time comparisons, and aggregates
   are not current rule features. A Datalog-style core is a possible later
   direction, contingent on a proof semantics for each construct and
   differential tests against the current bounded engine.
4. **Discovery quality and candidate durability:** the 1,162-fact source-separated
   diagnostic now covers cited language-frame acquisition, reviewed extraction,
   rule transfer to unlabeled pairs, linked distractors, and held-out
   counterexample rejection, but uses generated sentences. Expand evaluation to
   linked, noisy knowledge bases
   with known rules and planted counterexamples. Pending fact candidates already
   survive restart when their citation and learned-frame license still validate;
   `experiments/v1_217_natural_candidate_review.py` covers restore, later
   acceptance, rejection, and ambiguous queues. The loader removes invalid
   proposals from the active queue but retains their details and validation
   reasons in an inspect-only history. The same diagnostic covers
   source-revision invalidation, persistence of the reason, explicit clearing,
   and the rule that invalid candidates cannot be accepted until their evidence
   and license are revalidated.

Keep the current proof and abstention contract as the gate for these changes:
every new result needs a verifiable derivation or an explicit unknown/conflict
state, and incomplete search must not leak partial conclusions.

`experiments/v1_185_reasoning_contract.py` already checks proof verification,
malformed-proof rejection, complete absence versus incomplete search,
contradiction handling, typed schemas, and depth-limit abstention across
reasoning families. Keep this as a regression contract as inference schemas
and proof forms expand; add new families to its reported pass/fail output.
For typed three-premise rules it checks positive proofs, complete absence,
search-limit abstention, contradictions, and malformed kind evidence. The
symmetric-schema depth-limit regression is included. Inference contradictions
carry `reason_code="contradiction"` so callers can distinguish them from other
ambiguous outcomes. Re-run this diagnostic after changes to inference bounds,
schema application, or proof verification.

`experiments/v1_173_retrieval_route_ablation.py` disables seven learned
retrieval routes independently on 320 fixed held-out phrase/input pairs. In
the current run, parameterized numeric, aligned phrase, contrastive slot,
positional analogy, VSA fallback, and learned composition each lost all
route-focused answers when ablated. Lexical retrieval retained 16/32 correct,
showing overlap on part of its fixture. Exact phrase memory is separately
load-bearing. These fixtures demonstrate targeted route contribution; they do
not estimate each route's value across the full experiment corpus or measure
the effect of route order. The diagnostic now reports correctness, coverage,
wrong answers, abstentions, ambiguous requests, and evidence attribution.

Before removing or merging routes, extend this ablation to a shared held-out
corpus containing phrases eligible for multiple routes, conflict cases,
near-miss phrases, and unsupported requests. Compare each route removal with
the full router and preserve route disagreement handling in every variant.
`experiments/v1_229_shared_route_ablation.py` now supplies the first such
interaction fixture. On a phrase where numeric-parameter and aligned-phrase
routes support different procedures, the full router asks for clarification.
Removing either route independently makes the remaining route answer; removing
any of the other five tested routes preserves the conflict. The near-miss and
unsupported phrases abstain under all seven ablations. The expanded conflict
check includes empty, singleton, duplicate, negative, and mixed inputs, and
checks uncontested transfer for numeric values 6 and 7. This demonstrates that
the two routes jointly support safe conflict detection in this fixture; it is
not a broad estimate of router quality. Expand the corpus with more operations,
overlapping route combinations, and teacher-labeled resolutions before using
it to change route behavior.

For cross-domain maintenance, keep each domain's input types, semantic
representation, evidence record, and verifier explicit. Share the mechanical
discipline and evaluation format where possible; do not add a generic
canonicalizer merely to reduce code. Treat math scope as a deliberate boundary
decision: either maintain its current bounded expression, unit, and equation
operations with independent checks and diagnostics, or narrow operations based
on measured maintenance and evaluation costs. Coding and translation follow
the same per-domain evidence and validation discipline. Natural-language
routing remains a shared access layer, not a shared domain semantics layer.

## Scope

The long-term objective is a non-LLM system that can converse, write, answer
questions, and research by combining grounded language rules, explicit
knowledge, symbolic inference, and source-backed retrieval. The current
implementation now includes a terminal interface; example-based integer-list
rule learning; local text/PDF and explicitly requested bounded web retrieval;
cited positive and negative facts;
learned sentence, question, and path frames; controlled fact writing; and
short-turn dialogue with clarification and pronoun handling.

These are bounded capabilities, not broad language understanding. The shell
does not perform open-ended web search, parse arbitrary prose, discover facts
without evidence, or generate free-form essays. It can capture explicitly
requested pages and bounded same-origin crawls as cited research sources.
Language patterns may be explicitly taught or narrowly induced from
source-backed frames under mechanical checks; factual assertions still require
evidence, and answers abstain when
the stored rules or evidence do not identify a result. Further progress should
broaden typed operations beyond integer lists, support richer composition and
qualifiers in facts, improve language parsing and dialogue repair, and expand
retrieval while retaining provenance. Evaluate each addition on held-out
generalization, evidence traceability, ambiguity handling, and abstention.
The roadmap also includes mathematics, coding, and translation as typed
domains accessed through learned CRMS natural language, alongside richer fact
composition and qualifiers, improved language parsing and dialogue repair, and
broader provenance-preserving retrieval.
The next research-language priorities are broader corpus-driven relation
discovery with source-separated support, reusable frame induction from reviewed
claims, safer sentence-level role extraction, and held-out tests of paraphrase
and inverse-question transfer. These address the observed cost of teaching one
relation frame at a time while preserving explicit evidence review.
No neural language model, pretrained embedding, or hidden synonym list is part
of the current implementation. Learned lexical associations and deterministic
vector fallback remain evidence-based retrieval mechanisms rather than
general language understanding.
