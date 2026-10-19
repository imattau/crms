# CRMS and strong instruction models: capability and interaction comparison

**Purpose:** give CRMS development a realistic external reference for how a
strong instruction-tuned model in the 70B parameter class or above typically
handles tasks and user interaction. This is a qualitative comparison, not a
head-to-head benchmark. No external model was run for this document.

## How to read this comparison

- **CRMS result** means a result recorded by a named local experiment or
  runtime evaluation. It applies only to that test set and configuration.
- **Comparator expectation** means a broad capability pattern reported in
  model cards, technical reports, or product behavior. It is not a guarantee
  for every 70B+ model, prompt, language, or deployment.
- **Implication** is a design inference for CRMS, not an observed benchmark
  result.

Parameter count alone does not determine behavior. Training data, post-training,
instruction tuning, tool access, context limits, quantization, and runtime
configuration all matter. Two current, concrete reference points are Meta's
Llama 3.3 70B Instruct and Qwen3-235B-A22B. Meta describes Llama 3.3 as an
instruction-tuned assistant-chat model with multilingual text and code output;
its published card reports instruction-following, reasoning, coding, math, and
multilingual benchmark results. Qwen describes Qwen3 as supporting instruction
and thinking modes, 119 languages and dialects, coding, and agentic use; the
235B-A22B name denotes 235B total parameters with 22B activated per token.
These are developer descriptions and evaluations, not independent guarantees
of correctness. [Llama 3.3 70B model card](https://github.com/meta-llama/llama-models/blob/main/models/llama3_3/MODEL_CARD.md),
[Qwen3 model documentation](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/concepts.md).
For a concrete scale reference, Meta reports Llama 3.3 70B Instruct scores of
92.1 on IFEval, 88.4 pass@1 on HumanEval, 50.5 on GPQA Diamond, and 77.0 on
MATH. These are the model developer's results under the model-card protocols;
they are not directly comparable with CRMS's smaller, differently constructed
experiments or a claim of equal performance. [Llama 3.3 model-card results](https://github.com/meta-llama/llama-models/blob/main/models/llama3_3/MODEL_CARD.md).

## What the user typically experiences

A strong instruction model can often take an ordinary request, produce a
complete-looking answer or artifact in the requested format, and continue when
the user asks for a revision, explanation, or another related task. Depending
on the model and prompt, it can respond with prose, lists, tables, translations,
or code; some model families also expose selectable or hybrid thinking modes.
This is an expectation about broad instruction-tuned systems, not a claim that
every 70B+ model handles every request well. The claim is inferred from the
documented assistant-chat use cases and broad instruction, coding, and
multilingual evaluations above; CRMS has not been compared head-to-head here.

The user-facing answer is not itself a proof. A fluent model may omit a request
part, invent a detail, or produce code that fails. Citations and tool-backed
checks depend on the surrounding system, and a thinking mode does not by itself
guarantee that a displayed explanation faithfully represents the computation.
CRMS can expose proof steps and source lineage when the relevant facts and
rules are represented, but its user-visible coverage and wording flexibility
remain much narrower.

## Comparison by user task

| User task or interaction | Strong 70B+ instruction-model expectation | CRMS evidence and current boundary | Development implication |
|---|---|---|---|
| Ask a familiar question in ordinary wording | Usually answers directly across many phrasings, because language understanding and generation are learned across broad corpora. Coverage varies by topic and wording. | The cross-surface benchmark shows frame and entity transfer, but independently worded paraphrase/synonym groups remain much weaker than canonical forms. In v1_327, the paraphrase layer improved held-out answers substantially while retaining abstention on controlled negatives. | Prioritize broad, held-out language transfer. Track coverage and wrong answers separately; keep abstention for truly unsupported cases. |
| Ask about source material | Can summarize, answer questions, compare passages, and synthesize details when the text is in context or retrieved. Source fidelity and citations require explicit retrieval/tool design. | The chat corpus runs improved sentence retrieval, source labels, and quoted-evidence answers. Retrieval/ranking evaluations still expose ambiguity and occasional wrong selections; source text is not equivalent to a verified fact. | Make source-grounded answers concise and source-linked, and preserve the distinction between quoted evidence and accepted knowledge. |
| Ask a multi-part or follow-up question | Typically maintains conversational context, answers multiple requests, and adapts after clarification or correction, although it can lose details in long or complex conversations. | `v1_339` processes repeated explicit clauses separately and checks a supported first question followed by unsupported Minix: both parts are labeled, the first is answered, and the second is disclosed as unsupported. `v1_325` handles shared-verb entity lists and discloses a missing list item. `v1_352` routes “How do you know?” and “Are you sure?” after quoted evidence to the same cited-source explanation as “Why?”. `v1_161` tests the entity switch “And Italy?” after a grounded capital question. `v1_362` now verifies that source-only referents survive a CLI restart only while their citations resolve in the loaded index, and that ambiguous follow-ups ask for clarification. These are bounded dialogue operations; general context retention remains incomplete. | Treat conversation management as a capability in its own right: detect all requested parts, retain referents, and report omissions. |
| Ask “why?” or request a derivation | Often provides a fluent explanation, but the explanation may not faithfully expose the internal computation or prove every claim. | CRMS can validate proof steps and render explanations with source lineage; its explanation experiment verified and parse-back checked all 31 controlled conclusions. This is a narrow symbolic domain. | Keep proof-backed explanations as a CRMS differentiator. Make the evidence chain readable and ensure each sentence is supported by verified steps. |
| Ask a multi-step reasoning question | Often attempts novel combinations and can explain a proposed chain; accuracy is uneven and fluent reasoning can contain errors. | The inference engine handles chains and lattices under bounded search, with proof caps and depth controls. Recursive depth, cycles, and integrity constraints remain important limits. | Expand reasoning through explicit composition, cycle/integrity checks, and measured search bounds rather than relying on fluent plausibility. |
| Ask for math | Commonly solves a broad range of routine and many advanced math tasks, but may make arithmetic or reasoning errors; dedicated tools improve exactness. | `v1_206` demonstrates grounded arithmetic and bounded equation operations, not general mathematical competence. `v1_356` composes an exact scalar expression over every element in a list, preserving rational values and operator provenance. | Grow the exact grammar and proofable operations; test unsupported notation, ambiguity, and adversarial cases. |
| Ask for code | Commonly drafts code, explains it, adapts it to instructions, and revises it interactively. Generated code can be syntactically plausible but incorrect or unsafe without execution and tests. | `v1_217` validates code generation for learned operators and exact bounds. `v1_355` checks contrastive learning of `then`, transfers the connective to held-out operation pairs, and now verifies three- and four-clause compositions as executable, evidence-linked artifacts; an unsupported middle operation still abstains. `v1_356` maps exact math over list values. `v1_357` composes a learned list stage with an exact learned math map in one request, retaining both lineages and validating the composed artifact. These remain bounded typed operations, not open-ended programming. | Expand compositional coverage and functional validation in a bounded sandbox; correctness must come from tests, not code fluency. |
| Ask for translation | Often produces useful translations across common language pairs and can adapt tone/register; quality varies with language, domain, and ambiguity. | `v1_207` demonstrates example-grounded aligned-frame translation and persistence, not open-vocabulary translation. | Broaden reviewed lexicon and morphology while tracking slot preservation, adequacy, register, and ambiguity. |
| Ask for a creative or open-ended artifact | Can produce stories, plans, explanations, and varied prose from a brief, then revise to feedback. | `crms_story.py` now produces a deterministic five-beat fictional story from a topic and labels its details as invented; `v1_353` checks the chat route and topic clarification. `v1_242` still shows that recombination abstains on unseen hand-authored operation wording. CRMS does not yet support broad creative generation, planning, or revision. | Grow narrative composition from human-reviewed prompts and quality criteria; preserve the boundary between invented fiction and cited facts. |
| Challenge or correct an answer | Can respond to correction conversationally, but may accept a false correction or change its answer inconsistently unless the interaction is constrained. | `/wrong` is logged against the answer's proof/source references; validated learned rules used by a rejected proof are suspended as `needs_review`, while facts and teacher-supplied rules remain unchanged. Revalidation can restore a learned rule. This is still a narrow correction path, not broad belief revision. | Extend correction to exact fact/source disputes and derived-case dependents; measure false suspensions, recovery after revalidation, and abstention. |
| Ask about uncertainty or conflicting evidence | May hedge or cite sources when prompted or equipped with retrieval, but confidence language is not inherently calibrated and citations can be incomplete or mismatched. GPT-4's report explicitly notes that strong performance coexists with factual errors and reasoning mistakes. [GPT-4 technical report](https://arxiv.org/abs/2303.08774) | CRMS distinguishes accepted facts, quoted candidates, unsupported questions, and proof limits in many routes; extraction and candidate ranking can still fail. | Measure calibration by outcome, not tone. Keep source disagreement, unverified claims, missing premises, and unsupported requests distinct. |

“Typically” here describes the interaction range a user can reasonably expect
from a well-tuned large instruction model: a natural-language request can often
be handled without first teaching one frame per relation, and the user can
follow up in ordinary language. It does not mean a large model is always right.
Published technical reports document hallucinations and remaining reliability
limits even for highly capable systems. [GPT-4 technical report](https://arxiv.org/abs/2303.08774).

## What CRMS's measurements currently say

These results are component evidence, not a single overall capability score:

- `v1_315_cross_surface_question_transfer.py`: canonical and explicitly
  licensed frames transfer strongly in the controlled fixture; independent
  paraphrase and lexical-synonym groups remain a major gap. The benchmark
  records zero wrong near-misses in its fixed set, but that is not a general
  safety guarantee.
- `v1_327_paraphrase_benchmark_nl_layer.py`: the language layer raised
  development accuracy from 50/78 to 73/78, held-out accuracy from 31/45 to
  44/45, and unseen-set accuracy from 29/44 to 42/44, with zero wrong answers
  on those sets in the current runtime. Its controlled refusal checks also
  abstained on all negatives. These remain benchmark-wrapper results, not a
  70B comparison or a claim about production chat coverage.
- `v1_242_grounded_recombination_benchmark.py`: learned components recombine
  successfully in a structured grid at larger example counts (16/16 at k=8
  and 8/16 at k=12); all controlled negatives abstained and no wrong answers
  were recorded. All 10 hand-authored unseen wordings abstained. This shows
  bounded compositional transfer, not general creative writing.
- `v1_206`, `v1_207`, and `v1_217` exercise bounded math, aligned translation,
  and learned-operator code generation respectively. They do not sample broad
  domain competence.
- `v1_355_learned_sequence_connective_codegen.py` demonstrates two held-out
  sequence crossings using one contrastively learned `then` connective, then
  composes three and four grounded clauses into verified artifacts at the
  default bounded rule depth. The four-clause case passes four held-out input
  probes through generated code and natural-language chat; an unsupported
  middle operation abstains. The code retains component and connective
  evidence. This is controlled composition, not general coding ability or a
  70B comparison.
- `v1_356_grounded_math_list_composition.py` checks a request that crosses
  math and code: it applies a learned exact scalar expression elementwise,
  preserves fractional results, embeds scalar and outer composition
  provenance, and routes through the terminal's explanation/evidence turns.
  Its constraints and refusal cases are local tests, not broad coding parity.
- `v1_357_cross_domain_list_math_composition.py` composes a transferred
  sequence rule and a learned exact math expression in one code request. It
  checks both components, the combined behavior, and recombines the same
  sequence with a second formula that returns exact fractions. It also checks
  deterministic provenance, refusal when either stage lacks support, a polite
  natural-language function request, and chat explanation/evidence follow-ups.
  The connective transfers to a new remove-duplicates→sort pair before math is
  applied.
  It also checks that stage-specific failures suggest the right next step and
  that an explanation after a failed generation does not reuse stale code.
  This demonstrates bounded reuse across a small cross-product, not the
  planning breadth or interaction
  flexibility of a 70B+ model.
- `v1_350` and `v1_351` test direct-edge preference and verified proof
  explanations. The explanation set achieved 31/31 verified and round-tripped
  cases, with structured fallbacks where no learned wording existed. This is
  evidence for proof transparency on the tested graph, not for open-domain
  explanations.

The detailed experiment conditions and caveats are recorded in
[`benchmark_baselines.md`](benchmark_baselines.md). Do not add these unlike
sample sets into a single percentage: they measure different tasks, routes,
and evidence standards.

## Overall assessment

CRMS is not currently comparable to a strong 70B+ instruction model in breadth,
language flexibility, open-ended generation, or conversational range. A large
instruction model can usually attempt a much wider set of requests and keep a
natural-language exchange moving with less explicit setup. Its output can be
useful and fluent, but fluency does not establish correctness, provenance, or
faithful reasoning.

CRMS has a different, narrower strength: where facts, rules, frames, and
procedures are represented and verified, it can expose exact evidence,
proofs, lineage, review status, and correction effects. That architecture
doesn't compensate for missing coverage. Users need both: broad understanding
and flexible composition, plus reliable ways to ground, inspect, correct, and
retract what the system says.

The useful development target is therefore not “sound like a 70B model.” It is
to close the user-visible gaps—ordinary-language coverage, multi-part request
handling, follow-up continuity, useful composition across math/code/translation
and knowledge—while retaining explicit evidence and verification. Progress
should be reported as task-specific coverage, correctness, abstention, and
interaction quality. No parity claim is supported by the current measurements.

## Optional future interaction evaluation

The qualitative comparison above is sufficient for roadmap direction; it does
not depend on running a large model. If a later direct evaluation would answer
a specific open question, use the same task text and source context for CRMS
and one pinned comparator. Include natural follow-ups, corrections, and
requests for concise versus detailed output. Score:

1. whether every requested part was answered;
2. correctness and source support of each claim;
3. whether uncertainty and missing information were stated accurately;
4. whether the system handled clarification and correction consistently;
5. answer usefulness, brevity, and readability;
6. evidence quality, with proof verification measured separately from prose;
7. coverage, abstention, latency, and resource use.

Use human-written prompts alongside generated controls. A helpful answer with
no traceable source and a grounded answer that misses half the user's request
are different failure types, and the evaluation should preserve that distinction.
