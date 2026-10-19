# Large-corpus natural-language chat audit

**Run date:** 2026-10-18  
**Model:** `data/crms_project_model_academic.sqlite` (copied to a temporary directory for the chat run)  
**Corpus at first audit:** 857 indexed documents: 297 project sources and 560 arXiv records. A later expansion reached 1,994 indexed documents: 297 project sources and 1,697 arXiv records. All arXiv records have metadata and abstracts; 8 exact-version CC0/CC BY records also have full text. The current merged source text is 7,289,502 UTF-8 bytes (910,842 CRMS word units). This is a useful retrieval stress corpus, not a measure of LLM-scale knowledge.

## What I exercised

I drove `crms_chat.py` through the portable-model path with temporary dialogue and review-state files. Prompts covered paper lookup, paraphrases, multi-document/topic questions, follow-up references, summarization, latest/recent wording, unsupported facts, and conversational basics. I asked questions in software testing, protein-function prediction, spoken question answering, graph theory, and machine learning.

## Observed behavior

| Prompt or prompt pattern | Observed result | Gap |
|---|---|---|
| “What research topics are represented in this model?” | “Please name the entity this pronoun refers to.” (reproduced with both corpus sizes) | Deictic reference (“this model”) is treated as unresolved conversational pronoun, even though the intended referent is the loaded corpus/model. |
| “What does the research say about spoken question answering and speech recognition errors?” | Retrieved the matching arXiv title and abstract sentence, with citation. | Retrieval can find evidence, but the answer remains a quoted evidence block rather than a synthesized, direct response. |
| “How can software testing detect bugs when there is no known correct output?” | Retrieved a broadly relevant testing paper, but its abstract described testers’ cognitive processes, not the requested technique. | Lexical/topic proximity can beat the answer-bearing document; no explicit “evidence does not answer this” check. |
| “Tell me about the paper that studies toroidal graph cops.” | Asked which entity “that” refers to. (reproduced with both corpus sizes) | Relative-clause / anaphora question form fails despite an exact title in the corpus. |
| “What is the main result of *On the cop number of toroidal graphs*?” | Correctly quoted “the cop number of toroidal graphs is at most 3.” | Exact title lookup works. |
| “Can you explain the result in simpler terms?” | On the expanded corpus, returned an unrelated paper about explaining why-questions. In the earlier run it emitted an unrelated review candidate about spoken QA. | Follow-up resolution and candidate relevance are broken; the antecedent “result” is lost and unrelated evidence leaks into the answer path. |
| “What is the latest research in machine learning in this corpus?” | Asked to ground “the latest research” as a cardinal value (reproduced with both corpus sizes). | Temporal adjective “latest” is misclassified as a number phrase instead of a sort/filter request. |
| “What can you do?” | Returned “Ask about indexed sources or accepted facts...” | Functional but terse; conversational capability prompt is not handled as a distinct helpful template. |
| “Tell me a joke.” | Returned a concise scope statement. | Safe abstention works. |
| “Who won the 2024 Nobel Prize in Physics?” | Said it did not know from the sources and facts it had. | Correctly distinguishes absent support from source-backed evidence. |
| “Thanks” | Returned “You’re welcome.” | Basic courtesy handling works. |

Additional corpus questions such as “What are some papers about testing software?” and “What do the sources say about protein function prediction?” found plausible papers, but returned only the best paper’s title/abstract excerpt. “Which papers discuss spoken question answering?” did not produce a multi-paper list; on the expanded corpus it produced an unverified fact candidate from one abstract instead. Summarizing the cop-number paper selected the exact result sentence but also added several unrelated graph papers, reducing precision.

## Priority gaps from this run

1. **Conversation-state isolation and relevance gating.** Pending candidate review must not interrupt an unrelated follow-up or attach an unrelated candidate. Resolve “that result” against the immediately previous answer before routing to global candidate review.
2. **Question intent and reference resolution.** Handle corpus/model deictics, relative clauses, “explain that,” and multi-turn references before treating words like “this,” “that,” or “latest” as unresolved pronouns/entities/numbers.
3. **Answerability after retrieval.** A high lexical match is not enough. Check that the retrieved sentence supports the requested relation or method; otherwise say the corpus found a nearby topic but no direct answer.
4. **Multi-document retrieval.** “Which papers” and “what topics” should return a short, cited list or corpus-level answer, not silently collapse to one hit.
5. **Summary precision.** For a named paper, constrain extractive summary selection to that document unless the user requests comparison or broader context.
6. **Answer realization.** Where evidence directly states a result, lead with a concise natural sentence and keep citation/diagnostics secondary. Preserve explicit uncertainty when the evidence is only an abstract or is indirect.

## Reproduction

```sh
tmpdir=$(mktemp -d)
cp data/crms_project_model_academic.sqlite "$tmpdir/model.sqlite"
printf '%s\n' \
  'What research topics are represented in this model?' \
  'Tell me about the paper that studies toroidal graph cops.' \
  'What is the main result of On the cop number of toroidal graphs?' \
  'Can you explain the result in simpler terms?' \
  'What is the latest research in machine learning in this corpus?' \
  '/quit' | python3 crms_chat.py --model-db "$tmpdir/model.sqlite" \
    --dialogue-state "$tmpdir/dialogue.json" \
    --candidate-session "$tmpdir/candidates.json" \
    --rule-session "$tmpdir/rule-session.json" \
    --math-session "$tmpdir/math-session.json" \
    --translation-session "$tmpdir/translation-session.json"
rm -rf "$tmpdir"
```

## Follow-up: corpus-derived relation-frame quality

I ran the relation-frame miner over all 2,006 indexed documents (up to 100,000
sentences). The first pass yielded 23 proposals. Manual inspection found
function and reference words proposed as relations (`this`, `its`, `is`),
fragments such as “Natural questions now require”, attachment words such as
`using`, and title/list residue. The miner now requires a complete punctuated
sentence, rejects all-function-word relation strings and malformed relation
surfaces, and avoids treating determiners, pronouns, and common clause-opening
words as named subjects in the bounded surface parser. Negative class claims
also require a capitalized subject, so clipped lowercase continuations do not
become named facts.

On the same full-corpus run, the proposal count fell from 23 to 3. The remaining
review-only frames were `is-a` (8 examples across 6 sources), `achieves` (2
across 2 sources), and `returns` (2 across 2 sources). A bounded common-noun
copular pattern now recovers statements such as “The parser is a tokenizer”
while rejecting pronoun subjects and lowercase fragments. This is a substantial
precision improvement and a small recall gain; active relation extraction
still relies heavily on capitalization and inflection heuristics.

The reviewed `is-a` frame now also supports bounded definition and polar forms:
“What is the parser?” and “What kind of thing is the parser?” return
“tokenizer,” and “Is the parser a tokenizer?” returns “Yes.” “Is the parser a
compiler?” remains unknown because the corpus has no positive or negative fact
for that claim. Through the chat CLI, CRMS reports its stored parser→tokenizer
fact and says that no evidence establishes the compiler claim; it no longer
substitutes a nearby source excerpt for this recognized question. These forms
use explicit `is-a` facts and do not turn missing evidence into a false answer.
The runtime diagnostic also confirms the truth boundary: explicitly negative
type evidence returns “No,” missing evidence stays unknown, and positive plus
negative evidence for the same type is reported as ambiguous.

I accepted the two-source `achieves` proposal into a fresh in-memory learner.
CRMS answered “What does RSIFlow achieve?” and “What does TITAN achieve?” from
the reviewed facts, and abstained for “What does a new method achieve?” The
CLI realizes the two supported answers as declarative sentences. For the
unseen subject it explains that the `achieves` question frame is understood,
but no accepted fact is stored, then asks for a fact or source instead of
showing a nearby lexical match. The source-derived frame is useful after
review; it does not invent an unseen subject's result.
`experiments/v1_274_corpus_relation_learning.py` reproduces
mining, review, both answers, an inverse “Who achieves BLEU improvements?”
question, and abstention for an unseen subject. “Which method achieves the
SOTA average performance?” still needs a separately learned wh-frame. The
corpus quality and end-to-end diagnostics passed alongside the chat diagnostics
above.

## Follow-up: corpus-level language and described-paper requests

**Run date:** 2026-10-19. I drove the actual chat CLI against the 2,006-document
research index with fresh temporary dialogue and memory paths. The corpus
overview query and the described-paper query both exposed language routing
gaps. “What research topics are represented in this model?” was sent to
ordinary source search, and “Tell me about the paper that studies toroidal
graph cops” treated the relative “that” as an unresolved entity pronoun.

The chat now recognizes corpus overview questions and reports recurring terms
from indexed research titles, with representative citations and an explicit
label that this is a rough overview rather than a topic taxonomy. Described
paper requests route to the existing title-focused paper-list path. The
dialogue resolver treats “this model” and relative-clause “that” as grammar,
not entity references. Paper topic matching also handles simple plural forms
such as “cops” / “cop” and “graphs” / “graph”.

The same CLI pass now lists the intended *On the cop number of toroidal
graphs* paper for the relative-clause query. The main-result question still
returns quoted evidence, and “explain the result in simpler terms” correctly
abstains because no verified paraphrase rule exists. The protein-function
query returns one title-focused paper and one clearly labeled related paper.
The supervised-versus-unsupervised query still finds a source that mentions
both terms without contrasting them, then correctly says that the co-mention
does not establish a difference. The latest machine-learning request returns
recent topic-focused items, though it remains extractive and does not compare
their results.

`experiments/v1_273_natural_corpus_language.py` checks the corpus overview,
relative-clause handling, and the selected paper against the large index.
`v1_269_topic_paper_lists.py` and `v1_264_latest_dated_research.py` now run the
CLI directly against the corpus research index with temporary memory paths;
this keeps those runtime checks independent of the separate portable model
database packaging format. All three diagnostics passed after the routing and
matching changes.

## Follow-up: topicality in latest-research results

The latest-research route previously required all topic terms somewhere in a
dated record, then sorted only by publication date. That allowed a paper whose
abstract mentioned “graph neural networks” only as a baseline to precede
papers focused on graph neural networks. The chat route now labels results as
topic-focused when all topic terms appear in the title or first abstract
sentence, then orders those records by date. It can include one newer broad
mention in a separate section when that mention is newer than the focused
results. Code files are excluded from dated research results even if a test
fixture contains a `Published:` string.

`python3 experiments/v1_271_latest_topic_relevance.py` checks the ranking and
labels on synthetic cases and the 2,006-document corpus. On “graph neural
networks,” MAEM and Graph Additive Models now precede the newer but broader
GraphBEAT mention. `python3 experiments/v1_264_latest_dated_research.py` and
the full `python3 experiments/v1_266_large_corpus_chat_followups.py` regression
pass after the change. This is a bounded title/opening-sentence relevance
heuristic; it does not infer full paper topic or contribution.

## Follow-up: method-reference follow-ups

Full questions such as “Why does this method work?” now bind to the most recent
source result instead of entering entity-pronoun resolution with an unbound
“this.” CRMS searches that source's abstract for an explicit causal sentence
and quotes it with an exact citation. If it finds only a procedural sentence,
it labels it as a description of how the method is applied and states that the
source does not explain why it works. If neither is available, it says the
source gives no explanation and quotes its first abstract sentence. This is
source-grounded reference resolution, not an inferred explanation.

`python3 experiments/v1_272_research_method_followups.py` checks causal,
procedural-only, and live multi-turn cases. The full 2,006-document chat
regression and dated-research follow-up diagnostic also pass after this change.

## Follow-up: mathematical proof intent routing

The math-proof failure above came from exact lexical overlap: the query term
`sqrt` matched paper titles and “prove” matched an unrelated abstract, while
the selected evidence did not contain “irrational.” CRMS now recognizes a
bounded set of explicit mathematical proof requests after the supported exact
math route has had a chance to answer. If that route cannot solve the request,
chat states that it has no verified proof rule instead of presenting loosely
matching research as a proof. This is an abstention boundary, not a theorem
prover; the class of mathematical cues is deliberately small and will need
expansion alongside actual proof mechanisms.

`python3 experiments/v1_268_math_proof_routing.py` validates that the
irrationality-proof request abstains without the unrelated bandit paper, while
`2 + 3` still returns exact arithmetic. The existing large-corpus regression
`python3 experiments/v1_266_large_corpus_chat_followups.py` also passes on the
full 2,006-document portable model after the routing change.

## Follow-up: topic-based paper lists

The corpus sweep showed that “Which papers ...?” requests were falling through
to single-answer retrieval. Chat now recognizes bounded paper-list forms such
as “Which papers discuss X?” and “List studies about X.” It ranks the retrieved
documents by topic-term coverage in their titles and abstracts, returns direct
title matches separately from related term matches, includes a sentence and a
source link for each, and abstains if candidates share too few terms. A rarer
topic term acts as an anchor so common words like “function” and “prediction”
do not admit unrelated papers.

On the 2,006-document corpus, “Which papers discuss protein function
prediction?” returns the exact-title match *Metamorphic Testing for Quality
Assurance of Protein Function Prediction Tools* and labels *Deep Learning of
High-Order Interactions for Protein Interface Prediction* as a related
two-of-three-term match. The separate diagnostic
`python3 experiments/v1_269_topic_paper_lists.py` also verifies a corpus with
an unrelated one-term distractor and a no-match topic; the distractor is
excluded and the no-match request abstains. This remains lexical, auditable
topic matching rather than semantic paper understanding. Display order is
retained across turns, and “What does the second paper say?” summarizes the
second listed source with its identity and citation preserved.

## Follow-up: source-grounded comparison questions

The sweep's “What is the difference between supervised and unsupervised
learning?” prompt had returned a nearby semi-supervised definition as if it
answered the comparison. CRMS now recognizes explicit two-concept comparison
forms and searches for a sentence containing both concepts plus an explicit
contrast marker (such as “whereas” or “unlike”). It quotes that sentence when
found. If a source only co-mentions both concepts, CRMS cites the passage and
says it cannot establish their difference from that evidence.

`python3 experiments/v1_270_source_grounded_comparisons.py` verifies both
branches and drives the live academic corpus. It confirms that the
semi-supervised abstract is identified as a co-mention, not a direct
supervised-versus-unsupervised comparison. This does not yet support
comparisons based on definitions spread across multiple sources or learned
comparison rules.

## Follow-up: date-aware latest-research questions

The first run exposed that “What is the latest research in machine learning in
this corpus?” was sent to exact math and interpreted as a missing cardinal.
The arXiv index also contained mostly 2019–2020 records because its existing
pages were relevance ordered. The importer now accepts `--sort-by
submittedDate`, and six subject pages were added in descending submission
date order. `search_latest` uses SQLite FTS to require all topic terms, then
orders matching records by an explicit `Published:` date. In the updated
portable chat, the same question returns three cited papers dated 2026-10-15;
the ordinary `What is 2 + 3?` still returns exact arithmetic. The targeted
diagnostic is `python3 experiments/v1_264_latest_dated_research.py`.

The chat now retains the first cited source from a research response for the
next turn. “Can you explain the result in simpler terms?” returns the exact
abstract sentence and link from that source, and says plainly that CRMS has no
verified paraphrase rule yet. This prevents the previous follow-up from
drifting to a different paper. It resolves the reference and preserves
provenance. A same-language plain-register frame can now supply a rewrite when
the sentence fits a teacher-aligned template. Two examples for the cop-number
result license the rule “We show that the cop number of {graph} is at most
{number}” → “You need no more than {number} cops to catch a robber on {graph}.”
Chat applies it to the cited paper, retains the citation, and reports the
aligned-example count. This verifies template reuse and slot copying; it does
not prove that arbitrary paraphrases are semantically equivalent. The runtime
check also confirms the taught frame is reintegrated into the portable SQLite
model. With no matching frame or missing slot mappings, CRMS abstains and shows
the source.

Named-paper summaries now select a unique title-matched source before sentence
selection. “/summarize the paper on the cop number of toroidal graphs” stays
within arXiv:1904.07946v3, including “show more sentences.” An underspecified
paper request such as “the paper about Python” asks for more title text instead
of combining unrelated works.

Other language gaps from the audit remain open: deictic and relative-clause
resolution, broad paraphrase coverage, evidence answerability, multi-paper
listing, and robust title resolution for varied ways of referring to a paper.

## Follow-up: cross-domain question sweep

**Run date:** 2026-10-19  
**Corpus:** same 2,006-document portable academic model, copied with its
memory sidecar into a fresh temporary directory; every chat used temporary
dialogue and review state. No project model state was changed.

I drove an additional mixed-domain sequence through the actual CLI:

| Prompt | Observed result | Gap or interpretation |
|---|---|---|
| “How do I prove that sqrt(2) is irrational?” | Returned an unrelated arXiv paper on zeroth-order adversarial bandit regret. | Math intent was not routed to exact math or a clarification path; lexical research retrieval supplied irrelevant evidence. This is a high-priority routing and answerability failure. |
| “Translate ‘good morning’ into French.” | “No learned source frame matches this sentence for the target language.” | Honest abstention: translation has no matching learned frame. The response could offer a concrete next step, but it did not invent a translation. |
| “Write a Python function that reverses a list.” | Asked to teach the operation or clarify it before generating code. | Honest capability boundary for an operation not represented in the learned code grammar; coding is not yet general-purpose. |
| “What is the difference between supervised and unsupervised learning?” | Returned one source sentence defining semi-supervised learning. | Near-topic lexical retrieval was presented as an answer without checking that the evidence addresses the requested contrast. |
| “Which papers discuss protein function prediction?” | Returned one paper about testing protein-function prediction tools, quoting a general motivation sentence. | “Which papers” collapsed to one hit and the ranking favored a co-occurring phrase over papers directly about prediction methods. |
| “Why does this method work?” | Asked which entity “this” refers to. | Expected without prior context; question demonstrates the need for a prior-answer antecedent. Combined with the earlier follow-up regression, contextual reference handling remains fragile. |
| “What are the newest papers about graph neural networks?” | Returned three date-sorted papers; the first is about cancer risk stratification and only the second is directly about graph learning. | Date sorting works, but topical relevance is too weak for a “newest about X” request. Topic filtering/ranking needs a relevance threshold. |
| “What is the connection between retrieval and reasoning in CRMS?” | Returned a sentence saying retrieval is useful before a relation frame is taught. | The sentence is relevant to retrieval, but does not answer the requested relationship between retrieval and reasoning. Evidence-answerability remains absent. |
| “Summarize the evidence about software testing without an oracle.” | Returned a five-sentence extractive summary spanning unrelated software-testing papers. | Summary selection is too broad for a focused method question; it should constrain to answer-bearing sources or say evidence is insufficient. |

This sweep strengthens the separation between **coverage** and **language
behavior**. More source documents may improve topic coverage, but they will not
fix domain routing, question intent, answerability checks, comparative/list
intent, or follow-up reference resolution. The next evaluation should score
each response on (1) route selection, (2) whether cited evidence answers the
question, (3) directness, and (4) abstention quality. Translation and code
responses above are appropriately cautious; their main shortcoming is that
they do not offer a useful bounded next step.

Reproduce the mixed-domain sequence (it runs in one conversation so the last
prompt also exercises dialogue state):

```sh
tmpdir=$(mktemp -d)
cp data/crms_project_model_academic.sqlite "$tmpdir/model.sqlite"
cp -a data/crms_project_model_academic.sqlite.memories "$tmpdir/model.sqlite.memories"
printf '%s\n' \
  'How do I prove that sqrt(2) is irrational?' \
  'Translate “good morning” into French.' \
  'Write a Python function that reverses a list.' \
  'What is the difference between supervised and unsupervised learning?' \
  'Which papers discuss protein function prediction?' \
  'Why does this method work?' \
  'What are the newest papers about graph neural networks?' \
  'What is the connection between retrieval and reasoning in CRMS?' \
  'Summarize the evidence about software testing without an oracle.' \
  '/quit' | python3 crms_chat.py --model-db "$tmpdir/model.sqlite" \
    --dialogue-state "$tmpdir/dialogue.json" \
    --candidate-session "$tmpdir/candidates.json" \
    --rule-session "$tmpdir/rules.json" \
    --math-session "$tmpdir/math.json" \
    --translation-session "$tmpdir/translations.json"
rm -rf "$tmpdir"
```

## Follow-up: answer presentation and topic drift

**Run date:** 2026-10-19. I drove a fresh CLI session against the 2,006-document
academic research index with separate temporary knowledge, dialogue, and review
state. The corpus overview, named-paper follow-up, latest-topic results,
protein-function paper list, and supervised-versus-unsupervised abstention all
behaved as described above. This pass focused on whether ordinary questions
get a direct, question-shaped answer and whether unrelated state leaks into
them.

| Prompt | Observed result | Gap |
|---|---|---|
| “What is the main result of On the cop number of toroidal graphs?” | Returned a metadata block (title, abstract, authors, date and license), even though the abstract contains a direct result sentence. | Named-source retrieval does not consistently lead with the answer-bearing sentence; presentation remains retrieval-shaped. |
| “Can you explain the result in simpler terms?” | Correctly retained the cited paper and said no verified paraphrase rule exists, then quoted its result sentence. | Honest boundary and follow-up resolution work; the response offers no grounded next step or simpler explanation. |
| “How can software testing work when there is no known correct output?” | Returned the genetic-algorithm testing abstract, including its metamorphic-testing method and evidence. | Relevant and answer-bearing, though still a long raw abstract instead of a concise answer sentence. |
| “What does the parser do?” | Returned a source sentence about a “narrow learned compositional rule” rather than an answer about the parser. | A lexical hit on “parser” can outrank the requested entity/relation and be presented as evidence without an answerability check. |
| “What is a tokenizer?” | Proposed `parser — is-a → tokenizer` from a source sentence and asked for review. | Review is appropriately gated, but the sentence is an example of a tokenizer, not a definition of tokenizer; the candidate does not answer the question. |
| “Tell me a joke.” / “What can you do?” / “Thanks.” | Scope statement, capability prompt, and courtesy response were concise and appropriate. | Basic chat templates work, though “What can you do?” could describe concrete supported actions. |
| “Who won the 2024 Nobel Prize in Physics?” | Said it did not know from available sources and facts. | Correct abstention. |

This run separates three problems that can look alike in a transcript:
(1) source coverage, (2) whether a retrieved sentence answers the requested
relation, and (3) how supported information is phrased. The parser result is a
relation/answerability failure, while the named-paper block and long abstract
are response-construction failures. Adding documents alone will not repair
those two behaviors. The candidate review path also needs to check that a
candidate has the right semantic role for the query before showing it as a
possible answer.

The named-paper main-result failure now has a bounded answer-first route.
“What is the main result of On the cop number of toroidal graphs?” resolves
the unique title, selects the abstract sentence beginning “We show,” returns
that source sentence with a short paper link, and retains its exact citation
for a follow-up. If the abstract has no recognizable result cue, CRMS says it
cannot isolate the result instead of choosing an arbitrary sentence.
`python3 experiments/v1_275_answer_first_paper_results.py` checks both the
live corpus and synthetic clear/unclear abstract cases. A targeted follow-up
now handles the parser relation and tokenizer example gaps with bounded
question-frame rules: “What does the parser do?” no longer quotes a one-term
mention as an answer and asks which parser the user means when no accepted
action fact is available. If matching action facts have been accepted, the
reply uses those facts. “What is the
parser?” routes to the matching review-only `parser — is-a → tokenizer` claim;
and “What is a tokenizer?” labels that inverse instance claim as an example,
not a definition. These behaviors are checked by
`python3 experiments/v1_276_question_role_answerability.py` against the live
corpus and chat CLI. This improves these specific learned fact and query-frame
interactions; it is not general semantic parsing.

The session used only temporary conversational stores; it read the academic
research index in place. The results above are reproduced by the input batch
in the runtime transcript. I repeated “What does the parser do?” and “What is
a tokenizer?” as separate first-turn queries with fresh temporary state; both
original behaviors reproduced, so they were not caused by follow-up context.

## Follow-up: PMC full text and quoted paper requests

**Run date:** 2026-10-19. I merged 20 CC BY/CC0 PMC full-text articles with the
2,933-document expanded model, then drove the packaged model through fresh
chat state. The 2,953-document evaluation corpus contains 9,932,862 UTF-8
bytes (1,300,612 CRMS word units; this is not an LLM token count). The
distributable model is
`data/crms_project_model_academic_expanded_pmc.sqlite`.

| Prompt | Observed result | Gap or improvement |
|---|---|---|
| `Summarize 'Cross-domain signal grammars of transcription termination'` | Initially mixed the named paper with unrelated arXiv papers because quote marks at the title boundaries survived tokenization. After fixing boundary normalization and excluding labeled metadata, figure-caption blocks, and table rows, it returns two relevant prose sentences from the named paper. | Quoted exact-title lookup and layout-aware extraction are covered by `v1_279_quoted_paper_title_scope.py`. Explicit table and figure requests still retrieve their corresponding structured content. |
| `Who are the authors of 'Cross-domain signal grammars of transcription termination'?` | Initially returned a raw metadata block. It now returns `Authors: Shouqing Hou, Hongru Ma, Xuye Lang, Yuan Yao` with a short source tag and exact follow-up citation. | A bounded author-field route reads source metadata without trying to paraphrase it. |
| `What is the main result of 'Cross-domain signal grammars of transcription termination'?` | Initially reported no abstract because the JATS importer did not label the abstract element. After adding `Abstract:` during import, the first detector still abstained on the review’s “showing how” wording. It now returns the exact abstract sentence about shared kinetic constraints and divergent molecular solutions. | JATS abstract labeling and the narrow “showing how” result cue are checked against fixture and real PMC text. Existing packages need a rebuild to gain the label. |

The evaluation showed that title scope, metadata separation, and result
sentence selection are separate mechanisms. Source volume alone did not fix
them. The importer now accepts the current PMC dataset’s canonical
`s3://pmc-oa-opendata/...` object URLs by translating that exact bucket to its
public HTTPS endpoint, then retaining its license and checksum checks. The
offline importer diagnostic and JATS diagnostic pass. `v1_279` checks exact
title scoping, clean author lookup, abstract result extraction, quote variants,
decoy rejection, and runtime behavior against a 2,933-document base corpus.
General summaries now suppress pipe-delimited table rows and figure-caption
blocks while retaining them for explicit table, figure, caption, row, or column
requests. An explicit table request trims an adjacent figure caption when both
were flattened into one text span. Runtime checks on the real PMC paper confirm
that the general summary returns prose claims and the explicit Table 1 request
returns a Markdown table with its original headers and cell wording, excludes
the Figure 1 legend and other table numbers, and carries the exact source-span
citation. `v1_279_quoted_paper_title_scope.py` now checks this through both the
research API and chat CLI. More complex table layouts and multi-page tables
still need corpus evaluation.

## Follow-up: broad encyclopedia corpus and natural-language chat

**Run date:** 2026-10-19. I imported the official Simple English Wikipedia
article dump into a separate SQLite research index, then combined it with the
2,953-document expanded academic model. The new portable model is
`data/crms_project_model_academic_simplewiki.sqlite`; it contains 288,431
documents, 601,822,277 UTF-8 bytes of extracted text, and 92,372,919 CRMS word
units. These are corpus counts, not a comparison to LLM training tokens. The
encyclopedia portion has 285,478 pages. Each page keeps its title, revision
specific Wikipedia URL, revision ID, and the CC BY-SA 4.0 license notice
supplied to the importer. The model embeds source text and is runnable without
the dump file.

I drove the portable model in a fresh `/tmp` state directory. The model loaded
successfully with the combined research index. Questions and observed behavior:

| User input | Runtime behavior | Gap exposed |
| --- | --- | --- |
| `What is photosynthesis?` | “I don't know this from the sources and facts I have.” | Direct factual questions do not fall through to source retrieval, even though the source page is present. |
| `Summarize photosynthesis.` | Returned two quoted source sentences, one starting with `]]`; a preceding clipped result was labelled “Source text: Effectiveness.” | Summary retrieval finds the subject, but can include flattened wikitext debris and an orphaned section heading/snippet. |
| `What does the source say about photosynthesis?` | Returned only “Today, the average rate of energy capture by photosynthesis globally is about 130 terawatts.” | An explicitly source-seeking question returns a supporting sentence, but no definition or answer to the likely intent. |
| `Where can I find information about volcanoes?` | Returned a fragment about information added to Find a Grave. | Lexical overlap wins over topic relevance; retrieval does not reliably interpret the requested subject. |
| `Why does the sky look blue?` | Returned a description of the 1994 film *Blue Sky*. | Phrase overlap (“blue sky”) outranks the question’s causal meaning and yields a confidently irrelevant passage. |
| `Who was the first person to walk on the Moon?` | “I found relevant source text, but no accepted fact supports an answer yet.” | The corpus can supply evidence, but the chat path does not turn a source sentence into a supported answer for this question frame. |

This run confirms that adding broad source text improves what can be retrieved,
but does not by itself make ordinary questions answerable. The highest-value
next steps are (1) route unanswered factual questions through answer-oriented
source retrieval, (2) score full query intent and relation rather than isolated
terms, (3) select a complete source sentence that answers the requested slot,
and (4) clean wikitext artifacts during ingestion while preserving the exact
source span and citation. Replies should keep the evidence/accepted-fact
distinction already present. A larger corpus makes irrelevant lexical matches
more frequent, so retrieval quality and abstention need evaluation as corpus
size grows.

## Follow-up: exact-title definitions and causal questions

After the audit above, I added two bounded natural-language retrieval paths in
`crms_chat.py` and reran the portable model in a fresh `/tmp` state directory.
For `What is X?`, CRMS now quotes a definition only when one indexed page has
the exact requested title and its extractive summary contains one sentence
beginning with that title plus an explicit definitional predicate. `What is
photosynthesis?` now returns the definition sentence from the Photosynthesis
page, labelled as quoted evidence rather than an accepted fact. If that check
fails, the chat asks which meaning to look up instead of presenting a loose
lexical match; `What is Python?` now asks for clarification instead of quoting
a reticulated-python sentence as the definition of Python.

For `Why ...?`, CRMS now searches a wider candidate set and only returns a
sentence that contains all retained topic terms, an explicit cause/result
marker near the topic, and an assertion rather than an example. The live
question `Why does the sky look blue?` now quotes the sentence attributing the
blue color to random scattering by gas molecules. `Why is the sky purple?`
returns an abstention because no sentence meets those checks. Asking `why?`
after the returned evidence resolves and displays the cited source sentence.

These are deliberately narrow, evidence-preserving language rules. They do not
solve paraphrase, implicit causation, definitions whose wording does not begin
with the exact page title, or general answer composition. The general retrieval
failure remains visible outside these frames; other natural-language
questions can still select lexical decoys because the broad source-retrieval
route does not yet model the full question relation. Those gaps need a broader
learned question-frame and source-sentence ranking layer.

## Follow-up: who/where questions and source-finding requests

I reran the same broad-corpus chat in a separate temporary state directory and
added three question-shaped routes:

| Input | Runtime result | Constraint |
| --- | --- | --- |
| `Who was the first person to walk on the Moon?` | Quotes the Neil Alden Armstrong source excerpt through “the first person to walk on the moon.” | Searches a widened candidate set, requires every content term in one assertion sentence, and requires a complete named subject. |
| `Who created Python?` | Quotes `Guido van Rossum created Python` from indexed evidence. | Does not accept a lone surname or a sentence that starts with the asked-about object. |
| `Where does Alan Turing work?` | Quotes “During World War II, Turing worked at Bletchley Park.” | Requires an exact-title Alan Turing page and a matching work-location predicate there; the Turing-machine decoy is excluded. |
| `Where can I find information about volcanoes?` | Lists five indexed article titles that contain the topic in their titles. | Treats this as source discovery and strips importer license metadata from display links. |

These outputs are still quoted evidence, not accepted facts. The who route may
return a longer excerpt than a natural answer, and only recognizes a limited
English wh-question scaffold. It does not yet discover these frames from
examples or handle broad paraphrase. The runtime check filtered candidate hits
by query-term coverage before opening their source text; the corpus-scale
search still deserves latency profiling beyond these six conversational
queries.

I then exercised the feedback loop in a separate scratch knowledge store:
`Who created Python?` returned the source excerpt and a review-only
`Guido van Rossum — created → Python` candidate. Before acceptance, the
candidate was not in the fact store. After `accept candidate 1`, the exact
source citation was stored with the fact, and the existing acceptance path
recorded both the fact-pattern surface and the question example `Who created
Python?` with Python as its bound entity. Repeating the question then produced
`Guido van Rossum created Python.` from the accepted fact. This verifies one
candidate-to-fact-to-frame cycle; it does not prove transfer to unseen
entities or paraphrased questions.

## Follow-up: second natural-language drive against the broad model

**Run date:** 2026-10-19. I drove the same 288,431-document model in fresh
scratch stores, covering definition, causal, location, source-discovery, person,
paraphrase, yes/no, comparison, greeting, and capability questions. The narrow
routes held up for `What is photosynthesis?`, `Why does the sky look blue?`,
`Where does Alan Turing work?`, and `Where can I find information about
volcanoes?`; each produced a relevant source-backed response. `Hello` and
`What can you do?` also produced short scope responses.

The person-question run exposed several natural-language failures:

| Input | Runtime behavior | Gap exposed |
| --- | --- | --- |
| `Who created Python?` | Correct quoted sentence, but source was the CRMS project README; a review-only candidate was appended. | Source ranking can prefer project material over a direct reference source. |
| `Who made Python?` / `Who is the creator of Python?` | Abstained despite Python source text containing the creator. | Relation paraphrases are not mapped to the same answer frame. |
| `Python was created by whom?` | Returned a source passage rather than a concise answer. | Passive question syntax does not route to the person-answer path. |
| `What did Guido van Rossum create?` | Returned raw infobox text from the Guido page. | Reverse relation questions are not understood, and source cleanup is weak. |
| `Who designed the Analytical Engine?` / `Who created the C language?` | Abstained. | The current person route misses answer-bearing sentences when its exact query terms or leading-name shape do not align. |
| `Which river flows through Paris?` | Returned a River Cole disambiguation passage. | Lexical retrieval can select a decoy and does not enforce the requested location relation. |
| `Is Sydney the capital of Australia?` | Returned Sydney city infobox text instead of yes/no or a clear unsupported answer. | Yes/no questions have no truth/negation decision route. |
| `Did Guido van Rossum create Linux?` | Returned Guido's infobox rather than a supported negative/unknown response. | Subject, relation, and object are not jointly checked for yes/no questions. |
| `Compare Python and Java.` | Reported a co-mention, then displayed a large flattened Python infobox. | Comparison intent is detected, but no structured contrast is composed; raw source text leaks into the answer. |

The route took about 44 seconds for one chat process to answer this 13-question
sequence against the combined index. This is a coarse interactive observation,
not a benchmark; startup, repeated full-text retrieval, and excerpt ranking need
separate timing before performance claims. The main language priorities are
mapping paraphrased, passive, and reverse frames to a relation representation;
retrieving evidence that fills the requested answer slot; adding a conservative
yes/no check over accepted facts and source evidence; and keeping raw imported
markup out of the primary reply. The correct definition, causal, location, and
source-discovery examples show that bounded routes work, but do not generalize
across all question forms.

## Follow-up: passive-source answer realization and review learning

I used the Python creator question to trace a specific failure path. The
research layer already realized explicit passive evidence, but the chat-level
`who` route replaced that concise answer with a different active sentence from
the project README. I changed the route to prefer the existing source-grounded
realization and to derive any review candidate from the same cited source
sentence. The default response is now:

> Guido van Rossum created Python. [Source: History and License — Python
> 3.12.15 documentation; quoted evidence, not an accepted fact]

The source contains a bounded temporal adjunct and a comma-bearing parenthetical
aside. The surface-relation candidate parser now permits a narrow time/location
adjunct before an explicit passive `by` agent, and parses one bounded
comma-bearing parenthetical aside while retaining the exact original sentence
as the candidate evidence. Candidate generation remains review-only. The chat
shows the proposed triple before asking whether to accept it.

In a fresh runtime store, `Who created Python?` produced the concise answer and
the aligned `Guido van Rossum — created → Python` candidate. After explicit
acceptance, the chat answered the question from the stored fact, and a repeated
question returned the same declarative sentence. This validates one passive
source → reviewed fact → answer path. It does not establish synonym transfer,
unseen-entity generalization, or safe extraction from arbitrary parentheticals.

## Follow-up: corpus predicate-alignment coverage

I exercised the existing report-only predicate-alignment miner against the
expanded broad corpus to see whether it could address the `made`/`created`
paraphrase failure without a built-in synonym list. With its default sample of
1,000 documents it proposed no alignments. Six additional 1,000-document
windows also yielded none. A 10,000-document sample produced 11 reusable
relation-frame proposals, but still zero predicate alignments, including no
`made`/`created` proposal. The same 10,000-document sample did produce
11 relation-frame proposals, so this is specifically a limitation of the
alignment evidence criterion rather than a failure to parse any facts.

The current aligner requires at least two distinct subject–object pairs to be
stated with both predicates in independent documents. This is strong evidence
when it occurs, but appears too sparse to serve as the main route for learning
ordinary relation paraphrases from a broad corpus. A next discovery direction
is to propose role-compatible predicate hypotheses from wider distributional
evidence (subject/object classes and local argument patterns), keep those
hypotheses report-only, and require explicit review plus held-out examples
before they become usable language rules. The test needed for that direction is
not merely proposal count: it must measure useful paraphrase coverage and
false-alignment rate on held-out predicates.

## Follow-up: resolving a page-subject pronoun for a natural question

The corpus contains a direct source for `Who made Python?`, but the relevant
sentence is on the `Python (programming language)` page and begins “It was
made by a Dutch programmer named Guido van Rossum.” The generic query search
ranked a Monty Python film decoy first, while the old person-answer route
required a leading named subject. I added a bounded fallback that searches
pages whose title matches the asked-about object, then realizes only an
assertive passive sentence with an explicit named agent and the same predicate
as the question. The page title supplies the exact antecedent for the opening
pronoun; no relation synonym is inferred.

In runtime, `Who made Python?` now returns `Guido van Rossum made Python.` with
the source title. It offers a review-only `Guido van Rossum — made → Python`
candidate citing the original sentence. After acceptance, the fact and the
exact observed question example are stored; asking again returns the answer
from the local knowledge store. Accepting a second page-title example with a
different object licenses the exact `Who made X?` frame for another stored
`made` fact, while `Who created X?` remains unknown. The ordinary entity and
relation acceptance gate remains in place. This shows varied-entity frame
transfer for `made`; it does not establish that `made` and `created` share one
relation.

This behavior is covered by
`experiments/v1_275_page_title_anaphora_qa.py`. Its scratch SQLite corpus puts
a misleading Monty Python film result alongside the Python article, verifies
the exact citation and no-write-before-review behavior, exercises acceptance
and repeat answering, verifies question-frame transfer from two reviewed
objects to a third stored object, ensures `created` does not transfer to the
learned `made` relation, and checks that conflicting page-title antecedents
cause the chat to ask which page the user means.

## Follow-up: source-grounded yes/no answers

I added a bounded parser for copular nominal relations and do-support questions,
then matched the parsed subject, relation, and object against review-only facts
extracted from exact cited source sentences. An exact positive source statement
is reported as source-backed support for “yes”; an explicit negative candidate
supports “no.” The candidate remains pending until accepted. If no exact
positive or negative statement is found, the reply abstains instead of quoting
a lexical decoy or treating absence as false. Conflicting source polarities are
surfaced for review.

The broad corpus chat now quotes `The capital of France is Paris.` for
`Is Paris the capital of France?` and proposes `Paris — capital of → France`.
It abstains on `Is Sydney the capital of Australia?` because the indexed model
does not contain a direct source statement for that proposition, and it
abstains on `Did Guido van Rossum create Linux?` despite nearby Python results.
The Python positive question quotes its direct source. In a scratch runtime,
accepting one explicit negative and one positive capital claim led to `No` and
`Yes` on repeat questions. The optimized broad-corpus run took about six seconds
for three polar questions; this is an interactive observation, not a benchmark.

The flow and decoy guard are covered by
`experiments/v1_276_source_grounded_polar_chat.py`; the existing stored-fact
polar diagnostic also passes. These mechanics cover two bounded English
question forms. They do not solve general paraphrase, broader relation syntax,
or world-knowledge exclusivity: a missing statement remains unknown unless a
source explicitly negates the proposition.

## Follow-up: preserve grounded missing-premise explanations

Integrating direct source-backed polar answers exposed a response-ordering
hazard: the source route could replace an existing rule-search result that had
identified a specific missing premise. I changed the router to preserve that
inference result and improved its wording to state the known premise, the
missing premise(s), and the next action. For example, with `Ann — parent → Bob`
stored and the rule `parent + parent → grandparent`, the natural questions
`Is Ann a grandparent of Cara?` and `Who is a grandparent of Cara?` now explain
that the system has the Ann–Bob link and still needs `Bob — parent → Cara`.
The wording does not insert that missing fact or assert the conclusion.

`experiments/v1_263_grounded_abduction_language.py` now exercises both natural
question forms through the chat CLI as well as the underlying inference API.
It passes alongside the stored-fact polar and source-candidate polar
diagnostics, confirming the new source abstention route does not mask a
grounded proof gap.

## Follow-up: full 288k-document corpus chat drive

**Run date:** 2026-10-19. I exercised the portable model containing 288,431
academic and Simple English Wikipedia documents. Its existing research
sidecar was empty, so I materialized the searchable index from the model into
a disposable scratch copy (126.8 seconds; about 1.7 GB of indexed sidecar
data). The 15-question chat drive then took about 64.6 seconds. The model and
its sidecar in `data/` were not modified.

The large corpus did retrieve useful evidence for photosynthesis, the cause of
the blue sky, Alan Turing's Bletchley Park work, and Python's creator. The
question forms and answer composition still fail in predictable ways:

| Input | Runtime behavior | Gap exposed |
| --- | --- | --- |
| `Python was created by whom?` | Returned an unverified candidate block rather than a realized answer. | Passive `by whom` syntax was not entering the person-answer route. |
| `What did Guido van Rossum create?` | Returned the Guido page's raw infobox. | Reverse relation questions can bypass the controlled source realizer. |
| `Which river flows through Paris?` | Returned a River Cole disambiguation page. | Query entity/relation constraints are not enough to reject a lexical location decoy. |
| `Compare Python and Java.` | Returned a flattened Python infobox after reporting a co-mention. | The comparison route has no concise structured contrast and leaks imported markup. |
| `What can you tell me about the Analytical Engine?` | Returned an image caption naming Charles Babbage, not a direct design fact. | Broad `what about` questions can mistake caption evidence for the requested relation. |
| `What are the latest papers on graph theory?` | Listed recent papers whose abstracts only mention graph-related terms incidentally. | Topic and recency ranking admit papers that are not actually about the requested topic. |

I added a bounded passive-whom normalization to the person route. For a form
such as `Python was created by whom?`, it constructs the corresponding
`Who created Python?` retrieval question, realizes the answer from the cited
passive source sentence, and keeps the extracted relation review-only. A
fresh CLI session now says `Guido van Rossum created Python.` and displays the
review candidate from the same evidence. The focused chat fixture in
`experiments/v1_280_passive_by_whom_source_chat.py` passes. The broader
`v1_266` multi-question `no-context` scenario still times out after 45 seconds
even with the new probe isolated; an earlier run with that probe batched also
exceeded 90 seconds. This leaves broader integration latency unresolved while
the focused route check is green.

## Follow-up: typed relation retrieval and durable review

I replayed `Which river flows through Paris?` against the existing
285,478-document Simple English Wikipedia search index. Before this change,
the chat returned the River Cole disambiguation passage because it shared
`river` and `flows` with the query. The corpus also contains two direct
assertions for the answer: one says the Seine flows through Paris, and another
identifies the Seine as a river.

The chat now recognizes the bounded `Which/What TYPE VERB PREPOSITION ENTITY?`
shape. It retrieves candidates without the requested type word, checks that
the requested predicate and entity occur in the same assertion sentence, and
requires a separate explicit class sentence for the same page entity. This
produces: “The Seine fits: the sources say it flows through Paris and identify
it as a river.” Both claims are review-only candidates. A matching source page
or a lexical co-mention by itself is insufficient. An unsupported probe,
`Which river flows through Nacre City?`, abstains.

The runtime check also found two review-state failures: asking an unrelated
question discarded the pending claims, and restoring the session rejected the
typed candidates because the generic extractor could not re-derive their
argument roles. Pending candidates now survive unrelated questions, remain
available after restart, and are revalidated against the original typed query
and current cited source. Accepting one candidate keeps the other in the queue;
the queue no longer reruns broad retrieval after the final acceptance and
replaces the grounded answer with the River Cole decoy; after acceptance it
only reports a direct learned-fact answer when one is available.

Both accepted claims are reintegrated into the fact store. Their source wording
and the observed typed question are recorded as learning examples, while one
example alone remains below the transfer-licensing threshold. Repeating the
question after both claims are accepted realizes it as a stored-fact answer
and does not ask for review again. The combined source-grounded chat,
`Which`/`What` wording, abstention, unrelated-question persistence, restart,
review, accepted-fact reuse, and no-premature-generalization checks pass in
`experiments/v1_280_passive_by_whom_source_chat.py` and against the full
SimpleWiki index. This scaffold does not yet cover every relation phrase,
multiword class, or alternate question syntax.

## Follow-up: reviewed language-frame transfer without the corpus

I tested the path beyond source-backed answers using three distinct river/city
pairs. CRMS proposed a relation and an explicit `is-a` claim for each source;
after reviewing all six candidates, both relation examples were retained as
fact-pattern examples and all three reviewed fact pairs were stored. The
third source sentence, “The Nacre River is a river,” has overlapping subject
and class spans. Candidate acceptance now stores that explicit reviewed type
fact while declining to learn an ambiguous class sentence frame.

With only the accepted SQLite/JSON knowledge and an empty research index,
`What river flows through Nacre City?` returns “The Nacre River flows through
Nacre City.” The result includes both `flows through` and `is-a` proof
evidence. This demonstrates that varied source examples can teach an answer
frame that CRMS later uses without reopening the corpus. The runtime path and
fact evidence are covered in
`experiments/v1_281_reviewed_typed_frame_transfer.py`; the existing one-example
guard, source decoy, polar-answer, and missing-premise checks also pass.
That experiment also packs the accepted facts, learned frames, and source
documents into one SQLite model, then launches CRMS from that file and answers
the question again. This verifies the learned experience and source text
survive the portable-model boundary together.

## Follow-up: fresh natural-language chat drive and structured-source noise

**Run date:** 2026-10-19. I drove ten new questions through the chat CLI with
fresh state under `/tmp` and the existing 285,478-page Simple English
Wikipedia index. No indexed source or project model was changed.

| Input | Runtime behavior | Gap exposed |
| --- | --- | --- |
| `Who invented the telephone?` / `Who was the telephone invented by?` | Both returned Alexander Graham Bell from the Edinburgh source. | Both active and passive question wording work on this relation. |
| `What did Ada Lovelace write?` | Generic relevant-source fallback, no answer. | Reverse object questions still need relation-specific evidence and routing. |
| `Where did Alan Turing work?` | Returned the Bletchley Park sentence. | This location question form works. |
| `Why do leaves change color in autumn?` / `What causes tides?` | Both reported topic matches without a causal sentence. | Causal retrieval does not yet select a relevant explanatory claim from this broad corpus. |
| `Compare Python and Java.` | Printed a long normalized Python infobox as its “co-mention” evidence. | Imported structured metadata was being treated as narrative prose. |
| `What are the main differences between a crocodile and an alligator?` | Asked which meaning to look up, despite two named entities. | Comparison entity resolution/clarification is too eager. |
| `Who is the president of France?` | Returned Pierre Mendès France. | A present-tense role question can surface an obsolete historical officeholder; corpus freshness and time qualification are missing. |
| `Summarize the life of Marie Curie.` | Returned an infobox and references block before a useful career sentence. | General summaries admitted non-prose source sections. |

I added a structured-metadata filter to extractive summary and source comparison.
It drops normalized infobox/property spans and reference/navigation sections
where prose is expected. Replaying the same comparison now gives a concise
abstention without dumping the infobox; the Marie Curie summary selects
biographical prose about her personal and scientific life. A focused summary
diagnostic also exposed redundant sentence selection that left out a query
term; sentence selection now favors uncovered query terms, using relevance to
break ties. The summary diagnostic passes after that change. These are source
selection fixes, not a full answer-realization or summary-quality solution:
citations remain verbose, summaries remain extractive, and the reverse,
causal, ambiguous-comparison, and time-sensitive question gaps remain open.

## Follow-up: transfer of a reviewed irregular predicate form

The corpus has the direct sentence “Lovelace wrote the first computer program
in 1844,” but a fresh `What did Ada Lovelace write?` chat turn did not answer.
The existing learning model can store an explicitly reviewed canonical
relation (`write`) and its observed source form (`wrote`), but two gaps blocked
transfer: the source realizer discarded licensed sibling predicate forms on
object questions, and its object slot accepted only capitalized names. I
connected the inverse realizer to forms licensed under the queried canonical
relation and allowed a bounded common-noun object span. The chat now surfaces
such a source realization as one cited sentence labelled “quoted evidence, not
an accepted fact.”

The focused transfer diagnostic teaches `write`/`wrote` from two reviewed
source examples, then asks about a third entity whose held-out sentence uses
`wrote`. It checks that the cited sentence is returned and that an unrelated,
unlicensed relation does not produce a source answer. This path passes through
the CLI and the stored examples are the only source of the irregular-form
license; no built-in irregular verb list was added. The diagnostic is
`experiments/v1_282_reviewed_irregular_inverse_retrieval.py`. The adjacent
surface-relation, passive question, typed-frame transfer, and extractive-summary
diagnostics also pass. This advances reviewed morphology transfer, but does not
yet discover irregular paradigms automatically from unlabelled corpus text.

Reviewing the held-out fact now also teaches its object-question frame from the
canonical relation: after accepting `Grace Hopper — write → the compiler
notes`, CRMS answers `What did Grace Hopper write?` from the accepted fact.
This reuses the teacher-confirmed canonical relation while preserving `wrote`
as the cited source form. Object-question examples are generated only for
single-token, non-auxiliary relations; multiword relation syntax still needs
explicit examples.

## Follow-up: query-anchored corpus hypothesis for an unseen irregular form

I replayed `What did Ada Lovelace write?` against the full SimpleWiki index,
starting with an empty knowledge store. The broad retrieval route selected an
irrelevant lead sentence and did not find the later sentence “Lovelace wrote
the first computer program in 1844.” The issue had two parts: the sentence
splitter treated the period after a year as a decimal boundary, and the source
did not contain the question's full name because it used the surname on the
exact-title Ada Lovelace page.

The splitter now preserves periods only inside numeric tokens, so a sentence
ending in a year is separated from the following sentence. For a bounded
`What/Which did ENTITY VERB?` question, CRMS can now inspect that entity's
unique exact-title page and propose a review-only predicate-form hypothesis
when a simple assertion uses the same consonant skeleton with a different
vowel pattern. It does not answer or store the inferred mapping. The CLI states
that `wrote` may match `write` and asks for review. Accepting the cited
candidate stores the fact, teaches the object-question frame, and keeps the
surname span scoped to that cited page rather than adding `Lovelace` as a global
entity alias. Repeating the question then quotes the accepted source sentence.

This is an intentionally weak candidate generator: consonant similarity can
produce false matches, so it remains review-only. It does not discover all
irregular morphology or handle every source clause shape. `v1_282` now covers
both held-out transfer from reviewed examples and the no-prior-lesson
corpus-to-review-to-answer loop. The actual 285,478-page chat replay, that
diagnostic, the sentence-focused retrieval diagnostic, and the extractive
summary diagnostic pass. The same retrieval diagnostic exposed that snippets
could prefer two common subject/topic words over one numeric entity identifier;
numeric identifier terms now receive extra weight in snippet selection.

I checked the candidate generator against eleven additional exact-title
questions covering Ada Lovelace, Alan Turing, Charles Babbage, Alexander Graham
Bell, Marie Curie, and Guido van Rossum. Only the known Ada `write`/`wrote`
pair produced a hypothesis; wrong-relation probes such as `invent` and
`design` abstained. This is a small boundary check, not a corpus-wide precision
estimate. The source-object parser now also retains proper-name objects such as
`Notes on the Analytical Engine`, while requiring the same page and cited
sentence evidence. The review gate remains necessary because consonant
skeletons alone cannot prove shared meaning.

## Large-corpus natural-language drive: 1,200-document controlled corpus

I drove the CLI against a generated corpus of 1,200 independent source files
(7,200 sentences, six per file), with entity IDs spread across the full corpus.
The corpus intentionally repeats three relation shapes—river/city location,
research topic, and instrument designer—with active/passive variants and
distractor sentences. All data and chat state were created in a temporary
directory; no project or user knowledge store was used. The run also exported
the indexed corpus to a portable SQLite model and replayed a question after
the source directory and original index were taken offline.

The first 30 baseline questions expected exact evidence sentences. CRMS
surfaced the expected sentence in 10/30. The 20 misses were systematic rather
than random: all ten river/city questions and all ten research-topic questions
failed. The score is per turn: an expected sentence only counts when it is in
that question's own response. Typical abstentions parsed “Which river flows through …?”
as a request for “a river flows through …”, and “What did researchers …
study?” as “did researchers … study”; neither form retrieved the matching
sentence. The designer questions did find the correct sentence, but generated
ten unverified candidates across ten entities. Thus direct evidence retrieval
is sensitive to relation and question-frame shape even when every target
sentence is present and highly lexical.

Of twelve paraphrase probes, seven surfaced the expected evidence. Successes
included “Who was responsible for designing …?”, “What body of water crosses
…?”, and “What topic was studied by …?”. Failures included “Which stream
passes through …?”, “What research happened at …?”, “Who created the
instrument?” and “What did the institute investigate?”. Several are relation
synonyms or nominalizations; others change the expected answer type. A
negative control using “orchestrating” abstained. The two unsupported-question
controls were inconsistent: an invented engine question abstained, but a
population question for a nonexistent city asked which meaning to look up.

The learning phase succeeded on a narrower path: two reviewed examples
licensed `designed`, a held-out question produced a source-backed candidate,
acceptance stored it, and the accepted fact answered both the same subject
question and an inverse object question. The portable model embedded all
1,200 documents, but the replayed river question failed exactly as it did
before export. This separates packaging from language coverage: the source
text survived distribution; the query-to-evidence route still missed it.

The run now writes every baseline reply, paraphrase reply, unknown reply,
learning outcome, and portable-model outcome to
`experiments/reports/large_corpus_chat_audit.json`. The reproducible driver is
`experiments/v1_251_large_corpus_chat_stress.py`. Its exact-answer and
portable-retrieval gates are recorded as findings rather than aborting before
the report is saved. These measurements are for a deliberately controlled
synthetic corpus, not an estimate of performance on ordinary prose. The next
evaluation should preserve this reproducible set while adding a held-out set
of real sentences and human-authored paraphrases, then prioritize question
normalization/relation routing and candidate-queue hygiene based on measured
misses.

## Follow-up against the packaged academic-source corpus

I also ran `experiments/v1_266_large_corpus_chat_followups.py` against the
portable academic model (at least 1,500 indexed research documents), with
isolated chat state. The first attempt hit the script's 45-second subprocess
timeout during a ten-question conversation, so I raised the diagnostic limit
to 120 seconds and reran it. The conversation completed, but the driver stopped
on its “Why?” assertion. The first “Who created Python?” reply quoted the
claim from “CRMS prototype”; the follow-up “Why?” repeated it while citing
`CRMS_README.md`, and later “Who is the creator of Python?” / “What did Guido
van Rossum create?” turns retrieved “History and License — Python 3.12.15
documentation.” The assertion expected an older sentence and a fixed URL, so
it is stale, but the mismatch also exposes a real provenance problem: “Why?”
does not preserve the source that supported the previous answer.

That real-corpus conversation also exposed useful language behavior before the
assertion stopped the remaining probes: “What is causal forgetting in CRMS?”
asked which meaning to look up, despite the topic being present in project
material; the `creator` noun and inverse “What did Guido ... create?” form
retrieved the docs sentence, while “Who made Python?” abstained; a later
question received a count of pending candidates instead of a direct answer;
“What does the second paper say?” correctly asked for a paper-list context;
and “Is Sydney the capital of Australia?” said it could not answer yes/no from
its sources. The follow-up audit should use response-shape checks and source
identities from the actual packaged corpus rather than hard-coded historical
text, then continue past the initial mismatch so the remaining real-corpus
questions are still exercised.

## Follow-up: sentence-level subject matching for mixed documents

The first controlled-corpus run found that the typed-relation route required
the document title to name the relation subject. I changed it to accept a
bounded named subject parsed directly from the beginning of the evidence
sentence, even when the document is a mixed record with an unrelated title.
When it finds the relation but no separate type assertion, chat quotes the
exact sentence and says it has not independently verified the requested type.
This preserves the evidence and its limit instead of promoting the subject's
wording into an accepted class fact.

The ten baseline river questions now surface their exact cited sentences in
the right response. The same 1,200-document drive now returns expected
evidence for 30/30 baseline questions, up from 10/30, and the portable model
replay retrieves the same sentence with a citation. The question is still
source evidence, not automatic fact acceptance. The bounded
`What/Which did SUBJECT VERB?` route matches the subject at the start of an
asserted sentence and permits only exact or mechanically recognized
inflected verb forms. When it can isolate a simple object span, CRMS offers a
review-only fact candidate with the canonical question relation and observed
source verb. Acceptance stores the fact and teaches its sentence frame; varied
accepted examples license transfer. The `study`/`studied` chat diagnostic
accepts two source candidates, verifies the frame is licensed, and confirms
an unsupported entity and an unlicensed `invent` question remain unanswered.
No fact is written before acceptance.

A second diagnostic verifies reviewed relation wording. Once `study` exists
as accepted knowledge, a question using `study` can surface a source sentence
that says `investigated` as a relation-alignment hypothesis, with an explicit
warning and no answer. Accepting it stores the source fact under the canonical
`study` relation and records `investigated` as its observed frame predicate.
After varied accepted examples license that frame, `What did ... investigate?`
retrieves the accepted object. The same route does not propose `invent` from
the unrelated `studied` sentence. This is corpus-grounded, teacher-reviewed
relation learning; it does not infer synonymy from word similarity.

An initial paraphrase score of 7/12 counted “Who created the Vela instrument?”
as positive even though its source only says “designed.” The corrected
1,200-document probe set has 11 positive cases and 3 relation-conflict controls:
7/11 positives surface the expected evidence, and all 3 negative controls
abstain. Remaining positive misses are `stream`/`waterway`, “research happened
at,” and `investigate` versus `study`. After explicit review,
`investigated` can map to the accepted canonical `study` relation. Unsupported
population questions now abstain without clarification.
Repeated or unrelated questions no longer append the total pending-candidate
count to their reply; the full queue remains available through
`/pending-candidates`. The corpus report checks this behavior and records zero
unsolicited queue-count notices.

## Packaged academic corpus chat follow-up (October 2026)

The expanded follow-up harness now records each failed probe and continues
through the independent conversations. This prevents a stale expectation from
hiding later chat behavior. On the 1,500+ document package, the “Why?” follow-up
retains the prior answer's source identity. A causal-forgetting definition
question now falls through to the matching project source passage when there is
no exact-title page. `Who made Python?` still abstains because no reviewed
relation mapping licenses `made` as `created`; this is a language coverage gap,
not a source-evidence failure.

The replay also confirmed a summary coverage gap: “Summarize the CRMS reasoning
design” returned the “strong on” passage but omitted the matching “weak on”
passage. I tightened sentence coverage for multi-term summaries so selected
sentences must contain at least two query content terms. The replay now returns
both strength and limitation sentences and drops the generic “That is a design
choice” sentence. The Alan Turing work-location question abstains because the
corpus contains an illustrative question, not a verified location claim.

The paper ordinal follow-up had a concrete retrieval bug. It found the second
paper, then searched its title as if title words had to appear in the abstract,
so it returned no matching source sentences. The route now reads the selected
paper's indexed abstract directly and returns up to three exact sentences with
verified citations. A runtime chat against the 2,953-document academic/PMC
index confirmed that “What does the second paper say?” returns the second listed
paper, *Potatoes and Onions*, with three cited abstract sentences. The ordinal
turn now works. The corrected synthetic-corpus audit finds 7 of 11 positive
paraphrase probes on a fresh store, while all 3 relation-conflict controls
abstain; unreviewed relation wording remains a language-learning gap. The
audit's unknown-answer gate now uses its recorded
abstention classifications instead of requiring one exact phrase. The latest
replay classifies both unknown probes as abstentions, while baseline evidence
remains 30/30 and portable-model retrieval passes.

The latest post-change 1,200-document replay still passes all 30/30 baseline
questions and portable-model retrieval. Positive paraphrase evidence is now
measured against only the 11 supported probes: 7 return the expected sentence;
all 3 relation-conflict controls abstain. The four positive misses are
`stream`/`river`, `waterway`/`river`, “what research happened at” versus a
`studied` clause, and `investigate` versus `studied`. The stream/waterway cases
also need explicit type evidence or a reviewed type hierarchy: lexical overlap
alone must not establish that a river is a stream or waterway.

The summary coverage adjustment was checked against the packaged corpus in
actual chat and returned both paired reasoning capability statements with
exact citations. The reviewed object-question, passive question, typed-frame,
and irregular inverse-retrieval diagnostics all still pass after the retrieval
change.

## Reviewed relation learning compatibility

The corpus-only predicate alignment path was replayed against repeated shared
subject/object pairs. Two independent pairs licensed a review proposal for
`studied` as wording for canonical `investigated`; before acceptance the store
remained unchanged, and after acceptance a held-out `studied` sentence became
reviewable and answerable. Chat preserved the held-out source wording in its
answer. The diagnostic had expected the canonical verb to be rewritten into
that source sentence; I corrected the expectation to require source-faithful
realization instead.

The broader corpus relation learner also replayed against 2,006 indexed
documents: it mined three review-only relation frames, accepted facts only
after review, answered supported forward and inverse questions, and abstained
for an unseen entity. Both corpus relation-learning diagnostics pass. They
confirm `investigate`/`study` needs repeated paired evidence and explicit
acceptance; a single similar sentence is insufficient.

## Reviewed transitive type hierarchies

Typed source questions can now use the fact store's verified transitive proof
for `is-a`. This permits a composed classification such as `The Serein River
is-a river` plus `river is-a waterway`, but only when `is-a` is explicitly
marked transitive. Chat carries the proof's source citations into its answer
and labels the classification as derived from accepted facts. It abstains when
there is no accepted type chain and reports a conflict when explicit negative
evidence contradicts the derived class.

The runtime diagnostic `experiments/v1_285_transitive_type_chat.py` passes all
three cases: missing type evidence abstains; accepted transitive evidence
answers with citations to the route, entity classification, and taxonomy
sources; conflicting negative evidence blocks the answer. The existing direct
type-transfer diagnostic also passes.

The type-hierarchy proof is now exercised through the complete chat learning
loop, not only by preloading accepted facts. `experiments/v1_286_corpus_type_hierarchy_learning_chat.py`
first asks the user to accept the source-backed `Serein is-a river` claim,
then reports a multi-source `is-a` corpus frame without changing the store.
After the reviewer accepts the cited taxonomy and teaches `is-a` as transitive,
chat answers `Which waterway flows through Nacre City?` with the relation and
all three source titles. The accepted hierarchy is reloaded and independently
proven from persisted knowledge. This makes the distinction clear: the system
can discover candidate class rules from text, but only reviewed source facts
and an explicit schema enable the generalized answer.

## Overlapping entity/type words in reviewed corpus frames

A type fact such as `The Serein River is a river` contains the class noun inside
the entity name. The corpus parser correctly proposed `Serein River is-a river`,
but the acceptance code's legacy method-name check did not recognize the newer
bounded common-noun copular parser. It therefore re-raised the expected span
ambiguity instead of retaining the reviewed class fact. Acceptance now treats
both copular class-membership proposal methods as type facts and uses the
subject-copula-class order to choose the unique non-overlapping role spans.
This stores the source-backed triple and retains a reusable sentence frame;
the uniqueness guard still rejects class clauses without one ordered parse.

The end-to-end learning diagnostic now uses the overlapping-name example,
mines the broader `is-a` taxonomy, and answers the transitive held-out question.
It also confirms the accepted frame extracts `A desert is a landform` as a
review-only held-out candidate without storing it. The surface relation-
discovery diagnostic and the 2,006-document corpus relation-learning
diagnostic also pass after the fix.

The conflict guard was replayed with an indexed negative sentence, `The Serein
River is not a waterway.` A positive transitive type proof no longer overrides
this direct counterclaim. The reply names the route source, the counterclaim,
and the taxonomy source that supports the positive derivation, so both sides
can be inspected. The 1,200-document / 7,200-sentence chat stress run also
still passes all 30 baseline questions, with the previously identified four
positive paraphrase/relation misses unchanged.

## Answer-time candidate relevance

When chat has already produced an accepted answer, it now checks any new
review proposals against the meaningful terms in the user's question. A
proposal must overlap at least two such terms before it is added to the
pending queue. This keeps a proposal about the C language from appearing
beside an answer about Python while preserving proposals when there is no
supported answer or the query is too sparse for a safe relevance check.
`experiments/v1_287_answer_candidate_relevance.py` exercises the decision
directly. After this change, the 1,200-document stress corpus still passes
30/30 baseline queries, transfer, abstention, relation-conflict controls, and
portable-model retrieval. Its four known positive language misses remain,
confirming that question-frame/relation coverage is the next substantial gap.

## Learned predicate alignments in typed questions

The typed source route now uses accepted predicate-family expansions while
searching. A two-pair, independently cited alignment of `passes through` with
`flows through` lets `Which river passes through Nacre City 0002?` retrieve a
held-out source sentence that says `The Serein River 0002 flows through Nacre
City 0002.` With no learned alignment, the same query abstains. The reply names
the source wording and the reviewed alignment, and keeps the held-out relation
and type claims in review instead of storing them automatically.
`experiments/v1_288_learned_typed_relation_wording.py` covers this full chat
path. The 1,200-pair relation-alignment stress diagnostic and existing corpus
predicate alignment, direct type, and transitive type learning diagnostics
also pass. The same diagnostic gives one alternate surface phrase two
separate canonical relations; typed retrieval abstains rather than selecting
one by order. On the actual 2,006-document academic index, corpus mining
currently yields three repeated relation frames (`is-a`, `achieves`, and
`returns`) but zero predicate alignments under the independent shared-pair
threshold. This confirms that the present exact-pair alignment method works
when its evidence exists, but does not yet discover broad paraphrases in that
real research corpus.

## Portable-model chat at 288,431 documents

I drove the actual packaged
`data/crms_project_model_academic_simplewiki.sqlite` model through the CLI. Its
embedded `research_documents` table contains 288,431 documents, 601,822,277
UTF-8 bytes of searchable body text, and 92,372,919 CRMS word units (measured
with the local tokenizer, not model tokens). The first
runtime probe exposed a serious answer-realization problem: “How do plants
make food?” and “Explain Newton's first law in simple terms” returned almost
the entire SimpleWiki article, because single-newline sections were treated
as one paragraph. Other probes showed that “What is the capital of France?”
found a review-only candidate, “What is photosynthesis?” returned a cited
definition, while the Mona Lisa author query and “What causes tides?” did not
produce answers. “Compare a river and a stream” correctly refused to infer a
difference from a source that only co-mentioned them.

The explanation path now chooses up to three independently relevant source
sentences rather than emitting the full newline-delimited article. Ordinal
focus terms constrain the selection, so a question about Newton's first law
does not return a passage about the second law. A replay against the packaged
288,431-document model returned one cited sentence for the plant question and
a first-law sentence for the Newton question. The reproducible CLI regression
fixture `experiments/v1_289_bounded_explanation_realization.py` passes on
wiki-like single-newline pages. The remaining factual gaps from the large
model probe are retained as retrieval and structured-metadata work, not
treated as a lack of corpus volume.

## Irregular verb forms in direct author questions

The 288,431-document SimpleWiki run found that `Who wrote Frankenstein?`
was treated only as a structured paper-author lookup. Since the novel page
has no `Authors:` metadata field, that route stopped despite an explicit lead
sentence saying the novel was `written by Mary Shelley`. The source-question
route now recognizes a bounded irregular verb paradigm (`write` / `wrote` /
`written`) for retrieval and can realize the cited passive clause as
`Mary Shelley wrote Frankenstein.` It remains labeled as source evidence and
is not promoted to an accepted fact. A runtime probe against the actual
SimpleWiki research index produced that sentence with an exact citation.
The same runtime audit showed that `Who painted the Mona Lisa?` had direct
source support but failed because the lead uses a reduced passive clause:
“The Mona Lisa ... is a 16th-century portrait, painted in oil by Leonardo da
Vinci ...”. The page-subject realization now handles a bounded descriptive
lead plus a participle with an intervening modifier, producing `Leonardo da
Vinci painted Mona Lisa.` Both questions were replayed against the actual
288,431-document research index and returned exact cited evidence.
`experiments/v1_290_irregular_who_passive_source.py` reproduces the irregular
and reduced-passive cases and confirms an absent title still abstains. These
syntactic patterns do not establish broader synonym equivalences such as
`authored` and `wrote`; those still need learned relation evidence.

The terminal-chat replay also exposed a presentation issue: each concise
answer is followed by a review candidate extracted from the same sentence.
The candidate is relevant and remains review-only, but repeating the claim
after the answer adds clutter. Answered source-backed turns now keep the short
answer and source label, then state only how many source claims are awaiting
review. Full evidence remains available through `/pending-candidates`, and
accept/reject commands still operate on the same persisted queue. The v1.290
CLI diagnostic verifies both the concise reply and the on-demand review path;
the passive-question regression was updated to expect the new display while
checking that candidates remain available and reviewable.

## Reviewable learning from irregular passive source claims

The corpus alignment miner still finds no repeated cross-source predicate
alignments in its bounded 10,000-document SimpleWiki scan. A separate runtime
probe showed a useful lower-level gap: the review-only claim extractor parsed
`written` as a passive participle with an explicit `by` agent, but its final
finite-verb filter discarded the `-en` form. It now keeps that already-parsed
passive relation as a source-backed proposal. The extractor also retains a
leading article when it belongs to a capitalized entity (`The Seine`), matching
the entity form used by the copular type claim (`The Seine is a river`).

`experiments/v1_291_reviewed_irregular_passive_frame.py` confirms that two
independently reviewed `was written by` examples induce a passive fact frame
that proposes the right agent, relation, and object for a held-out sentence.
The held-out proposal remains unstored until review, and the negated control is
excluded. This grows grammatical frame learning from evidence; it does not
teach a semantic synonym such as `authored` ↔ `written`, which still needs a
reviewed alignment with adequate support.

## Nominal relations and agent questions

The corpus also contains direct nominal evidence: `Mary Wollstonecraft
Godwin became Mary Shelley, the author of Frankenstein.` The source-fact
extractor now proposes `Mary Shelley — author of → Frankenstein` from that
appositive, still requiring review. When the user asks `Who is the author of
Frankenstein?`, chat can realize the exact nominal relation with that sentence
and citation; `/pending-candidates` exposes the proposed fact without writing
it to the accepted store.

For the related verbal wording `Who authored Frankenstein?`, a bounded
derivational rule removes regular past `-ed` only when the remaining stem
already has an agent-noun ending (here `author`). It then requires an exact
source sentence for that same nominal relation and object. This answers from
the cited `author of` evidence; it does not create a global `authored` ↔
`written` alias. A control query about who designed Frankenstein does not use
the author source. The route uses locally matching search passages rather than
scanning all sentences of each article; the paired questions complete through
the full 288,431-document chat runtime.

Explicitly accepted nominal relation examples also teach their question
frames. Two `author of` examples license `Who is the author of X?`; two
`capital of` examples license `What is the capital of X?`. A typed-question
parser guard keeps copulas and determiners such as `is the` out of the type
slot, so ordinary nominal questions reach their learned frames. The reproducible
CLI and held-out checks are in
`experiments/v1_292_nominal_relation_question_frames.py`.

For corpus cost, the nominal route now inspects verified search-hit spans
instead of splitting every sentence in each matching article. The direct
question route also caps its broad ranked search at 100 hits while retaining a
50-hit exact page-family lookup. The before/after probe for three person
questions on the full index fell from about 61 seconds to about 2 seconds;
the nominal `Who is the author...` and derived `Who authored...` chat replay
completed in about 1.3 seconds. These are interactive observations, not a
throughput benchmark. The disambiguated title check remains covered by the
Python page-title diagnostic.

### Follow-up: nominal relation to verbal question form

A sampled scan across ten 10,000-document slices of the 288,431-document
SimpleWiki research index found a `creator of` frame at offset 270,000, with two
distinct subject/object pairs: Camp Lazlo / The Juice and Iris Hineman /
PreCrime. Accepting those reviewed frames made `Who is the creator of
PreCrime?` answer correctly, but `Who created PreCrime?` still abstained. This
isolated a question-realization gap rather than missing knowledge.

The question-frame path now derives the regular past-tense `created` form from
a licensed `creator of` nominal frame, and only when that nominal frame has
multiple accepted examples. A negative boundary check ensures it does not
invent `authed` from `author`. The new `v1_292` diagnostic exercises both the
positive bridge and the control; the existing zero-frame corpus-learning and
irregular/passive source diagnostics also pass. This is a narrow morphology
rule, not broad paraphrase understanding; other agent-noun classes remain to
be measured and licensed separately.

### Agent-noun frame expansion and false-attribution guard

The full SimpleWiki index yielded direct nominal evidence for questions such as
`Who is the inventor of the battery?` (Alessandro Volta) and `Who is the
discoverer of bacterial conjugation?` (Joshua Lederberg), while the equivalent
verb queries (`Who invented the battery?`, `Who discovered bacterial
conjugation?`) had no direct answer route. The source-fact extractor also
proposed a false attribution from a list sentence around “Alfred Russel
Wallace, the inventor of telephone Alexander Graham Bell…”, attaching Wallace
to `inventor of telephone`.

I generalized reviewed nominal question frames from transparent `-er` and
`-tor` agent nouns: after two accepted relation examples, `inventor of` can
license `invented`, and `designer of` can license `designed`. A single accepted
inventor example still abstains, and `author` does not generate an `authed`
form. The appositive extractor now accepts a single lowercase object only when
it has an article, or a multiword lowercase object; it rejects the ambiguous
list sentence instead of assigning its relation to the preceding name. All
proposals still require review before storage.

The focused diagnostic passed, along with irregular-passive, nominal-question,
and transitive-type chat checks. The 1,200-document stress run also passed all
30/30 baseline sentence retrievals and its unsupported-question abstention gate;
7/11 positive paraphrase probes found the expected evidence, and all 3
relation-conflict controls abstained. Its remaining misses (`river` vs
`stream`/`waterway`, and `studied` vs `research`/`investigate`) are unchanged:
they need reviewed type or relation evidence, not lexical guessing.

### Real-index replay of an induced agent-noun rule

A dedicated replay now mines source-cited `inventor of` appositives from the
full local SimpleWiki index, checks that they come from different documents,
and accepts them only into a temporary knowledge base. One accepted example
still cannot answer its corresponding `Who invented ...?` query. After three
independent examples are accepted, the held-out query `Who invented the
battery?` answers `Alessandro Volta` and carries the exact SimpleWiki citation.
The replay is reproducible with
`experiments/v1_293_real_corpus_agent_noun_transfer.py`; it does not write to
the packaged model. This confirms a real-corpus language rule can be learned
from reviewed examples and applied to a held-out query using the stored
relation, rather than a built-in inventor/created-style synonym table.

### Page-title grounding for nominal relation claims

A further real-index chat probe asked `Who is the lead designer of Minecraft?`
The retrieved sentence says `He is the lead designer of Minecraft.` Without
its page context, storing `He` as the subject would be unsafe. Source fact
extraction now resolves a sentence-initial pronoun only when the exact cited
document has a bounded named-entity title; list/descriptive titles and calls
without a source index abstain. The resulting candidate records both the
pronoun and title antecedent as review evidence. On the full corpus, chat now
answers `Jens Bergensten is the lead designer of Minecraft.` with the exact
source citation, labels it as quoted evidence rather than an accepted fact,
and keeps the candidate available through `/pending-candidates`. No source
claim is automatically stored.

### Number agreement for reviewed nominal question frames

After a nominal relation's singular question frame is licensed by varied
accepted examples, it can now support regular plural agreement too: `Who is
the creator of X?` / `Who are the creators of X?` and `What is the capital of
X?` / `What are the capitals of X?`. The plural noun and `are` are generated
from the stored singular surface frame; no new facts or relation meanings are
introduced. One accepted example does not license the plural frame. The
nominal-frame diagnostic checks both the one-example abstention and licensed
forms.

### Real-corpus type claims and current paraphrase status

The synthetic `river`/`waterway` probe has two relevant paths: a reviewed
transitive taxonomy (diagnostic v1.286), and direct named-entity class evidence
from corpus prose. SimpleWiki says `The Ogun River is a waterway in Nigeria
that discharges into the Lagos Lagoon.` The extractor previously missed this
because it required the copular classification to end at the class noun. It
now proposes `Ogun River — is-a → waterway`, recording the trailing adjunct
separately. The claim remains review-only, and the negated form is not proposed
as positive. After acceptance, the explicit question `Is the Ogun River a
waterway?` answers Yes with the exact source citation. This supports that
entity's classification; it does not generalize `river` to `waterway` without
a reviewed type edge.

Status correction for the 7/11 paraphrase score: the score measures unreviewed
source-answer probes, not eventual capability after language learning. The
`investigate`/`study` variant has a tested review path through paired corpus
alignment (v1.260), and the `waterway` variant has a tested reviewed type path
(v1.286) plus direct instance extraction (v1.294). The “research happened at”
nominal question remains the unaddressed semantic-role/nominalization gap in
that probe set; evidence retrieval alone does not resolve it.

### Event-nominal query fallback: evidence without a paraphrase claim

The stress query `What research happened at Meridian Institute 0266?` did
retrieve the exact 1,200-document source sentence, but the typed-relation router
misread `research` as a requested class and `happened at` as a relation, then
overwrote the useful passage with a false “no source sentences” reply. The chat
now preserves the closest assertion only for this bounded `What [event] happened
at [entity]` shape when it contains the exact bound entity and a literal or
regularly derived query word (`research` / `researchers`). It says explicitly
that the sentence does not establish the requested relation and does not count
this as an answered paraphrase. Other typed questions still require their
relation to be licensed; the unlearned `flows through`/`passes through`
diagnostic continues to abstain.

The latest synthetic stress replay still retrieved all 30/30 baseline target
sentences and all three relation-conflict controls abstained. Eight of eleven
positive probes now surface their expected sentence, but one is this
related-evidence-only response; the report records it separately, so the
sentence-hit count is not treated as proof of paraphrase understanding. The
three remaining probe misses are `stream`/`river`, `waterway`/`river`, and the
unreviewed `investigate`/`study` wording. The latter has a separate paired,
reviewed corpus-alignment path.

### Source-backed candidate reply wording

The same chat replay showed that a review-only fact was presented as a
subject–relation–object triple followed by a duplicate evidence sentence. The
reply now uses the exact source sentence and short source name, and labels it
as a claim awaiting review rather than an accepted fact. When that same
sentence is already shown, the chat replaces the duplicate numbered candidate
line with a pointer to `/pending-candidates`. The 1,200-document stress fixture
checks this response shape and retains the distinction between quoted evidence
and accepted knowledge.

### Follow-up regressions from longer untaught-corpus chats

A fresh three-file replay exposed a risk in ordinary lexical retrieval: a
question naming Marie Curie could receive an Einstein sentence because both
sentences mention the Nobel Prize. Natural-language retrieval now treats
capitalized names and named objects from the question as identity anchors and
filters source sentences that omit any of those terms. This reduces false
answers from topical overlap; it remains a lexical identity constraint, not a
full entity linker.

Location questions now search asserted source sentences for the named subject
and requested relation even when the source document has a generic title. The
fallback also uses a plain `location statement` abstention instead of wording
such as `located location`. Do-support yes/no parsing now carries a locative
preposition into the relation, and a small explicit irregular-verb fallback
handles `win`/`won` (plus a short fixed set) only when the subject and requested
object occur in the same cited sentence.

`Who created Python and Linux?` now reports partial evidence and names the
unresolved conjunct instead of silently returning only the Python evidence.
The zero-frame extractor also treats `Cara is a parent of Dan` as the relation
`parent of`, not as a type claim that Cara is-a parent. The long-chat candidate
queue regression replays repeated questions, multiple pending candidates,
`/pending-candidates`, and a follow-up answer in one process; it completes
without a traceback. These cases are covered by
`experiments/v1_295_natural_language_regressions.py`. The corpus-alignment
diagnostic now checks the updated sentence-first review wording while keeping
its alignment acceptance and held-out transfer gates.

### Predicate alignment discovery at corpus scale

The existing predicate aligner previously had a small fixture for learning
`studied` as wording for `investigated`. A new scale probe builds on the full
1,200-document mixed corpus and adds two independent source records that repeat
the same river/city pairs with `passes through`. The corpus miner proposes
`flows through` ↔ `passes through` from the two shared pairs, writes no facts
before review, and transfers the accepted wording to a chat query over the
indexed corpus. `experiments/v1_296_large_corpus_predicate_learning.py` passes.
This is still evidence-based, explicit review rather than an automatic claim
that every related-looking verb is a synonym.

### Full bundled-corpus natural-language spot check

A read-only copy of the bundled 288,431-document SQLite research index was
opened in a temporary chat session. `What is the capital city of France?`
returned the source sentence “The capital of France is Paris.” with a source
label and the required quoted-evidence/not-accepted-fact status. The first run
of `Where is Mount Everest located?` failed even though the exact-title page
contains “Everest is located in the Mahalangur Himal sub-range of the Himalayas
in the Solukhumbu district of Nepal.” The locative matcher allowed the page's
final title word as an alias but rejected it when followed by the copula
“is”. It now accepts that alias plus the finite forms `is`, `was`, `are`, and
`were` only within the unique exact-title document. The replay then returned
the exact Everest sentence and source label. The fixture regression
`experiments/v1_303_exact_title_locative_chat.py` covers both the existing
Alan Turing case and this title/coreference form.

This confirms two grounded natural-language question paths over the full
bundled corpus, not broad answer quality or general entity-coreference
coverage. Search-index installation took 136.06 seconds and generated a
2.23-GB temporary index; see `docs/sqlite_memory_design.md` for the full-corpus
inventory and timing.

### Structured metadata field retrieval

A later read-only probe of the bundled SimpleWiki index found that `Who
designed the Python programming language?` and `What is the capital of
Germany?` abstained even though their exact-title pages contain `designer =
Guido van Rossum` and `capital = Berlin`. The prose extractor correctly
excluded these infobox fields, but no structured-field answer route existed.
CRMS now recognizes a small explicit set of agent-role fields (designer,
creator, inventor, founder, and author) and a country `capital` field on one
exact-title page, cites the exact field span, and labels the answer as quoted
structured evidence rather than an accepted fact. This path does not infer
that an arbitrary field such as `manufacturer` means `creator`; multiple
exact-title records remain unresolved. The checked-in regression is
`experiments/v1_318_infobox_field_evidence.py`.
For the spot checks, only the Python-language and Germany pages were copied
from the 285,478-document bundled SimpleWiki index into temporary scratch
indexes; the full database was opened read-only and was not modified.

### Explicitly learning alternate question wording

A separate chat regression checks the supported path for a lexical alternative
when the user can label one example from an accepted fact. After two examples
license `created`, a teacher labels `Who made Tavel Compass?` with its accepted
answer. CRMS stores the new question surface under the existing relation,
answers that wording for a different entity after reload, and continues to
abstain on `Who crafted ...?`. This is user-supervised frame transfer, not
zero-shot synonym inference; the benchmark still records lexical transfer as
an open coverage gap. See
`experiments/v1_319_additional_synonym_question_frame.py`.

### `Why?` after proof-backed inference

The CLI could let the prior retrieval result take priority over a selected reasoning
proof. A multi-turn case with an unrelated family-guide sentence followed by
`Is Ann a grandparent of Cara?` reproduced it: the answer had a valid two-premise
proof, but `Why?` described the guide passage. The chat now routes this follow-up
to the dialogue's proof explanation first when the previous answer carried an
inference proof. `experiments/v1_320_chat_why_uses_selected_inference_proof.py`
checks that both premise sources and the rule appear in the explanation while
the unrelated passage does not. Existing `v1_131` explanation, `v1_185`
reasoning-contract, and `v1_295` natural-language regressions also pass.

### More answerable rule-learning probes

A single example of `reverse the list [1,2,3] -> [3,2,1]` correctly leaves a
version space open, but the best purely mathematical probe was `[0,-1,0]`.
The learner now looks for a short, positive, duplicate-free permutation whose
candidate outputs retain at least 80% of the best probe's distinct classes
and whose largest class stays bounded relative to the original. In this case
it asks for the output on `[1,2,3,5,4]`, separating 8 output classes among 15
candidate procedures. The rule remains unlearned until the teacher supplies
that output. `experiments/v1_49_natural_rule_demonstrations.py` checks probe
readability, separation, and persisted CLI learning; the experiment now also
keeps its pending rule-session file in its temporary directory.

### 1,200-document chat stress replay: abstention metric correction

Command: `python3 experiments/v1_251_large_corpus_chat_stress.py`

The current runtime replay indexed 1,200 generated source documents (7,200 sentences), surfaced
the exact expected sentence for all 30 baseline questions, kept all three negative relation
controls from answering, and preserved the embedded source corpus in a portable model after its
original index and source directory were taken offline. Both unsupported questions were
appropriately refused. One reply included a closest sentence, but explicitly said it did not
support a grounded answer and “I won't guess.” The previous report classifier missed that refusal
because it did not recognize this wording; it now records the result as
`abstained_with_related_evidence` and requires all unsupported queries to abstain.

Three positive probes remain open: `Which stream passes through Nacre City 0133?` and `Which
waterway runs through Nacre City 0133?` do not find the corresponding evidence, while `At which
institute did researchers study quartz field 0266?` detects multiple candidate sentences and
abstains. These are language and relevance gaps, not failures of source availability; the exact
sentence appears in the generated corpus. The benchmark keeps them visible instead of counting a
closest-sentence quote as a correct answer.

### Numbered-record disambiguation follow-up

The 1,200-document replay exposed a gate-level ranking gap: the institute question placed its
matching record beside the same-topic distractor and records 0000–0009, then abstained because
several candidates tied. The query's `0266` identifier had been treated as an ordinary omitted
number instead of an entity constraint. The evidence gate now requires each explicit numeric token
in the question to occur as a token in the candidate sentence. A rerun selected the exact Meridian
Institute 0266 sentence, and `experiments/v1_251_large_corpus_chat_stress.py` now makes that
large-corpus outcome a pass/fail check. The direct runtime gate also mixes the target with ten
numbered records and a same-ID, wrong-topic distractor. Baseline answers remain 30/30; four other
positive paraphrase probes remain unresolved, including the stream and waterway relation variants.

### Reviewed predicate transfer and typed-question composition

`python3 experiments/v1_296_large_corpus_predicate_learning.py` now tests the full transfer path
against the 1,200-document synthetic corpus. Two independent cross-document subject/object pairs
produce each report-only alignment: `flows through` / `passes through` and `flows through` / `runs
through`. No facts change before explicit acceptance. After acceptance, held-out typed questions
`Which stream passes through Nacre City 0000?` and `Which waterway runs through Nacre City 0004?`
combine the learned relation variants with separate cited class sentences. Chat returns the
answer-bearing source sentences and exposes resulting claims for review, preserving the fact-review
boundary. The types are explicitly stated in the fixture; CRMS does not infer them from entity names.

I also ran the read-only corpus alignment sampler against four 1,000-document windows of the
285,478-document SimpleWiki index. Each sampled window produced zero predicate-alignment proposals
(only one to three relation-frame proposals). This shows that repeated exact subject/object pairs
across separate documents are scarce in those windows, so the current learner cannot yet provide
broad real-corpus paraphrase transfer. The remaining stream/waterway probes stay unresolved; this
test does not infer those terms from topic similarity.
