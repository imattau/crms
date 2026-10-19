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
configuration all matter. For concrete reference points, Meta describes its
Llama 3.1 family as supporting broad knowledge, reasoning, coding, multilingual
use, and long context; its current docs point users to the later Llama 3.3 70B
Instruct model for that size class. Qwen2.5's technical report similarly
describes its 72B instruction model across language understanding, reasoning,
math, coding, long-text generation, and instruction following. These are
developer-reported evaluations, not independent guarantees of correctness.
[Meta Llama 3.1 overview](https://ai.meta.com/blog/meta-llama-3-1/),
[Meta model documentation](https://dev.meta.ai/llama/docs/model-cards-and-prompt-formats/llama3_1),
[Qwen2.5 technical report](https://arxiv.org/abs/2412.15115).

## Comparison by user task

| User task or interaction | Strong 70B+ instruction-model expectation | CRMS evidence and current boundary | Development implication |
|---|---|---|---|
| Ask a familiar question in ordinary wording | Usually answers directly across many phrasings, because language understanding and generation are learned across broad corpora. Coverage varies by topic and wording. | The cross-surface benchmark shows frame and entity transfer, but independently worded paraphrase/synonym groups remain much weaker than canonical forms. In v1_327, the paraphrase layer improved held-out answers substantially while retaining abstention on controlled negatives. | Prioritize broad, held-out language transfer. Track coverage and wrong answers separately; keep abstention for truly unsupported cases. |
| Ask about source material | Can summarize, answer questions, compare passages, and synthesize details when the text is in context or retrieved. Source fidelity and citations require explicit retrieval/tool design. | The chat corpus runs improved sentence retrieval, source labels, and quoted-evidence answers. Retrieval/ranking evaluations still expose ambiguity and occasional wrong selections; source text is not equivalent to a verified fact. | Make source-grounded answers concise and source-linked, and preserve the distinction between quoted evidence and accepted knowledge. |
| Ask a multi-part or follow-up question | Typically maintains conversational context, answers multiple requests, and adapts after clarification or correction, although it can lose details in long or complex conversations. | CRMS handles some explicit compound clauses and code/source explanation follow-ups. `v1_352` routes “How do you know?” and “Are you sure?” after quoted evidence to the same cited-source explanation as “Why?”. `v1_161` tests the entity switch “And Italy?” after a grounded capital question, with stored-frame and unsupported-entity controls. These are bounded dialogue operations; general context retention and open-ended follow-up remain incomplete. | Treat conversation management as a capability in its own right: detect all requested parts, retain referents, and report omissions. |
| Ask “why?” or request a derivation | Often provides a fluent explanation, but the explanation may not faithfully expose the internal computation or prove every claim. | CRMS can validate proof steps and render explanations with source lineage; its explanation experiment verified and parse-back checked all 31 controlled conclusions. This is a narrow symbolic domain. | Keep proof-backed explanations as a CRMS differentiator. Make the evidence chain readable and ensure each sentence is supported by verified steps. |
| Ask a multi-step reasoning question | Often attempts novel combinations and can explain a proposed chain; accuracy is uneven and fluent reasoning can contain errors. | The inference engine handles chains and lattices under bounded search, with proof caps and depth controls. Recursive depth, cycles, and integrity constraints remain important limits. | Expand reasoning through explicit composition, cycle/integrity checks, and measured search bounds rather than relying on fluent plausibility. |
| Ask for math | Commonly solves a broad range of routine and many advanced math tasks, but may make arithmetic or reasoning errors; dedicated tools improve exactness. | `v1_206` demonstrates grounded arithmetic and bounded equation operations, not general mathematical competence. | Grow the exact grammar and proofable operations; test unsupported notation, ambiguity, and adversarial cases. |
| Ask for code | Commonly drafts code, explains it, adapts it to instructions, and revises it interactively. Generated code can be syntactically plausible but incorrect or unsafe without execution and tests. | `v1_217` validates code generation for learned operators and exact bounds. `v1_355` adds a held-out multi-step sort/reverse composition, a contrastive teaching turn, CLI explanation/evidence follow-ups, and abstention on unsupported combinations. These remain bounded demonstrations, not open-ended programming. | Expand compositional coverage and functional validation in a bounded sandbox; correctness must come from tests, not code fluency. |
| Ask for translation | Often produces useful translations across common language pairs and can adapt tone/register; quality varies with language, domain, and ambiguity. | `v1_207` demonstrates example-grounded aligned-frame translation and persistence, not open-vocabulary translation. | Broaden reviewed lexicon and morphology while tracking slot preservation, adequacy, register, and ambiguity. |
| Ask for a creative or open-ended artifact | Can produce stories, plans, explanations, and varied prose from a brief, then revise to feedback. | CRMS's recombination benchmark (`v1_242`) succeeds on some learned grid combinations at higher example counts, but abstains on unseen hand-authored wording; this is not open-ended composition. | Add compositional schemas and controlled realization as separate capabilities. Preserve provenance for factual portions and label unconstrained generation distinctly. |
| Challenge or correct an answer | Can respond to correction conversationally, but may accept a false correction or change its answer inconsistently unless the interaction is constrained. | CRMS has explicit review, correction, provenance, and retraction mechanisms. These offer stronger inspectability where the knowledge is represented. | Make correction causal and persistent: show what changed, what depends on it, and which derived cases need revalidation. |
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
  development accuracy from 45/78 to 73/78, held-out accuracy from 28/45 to
  44/45, and unseen-set accuracy from 26/44 to 42/44, with zero wrong answers
  on those sets. Its controlled refusal checks also abstained on all negatives.
- `v1_242_grounded_recombination_benchmark.py`: learned components recombine
  successfully in a structured grid at larger example counts (16/16 at k=8
  and 8/16 at k=12); all controlled negatives abstained and no wrong answers
  were recorded. All 10 hand-authored unseen wordings abstained. This shows
  bounded compositional transfer, not general creative writing.
- `v1_206`, `v1_207`, and `v1_217` exercise bounded math, aligned translation,
  and learned-operator code generation respectively. They do not sample broad
  domain competence.
- `v1_355_learned_sequence_connective_codegen.py` demonstrates one user-facing
  multi-step coding path: repeated contrastive examples license `then`, a
  held-out operation sequence is recombined, code executes with parity, and
  the CLI answers explanation/evidence follow-ups. It does not compare with a
  70B model or establish general coding ability.
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

## Suggested interaction evaluation

For a later direct benchmark, use the same task text and source context for
CRMS and one pinned comparator. Include natural follow-ups, corrections, and
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
