"""Interactive terminal shell for CRMS grounded dialogue and research."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from crms_dialogue import CRMSDialogue
from crms_codegen import (
    describe_generated_code, generate_math_python, generate_python,
    generate_unit_conversion_python, natural_language_request,
    render as render_codegen, show_generated_code_evidence,
)
from crms_inference import RuleReviewResult
from crms_knowledge import (CRMSKnowledgeBase, FactCandidate,
                            _analyze_predicate_spelling)
from crms_math import CRMSMath, render as render_math
from crms_model import CRMSModel, Prediction
from crms_package import (
    export_model_database, install_model_database, inspect_model_database,
    model_database_has_research, model_database_rule_settings,
)
from crms_question_induction import (
    propose_analogical_multi_qualified_question_frames,
    propose_analogical_qualified_question_frames,
    propose_analogical_question_frames,
)
from crms_question_role_induction import (
    propose_active_role_alternation_frames,
)
from crms_research import (
    CRMSResearchIndex, CRMSSQLiteResearchIndex, SearchHit,
    _RESEARCH_STOPWORDS, _is_code_source, _is_imported_structured_metadata,
    _research_query_terms,
    _sentence_context_kind, _sentence_spans,
)
from crms_text import tokens as normalized_tokens
from crms_translation import (
    CRMSTranslation, infer_shared_slot_templates,
    render as render_translation,
)


HELP = """Commands:
  /help          show this guide
  /source PATH|URL add a supported local file or capture one HTTP(S) page
  /source-dir PATH [--replace|--verify]
                 recursively index text/markup, tables, slides, chats, HTML, DOCX, ODT, EPUB, and PDFs
                 --verify checks file contents when size and timestamp are unchanged
  /summarize QUERY
                 select exact, cited source sentences for an extractive summary
  Show more/fewer sentences | Show the first N sentences
                 refine the most recent source-grounded summary
  /crawl URL|MAX_PAGES|MAX_DEPTH
                 capture a bounded set of same-origin linked pages
  /teach-fact S|R|O|QUERY|PHRASE|POLARITY[|SUBJECT SURFACE|OBJECT SURFACE]
                 teach a cited sentence example (POLARITY: positive/negative)
  Teach a sourced fact pattern from examples: "SENTENCE" => "SUBJECT" | "RELATION" | "OBJECT"; ...
                 learn wording from 2–8 exact indexed sentences sharing relation/polarity
  Optional ["SUBJECT PHRASE" | "PREDICATE PHRASE" | "OBJECT PHRASE"] labels
                 align sentence wording with canonical fact slots
  Add | "negative" before the optional spans to teach an explicit negative fact
  /teach-context-fact S|R|O|QUERY|KEY=VALUE[|KEY=VALUE...]
                 record a source-backed fact with explicit qualifiers
  /teach-context-frame S|R|O|QUERY|PREDICATE|SENTENCE|KEY=VALUE[|KEY=VALUE...]
                 teach a cited sentence frame that extracts qualifiers
  /teach-question Q|R|FIELD|ENTITY|ANSWER
                 teach a fact-backed question example (FIELD: subject/object)
  /teach-question-pattern Q|R|FIELD|ENTITY|ANSWER
                 teach a reviewed query slot mapped into a fact-endpoint pattern
  Teach a question frame from examples: "QUESTION 1" => "ANSWER 1"; "QUESTION 2" => "ANSWER 2"
                 learn a question pattern only when both examples match one fact relation
  Teach paired question frames from examples: 4–8 "QUESTION" => "ANSWER" pairs
                 learn subject- and object-answer wordings transactionally
  Teach an additional question example: "QUESTION" => "ANSWER"
                 extend one exact, already licensed fact-backed frame
  Teach an additional contextual question example: "QUESTION" => "ANSWER"
                 extend one exact, already licensed qualified frame
  Teach a yes/no frame from examples: "QUESTION 1" => yes/no; "QUESTION 2" => yes/no
                 learn a truth question only from matching positive or negative facts
  Teach a path-question frame from examples: "QUESTION 1" => "ANSWER 1"; "QUESTION 2" => "ANSWER 2"
                 learn a bounded relation path from 2 to 8 proof-backed examples
  /suggest-question-frames
                 report source-backed question-frame analogies and holdout checks
  /suggest-predicate-forms [FACT_OFFSET|MAX_HITS_PER_FACT]
                 find repeated alternate wording for accepted relations; report-only
  /accept-predicate-form SELECTOR[|FACT_OFFSET|MAX_HITS_PER_FACT]
                 accept a regenerated, source-reviewed predicate alignment
  Review alternate predicate forms
                 inspect report-only wording proposals; accept one by its ID
  /suggest-corpus-frames [DOC_OFFSET]
                 find repeated zero-frame sentence patterns across indexed sources
  /accept-corpus-frame SELECTOR[|DOC_OFFSET]
                 accept one source-separated frame and its cited example facts
  /suggest-corpus-alignments [DOC_OFFSET]
                 find repeated corpus-only predicate alignments; report-only
  /accept-corpus-alignment SELECTOR[|DOC_OFFSET]
                 accept a reviewed corpus predicate alignment from cited pairs
  /suggest-question-role-rules
                 report active subject/object role alternations; report-only
  /train-question-frames
                 accept mechanically validated frames with current evidence
  Review question frame proposals
                 inspect source-separated report-only frame candidates
  Accept question frame proposal ID
                 revalidate and retain one exact frame proposal
  /teach-math QUESTION|ANSWER
                 teach an exact operation phrase from a natural-language example
  /cancel-math    stop waiting for a contrastive math example
  The result is ANSWER
                 answer CRMS's pending contrastive math question
  Teach math from examples: "QUESTION 1" -> ANSWER 1; "QUESTION 2" -> ANSWER 2; ...
                 conversationally teach 2 to 8 examples as one checked batch
  Teach unit conversions from examples: "2 meters" -> "200 centimeters"; ...
                 conversationally teach 2 to 8 aligned quantity pairs
  /teach-unit-equivalence QUANTITY|QUANTITY
                 teach an exact unit conversion from aligned quantity examples
  /teach-translation SL|TL|REGISTER|SRC TEMPLATE|TGT TEMPLATE|SRC1|TGT1|SRC2|TGT2
                 teach a two-example translation frame with aligned named slots
  Teach a translation or same-language rewrite frame: "SRC TEMPLATE" => "TGT TEMPLATE"; 2–8 aligned pairs
                 conversationally teach a frame from 2 to 8 aligned pairs
  Example: Teach a rewrite frame from English to English in plain register: "SOURCE {slot}" => "TARGET {slot}"; "source A" -> "target A"; "source B" -> "target B"
  Teach translation or rewrite examples from SL to TL in REGISTER register: "SRC1" -> "TGT1"; ...
                 infer copied slots only when aligned changing spans match
  Teach an additional translation example from SL to TL in REGISTER register: "SRC" -> "TGT"
                 extend one uniquely matching licensed frame with an aligned pair
  /teach-about Q|ENTITY
                 teach a request frame for a sourced entity digest
  Teach an about-request frame from examples: "REQUEST 1" => "ENTITY 1"; "REQUEST 2" => "ENTITY 2"
                 teach from 2 to 8 distinct entities in one request frame
  /teach-qualified-question Q|R|FIELD|ENTITY|ANSWER|KEY=VALUE[|KEY=VALUE...]
                 teach an entity-and-context question frame
  /teach-alias ALIAS|ENTITY|SOURCE QUERY
                 teach a source-cited name variant for a stored entity
  /forget-alias ALIAS[|SOURCE]
                 remove a learned alias so it can be corrected
  /retract-fact POLARITY|SUBJECT|RELATION|OBJECT|SOURCE[|KEY=VALUE...]
                 retract one source's support for a stored fact
  /aliases       inspect learned entity aliases
  /alias-rules   inspect induced plural rules and supporting evidence
  /teach-polar Q|SUBJECT|RELATION|OBJECT|yes/no
                 teach an evidence-backed yes/no example
  /ask-context QUESTION|KEY=VALUE[|KEY=VALUE...]
                 answer a learned question with explicit fact qualifiers
  /ask-path-between START|TARGET|REL1>REL2[|KEY=VALUE...]
                 check a bounded, proof-producing path between two entities
  /teach-inference-rule ID|REL1|REL2|CONCLUSION[|middle_kind=KIND]
                 declare a two-premise rule, optionally typing its middle entity
  /teach-inference-rule ID|REL1|REL2|REL3|CONCLUSION|middle_kind=K1|second_middle_kind=K2
                 declare a typed three-premise chain rule
  Teach CRMS rule "ID": if X has relation "R1" to Y and Y has relation "R2" to Z, then X has relation "R3" to Z.
                 explicitly teach a two-premise rule in ordinary language
  Teach CRMS rule "ID": if X has relation "R1" to Y, Y is of kind "K1", and Y has relation "R2" to Z, Z is of kind "K2", and Z has relation "R3" to W, then X has relation "R4" to W.
                 explicitly teach a typed three-premise rule in ordinary language
  /teach-relation-type RELATION|transitive/symmetric/irreflexive/asymmetric/functional/closed-world|SOURCE
                 declare relation behavior, a constraint, or a closed-world boundary
  Teach CRMS that the relation "RELATION" is transitive/symmetric/irreflexive/asymmetric/functional/closed-world.
                 declare a bounded relation schema in ordinary language
  /suggest-inference-rules [MIN_SUPPORT|HOLDOUT_SOURCE_PREFIX][|arity=3]
                 discover/review rules; arity=3 enables typed three-premise search
  /accept-inference-rule N|ID|HOLDOUT_SOURCE_PREFIX[|arity=3]
                 install a candidate only after passing holdout validation
  Accept rule candidate N as "ID" using held-out source prefix "PREFIX".
                 accept through the same source-separated validation gate
  /infer-relation SUBJECT|RELATION|OBJECT
                 check a derived triple with cited rule premises
  /abduce SUBJECT|RELATION|OBJECT[|KEY=VALUE,...]
                 find bounded cited hypotheses from the latest pending candidates
  /practice-inference SUBJECT|RELATION|OBJECT
                 store a verified inference separately as a derived case
  /practice-question QUESTION
                 answer and retain one unique proof-backed inference
  /auto-practice on|off
                 session-only write-back for unique proof-backed answers
  /derived-cases inspect practice artifacts and current proof validity
  Turn auto-practice on|off
                 conversational session-only control for proof-backed practice
  Show derived cases
                 inspect practiced conclusions, current validity, and lineage
  /counterfactual-path-without-source START|TARGET|REL1>REL2|SOURCE[|KEY=VALUE...]
                 check whether a path survives removing one cited source
  /teach-path-question Q|REL1>REL2|ENTITY|ANSWER
                 teach a question over a fact path of up to three relations
  /teach-counterfactual-source-question Q|REL1>REL2|START|TARGET|SOURCE[|KEY=VALUE...]
                 teach a sourced counterfactual question frame
  /teach-counterfactual-path-question Q|REL1>REL2|START|TARGET|SOURCE[|KEY=VALUE...]
                 teach a frame that varies both endpoints and source
  /teach-rule I|INPUT CSV|OUTPUT CSV
                 teach one grounded list-transformation example
  /retry-rule I   rerun stored demonstrations under current rule bounds
  Try to learn the rule for INSTRUCTION
                 rerun stored examples in ordinary CRMS language
  /procedure-scaffolds [MIN_SUPPORT]
                 inspect successful procedure abstractions and their evidence
  /primitive-proposals [MIN_SUPPORT]
                 inspect held-out and MDL-gated primitive proposals
  /accept-primitive ID|N
                 accept the exact proposal ID, or a current list number
  Show primitive proposals
                 review report-only operations from held-out and MDL checks
  Accept primitive proposal ID
                 explicitly add one current, validated operation to the search grammar
  /accepted-primitives
                 inspect explicitly accepted primitive schemas
  /accepted-primitive-artifacts
                 inspect the evidence lineage retained for accepted schemas
  /revoke-primitive N
                 remove an accepted schema when no learned rule depends on it
  /apply-rule I|INPUT CSV
                 apply a learned instruction rule to an integer list
  /explain-rule I|INPUT CSV
                 inspect the procedure and examples grounding a prediction
  /rules         inspect learned list-transformation rules
  /write-fact S|R|O|positive/negative
                 write a stored fact with a learned sentence frame
  /write-about ENTITY[|KEY=VALUE...]
                 compose a short sourced digest from learned sentence frames
  Write about ENTITY
                 compose the same digest from verified facts and learned frames
  /facts         inspect stored positive and negative facts
  /sources [PAGE] inspect corpus size and browse indexed sources (50 per page)
  /accept [N]    explicitly accept a reviewed fact candidate (default: 1)
  /reject N      dismiss one reviewed fact candidate without storing it
  /pending-candidates
                 list pending candidates, including ones restored from disk
  /invalidated-candidates
                 inspect queued facts that no longer pass source/frame checks
  /clear-invalidated-candidates
                 clear the inspect-only invalidation history
  /skip          dismiss current fact candidates
  /reset         clear conversational referent and pending clarification
  /cancel-rule   stop waiting for a contrastive rule example
  /quit          save state and exit
Ask a question directly to search the supplied index and use learned facts.
Math accepts "What is INTEGER PHRASE INTEGER?"; operation phrases require
multiple exact examples before CRMS will evaluate them.
Candidates from research are never committed until you explicitly accept them.
Say "accept candidate 1" or "reject candidate 1" to review one proposal;
several proposals require a number. /accept, /reject, and /skip are available
too. Acceptance revalidates the source citation. /abduce checks only candidates
from the most recent research query and never accepts them.
To teach a transformation in conversation, enter:
  reverse the list [1,2,3] -> [3,2,1]
To ground two phrases to one rule from the same evidence, enter:
  Teach both "reverse the list" and "invert the sequence" using the same examples: [1,2,3] -> [3,2,1]; [5,0,-2] -> [-2,0,5]
To apply one learned rule to multiple lists, enter:
  Reverse the list [1,2,3] and [5,0,-2]
Use [] for an empty list. Add another input/output pair when CRMS asks for one.
When CRMS names a contrastive input, reply with its output, for example:
  The output is [3,2,1]
That pending input is saved across chat restarts. Use /cancel-rule to stop waiting.
"""

HELP_SHORT = """CRMS is a bounded, source-grounded learning system. Try:
  Who likes tea?                         ask a grounded question
  /source PATH                           add a document as evidence
  /teach-fact Alice|likes|tea|SOURCE QUERY|likes|positive
                                         teach one cited fact
  Teach a question frame from examples: "Who likes juice?" => "Carol"; "Who likes coffee?" => "Bob"
                                         license a reusable question pattern
  2 + 3 * 4                              use exact arithmetic

Use /help all for the complete command reference. Unknown facts and wording
are explained; CRMS abstains unless its stored evidence supports an answer.
"""

_RULE_DEMONSTRATION_PATTERNS = (
    re.compile(
        r"^\s*(?P<instruction>.+?)\s*\[(?P<input>[^\[\]]*)\]\s*"
        r"(?:->|=>|becomes|maps\s+to|yields)\s*"
        r"\[(?P<output>[^\[\]]*)\]\s*[.!?]*\s*$",
        flags=re.IGNORECASE),
    re.compile(
        r"^\s*for\s+input\s+\[(?P<input>[^\[\]]*)\]\s*,?\s*"
        r"(?P<instruction>.+?)\s+(?:->|=>|produces|maps\s+to|yields)\s*"
        r"\[(?P<output>[^\[\]]*)\]\s*[.!?]*\s*$",
        flags=re.IGNORECASE),
    re.compile(
        r"^\s*applying\s+(?P<instruction>.+?)\s+to\s+"
        r"\[(?P<input>[^\[\]]*)\]\s+(?:produces|gives|yields)\s*"
        r"\[(?P<output>[^\[\]]*)\]\s*[.!?]*\s*$",
        flags=re.IGNORECASE),
    re.compile(
        r"^\s*the\s+result\s+of\s+(?P<instruction>.+?)\s+on\s+"
        r"\[(?P<input>[^\[\]]*)\]\s+is\s*"
        r"\[(?P<output>[^\[\]]*)\]\s*[.!?]*\s*$",
        flags=re.IGNORECASE),
)
_RULE_BATCH_PREFIX_RE = re.compile(
    r"^\s*(?P<instruction>.+?)\s*:\s*(?P<examples>.+?)\s*$",
    flags=re.IGNORECASE)
_RULE_SHARED_PHRASES_RE = re.compile(
    r"^\s*(?:teach|learn)\s+both\s+(?P<first>\"[^\"]+\"|'[^']+')\s+and\s+"
    r"(?P<second>\"[^\"]+\"|'[^']+')\s+using\s+the\s+same\s+"
    r"examples\s*:\s*(?P<examples>.+?)\s*$",
    flags=re.IGNORECASE | re.DOTALL)
_RULE_EXAMPLE_PAIR_RE = re.compile(
    r"\[(?P<input>[^\[\]]*)\]\s*(?:->|=>|becomes|maps\s+to|yields)\s*"
    r"\[(?P<output>[^\[\]]*)\]",
    flags=re.IGNORECASE)
_RULE_BATCH_SEPARATOR_RE = re.compile(r"\s*(?:;|\band\b)\s*", re.IGNORECASE)
_NATURAL_TRANSLATION_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?(?:teach|learn)\s+(?:a\s+)?"
    r"(?:translation|rewrite)\s+frame\s+"
    r"from\s+([^:]+?)\s+to\s+([^:]+?)\s+in\s+([^:]+?)\s+register\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_TRANSLATION_EXAMPLES_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+(?:translation|rewrite)\s+examples\s+"
    r"from\s+([^:]+?)\s+to\s+([^:]+?)\s+in\s+([^:]+?)\s+register\s*:\s*"
    r"(.+?)\s*\Z", re.IGNORECASE | re.DOTALL)
_NATURAL_TRANSLATION_ADDITIONAL_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+(?:an?\s+)?(?:additional|another|one\s+more)\s+"
    r"(?:translation|rewrite)\s+example\s+from\s+([^:]+?)\s+to\s+([^:]+?)\s+"
    r"in\s+([^:]+?)\s+register\s*:\s*"
    r'"([^"\r\n]+)"\s*(?:=>|->)\s*"([^"\r\n]+)"\s*[.!?]*\s*\Z',
    re.IGNORECASE | re.DOTALL)
_NATURAL_TRANSLATION_PAIR_RE = re.compile(
    r'\s*"([^"\r\n]+)"\s*(?:=>|->)\s*"([^"\r\n]+)"\s*\Z')
_NATURAL_TRANSLATION_REGISTER_RESPONSE_RE = re.compile(
    r"\s*(?:please\s+)?(?:(?:i\s+mean|(?:the\s+)?source\s+language\s+is|"
    r"go\s+with|use|choose|select|pick)\s+)?"
    r"(?:the\s+)?(?P<label>[a-z][a-z -]{0,63}?)"
    r"(?:\s+(?:register|one|option))?[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_MATH_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+math\s+from\s+examples\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_MATH_PAIR_RE = re.compile(
    r'\s*"([^"\r\n]+)"\s*(?:->|=>)\s*([+-]?\d{1,100}(?:/[1-9]\d{0,99})?)\s*[.!?]?\s*\Z')
_NATURAL_UNIT_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+unit\s+conversions\s+from\s+examples\s*:\s*"
    r"(.+?)\s*\Z", re.IGNORECASE | re.DOTALL)
_NATURAL_UNIT_PAIR_RE = re.compile(
    r'\s*"([^"\r\n]+)"\s*(?:->|=>)\s*"([^"\r\n]+)"\s*\Z')
_NATURAL_MATH_FEEDBACK_RE = re.compile(
    r"\s*(?:(?:the\s+)?(?:answer|result|output)\s*(?:is|:)|"
    r"it\s+(?:is|should\s+be|equals)|then)?\s*"
    r"([+-]?\d{1,100}(?:/[1-9]\d{0,99})?)\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_PRIMITIVE_PROPOSAL_REQUEST_RE = re.compile(
    r"\s*(?:please\s+)?(?:(?:show|list)(?:\s+me)?\s+"
    r"(?:the\s+)?(?:current\s+)?(?:validated\s+)?primitive\s+proposals|"
    r"(?:what|which)\s+primitive\s+proposals\s+are\s+available)\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_PRIMITIVE_ACCEPT_RE = re.compile(
    r"\s*(?:please\s+)?accept\s+(?:the\s+)?primitive\s+proposal\s+"
    r"(?:with\s+id\s+)?(primitive-proposal-v1-[a-f0-9]{64})\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_PRIMITIVE_LEARN_RE = re.compile(
    r"\s*(?:please\s+)?(?:learn|train|synthesize)\s+(?:from|using)\s+"
    r"(?:the\s+)?(?:current\s+)?(?:validated\s+)?primitive\s+proposal\s+"
    r"(?:with\s+id\s+)?(primitive-proposal-v1-[a-f0-9]{64})\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_PRIMITIVE_SELF_LEARN_RE = re.compile(
    r"\s*(?:please\s+)?(?:learn|discover\s+and\s+learn)\s+"
    r"(?:(?:the\s+)?best\s+|one\s+)?(?:current\s+)?"
    r"(?:validated\s+)?primitive\s+(?:proposal|rule)s?\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_RULE_RETRY_RE = re.compile(
    r"\s*(?:please\s+)?(?:retry|relearn|try\s+(?:to\s+)?learn)\s+"
    r"(?:the\s+)?(?:stored\s+)?rule\s+(?:for|from)\s+(.+?)\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_INFERENCE_RULE_REVIEW_RE = re.compile(
    r"\s*(?:please\s+)?(?:review|validate|check)\s+(?:the\s+)?"
    r"(?:inference\s+)?rule\s+(?:candidates|proposals)\s+"
    r"(?:against|using)\s+(?:the\s+)?held[- ]out\s+sources?"
    r"(?:\s+with\s+prefix)?\s+(.+?)\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_INFERENCE_RULE_ACCEPT_RE = re.compile(
    r"\s*(?:please\s+)?accept\s+(?:the\s+)?(?:inference\s+)?"
    r"rule\s+candidate\s+(?P<number>\d+)\s+as\s+['\"]"
    r"(?P<rule_id>[^'\"\r\n]+)['\"]\s+"
    r"(?:using|against)\s+(?:the\s+)?held[- ]out\s+source\s+prefix\s+"
    r"['\"](?P<prefix>[^'\"\r\n]+)['\"]"
    r"(?:\s+with\s+arity\s*(?P<arity>[23]))?\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_INFERENCE_RULE_TEACH_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+(?:crms\s+)?rule\s+['\"]"
    r"(?P<rule_id>[^'\"\r\n]+)['\"]\s*:\s*"
    r"if\s+X\s+has\s+relation\s+['\"](?P<first>[^'\"\r\n]+)['\"]"
    r"\s+to\s+Y\s+and\s+Y\s+has\s+relation\s+"
    r"['\"](?P<second>[^'\"\r\n]+)['\"]\s+to\s+Z\s*,?\s*"
    r"then\s+X\s+has\s+relation\s+['\"]"
    r"(?P<conclusion>[^'\"\r\n]+)['\"]\s+to\s+Z\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_TYPED_INFERENCE_RULE_TEACH_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+(?:crms\s+)?rule\s+['\"]"
    r"(?P<rule_id>[^'\"\r\n]+)['\"]\s*:\s*"
    r"if\s+X\s+has\s+relation\s+['\"](?P<first>[^'\"\r\n]+)['\"]"
    r"\s+to\s+Y\s*,?\s+Y\s+is\s+of\s+kind\s+['\"]"
    r"(?P<middle_kind>[^'\"\r\n]+)['\"]\s*,?\s+and\s+Y\s+has\s+"
    r"relation\s+['\"](?P<second>[^'\"\r\n]+)['\"]\s+to\s+Z"
    r"\s*,?\s+Z\s+is\s+of\s+kind\s+['\"]"
    r"(?P<second_middle_kind>[^'\"\r\n]+)['\"]\s*,?\s+and\s+Z\s+"
    r"has\s+relation\s+['\"](?P<third>[^'\"\r\n]+)['\"]\s+to\s+W"
    r"\s*,?\s+then\s+X\s+has\s+relation\s+['\"]"
    r"(?P<conclusion>[^'\"\r\n]+)['\"]\s+to\s+W\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_RELATION_TYPE_TEACH_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+(?:crms\s+)?that\s+the\s+relation\s+"
    r"['\"]([^'\"\r\n]+)['\"]\s+is\s+"
    r"(transitive|symmetric|irreflexive|asymmetric|functional|closed-world)"
    r"\s*[.!?]*\s*\Z", re.IGNORECASE)
_NATURAL_QUESTION_FRAME_REVIEW_RE = re.compile(
    r"\s*(?:please\s+)?(?:review|show|list)(?:\s+me)?\s+"
    r"(?:the\s+)?(?:current\s+)?question\s+frame\s+proposals\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_PREDICATE_FORM_REVIEW_RE = re.compile(
    r"\s*(?:please\s+)?(?:review|show|list)(?:\s+me)?\s+"
    r"(?:the\s+)?(?:current\s+)?(?:alternate\s+)?"
    r"predicate(?:[- ]form)?s?(?:\s+proposals?)?\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_PREDICATE_FORM_ACCEPT_RE = re.compile(
    r"\s*(?:please\s+)?accept\s+(?:the\s+)?predicate[- ]form\s+"
    r"proposal\s+(?:with\s+id\s+)?([a-f0-9]{24})\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_QUESTION_FRAME_TRAIN_RE = re.compile(
    r"\s*(?:please\s+)?(?:learn|train)\s+(?:the\s+)?"
    r"(?:current\s+)?(?:validated\s+)?question[- ]frame\s+proposals\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_QUESTION_FRAME_ACCEPT_RE = re.compile(
    r"\s*(?:please\s+)?accept\s+(?:the\s+)?question\s+frame\s+proposal\s+"
    r"(?:with\s+id\s+)?(question-frame-proposal-v1-[a-f0-9]{24}|"
    r"question-role-alternation-v1-[a-f0-9]{24})\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_AUTO_PRACTICE_RE = re.compile(
    r"\s*(?:please\s+)?(?:(?:turn|switch)\s+auto-practice\s+(on|off)|"
    r"(enable|disable)\s+auto-practice)\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_DERIVED_CASES_RE = re.compile(
    r"\s*(?:please\s+)?(?:show|list)(?:\s+me)?\s+"
    r"(?:the\s+)?(?:current\s+)?derived\s+cases\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_ABOUT_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+(?:an?\s+)?about[- ]request\s+frame\s+"
    r"from\s+examples\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_TIMELINE_REQUEST_RE = re.compile(
    r"\s*(?:please\s+)?(?:tell\s+me\s+the\s+story\s+of|"
    r"write\s+a\s+timeline\s+for)\s+(.+?)\s+"
    r"(?:ordered\s+by|in)\s+(year|date)\s*[.!?]*\s*\Z",
    re.IGNORECASE)
_NATURAL_ABOUT_PAIR_RE = re.compile(
    r'\s*"([^"\r\n]+)"\s*(?:=>|->)\s*"([^"\r\n]+)"\s*[.!?]?\s*\Z')
_NATURAL_QUESTION_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+a\s+question\s+frame\s+"
    r"from\s+examples\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_PAIRED_QUESTION_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+(?:paired|related)\s+question\s+frames\s+"
    r"from\s+examples\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_QUESTION_PAIR_RE = re.compile(
    r'\s*"([^"\r\n]+)"\s*(?:=>|->)\s*"([^"\r\n]+)"\s*[.!?]?\s*\Z')
_NATURAL_QUESTION_ADDITIONAL_RE = re.compile(
    r'\s*(?:please\s+)?teach\s+(?:one\s+more|an?\s+additional)\s+'
    r'question\s+example\s*:\s*"([^"\r\n]+)"\s*(?:=>|->)\s*'
    r'"([^"\r\n]+)"\s*[.!?]?\s*\Z', re.IGNORECASE)
_NATURAL_QUALIFIED_QUESTION_ADDITIONAL_RE = re.compile(
    r'\s*(?:please\s+)?teach\s+(?:one\s+more|an?\s+additional)\s+'
    r'(?:contextual|qualified)\s+question\s+example\s*:\s*'
    r'"([^"\r\n]+)"\s*(?:=>|->)\s*"([^"\r\n]+)"\s*[.!?]?\s*\Z',
    re.IGNORECASE)
_NATURAL_POLAR_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+a\s+yes/no\s+frame\s+"
    r"from\s+examples\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_POLAR_PAIR_RE = re.compile(
    r'\s*"([^"\r\n]+)"\s*(?:=>|->)\s*(yes|no)\s*[.!?]?\s*\Z',
    re.IGNORECASE)
_NATURAL_PATH_QUESTION_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+a\s+path[- ]question\s+frame\s+"
    r"from\s+examples\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_FACT_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+a\s+sourced\s+fact\s+pattern\s+"
    r"from\s+examples\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_TEACHER_FACT_PREFIX_RE = re.compile(
    r"\s*(?:please\s+)?teach\s+(?:me\s+)?a\s+fact\s+pattern\s+"
    r"from\s+labeled\s+examples\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_NATURAL_FACT_PAIR_RE = re.compile(
    r'\s*"([^"\r\n]+)"\s*(?:=>|means)\s*'
    r'"([^"\r\n]+)"\s*\|\s*"([^"\r\n]+)"\s*\|\s*'
    r'"([^"\r\n]+)"'
    r'(?:\s*\|\s*"(positive|negative)")?'
    r'(?:\s*\[\s*"([^"\r\n]+)"\s*\|\s*'
    r'"([^"\r\n]+)"\s*\|\s*"([^"\r\n]+)"\s*\])?\s*\Z',
    re.IGNORECASE)
_NATURAL_FACT_RETRACTION_RE = re.compile(
    r'\s*(?:please\s+)?retract\s+the\s+(positive|negative)\s+fact\s+'
    r'"([^"\r\n]+)"\s+from\s+source\s+"([^"\r\n]+)"'
    r'(?:\s+in\s+context\s+"([^"\r\n]+)")?\s*[.!?]*\s*\Z',
    re.IGNORECASE)
_NATURAL_USER_FACT_TEACH_RE = re.compile(
    r'\s*(?:please\s+)?remember\s+that\s+"([^"\r\n]+)"\s+'
    r'as\s+a\s+fact\s+from\s+source\s+"([^"\r\n]+)"\s*[.!?]*\s*\Z',
    re.IGNORECASE)
_NATURAL_CANDIDATE_DECISION_RE = re.compile(
    r"\s*(?:please\s+)?(?:i\s+)?"
    r"(?P<decision>accept|approve|reject|decline|dismiss|skip)"
    r"(?:\s+(?:(?:the|this|that)\s+)?"
    r"(?:candidate|fact|claim|proposal|it|this|that))?"
    r"(?:\s+(?P<number>\d+))?\s*[.!]?\s*\Z",
    re.IGNORECASE)


def _training_sentence(hit, subject: str, obj: str,
                       predicate_phrase: str, *, subject_phrase: str | None = None,
                       object_phrase: str | None = None) -> str | None:
    """Find one exact sentence with unique, non-overlapping labeled spans."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", hit.snippet):
        sentence = sentence.strip()
        words = normalized_tokens(sentence)
        spans = []
        valid = True
        for value in (subject_phrase or subject, object_phrase or obj,
                      predicate_phrase):
            phrase = normalized_tokens(value)
            starts = [i for i in range(len(words) - len(phrase) + 1)
                      if words[i:i + len(phrase)] == phrase]
            if not phrase or len(starts) != 1:
                valid = False
                break
            spans.append((starts[0], starts[0] + len(phrase)))
        if valid and not any(a[0] < b[1] and a[1] > b[0]
                             for i, a in enumerate(spans)
                             for b in spans[i + 1:]):
            return sentence
    return None


def _parse_integer_list(value: str, *, allow_empty: bool = False) -> list[int]:
    parts = value.split(",")
    if not value.strip() and allow_empty:
        return []
    if not value.strip() or any(not part.strip() for part in parts):
        raise ValueError("provide a comma-separated list of integers")
    return [int(part.strip()) for part in parts]


def _normalize_natural_rule_instruction(instruction: str) -> str | None:
    instruction = instruction.strip().rstrip(" .?!:").strip()
    instruction = re.sub(
        r"^(?:please\s+)?(?:apply(?:ing)?|perform(?:ing)?|run(?:ning)?|"
        r"teach(?:ing)?)\s+",
                         "", instruction, flags=re.IGNORECASE)
    instruction = re.sub(r"^(?:what is the result of|what happens if i)\s+",
                         "", instruction, flags=re.IGNORECASE)
    instruction = re.sub(r"\s+(?:to|on)$", "", instruction, flags=re.IGNORECASE)
    if not instruction or re.match(
            r"^(what|which|who|how|is|are|did|does|do)\b",
            instruction, flags=re.IGNORECASE):
        return None
    return instruction


def _natural_summary_request(message: str) -> str | None:
    match = re.fullmatch(
        r"\s*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:summarize|summarise|summary\s+of|"
        r"give\s+me\s+a\s+summary\s+of)\s+(.+?)\s*[.!?]?\s*",
        message, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _natural_definition_topic(message: str) -> str | None:
    """Recognize a simple definition question for exact-title lookup."""
    match = re.fullmatch(
        r"\s*what\s+(?:is|are)\s+(?P<topic>.+?)\s*[?!.]?\s*",
        message, flags=re.IGNORECASE)
    if match is None:
        return None
    topic = re.sub(r"^(?:a|an|the)\s+", "", match.group("topic").strip(),
                   flags=re.IGNORECASE)
    return topic or None


def _exact_title_hits(index: CRMSSQLiteResearchIndex,
                      title: str) -> list[SearchHit]:
    return [hit for hit in index.search(title, limit=50, context_chars=240)
            if hit.title.casefold() == title.casefold()]


def _exact_title_definition(index: CRMSSQLiteResearchIndex,
                            topic: str) -> dict[str, Any] | None:
    """Quote a definition only from one exact-title source and its own lead."""
    hits = _exact_title_hits(index, topic)
    if len(hits) != 1:
        return None
    summary = index.summarize(topic, limit=20, precomputed_hits=hits)
    title_pattern = re.compile(
        r"^\s*" + re.escape(topic) +
        r"(?:\s*\([^)]*\))?\s+(?:is|are|was|were|means|refers\s+to)\b",
        flags=re.IGNORECASE)
    definitions = [sentence for sentence in summary.sentences
                   if title_pattern.search(sentence.text)]
    if len(definitions) != 1:
        return None
    sentence = definitions[0]
    return {
        "document_id": sentence.document_id,
        "title": sentence.title,
        "location": sentence.location,
        "text": sentence.text,
        "citation": sentence.citation,
    }


def _natural_where_lookup(message: str) -> tuple[str, str] | None:
    """Parse a bounded where-question that asks for a person/place relation."""
    match = re.fullmatch(
        r"\s*where\s+(?:does|did|do|is|are|was|were)\s+"
        r"(?P<entity>.+?)\s+(?P<predicate>work|live|was\s+born|born|"
        r"is\s+located|are\s+located|located|is\s+based|are\s+based|based)"
        r"\s*[?!.]?\s*", message, flags=re.IGNORECASE)
    if match is None:
        return None
    entity = re.sub(r"^(?:the|a|an)\s+", "", match.group("entity").strip(),
                    flags=re.IGNORECASE)
    predicate = re.sub(r"\s+", " ", match.group("predicate").casefold())
    for prefix in ("was born", "is located", "are located", "is based",
                   "are based"):
        if predicate.startswith(prefix):
            predicate = prefix.split()[-1]
            break
    return (entity, predicate) if entity else None


def _natural_typed_relation_question(
        message: str) -> tuple[str, str, str, str] | None:
    """Parse `Which TYPE VERB PREPOSITION ENTITY?` without alias guessing."""
    match = re.fullmatch(
        r"\s*(?:which|what)\s+(?P<type>[a-z][\w’'-]*)\s+"
        r"(?P<predicate>[a-z][\w’'-]*)\s+"
        r"(?P<preposition>through|into|across|along|within|near|from|to|in|at|on)\s+"
        r"(?P<object>.+?)\s*[?!.]?\s*",
        message, flags=re.IGNORECASE)
    if match is None:
        return None
    object_text = re.sub(r"^(?:a|an|the)\s+", "",
                         match.group("object").strip(), flags=re.IGNORECASE)
    if not normalized_tokens(object_text):
        return None
    return (match.group("type").casefold(),
            match.group("predicate").casefold(),
            match.group("preposition").casefold(), object_text)


def _candidates_relevant_to_answer(
        question: str, candidates: list[FactCandidate]) -> list[FactCandidate]:
    """Drop weakly related proposals when a supported answer already exists."""
    query_terms = (set(_research_query_terms(question))
                   - _RESEARCH_STOPWORDS)
    if len(query_terms) < 2:
        return candidates
    return [
        candidate for candidate in candidates
        if len(query_terms & set(_research_query_terms(
            f"{candidate.subject} {candidate.relation} "
            f"{candidate.object}"))) >= 2]


def _natural_typed_relation_source_evidence(
        index: CRMSSQLiteResearchIndex,
        query: tuple[str, str, str, str],
        question: str | None = None,
        licensed_predicate_families: dict[str, set[str]] | None = None
        ) -> dict[str, Any]:
    """Find source sentences that jointly fill a typed relation question.

    Retrieval proposes candidate pages; the answer requires a sentence with
    the requested predicate and object, plus explicit class evidence for the
    same page entity. Lexical co-occurrence alone cannot name an answer.
    """
    requested_type, predicate, preposition, object_text = query
    question_surface = (question.strip().rstrip("?.!") if question
                        else "Which " + requested_type + " " + predicate
                        + " " + preposition + " " + object_text)
    object_terms = tuple(normalized_tokens(object_text))
    default_relation = f"{predicate} {preposition}"
    relation_phrases = {default_relation: {default_relation}}
    for canonical, forms in (licensed_predicate_families or {}).items():
        relation_phrases[canonical] = set(forms)
    all_phrases = sorted({phrase for forms in relation_phrases.values()
                          for phrase in forms})
    evidence_by_entity: dict[tuple[str, ...], dict[str, Any]] = {}
    hits_by_document = {}
    for phrase in all_phrases:
        search_query = " ".join((phrase, object_text))
        for hit in index.search(search_query, limit=500, context_chars=240):
            hits_by_document.setdefault(hit.document_id, hit)
    for hit in hits_by_document.values():
        if _is_code_source(hit.location):
            continue
        document = index.document(hit.document_id)
        page_entity = hit.title.split("(", 1)[0].strip()
        for start, end in _sentence_spans(document.text):
            sentence = document.text[start:end]
            if (_sentence_context_kind(sentence, document.text, start)
                    != "assertion"):
                continue
            sentence_terms = tuple(normalized_tokens(sentence))
            if not all(term in sentence_terms for term in object_terms):
                continue
            relation_match = None
            relation_subject = None
            matched_surface = None
            canonical_relation = default_relation
            for canonical, forms in relation_phrases.items():
                for phrase in forms:
                    phrase_pattern = r"\s+".join(
                        re.escape(term) for term in normalized_tokens(phrase))
                    if not phrase_pattern:
                        continue
                    for phrase_match in re.finditer(
                            rf"\b{phrase_pattern}\b", sentence,
                            flags=re.IGNORECASE):
                        phrase_start, phrase_end = phrase_match.span()
                        raw_subject = sentence[:phrase_start].strip()
                        subject_prefix = re.sub(
                            r"^(?:the|a|an)\s+", "", raw_subject,
                            flags=re.IGNORECASE)
                        page_lead = re.match(
                            r"^\s*(?P<article>the\s+)?"
                            + re.escape(page_entity) + r"\b",
                            sentence[:phrase_start], flags=re.IGNORECASE)
                        # Keep the subject parse narrow and explicit. The
                        # learned predicate alignment changes only the
                        # relation wording; it does not relax argument roles.
                        if page_lead is not None:
                            relation_subject = (
                                (page_lead.group("article") or "")
                                + page_entity)
                        elif (subject_prefix
                              and subject_prefix[0].isupper()
                              and re.fullmatch(
                                  r"[A-Z0-9][\w’'.-]*(?:\s+"
                                  r"[A-Z0-9][\w’'.-]*)*",
                                  subject_prefix) is not None):
                            relation_subject = raw_subject
                        else:
                            continue
                        tail = sentence[phrase_end:]
                        object_match = re.search(
                            r"\s+(?:(?:the|a|an|north|south|east|west|"
                            r"upper|lower)\s+){0,5}"
                            + r"(?P<object>" + r"\s+".join(
                                re.escape(term) for term in object_terms)
                            + r")\b", tail, flags=re.IGNORECASE)
                        if object_match is None:
                            continue
                        relation_match = (
                            phrase_start, phrase_end + object_match.end())
                        matched_surface = phrase
                        canonical_relation = canonical
                        break
                    if relation_match is not None:
                        break
                if relation_match is not None:
                    break
            if relation_match is None or relation_subject is None:
                continue
            clause = sentence[max(0, relation_match[0] - 20):relation_match[1]]
            negative = bool(re.search(
                r"\b(?:not|never|no|doesn't|didn't|isn't|wasn't)\b",
                clause, flags=re.IGNORECASE))
            subject = relation_subject
            subject_key = re.sub(r"^(?:the|a|an)\s+", "", subject,
                                 flags=re.IGNORECASE)
            subject_terms = tuple(normalized_tokens(subject_key))
            matched_terms = tuple(sorted(set(
                (*subject_terms,
                 *normalized_tokens(matched_surface or default_relation),
                 *object_terms))))
            relation_evidence = _cited_sentence_evidence(
                index, hit, start, end, matched_terms)
            if relation_evidence is None:
                continue
            relation_candidate = FactCandidate(
                subject, canonical_relation, object_text,
                relation_evidence["citation"],
                f"<subject> {matched_surface} <object>",
                sentence, not negative,
                language_evidence=(
                    {
                        "kind": "surface_relation_discovery",
                        "method": "typed relation source pattern",
                        "review_required": True,
                        "predicate_phrase": matched_surface,
                        "subject": subject,
                        "object": object_text,
                        "sources": [relation_evidence["citation"]],
                        "warning": ("Question wording was aligned to this "
                                    "source sentence; confirm the relation "
                                    "and argument roles."),
                    },
                    {
                        "kind": "typed_relation_source_match",
                        "method": "exact predicate, object, and sentence-subject alignment",
                        "review_required": True,
                        "requested_type": requested_type,
                        "question": question_surface,
                    },))

            title_pattern = (r"^\s*(?:the\s+)?"
                             + re.escape(subject_key)
                             + r"\s+(?:is|are|was|were)\s+"
                             + r"(?P<negative>not\s+)?(?:a|an)\s+"
                             + re.escape(requested_type) + r"\b")
            type_candidates = []
            for type_hit in index.search(
                    f"{subject_key} {requested_type}", limit=100,
                    context_chars=180):
                if _is_code_source(type_hit.location):
                    continue
                type_document = index.document(type_hit.document_id)
                for type_start, type_end in _sentence_spans(type_document.text):
                    type_sentence = type_document.text[type_start:type_end]
                    if (_sentence_context_kind(
                            type_sentence, type_document.text, type_start)
                            != "assertion"):
                        continue
                    type_match = re.match(title_pattern, type_sentence,
                                          flags=re.IGNORECASE)
                    if type_match is None:
                        continue
                    type_evidence = _cited_sentence_evidence(
                        index, type_hit, type_start, type_end,
                        tuple(sorted(set((*subject_terms, requested_type)))))
                    if type_evidence is None:
                        continue
                    type_subject = subject
                    type_candidates.append(FactCandidate(
                        type_subject, "is-a", requested_type,
                        type_evidence["citation"],
                        "<subject> is-a <type>", type_sentence,
                        not bool(type_match.group("negative")),
                        language_evidence=(
                            {
                                "kind": "surface_relation_discovery",
                                "method": "copular class-membership pattern",
                                "review_required": True,
                                "predicate_phrase": "is a",
                                "subject": type_subject,
                                "object": requested_type,
                                "sources": [type_evidence["citation"]],
                            },
                            {
                                "kind": "explicit_type_source_match",
                                "method": "direct copular class statement",
                                "review_required": True,
                                "requested_type": requested_type,
                                "question": question_surface,
                            },)))
            key = tuple(normalized_tokens(subject))
            item = evidence_by_entity.setdefault(key, {
                "entity": subject, "relation": [], "type": []})
            item["relation"].append(relation_candidate)
            item["type"].extend(type_candidates)
    return {"matches": [evidence_by_entity[key]
                        for key in sorted(evidence_by_entity)],
            "requested_type": requested_type,
            "predicate": predicate, "preposition": preposition,
            "object": object_text}


def _natural_object_wh_source_evidence(
        index: CRMSSQLiteResearchIndex,
        question: str, *,
        known_relations: set[tuple[str, ...]] | None = None
        ) -> dict[str, Any] | None:
    """Find an exact active-clause source for a bounded object question.

    The subject phrase and predicate must align with the beginning of one
    asserted sentence. Exact and mechanically recognized verb forms can
    produce a review-only fact candidate. A different source predicate is
    proposed only when the question's canonical relation already exists in
    accepted knowledge; accepting that proposal is the explicit human mapping.
    This route never writes a fact on its own.
    """
    match = re.fullmatch(
        r"\s*(?:what|which(?:\s+[a-z][\w’'-]*){0,2})\s+"
        r"(?:did|does|do)\s+(?P<subject>.+?)\s+"
        r"(?P<predicate>[a-z][\w’'-]*)\s*[?!.]?\s*",
        question, flags=re.IGNORECASE)
    if match is None:
        return None
    subject = match.group("subject").strip()
    subject_terms = tuple(normalized_tokens(subject))
    predicate = match.group("predicate").casefold()
    if not subject_terms or not predicate:
        return None
    known_relations = known_relations or set()
    relation_hypotheses: dict[
        tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
        tuple[dict[str, Any], FactCandidate]
    ] = {}
    # Search the subject phrase so regular verb forms such as study/studied
    # do not disappear at the lexical retrieval stage. The sentence scan
    # below independently checks the predicate and its argument order.
    for hit in index.search(" ".join(subject_terms),
                            limit=500, context_chars=240):
        if _is_code_source(hit.location):
            continue
        document = index.document(hit.document_id)
        for start, end in _sentence_spans(document.text):
            sentence = document.text[start:end]
            if (_sentence_context_kind(sentence, document.text, start)
                    != "assertion"):
                continue
            if re.search(r"\b(?:not|never|isn't|wasn't|didn't|doesn't)\b",
                         sentence, flags=re.IGNORECASE):
                continue
            tokens = list(re.finditer(
                r"[^\W_]+(?:['’][^\W_]+)*", sentence, flags=re.UNICODE))
            normalized = [tuple(normalized_tokens(token.group()))
                          for token in tokens]
            for position, token in enumerate(tokens):
                surface_tokens = normalized[position]
                if len(surface_tokens) != 1:
                    continue
                surface = surface_tokens[0]
                exact_or_inflected = (
                    surface == predicate
                    or _analyze_predicate_spelling(predicate, surface))
                relation_alignment = (
                    not exact_or_inflected
                    and (predicate,) in known_relations
                    and surface.endswith(("ed", "ing", "s"))
                    and surface not in {"is", "was", "does", "has"})
                if not exact_or_inflected and not relation_alignment:
                    continue
                source_subject = tuple(
                    word for part in normalized[:position] for word in part)
                if source_subject != subject_terms:
                    continue
                object_phrase = sentence[token.end():].strip(" .!?\t\r\n")
                object_words = tuple(normalized_tokens(object_phrase))
                if (not object_words or len(object_words) > 12
                        or re.search(r"[,;]", object_phrase)
                        or set(object_words) & {
                            "not", "never", "and", "or", "but", "at",
                            "by", "for", "from", "in", "into", "of",
                            "on", "over", "through", "to", "under",
                            "with", "during", "before", "after",
                        }):
                    continue
                evidence = _cited_sentence_evidence(
                    index, hit, start, end,
                    tuple(sorted(set((*subject_terms, surface)))))
                if evidence is not None:
                    evidence["context_kind"] = "assertion"
                    method = ("reviewed relation-alignment hypothesis"
                              if relation_alignment else
                              "exact-subject object-question source pattern")
                    warning = (
                        f"The question uses '{predicate}', while this source "
                        f"uses '{surface}'. Their relation is not established; "
                        "confirm the mapping and full object span before storing."
                        if relation_alignment else
                        "The subject and inflected predicate align to one "
                        "asserted sentence. Confirm the relation and full "
                        "object span before storing the fact.")
                    candidate = FactCandidate(
                        sentence[:token.start()].strip(), predicate,
                        object_phrase, evidence["citation"],
                        f"<subject> {surface} <object>", sentence, True,
                        language_evidence=({
                            "kind": "surface_relation_discovery",
                            "method": method,
                            "review_required": True,
                            "question": question,
                            "subject_phrase": sentence[:token.start()].strip(),
                            "predicate_phrase": surface,
                            "object_phrase": object_phrase,
                            "canonical_relation": predicate,
                            "sources": [evidence["citation"]],
                            "warning": warning,
                        },))
                    if relation_alignment:
                        key = (tuple(normalized_tokens(candidate.subject)),
                               tuple(normalized_tokens(candidate.relation)),
                               tuple(normalized_tokens(candidate.object)))
                        relation_hypotheses.setdefault(key, (evidence, candidate))
                    else:
                        evidence["candidate"] = candidate
                        return evidence
    if len(relation_hypotheses) == 1:
        evidence, candidate = next(iter(relation_hypotheses.values()))
        evidence["candidate"] = candidate
        return evidence
    return None


def _natural_polar_claim(message: str) -> tuple[str, str, str, str] | None:
    """Parse bounded copular-relation and do-support yes/no questions."""
    copular = re.fullmatch(
        r"\s*(?P<aux>is|are|was|were)\s+(?P<subject>.+?)\s+"
        r"(?:(?:the|a|an)\s+)?(?P<relation>[a-z][\w’'-]*(?:\s+"
        r"[a-z][\w’'-]*)*?)\s+(?P<preposition>of|in|at|for|to)\s+"
        r"(?P<object>.+?)\s*[?!.]?\s*",
        message, flags=re.IGNORECASE)
    if copular is not None:
        relation = (copular.group("relation") + " "
                    + copular.group("preposition"))
        return (copular.group("subject").strip(), relation,
                copular.group("object").strip(), "copular")
    proper_name = (
        r"[A-Z][\w’'-]*(?:\s+(?:(?:van|von|de|del|da|di|la|le)\s+)?"
        r"[A-Z][\w’'-]*)*")
    active = re.fullmatch(
        rf"\s*(?P<aux>(?i:did|do|does))\s+(?P<subject>{proper_name})\s+"
        r"(?P<relation>[a-z][\w’'-]*)"
        r"(?:\s+(?P<preposition>at|in|on|for|to|from|with|of))?\s+"
        r"(?P<object>.+?)\s*[?!.]?\s*",
        message)
    if active is not None:
        relation = active.group("relation").strip()
        if active.group("preposition"):
            relation += " " + active.group("preposition").strip()
        return (active.group("subject").strip(),
                relation,
                active.group("object").strip(), active.group("aux"))
    return None


def _natural_polar_evidence(
        knowledge: CRMSKnowledgeBase, index: CRMSSQLiteResearchIndex,
        claim: tuple[str, str, str, str]
        ) -> list[FactCandidate]:
    """Find exact source candidates for a parsed polar proposition."""
    subject, relation, object_, _mode = claim

    def entity_terms(value: str) -> tuple[str, ...]:
        words = tuple(normalized_tokens(value))
        if words and words[0] in {"a", "an", "the"}:
            words = words[1:]
        return words

    wanted_subject = entity_terms(subject)
    wanted_relation = tuple(normalized_tokens(relation))
    wanted_object = entity_terms(object_)
    if not wanted_subject or not wanted_relation or not wanted_object:
        return []
    # The relation may be inflected in the source ("create" / "created"),
    # so use the exact argument pair to find candidate documents and verify
    # predicate wording after sentence extraction. This also avoids scanning
    # a large set of documents that merely share a common relation word.
    query = " ".join((subject, object_))
    candidates: dict[tuple[Any, ...], FactCandidate] = {}
    required_entity_terms = set(wanted_subject) | set(wanted_object)
    for hit in index.search(query, limit=100, context_chars=240):
        if not required_entity_terms <= set(hit.matched_terms):
            continue
        if _is_code_source(hit.location):
            continue
        document = index.document(hit.document_id)
        for start, end in _sentence_spans(document.text):
            sentence = document.text[start:end]
            if not sentence.strip():
                continue
            if _sentence_context_kind(sentence, document.text, start) != "assertion":
                continue
            sentence_words = set(normalized_tokens(sentence))
            if not required_entity_terms <= sentence_words:
                continue
            matched_terms = tuple(sorted(
                (set(wanted_subject) | set(wanted_relation) | set(wanted_object))
                & sentence_words))
            if not matched_terms:
                continue
            evidence = _cited_sentence_evidence(
                index, hit, start, end, matched_terms)
            if evidence is None:
                continue
            parses = knowledge._discover_surface_relation_candidates(
                sentence, source=evidence["citation"], research_index=index)
            for candidate in parses:
                relation_words = tuple(normalized_tokens(candidate.relation))
                relation_matches = (
                    relation_words == wanted_relation
                    or (len(relation_words) == len(wanted_relation)
                        and all(left == right
                                or _analyze_predicate_spelling(left, right) is not None
                                for left, right in zip(wanted_relation,
                                                       relation_words))))
                if (tuple(normalized_tokens(candidate.subject)) != wanted_subject
                        or not relation_matches
                        or entity_terms(candidate.object) != wanted_object):
                    continue
                key = (tuple(normalized_tokens(candidate.subject)),
                       relation_words, entity_terms(candidate.object),
                       candidate.polarity)
                candidates.setdefault(key, candidate)
    if candidates:
        return [candidates[key] for key in sorted(candidates)]

    # A small explicit irregular-verb table supports source-backed polar
    # checks when the general candidate extractor has no frame yet. The
    # object must still occur in the same sentence after the asserted verb;
    # no unobserved paraphrase or inverse relation is inferred.
    irregular_forms = {
        "win": {"won"}, "build": {"built"}, "write": {"wrote"},
        "make": {"made"}, "go": {"went"}, "take": {"took"},
    }
    observed_forms = irregular_forms.get(" ".join(wanted_relation), set())
    if len(wanted_relation) == 1 and observed_forms:
        for hit in index.search(query, limit=100, context_chars=240):
            if not set(wanted_subject) <= set(hit.matched_terms):
                continue
            if _is_code_source(hit.location):
                continue
            document = index.document(hit.document_id)
            for start, end in _sentence_spans(document.text):
                sentence = document.text[start:end]
                if (_sentence_context_kind(sentence, document.text, start)
                        != "assertion"):
                    continue
                words = list(re.finditer(
                    r"[^\W_]+(?:['’][^\W_]+)*", sentence,
                    flags=re.UNICODE))
                normalized = [tuple(normalized_tokens(word.group()))
                              for word in words]
                flat = [part[0] if part else "" for part in normalized]
                if tuple(flat[:len(wanted_subject)]) != wanted_subject:
                    continue
                verb_position = len(wanted_subject)
                if (verb_position >= len(flat)
                        or flat[verb_position] not in observed_forms):
                    continue
                object_words = flat[verb_position + 1:]
                object_index = 0
                target_words = list(wanted_object)
                if target_words[:1] in (["a"], ["an"], ["the"]):
                    target_words = target_words[1:]
                for source_word in object_words:
                    target = target_words[object_index]
                    if (source_word == target
                            or (target.endswith("s")
                                and target[:-1] == source_word)
                            or (source_word.endswith("s")
                                and source_word[:-1] == target)):
                        object_index += 1
                        if object_index == len(target_words):
                            break
                if object_index != len(target_words):
                    continue
                matched_in_sentence = (
                    set(wanted_subject) | set(wanted_object)
                    | set(wanted_relation)) & set(flat)
                citation_evidence = _cited_sentence_evidence(
                    index, hit, start, end,
                    tuple(sorted(matched_in_sentence)))
                if citation_evidence is None:
                    continue
                source_object = sentence[words[verb_position].end():].strip(
                    " .!?\t\r\n")
                candidates[(wanted_subject, wanted_relation,
                            tuple(normalized_tokens(source_object)), True)] = FactCandidate(
                    subject, relation, source_object,
                    citation_evidence["citation"],
                    f"<subject> {' '.join(wanted_relation)} <object>",
                    sentence, True, language_evidence=({
                        "kind": "surface_relation_discovery",
                        "method": "bounded irregular verb with exact arguments",
                        "review_required": True,
                        "question": " ".join((subject, relation, object_)),
                        "predicate_phrase": flat[verb_position],
                        "warning": ("The subject, irregular verb form, and "
                                    "requested object occur in one asserted "
                                    "sentence; confirm that the wording has "
                                    "the same relation before accepting."),
                    },))
    
    return [candidates[key] for key in sorted(candidates)]


def _natural_source_lookup_topic(message: str) -> str | None:
    """Recognize a request to locate sources rather than ask a fact question."""
    match = re.fullmatch(
        r"\s*where\s+can\s+(?:i|we)\s+find\s+"
        r"(?:some\s+)?(?:information|info|sources?|articles?|pages?)\s+"
        r"(?:about|on|for)\s+(.+?)\s*[?!.]?\s*",
        message, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _render_source_lookup(index: CRMSSQLiteResearchIndex,
                          topic: str) -> str:
    topic_terms = set(normalized_tokens(topic))
    if not topic_terms:
        return "Name a topic and I can search the indexed sources."
    hits = index.search(topic, limit=100, context_chars=180)
    selected = []
    seen = set()
    for hit in hits:
        title_terms = set(normalized_tokens(hit.title))
        if not topic_terms <= title_terms or hit.title.casefold() in seen:
            continue
        seen.add(hit.title.casefold())
        selected.append(hit)
        if len(selected) == 5:
            break
    if not selected:
        return f"I couldn't find indexed source titles specifically about {topic}."
    lines = [f"Indexed sources about {topic}:"]
    for hit in selected:
        location = hit.location
        if location and " [dump:" in location:
            location = location.split(" [dump:", 1)[0]
        link = f" — {location}" if location else ""
        lines.append(f"- {hit.title}{link}")
    return "\n".join(lines)


def _cited_sentence_evidence(index: CRMSSQLiteResearchIndex, hit: SearchHit,
                             start: int, end: int,
                             matched_terms: tuple[str, ...]
                             ) -> dict[str, Any] | None:
    """Build and verify a source citation for one exact sentence span."""
    document = index.document(hit.document_id)
    page_number = None
    match_start = match_end = None
    if document.pages:
        page_offset = 0
        for page_index, page in enumerate(document.pages, start=1):
            page_end = page_offset + len(page)
            if page_offset <= start < page_end:
                if end > page_end:
                    break
                page_number = page_index
                matched_offsets = [
                    (start + token.start(), start + token.end())
                    for token in re.finditer(
                        r"[^\W_]+", document.text[start:end],
                        flags=re.UNICODE)
                    if normalized_tokens(token.group())
                    and normalized_tokens(token.group())[0] in matched_terms]
                if matched_offsets:
                    match_start = min(pair[0] for pair in matched_offsets)
                    match_end = max(pair[1] for pair in matched_offsets)
                break
            page_offset = page_end + len("\n\f\n")
        if page_number is None or match_start is None:
            return None
    sentence = document.text[start:end]
    sentence_hit = SearchHit(
        hit.document_id, hit.title, hit.location, hit.score, sentence,
        start, end, matched_terms, page_number, match_start, match_end)
    try:
        citation = index.citation(sentence_hit)
    except (KeyError, ValueError):
        return None
    return {"document_id": hit.document_id, "title": hit.title,
            "location": hit.location, "text": sentence,
            "citation": citation}


def _exact_title_location_evidence(
        index: CRMSSQLiteResearchIndex, entity: str, predicate: str
        ) -> dict[str, Any] | None:
    """Find an asserted location statement with the requested entity as subject."""
    hits = _exact_title_hits(index, entity)
    predicate_patterns = {
        "work": r"\bwork(?:s|ed|ing)?\s+(?:at|in|for)\b",
        "live": r"\bliv(?:e|es|ed|ing)\s+(?:at|in|near)\b",
        "born": r"\bborn\s+(?:at|in|on)\b",
        "located": r"\blocated\s+(?:at|in|near)\b",
        "based": r"\bbased\s+(?:at|in|near)\b",
    }
    pattern_text = predicate_patterns.get(predicate)
    if pattern_text is None:
        return None
    pattern = re.compile(pattern_text, re.IGNORECASE)
    entity_tokens = tuple(normalized_tokens(entity))
    if not entity_tokens:
        return None
    exact_title_document_ids = {hit.document_id for hit in hits} if len(hits) == 1 else set()
    if not exact_title_document_ids:
        hits = []
    # Exact-title pages can use page context for lead sentences. Also search
    # indexed source text directly so a mixed document can support the same
    # grounded answer without pretending that its title is the entity.
    seen = {hit.document_id for hit in hits}
    hits.extend(hit for hit in index.search(
        entity, limit=100, context_chars=240)
        if hit.document_id not in seen and not _is_code_source(hit.location))
    for hit in hits:
        document = index.document(hit.document_id)
        if hit.document_id in exact_title_document_ids:
            # A title search may return a metadata field (for example
            # DEFAULTSORT) instead of the article's assertion sentence. Once
            # the title is exact and unique, inspect sentence boundaries in
            # that one document rather than suppressing its other snippets.
            spans = _sentence_spans(document.text)
        elif (0 <= hit.start < hit.end
                and document.text[hit.start:hit.end] == hit.snippet):
            spans = [(hit.start + start, hit.start + end)
                     for start, end in _sentence_spans(hit.snippet)]
        else:
            spans = _sentence_spans(document.text)
        for start, end in spans:
            sentence = document.text[start:end]
            relation_match = pattern.search(sentence)
            if relation_match is None:
                continue
            subject_prefix = sentence[:relation_match.start()].strip()
            # Keep a narrow fronted temporal adjunct, such as "During World
            # War II, ...", outside the subject slot.
            temporal = re.match(r"during\b[^,]{1,120},\s*", subject_prefix,
                                flags=re.IGNORECASE)
            if temporal is not None:
                subject_prefix = subject_prefix[temporal.end():]
            subject_tokens = tuple(normalized_tokens(subject_prefix))
            valid_subject_prefixes = {
                entity_tokens, ("the", *entity_tokens),
                (*entity_tokens, "is"), (*entity_tokens, "was"),
                (*entity_tokens, "are"), (*entity_tokens, "were"),
                ("the", *entity_tokens, "is"),
                ("the", *entity_tokens, "was"),
                ("the", *entity_tokens, "are"),
                ("the", *entity_tokens, "were"),
            }
            if hit.document_id in exact_title_document_ids and len(entity_tokens) > 1:
                # Exact-title article context licenses its conventional final
                # name only as the subject alias in that same article.
                valid_subject_prefixes.add((entity_tokens[-1],))
            if subject_tokens not in valid_subject_prefixes:
                continue
            if _sentence_context_kind(
                    sentence, document.text, start) != "assertion":
                continue
            evidence = _cited_sentence_evidence(
                index, hit, start, end, entity_tokens)
            if evidence is not None:
                return evidence
    return None


def _natural_who_evidence(index: CRMSSQLiteResearchIndex,
                          question: str,
                          query_expansions: list[dict[str, Any]] | None = None
                          ) -> dict[str, Any] | None:
    """Find a person-bearing sentence that states the queried relation."""
    passive_by_whom = re.fullmatch(
        r"\s*(?P<object>.+?)\s+(?:was|were|is|are|has\s+been|have\s+been|had\s+been)\s+"
        r"(?P<predicate>[a-z][\w’'-]*)\s+by\s+whom\s*[?!.]?\s*",
        question, flags=re.IGNORECASE)
    if passive_by_whom is not None:
        object_text = passive_by_whom.group("object").strip()
        object_text = re.sub(r"^(?:a|an|the)\s+", "", object_text,
                             flags=re.IGNORECASE)
        canonical = (f"Who {passive_by_whom.group('predicate')} "
                     f"{object_text}?")
        evidence = _natural_who_evidence(index, canonical, query_expansions)
        if evidence is not None:
            evidence = dict(evidence)
            evidence["normalized_question"] = canonical
        return evidence
    nominal_who = re.fullmatch(
        r"\s*who\s+(?:is|was)\s+(?:the\s+)?"
        r"(?P<role>[a-z][\w’'-]*(?:\s+[a-z][\w’'-]*){0,2})\s+of\s+"
        r"(?P<object>.+?)\s*[?!.]?\s*",
        question, flags=re.IGNORECASE)
    if nominal_who is not None:
        role_tokens = tuple(normalized_tokens(nominal_who.group("role")))
        # Keep this route for agent nouns. A Who question for "the capital of
        # France" would ask for the wrong answer type, even if the phrase is
        # syntactically parallel.
        if role_tokens and role_tokens[-1].endswith(
                ("er", "or", "ist", "ian", "ant", "ent", "ess")):
            object_text = re.sub(
                r"^(?:the|a|an)\s+", "", nominal_who.group("object").strip(),
                flags=re.IGNORECASE)
            object_text = re.sub(r"[?!.]+$", "", object_text).strip()
            object_tokens = tuple(normalized_tokens(object_text))
            relation_tokens = (*role_tokens, "of")
            required = set((*relation_tokens, *object_tokens))
            matched_by_answer: dict[tuple[str, ...], dict[str, Any]] = {}
            knowledge = CRMSKnowledgeBase()
            for hit in index.search(
                    " ".join((*relation_tokens, *object_tokens)),
                    limit=50, context_chars=240):
                if _is_code_source(hit.location):
                    continue
                document = index.document(hit.document_id)
                # Search hits usually carry the exact matching text span.
                # Split only that local passage when it verifies against the
                # source body; scanning every sentence of every whole article
                # made nominal questions needlessly expensive on SimpleWiki.
                if (0 <= hit.start < hit.end
                        and document.text[hit.start:hit.end] == hit.snippet):
                    passage_start = hit.start
                    candidate_spans = [
                        (passage_start + start, passage_start + end)
                        for start, end in _sentence_spans(hit.snippet)]
                else:
                    candidate_spans = _sentence_spans(document.text)
                for start, end in candidate_spans:
                    sentence = document.text[start:end]
                    if (not required <= set(normalized_tokens(sentence))
                            or _sentence_context_kind(
                                sentence, document.text, start) != "assertion"):
                        continue
                    source_evidence = _cited_sentence_evidence(
                        index, hit, start, end, tuple(sorted(required)))
                    if source_evidence is None:
                        continue
                    proposals = knowledge._discover_surface_relation_candidates(
                        sentence, source=source_evidence["citation"],
                        research_index=index)
                    aligned = [candidate for candidate in proposals
                               if candidate.polarity
                               and tuple(normalized_tokens(candidate.relation))
                                   == relation_tokens
                               and tuple(normalized_tokens(candidate.object))
                                   == object_tokens]
                    if len(aligned) != 1:
                        continue
                    candidate = aligned[0]
                    answer_key = tuple(normalized_tokens(candidate.subject))
                    realized = {
                        "text": (f"{candidate.subject} is the "
                                 f"{' '.join(role_tokens)} of "
                                 f"{candidate.object}."),
                        "source_title": hit.title or "source",
                        "citation": source_evidence["citation"],
                        "document_id": hit.document_id,
                        "method": "explicit nominal appositive realization",
                        "stored_as_fact": False,
                    }
                    source_evidence = dict(source_evidence)
                    source_evidence["realized_answer"] = realized
                    source_evidence["normalized_question"] = question
                    matched_by_answer.setdefault(answer_key, source_evidence)
            if len(matched_by_answer) == 1:
                return next(iter(matched_by_answer.values()))
            if len(matched_by_answer) > 1:
                return {
                    "ambiguous_pages": sorted({
                        str(item.get("title") or "source")
                        for item in matched_by_answer.values()}),
                    "text": "",
                }
    else:
        # Try a source-checked deverbal agent noun for a regular past-tense
        # predicate (e.g. "authored" -> "author of", "designed" ->
        # "designer of"). This does not license the word pair globally: the
        # nominal relation must appear in an assertion sentence that fills the
        # same object slot, and the reply cites that sentence.
        active = re.fullmatch(
            r"\s*who\s+(?:(?:did|do|does)\s+)?"
            r"(?P<predicate>[a-z][\w’'-]*ed)\s+"
            r"(?P<object>.+?)\s*[?!.]?\s*",
            question, flags=re.IGNORECASE)
        if active is not None:
            predicate = active.group("predicate").casefold()
            object_text = re.sub(
                r"^(?:the|a|an)\s+", "", active.group("object").strip(),
                flags=re.IGNORECASE)
            object_text = re.sub(r"[?!.]+$", "", object_text).strip()
            stem = predicate[:-2]
            agent_endings = ("er", "or", "ist", "ian", "ant", "ent", "ess")
            # Only reverse the regular past suffix when removal leaves an
            # observed agent-noun ending ("authored" -> "author"). Do not
            # speculate over role-building suffixes such as "designer";
            # those forms need their own reviewed examples and can multiply
            # full-corpus searches.
            roles = {stem} if stem.endswith(agent_endings) else set()
            nominal_answers = {}
            for role in sorted(roles):
                evidence = _natural_who_evidence(
                    index,
                    f"Who is the {role} of {object_text}?",
                    query_expansions)
                if evidence is None or evidence.get("realized_answer") is None:
                    continue
                answer = evidence["realized_answer"]["text"]
                nominal_answers.setdefault(answer, evidence)
            if len(nominal_answers) == 1:
                evidence = dict(next(iter(nominal_answers.values())))
                evidence["normalized_question"] = question
                evidence["derived_nominal_role"] = True
                return evidence
            if len(nominal_answers) > 1:
                return {
                    "ambiguous_pages": sorted({
                        str(item.get("title") or "source")
                        for item in nominal_answers.values()}),
                    "text": "",
                }
    words = tuple(normalized_tokens(question))
    if not words or words[0] not in {"who", "whom"}:
        return None
    scaffolding = {
        "who", "whom", "did", "do", "does", "is", "are", "was", "were",
        "can", "could", "will", "would", "may", "might", "must", "should",
        "the", "a", "an", "to", "on", "in", "at", "for", "of", "by",
        "with", "from",
    }
    focus = tuple(dict.fromkeys(word for word in words if word not in scaffolding))
    if not focus:
        return None
    direct_question = re.fullmatch(
        r"\s*who\s+(?:(?:did|do|does)\s+)?"
        r"(?P<predicate>[a-z][\w’'-]*)\s+(?P<object>.+?)\s*[?!.]?\s*",
        question, flags=re.IGNORECASE)
    object_title_terms = set()
    if direct_question is not None:
        direct_object = re.sub(
            r"^(?:a|an|the)\s+", "",
            direct_question.group("object").strip(), flags=re.IGNORECASE)
        object_title_terms = set(normalized_tokens(direct_object))
        # Search the exact page family for the requested object. Lead
        # sentences often continue with "it" instead of repeating the title;
        # the ordinary lexical route cannot connect that pronoun to the page.
        page_answers = {}
        page_hits = [
            hit for hit in index.search(
                direct_object, limit=50, context_chars=240)
            if tuple(normalized_tokens(
                hit.title.split("(", 1)[0].strip()))
            == tuple(normalized_tokens(direct_object))
        ]
        for hit in page_hits:
            if _is_code_source(hit.location):
                continue
            page_entity = hit.title.split("(", 1)[0].strip()
            if tuple(normalized_tokens(page_entity)) != tuple(
                    normalized_tokens(direct_object)):
                continue
            document = index.document(hit.document_id)
            for start, end in _sentence_spans(document.text):
                sentence = document.text[start:end]
                if _sentence_context_kind(
                        sentence, document.text, start) != "assertion":
                    continue
                matched = tuple(dict.fromkeys(
                    token for token in (*object_title_terms,
                                        *normalized_tokens(
                                            direct_question.group("predicate")))
                    if token in set(normalized_tokens(sentence))))
                evidence = _cited_sentence_evidence(
                    index, hit, start, end, matched)
                if evidence is None:
                    continue
                evidence["context_kind"] = "assertion"
                realized = CRMSKnowledgeBase._realize_question_from_passive_source(
                    question, [evidence], query_expansions or [])
                if (realized is not None
                        and realized.get("method")
                        == "exact-title page-subject passive realization"):
                    evidence["realized_answer"] = realized
                    page_answers.setdefault(realized["text"], evidence)
        if len(page_answers) == 1:
            return next(iter(page_answers.values()))
        if len(page_answers) > 1:
            return {
                "ambiguous_pages": sorted({
                    item.get("title", "source")
                    for item in page_answers.values()}),
                "text": "",
            }
    candidates = []
    for hit in index.search(question, limit=100, context_chars=240):
        if not set(focus) <= set(hit.matched_terms):
            continue
        if _is_code_source(hit.location):
            continue
        document = index.document(hit.document_id)
        if (0 <= hit.start < hit.end
                and document.text[hit.start:hit.end] == hit.snippet):
            passage_start = hit.start
            candidate_spans = [
                (passage_start + start, passage_start + end)
                for start, end in _sentence_spans(hit.snippet)]
        else:
            candidate_spans = _sentence_spans(document.text)
        for start, end in candidate_spans:
            sentence = document.text[start:end]
            sentence_terms = set(normalized_tokens(sentence))
            if (not set(focus) <= sentence_terms
                    or _sentence_context_kind(
                        sentence, document.text, start) != "assertion"):
                continue
            leading_name = re.match(
                r"\s*([A-Z][\w'’.-]*(?:\s+(?:[A-Z][\w'’.-]*|"
                r"van|von|de|del|da|di|der|la|le|bin|al)){0,3})\b",
                sentence)
            if leading_name is None:
                continue
            name_terms = tuple(normalized_tokens(leading_name.group(1)))
            if (len(name_terms) < 2 or set(name_terms) & set(focus)
                    or name_terms[0] in {
                        "a", "an", "the", "this", "that", "these", "those",
                        "during", "after", "before", "when", "while",
                    }):
                continue
            focus_matches = [
                (normalized_tokens(token.group())[0], token.start(), token.end())
                for token in re.finditer(r"[^\W_]+", sentence,
                                         flags=re.UNICODE)
                if normalized_tokens(token.group())
                and normalized_tokens(token.group())[0] in focus]
            if not set(focus) <= {term for term, _start, _end in focus_matches}:
                continue
            excerpt_end = start + max(end for _term, _start, end in focus_matches)
            evidence = _cited_sentence_evidence(
                index, hit, start, excerpt_end, focus)
            if evidence is None:
                continue
            positions = [token_start for _term, token_start, _end
                         in focus_matches]
            span = max(positions) - min(positions)
            title_terms = set(normalized_tokens(hit.title))
            subject_title_overlap = len(set(name_terms) & title_terms)
            object_title_overlap = len(object_title_terms & title_terms)
            candidates.append((-subject_title_overlap, -object_title_overlap,
                               span, excerpt_end - start,
                               hit.title.casefold(),
                               evidence))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:5])
    return candidates[0][-1]


def _natural_object_wh_form_candidate(
        index: CRMSSQLiteResearchIndex,
        question: str) -> FactCandidate | None:
    """Propose a reviewed verb-form alignment from an exact-title assertion.

    This deliberately does not answer the question. The consonant skeleton is
    only a bounded hypothesis generator for vowel-changing forms such as
    ``write``/``wrote``; a reviewer must approve the source-backed alignment.
    """
    match = re.fullmatch(
        r"\s*(?:what|which(?:\s+[a-z][\w’'-]*){0,2})\s+"
        r"(?:did|does|do)\s+(?P<agent>.+?)\s+"
        r"(?P<base>[a-z][\w’'-]*)\s*[?!.]?\s*",
        question, flags=re.IGNORECASE)
    if match is None:
        return None
    agent = match.group("agent").strip()
    base = match.group("base").casefold()
    title_hits = _exact_title_hits(index, agent)
    if len(title_hits) != 1:
        return None
    hit = title_hits[0]
    document = index.document(hit.document_id)
    title = hit.title.split("(", 1)[0].strip()
    title_words = tuple(normalized_tokens(title))
    if not title_words or title_words != tuple(normalized_tokens(agent)):
        return None
    surname = title_words[-1]

    def consonant_skeleton(word: str) -> str:
        return "".join(character for character in word.casefold()
                       if character.isalpha() and character not in "aeiou")

    base_skeleton = consonant_skeleton(base)
    candidates = []
    for start, end in _sentence_spans(document.text):
        sentence = document.text[start:end]
        if (_sentence_context_kind(sentence, document.text, start)
                != "assertion"):
            continue
        clause = re.fullmatch(
            r"\s*(?P<subject>[A-Z][\w’'-]*(?:\s+[A-Z][\w’'-]*)*)\s+"
            r"(?P<verb>[a-z][\w’'-]*)\s+(?P<object>[^.!?;,:]+?)"
            r"\s*[.!?]\s*", sentence)
        if clause is None:
            continue
        source_subject = clause.group("subject").strip()
        subject_words = tuple(normalized_tokens(source_subject))
        if subject_words not in {title_words, (surname,)}:
            continue
        surface = clause.group("verb").casefold()
        surface_skeleton = consonant_skeleton(surface)
        if (surface == base or not base_skeleton
                or surface_skeleton != base_skeleton
                or len(surface) > len(base) + 2
                or len(base) > len(surface) + 2):
            continue
        object_text = clause.group("object").strip()
        # Remove only a trailing year adjunct. Other prepositional phrases can
        # be part of an object's name (for example, ``Notes on the Engine``).
        adjunct = re.search(
            r"\s+(?:in|during)\s+(?:the\s+)?(?:year\s+)?\d{3,4}\s*$",
            object_text, flags=re.IGNORECASE)
        if adjunct is not None:
            object_text = object_text[:adjunct.start()].rstrip()
        object_words = tuple(normalized_tokens(object_text))
        if (not object_words or len(object_words) > 12
                or (object_words[0] not in {"a", "an", "the"}
                    and not object_text[:1].isupper())
                or set(object_words) & {"not", "never", "but", "or"}):
            continue
        source = _cited_sentence_evidence(
            index, hit, start, end, tuple(dict.fromkeys(
                (*subject_words, surface, *object_words))))
        if source is None:
            continue
        discovery = {
            "kind": "surface_relation_discovery",
            "method": "question-anchored consonant-skeleton form hypothesis",
            "canonical_relation": base,
            "predicate_phrase": surface,
            "subject_phrase": source_subject,
            "object_phrase": object_text,
            "page_title_coreference": True,
            "question": question,
            "review_required": True,
            "warning": (f"The exact-title page connects {source_subject} to "
                        f"{title}; consonant similarity only proposes that "
                        f"'{surface}' may be a form of '{base}'. Confirm the "
                        "relation and roles against the cited sentence."),
        }
        candidate = FactCandidate(
            title, base, object_text, source["citation"],
            f"<subject> {surface} <object>", sentence, True,
            language_evidence=(discovery,))
        candidates.append((start, candidate))
    return candidates[0][1] if len(candidates) == 1 else None


def _reviewable_who_candidates(
        knowledge: CRMSKnowledgeBase, index: CRMSSQLiteResearchIndex,
        question: str, evidence: dict[str, Any]) -> list[FactCandidate]:
    """Propose a reviewed active subject–predicate–object claim when aligned."""
    match = re.fullmatch(
        r"\s*who\s+(?:(?:did|do|does)\s+)?"
        r"(?P<predicate>[a-z][\w’'-]*)\s+(?P<object>.+?)\s*[?!.]?\s*",
        question, flags=re.IGNORECASE)
    if (match is None
            or match.group("predicate").casefold() in {"is", "was"}):
        nominal = re.fullmatch(
            r"\s*who\s+(?:is|was)\s+(?:the\s+)?"
            r"(?P<role>[a-z][\w’'-]*(?:\s+[a-z][\w’'-]*){0,2})\s+of\s+"
            r"(?P<object>.+?)\s*[?!.]?\s*",
            question, flags=re.IGNORECASE)
        if nominal is None:
            return []
        role = tuple(normalized_tokens(nominal.group("role")))
        object_text = re.sub(
            r"^(?:the|a|an)\s+", "", nominal.group("object").strip(),
            flags=re.IGNORECASE)
        object_text = re.sub(r"[?!.]+$", "", object_text).strip()
        proposals = knowledge._discover_surface_relation_candidates(
            evidence["text"], source=evidence["citation"],
            research_index=index)
        return [candidate for candidate in proposals
                if candidate.polarity
                and tuple(normalized_tokens(candidate.relation))
                    == (*role, "of")
                and tuple(normalized_tokens(candidate.object))
                    == tuple(normalized_tokens(object_text))]
    predicate = tuple(normalized_tokens(match.group("predicate")))
    object_text = re.sub(r"[?!.]+$", "", match.group("object")).strip()
    object_text = re.sub(r"^(?:a|an|the)\s+", "", object_text,
                         flags=re.IGNORECASE)
    object_words = tuple(normalized_tokens(object_text))
    if not predicate or not object_words:
        return []
    proposed = knowledge._discover_surface_relation_candidates(
        evidence["text"], source=evidence["citation"],
        research_index=index)
    aligned = [candidate for candidate in proposed
               if tuple(normalized_tokens(candidate.relation)) == predicate
               and tuple(normalized_tokens(candidate.object)) == object_words]
    return aligned if len(aligned) == 1 else []


def _natural_why_evidence(index: CRMSSQLiteResearchIndex,
                          question: str) -> dict[str, Any] | None:
    """Find one sentence that states a cause for the queried proposition."""
    words = tuple(normalized_tokens(question))
    if not words or words[0] != "why":
        return None
    scaffolding = {
        "why", "does", "did", "do", "is", "are", "was", "were",
        "can", "could", "will", "would", "may", "might", "must",
        "should", "the", "a", "an", "this", "that", "these", "those",
        "of", "in", "on", "at", "to", "for", "with", "from", "by",
        "look", "looks", "appear", "appears", "seem", "seems",
    }
    focus = tuple(dict.fromkeys(word for word in words
                                if word not in scaffolding))
    if len(focus) < 2:
        return None
    cause_cue = re.compile(
        r"\b(?:because|due\s+to|as\s+a\s+result|therefore|thus|"
        r"caus(?:e|es|ed|ing)|result(?:s|ed)?\s+(?:from|in)|"
        r"lead(?:s|ing)?\s+to|mak(?:e|es|ing)|so\s+that)\b",
        flags=re.IGNORECASE)
    candidates = []
    for hit in index.search(" ".join(focus), limit=50, context_chars=240):
        document = index.document(hit.document_id)
        if _is_code_source(document.location):
            continue
        for start, end in _sentence_spans(document.text):
            sentence = document.text[start:end]
            sentence_words = set(normalized_tokens(sentence))
            cue_match = cause_cue.search(sentence)
            if (not set(focus) <= sentence_words or cue_match is None
                    or not (set(focus) & set(normalized_tokens(
                        sentence[max(0, cue_match.start() - 32):
                                 min(len(sentence), cue_match.end() + 32)])))
                    or _sentence_context_kind(
                        sentence, document.text, start) != "assertion"):
                continue
            page_number = None
            match_start = match_end = None
            if document.pages:
                page_offset = 0
                for page_index, page in enumerate(document.pages, start=1):
                    page_end = page_offset + len(page)
                    if page_offset <= start < page_end:
                        if end > page_end:
                            break
                        page_number = page_index
                        matched_offsets = [
                            (start + token.start(), start + token.end())
                            for token in re.finditer(
                                r"[^\W_]+", sentence, flags=re.UNICODE)
                            if token.group().casefold() in focus]
                        if matched_offsets:
                            match_start = min(pair[0] for pair in matched_offsets)
                            match_end = max(pair[1] for pair in matched_offsets)
                        break
                    page_offset = page_end + len("\n\f\n")
                if page_number is None:
                    continue
            sentence_hit = SearchHit(
                hit.document_id, hit.title, hit.location, hit.score,
                sentence, start, end, focus, page_number,
                match_start, match_end)
            citation = index.citation(sentence_hit)
            candidates.append((
                -len(set(focus) & set(normalized_tokens(hit.title))),
                -(cue_match.end() - cue_match.start()),
                len(sentence), hit.document_id, start,
                {"document_id": hit.document_id,
                 "title": hit.title, "location": hit.location,
                 "text": sentence, "citation": citation}))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:-1])
    return candidates[0][-1]


def _natural_main_result_request(message: str) -> str | None:
    """Recognize a direct request for a named paper's main result."""
    match = re.fullmatch(
        r"\s*(?:what\s+is|what\s+was|state|give\s+me)\s+"
        r"(?:the\s+)?(?:main\s+)?(?:result|finding|conclusion)\s+"
        r"(?:of|from)\s+(.+?)\s*[?!.]?\s*",
        message, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _natural_paper_authors_request(message: str) -> str | None:
    """Recognize bounded author lookups for a named source."""
    match = re.fullmatch(
        r"\s*(?:who\s+(?:wrote|authored)|who\s+are\s+"
        r"(?:the\s+)?authors\s+(?:of|for))\s+(.+?)\s*[?!.]?\s*",
        message, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _render_paper_authors(index: CRMSSQLiteResearchIndex,
                          paper_reference: str) -> tuple[str, dict | None]:
    """Return an indexed author field with a citation to its exact span."""
    hit = _paper_scoped_summary_hit(index, "paper " + paper_reference)
    if hit is False or hit is None:
        return ("I couldn't identify one paper from that title. Give me more "
                "of its title so I can look up the authors.", None)
    document = index.document(hit.document_id)
    match = re.search(r"(?im)^Authors:\s*(.+?)\s*$", document.text)
    if match is None:
        # This helper is for structured paper metadata. Let the general
        # source-question route try sentence evidence when a title has no
        # Authors field (for example, a novel title whose page says "written
        # by ...").
        return "", None
    authors = match.group(1).strip()
    start, end = match.start(1), match.end(1)
    exact_hit = SearchHit(
        document.document_id, document.title, document.location, hit.score,
        authors, start, end, tuple(normalized_tokens(authors)))
    citation = index.citation(exact_hit)
    return (f"Authors: {authors} [Source: {document.title}]",
            {"document_id": document.document_id, "citation": citation})


def _render_main_result(index: CRMSSQLiteResearchIndex,
                        paper_reference: str) -> tuple[str, dict | None]:
    """Quote an explicit result sentence from one uniquely identified paper."""
    paper_hit = _paper_scoped_summary_hit(index, "paper " + paper_reference)
    if paper_hit is False or paper_hit is None:
        return ("I couldn't identify one paper from that title. Give me more "
                "of its title so I can look up the result.", None)
    document = index.document(paper_hit.document_id)
    abstract_match = re.search(r"(?im)^Abstract:\s*(.+)$", document.text)
    if abstract_match is None:
        return (f"I found {document.title}, but it has no abstract in the "
                "indexed text, so I can't identify its main result. "
                f"[Source: {document.title}]",
                None)
    abstract = abstract_match.group(1).strip()
    result_cue = re.compile(
        r"\b(?:we\s+(?:show|prove|demonstrate|establish|find|obtain|"
        r"achieve)|our\s+(?:results?|findings?)\s+(?:show|demonstrate|"
        r"indicate|establish)|the\s+results?\s+(?:show|indicate|"
        r"demonstrate)|results?\s+demonstrate|we\s+found)\b|"
        r"\bshowing\s+how\b|"
        r"\bwe\s+(?:evaluate|test|compare|analy[sz]e|study)\b"
        r"[^.!?]{0,160}\b(?:show|prove|demonstrate|establish|"
        r"indicate|find|obtain|achieve)\b",
        flags=re.IGNORECASE)
    sentences = [item.strip() for item in
                 re.split(r"(?<=[.!?])\s+", abstract) if item.strip()]
    result_sentence = next((sentence for sentence in sentences
                            if result_cue.search(sentence)), None)
    source = (f"[{document.title}]({document.location})"
              if document.location else document.title)
    if result_sentence is None:
        return (f"I found {source}, but its abstract has no clear result "
                "statement that I can isolate. Ask for the abstract to see "
                "the source wording.", None)
    start = document.text.find(result_sentence, abstract_match.start(1))
    if start < 0:
        return (f"I found {source}, but I couldn't verify the result "
                "sentence in the indexed source text.", None)
    exact_hit = SearchHit(
        paper_hit.document_id, document.title, document.location,
        paper_hit.score, result_sentence, start, start + len(result_sentence),
        tuple(normalized_tokens(result_sentence)))
    citation = index.citation(exact_hit)
    return (f"{result_sentence}\nSource: {source}",
            {"document_id": document.document_id, "citation": citation})


def _paper_scoped_summary_hit(index: CRMSSQLiteResearchIndex,
                              query: str):
    """Return one source hit when a summary explicitly names a paper title."""
    hits = index.search(query, limit=50, context_chars=240)
    if not hits:
        return False if re.search(
            r"\b(?:paper|article|study|publication|work)\b", query,
            flags=re.IGNORECASE) else None
    # Natural requests often quote a paper title. The tokenizer intentionally
    # preserves apostrophes inside words, so an opening quote can otherwise
    # turn ``'Cross-domain`` into a token that cannot equal ``cross-domain``
    # in the indexed title. Normalize only quote marks at token boundaries;
    # punctuation inside a title remains meaningful to ordinary tokenization.
    quote_edges = "\"'“”‘’"

    def reference_words(value: str) -> tuple[str, ...]:
        return tuple(token.strip(quote_edges) for token in normalized_tokens(value)
                     if token.strip(quote_edges))

    query_words = reference_words(query)
    query_key = tuple(query_words)
    explicit_paper = re.search(
        r"\b(?:paper|article|study|publication|work)\b", query,
        flags=re.IGNORECASE) is not None
    generic = {"the", "a", "an", "of", "on", "about", "for", "in",
               "paper", "article", "study", "publication", "work", "titled",
               "called"}
    ranked = []
    exact = []
    for hit in hits:
        title_words = reference_words(hit.title)
        if (title_words and len(title_words) <= len(query_key)
                and any(query_key[start:start + len(title_words)] == title_words
                        for start in range(len(query_key) - len(title_words) + 1))):
            exact.append(hit)
        title_terms = set(title_words) - generic
        overlap = len(title_terms & set(query_words))
        coverage = overlap / len(title_terms) if title_terms else 0.0
        ranked.append((coverage, overlap, hit.score, hit))
    if exact:
        # A shorter paper title can occur inside the explicitly supplied
        # title (for example, "Reinforcement Learning" inside a longer
        # program-synthesis paper title). Prefer the most specific exact
        # title, while preserving abstention when multiple papers share that
        # same longest title.
        longest_title_length = max(
            len(reference_words(hit.title)) for hit in exact)
        longest_exact = [
            hit for hit in exact
            if len(reference_words(hit.title)) == longest_title_length]
        return longest_exact[0] if len(longest_exact) == 1 else False
    if not explicit_paper:
        return None
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2],
                                  item[3].document_id))
    best = ranked[0]
    if best[0] < 0.75 or best[1] < 2:
        return False
    if (len(ranked) > 1 and ranked[1][:2] == best[:2]):
        return False
    return best[3]


def _acronym_scoped_summary_hit(index: CRMSSQLiteResearchIndex,
                                query: str):
    """Keep an acronym-anchored topic summary within its best matching source."""
    acronyms = {
        token.casefold() for token in re.findall(
            r"\b[A-Z][A-Z0-9]{1,}\b", query)
        if token.casefold() not in {"who", "what", "where", "when", "why", "how"}
    }
    if not acronyms:
        return None
    query_terms = set(normalized_tokens(query))
    topic_terms = query_terms - acronyms - {
        "summarize", "summarise", "summary", "give", "me", "a", "the",
        "of", "about", "for", "in", "on", "please", "can", "could",
        "would", "you", "and", "or", "to", "with",
    }
    if not topic_terms or query_terms & {"compare", "versus", "vs", "both", "across"}:
        return None

    ranked = []
    for hit in index.search(query, limit=50, context_chars=240):
        if _is_code_source(hit.location):
            continue
        title_words = set(normalized_tokens(hit.title))
        local_words = set(normalized_tokens(hit.snippet))
        anchored = acronyms <= title_words | local_words
        if not anchored and hit.start is not None and hit.end is not None:
            document = index.document(hit.document_id)
            left = document.text.rfind("\n\n", 0, hit.start) + 2
            right = document.text.find("\n\n", hit.end)
            if right < 0:
                right = len(document.text)
            paragraph_words = set(normalized_tokens(document.text[left:right]))
            heading_blocks = document.text[:left].rsplit("\n\n", 2)
            heading = next((block for block in reversed(heading_blocks)
                            if re.match(r"\s*#{1,6}\s+", block)), "")
            anchored = (acronyms <= paragraph_words
                        or acronyms <= set(normalized_tokens(heading)))
        if not anchored:
            continue
        document = index.document(hit.document_id)
        document_words = set(normalized_tokens(document.text))
        covered = topic_terms & document_words
        coverage = len(covered) / len(topic_terms)
        if not covered:
            continue
        title_overlap = len(topic_terms & title_words)
        ranked.append((coverage, title_overlap, hit.score, hit))

    if not ranked:
        return False
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2],
                                  item[3].document_id))
    best = ranked[0]
    if best[0] < 0.75:
        return False
    if (len(ranked) > 1 and ranked[1][:2] == best[:2]):
        return False
    return best[3]


def _natural_latest_research_request(message: str) -> str | None:
    """Extract a topic from a direct request for the newest indexed research."""
    value = message.strip().rstrip(".!?").strip()
    value = re.sub(
        r"^(?:what(?:\s+is|\s+are|'s)?|which|show\s+me|find|list|"
        r"give\s+me)\s+", "", value, flags=re.IGNORECASE)
    match = re.fullmatch(
        r"(?:the\s+)?(?:latest|newest|most\s+recent)\s+"
        r"(?:research|papers?|studies|articles?|publications?)"
        r"(?:\s+(?:on|about|in|for|regarding)\s+(.+))?",
        value, flags=re.IGNORECASE)
    if match is None:
        return None
    topic = (match.group(1) or "").strip()
    topic = re.sub(
        r"\s+(?:in|from)\s+(?:this\s+)?(?:corpus|model|collection|"
        r"index|sources?)$", "", topic, flags=re.IGNORECASE).strip()
    return topic


def _natural_research_list_request(message: str) -> str | None:
    """Extract the topic from a direct request to list papers or studies."""
    value = message.strip().rstrip(".!? ")
    match = re.fullmatch(
        r"(?:which|what)\s+(?:research\s+)?(?:papers?|studies|articles?|"
        r"publications?)\s+(?:discuss|cover|examine|study|address|"
        r"investigate|are\s+about|focus\s+on)\s+(.+)",
        value, flags=re.IGNORECASE)
    if match is None:
        match = re.fullmatch(
            r"(?:list|find|show\s+me)\s+(?:the\s+)?(?:papers?|studies|"
            r"articles?|publications?)\s+(?:on|about|for|regarding)\s+(.+)",
            value, flags=re.IGNORECASE)
    topic = match.group(1).strip() if match else ""
    topic = re.sub(r"\s+in\s+(?:this\s+)?(?:corpus|model|collection|index)$",
                   "", topic, flags=re.IGNORECASE).strip()
    return topic or None


def _natural_paper_description_request(message: str) -> str | None:
    """Extract a topic from a natural description of a paper."""
    match = re.fullmatch(
        r"(?:tell\s+me\s+about|describe|find)\s+(?:the\s+)?"
        r"(?:paper|article|study)\s+(?:that|which)\s+"
        r"(?:studies|examines|describes|investigates|covers|discusses)\s+"
        r"(.+?)\s*[.!?]?", message.strip(), flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _natural_corpus_topics_request(message: str) -> bool:
    """Recognize corpus overview questions instead of lexical source search."""
    value = message.strip().rstrip(".!? ")
    return re.fullmatch(
        r"(?:what|which)\s+(?:research\s+)?topics\s+are\s+"
        r"(?:represented|covered|included)\s+in\s+"
        r"(?:this\s+)?(?:model|corpus|collection|index|sources?)",
        value, flags=re.IGNORECASE) is not None


def _render_corpus_topics(index: CRMSSQLiteResearchIndex) -> str:
    """Summarize recurring title vocabulary without claiming a taxonomy."""
    ignored = {
        "about", "after", "among", "analysis", "based", "between",
        "data", "deep", "during", "from", "using", "with", "their",
        "these", "those", "towards", "toward", "under", "through",
        "approach", "approaches", "method", "methods", "study", "studies",
        "model", "models", "learning", "research", "paper", "papers",
    }
    counts: dict[str, list[Any]] = {}
    for document in index.documents():
        if _is_code_source(document.location):
            continue
        for term in set(normalized_tokens(document.title)):
            topic_term = (term[:-1] if len(term) >= 5 and term.endswith("s")
                          and not term.endswith(("ss", "is")) else term)
            if len(topic_term) >= 4 and topic_term not in ignored:
                counts.setdefault(topic_term, []).append(document)
    ranked = sorted(counts.items(), key=lambda item: (-len(item[1]), item[0]))
    ranked = [item for item in ranked if len(item[1]) >= 3][:10]
    if not ranked:
        return "I don't have enough indexed titles to identify recurring topics."
    lines = ["Recurring terms in indexed research titles (a rough corpus overview, not a topic taxonomy):"]
    for term, documents in ranked:
        sample = sorted(documents, key=lambda doc: doc.title)[0]
        citation = (f"[{sample.title}]({sample.location})"
                    if sample.location else sample.title)
        lines.append(f"- {term} ({len(documents)} titles); for example: {citation}")
    lines.append("Ask about a term or request papers on a topic for focused results.")
    return "\n".join(lines)


_ARXIV_NATURAL_CATEGORIES = {
    "computational complexity": ("cs.CC", "Computational Complexity"),
    "computational linguistics": ("cs.CL", "Computation and Language"),
    "formal language": ("cs.FL", "Formal Languages and Automata Theory"),
    "formal languages": ("cs.FL", "Formal Languages and Automata Theory"),
    "logic in computer science": ("cs.LO", "Logic in Computer Science"),
    "mathematical logic": ("math.LO", "Logic"),
    "natural language processing": ("cs.CL", "Computation and Language"),
    "number theory": ("math.NT", "Number Theory"),
    "programming language": ("cs.PL", "Programming Languages"),
    "programming languages": ("cs.PL", "Programming Languages"),
}


def _render_arxiv_category_papers(
        index: CRMSSQLiteResearchIndex, category: str, label: str,
        *, limit: int = 5) -> tuple[str, list[dict]]:
    """List papers by their explicit primary arXiv category metadata."""
    hits = index.search(category, limit=min(index.document_count(), 40),
                        context_chars=240)
    matched = []
    for hit in hits:
        document = index.document(hit.document_id)
        primary = re.search(r"(?m)^Primary category:\s*([^\r\n]+)",
                            document.text)
        if primary is None or primary.group(1).strip() != category:
            continue
        abstract = re.search(r"(?im)^Abstract:\s*(.+)$", document.text)
        excerpt = (abstract.group(1).strip() if abstract else "")
        if excerpt:
            first_sentence = re.search(r"[.!?](?:\s|$)", excerpt)
            if first_sentence is not None:
                excerpt = excerpt[:first_sentence.start() + 1]
        source = (f"[{document.title}]({document.location})"
                  if document.location else document.document_id)
        matched.append((hit.score, hit, excerpt, source))
    matched.sort(key=lambda row: (-row[0], row[1].document_id))
    if not matched:
        return (f"I don't have papers indexed in the arXiv {label} category "
                f"({category}) yet.", [])
    lines = [f"Papers in the arXiv {label} category ({category}):"]
    documents = []
    for _score, hit, excerpt, source in matched[:limit]:
        line = f"- {hit.title}."
        if excerpt:
            line += f" {excerpt}"
        line += f" [Source: {source}]"
        lines.append(line)
        documents.append({"document_id": hit.document_id,
                          "title": hit.title})
    return "\n".join(lines), documents


def _render_research_list(index: CRMSSQLiteResearchIndex,
                          topic: str) -> tuple[str, list[dict]]:
    """List direct title matches and label weaker term matches separately."""
    def topic_tokens(value: str) -> set[str]:
        tokens = set(normalized_tokens(value))
        return {token[:-1] if len(token) >= 4 and token.endswith("s")
                and not token.endswith("ss") else token for token in tokens}

    topic_terms = topic_tokens(topic) - {
        "a", "an", "and", "the", "of", "on", "about", "for", "to",
        "with", "from", "in", "by", "paper", "papers", "study", "studies",
        "article", "articles", "research", "work", "discuss", "cover",
        "examine", "address", "investigate", "focus",
    }
    if not topic_terms:
        return ("Name a specific research topic so I can search the source index.",
                [])
    category_request = _ARXIV_NATURAL_CATEGORIES.get(
        " ".join(normalized_tokens(topic)).strip())
    if category_request is not None:
        return _render_arxiv_category_papers(index, *category_request)
    hit_by_id = {}
    for query in {topic, " ".join(sorted(topic_terms))}:
        for hit in index.search(query, limit=30, context_chars=240):
            hit_by_id.setdefault(hit.document_id, hit)
    hits = list(hit_by_id.values())
    term_document_counts = {term: 0 for term in topic_terms}
    cached_documents = {}
    for hit in hits:
        document = index.document(hit.document_id)
        cached_documents[hit.document_id] = document.text
        document_terms = topic_tokens(hit.title + " " + document.text[:5000])
        for term in topic_terms & document_terms:
            term_document_counts[term] += 1
    ordered_topic_terms = []
    for term in normalized_tokens(topic):
        normalized_term = (term[:-1] if len(term) >= 4 and term.endswith("s")
                           and not term.endswith("ss") else term)
        if normalized_term in topic_terms and normalized_term not in ordered_topic_terms:
            ordered_topic_terms.append(normalized_term)
    term_positions = {term: position for position, term
                      in enumerate(ordered_topic_terms)}
    anchors = set(sorted(
        topic_terms,
        key=lambda term: (term_document_counts[term], term_positions[term]))[:
            max(1, len(topic_terms) // 3)])
    direct: list[tuple[float, float, Any, str]] = []
    related: list[tuple[float, float, Any, str]] = []
    for hit in hits:
        if _is_code_source(hit.location):
            continue
        document_text = cached_documents[hit.document_id]
        title_terms = topic_tokens(hit.title)
        body_terms = topic_tokens(document_text[:5000])
        title_coverage = len(topic_terms & title_terms) / len(topic_terms)
        body_coverage = len(topic_terms & body_terms) / len(topic_terms)
        matched_terms = topic_terms & title_terms
        if title_coverage >= 0.75:
            direct.append((title_coverage, body_coverage, hit, document_text))
        elif (len(matched_terms) >= min(2, len(topic_terms))
              and bool(anchors & (title_terms | body_terms))
              and (title_coverage >= 0.5 or body_coverage >= 0.75)):
            related.append((title_coverage, body_coverage, hit, document_text))

    key = lambda item: (-item[0], -item[1], -item[2].score,
                        item[2].document_id)
    direct.sort(key=key)
    related.sort(key=key)
    direct = direct[:5]
    related = related[:3]
    if not direct and not related:
        return (f"I couldn't find papers with enough of the topic terms "
                f"'{topic}' in their titles or text. Try a shorter or more "
                "specific topic.", [])

    lines = [f"Research papers matching “{topic}”:"]

    def render_group(label: str,
                     records: list[tuple[float, float, Any, str]]) -> None:
        if not records:
            return
        lines.append(f"{label} ({len(records)}):")
        for _title_coverage, _body_coverage, hit, text in records:
            abstract = re.search(r"(?im)^Abstract:\s*(.+)$", text)
            excerpt = abstract.group(1).strip() if abstract else hit.snippet
            sentences = re.split(r"(?<=[.!?])\s+", excerpt)
            if sentences:
                excerpt = max(
                    sentences,
                    key=lambda sentence: (
                    len(topic_terms & topic_tokens(sentence)),
                        -len(sentence)))
            overlap = len(topic_terms & topic_tokens(hit.title))
            coverage = f"{overlap}/{len(topic_terms)} topic terms"
            if len(excerpt) > 260:
                excerpt = excerpt[:257].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
            source = (f"[{hit.document_id}]({hit.location})"
                      if hit.location else hit.document_id)
            lines.append(f"- {hit.title} ({coverage}). {excerpt} "
                         f"[Source: {source}]")

    render_group("Title matches", direct)
    render_group("Related term matches", related)
    ordered_records = [*direct, *related]
    documents = [{"document_id": hit.document_id, "title": hit.title}
                 for _title_coverage, _body_coverage, hit, _text
                 in ordered_records]
    return "\n".join(lines), documents


def _natural_research_explanation_request(message: str) -> bool:
    """Recognize short follow-ups that ask about the prior research result."""
    value = message.strip().rstrip(".!?").strip()
    return re.fullmatch(
        r"(?:why(?:\s+is\s+that)?|show\s+(?:the\s+)?"
        r"(?:source|citation))",
        value, flags=re.IGNORECASE) is not None or re.fullmatch(
        r"(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:explain|clarify|elaborate\s+on)\s+"
        r"(?:the\s+)?(?:result|finding|conclusion|it|that|this)"
        r"(?:\s+(?:in\s+(?:simpler|plain|simple)\s+terms|"
        r"more\s+(?:simply|clearly)))?",
        value, flags=re.IGNORECASE) is not None or re.fullmatch(
            r"what\s+does\s+(?:the\s+)?"
            r"(?:result|finding|conclusion|it|that|this)\s+mean",
            value, flags=re.IGNORECASE) is not None or _method_mechanism_followup(value)


def _method_mechanism_followup(message: str) -> bool:
    return re.fullmatch(
        r"(?:why|how)\s+(?:does|did|do|is|was|are|were)\s+"
        r"(?:this|that|the)\s+(?:method|approach|model|system|technique)\s+"
        r"(?:work|succeed|help|improve|perform)(?:\s+so\s+well)?",
        message.strip().rstrip(".!?").strip(), flags=re.IGNORECASE) is not None


def _render_research_explanation(index: CRMSSQLiteResearchIndex,
                                 evidence: dict,
                                 translation_model: CRMSTranslation,
                                 question: str = "") -> str:
    document_id = evidence["document_id"]
    try:
        source_text = index.resolve_citation(evidence["citation"])
        document = index.document(document_id)
    except (KeyError, TypeError, ValueError):
        return ("I can't verify the previous source excerpt now. Ask the "
                "question again to retrieve current evidence.")
    if evidence.get("use_full_document"):
        source_text = document.text
    source = (f"[{document.title}]({document.location})"
              if document.location else document.document_id)
    if _method_mechanism_followup(question):
        abstract = re.search(r"(?m)^Abstract:\s*(.+)$", document.text)
        abstract_text = abstract.group(1).strip() if abstract else document.text
        sentences = [sentence.strip() for sentence in
                     re.split(r"(?<=[.!?])\s+", abstract_text)
                     if sentence.strip()]
        causal = re.compile(
            r"\b(?:because|due\s+to|as\s+a\s+result|therefore|thereby|"
            r"thus|so\s+that|allows?|enables?|improves?|reduces?|"
            r"prevents?|results?\s+in|leads?\s+to|which\s+helps?)\b",
            flags=re.IGNORECASE)
        procedural = re.compile(
            r"\b(?:by\s+\w+ing|through|using|via|based\s+on|"
            r"(?:is|are|was|were)\s+used\s+for|designed\s+to|"
            r"we\s+(?:use|apply|combine|train|construct)|"
            r"our\s+(?:method|approach|model))\b",
            flags=re.IGNORECASE)
        explanation = next((sentence for sentence in sentences
                           if causal.search(sentence)), None)
        if explanation is not None:
            label = "The previous source explains the method this way"
        else:
            explanation = next((sentence for sentence in sentences
                               if procedural.search(sentence)), None)
            label = ("The previous source describes how the method is applied, "
                     "but does not state why it works")
        if explanation is None:
            explanation = sentences[0] if sentences else source_text.strip()
            label = ("I can't find an explanation of why the method works in "
                     "the previous source. It states")
        start = document.text.find(explanation)
        if start >= 0:
            exact_hit = SearchHit(
                document.document_id, document.title, document.location, 0.0,
                explanation, start, start + len(explanation),
                tuple(normalized_tokens(explanation)))
            citation = index.citation(exact_hit)
            return f"{label}: “{explanation}” [Source: {source}; {citation}]"
        return f"{label}: “{explanation}” [Source: {source}]"
    abstract = re.search(r"(?m)^Abstract:\s*(.+)$", source_text)
    statement = abstract.group(1).strip() if abstract else source_text.strip()
    sentence_end = re.search(r"[.!?](?:\s|$)", statement)
    if sentence_end is not None:
        statement = statement[:sentence_end.start() + 1]
    rewrite = None
    for register in ("plain", "plain language", "simple", "simplified"):
        rewrite = translation_model.rewrite(statement, register=register)
        if rewrite is not None and rewrite.status != "unknown":
            break
    if rewrite is not None and rewrite.status == "translated":
        return ("Using a learned plain-register frame: “" + str(rewrite.output)
                + f"”\nSource: {source}\nAligned examples: "
                f"{len(rewrite.evidence)}")
    if rewrite is not None and rewrite.status == "ambiguous":
        return ("More than one learned plain-language frame matches this "
                "result, so I can't choose a rewrite.\nSource: " + source)
    if (rewrite is not None and rewrite.status == "unknown"
            and rewrite.request and "aligned target values" in rewrite.request):
        return (rewrite.request + " The cited source states: “" + statement
                + "”\nSource: " + source)
    return ("I don't have a verified language rule to paraphrase this result "
            "yet. The cited source states: “" + statement + "”\nSource: "
            + source)


def _render_latest_research(index: CRMSSQLiteResearchIndex,
                            topic: str) -> tuple[str, dict | None, list[dict]]:
    hits = index.search_latest(topic, limit=min(index.document_count(), 100))
    if not hits:
        return ("I couldn't find dated source records matching that topic. "
                "Add sources with publication dates or ask about indexed text.",
                None, [])
    topic_terms = set(normalized_tokens(topic)) - {
        "a", "an", "and", "the", "of", "on", "about", "for", "to",
        "with", "from", "in", "by", "research", "paper", "papers",
        "study", "studies", "article", "articles", "publication",
        "publications", "latest", "newest", "recent", "most",
    }
    focused = []
    related = []
    for item in hits:
        if _is_code_source(item.hit.location):
            continue
        document = index.document(item.hit.document_id)
        abstract = re.search(r"(?m)^Abstract:\s*(.+)$", document.text)
        abstract_text = abstract.group(1).strip() if abstract else item.hit.snippet
        sentences = [sentence.strip() for sentence in
                     re.split(r"(?<=[.!?])\s+", abstract_text) if sentence.strip()]
        title_terms = set(normalized_tokens(item.hit.title))
        title_coverage = (len(topic_terms & title_terms) / len(topic_terms)
                          if topic_terms else 0.0)
        record = (item, document, abstract_text, sentences,
                  title_coverage)
        title_has_topic = bool(topic_terms) and topic_terms <= title_terms
        opening_has_topic = any(
            topic_terms <= set(normalized_tokens(sentence))
            for sentence in sentences[:1]) if topic_terms else False
        if title_has_topic or opening_has_topic:
            focused.append(record)
        else:
            related.append(record)

    # Within each relevance tier, preserve publication recency. Do not let a
    # recent mention outrank a more focused paper solely because it is newer.
    focused.sort(key=lambda record: record[0].publication_date, reverse=True)
    related.sort(key=lambda record: record[0].publication_date, reverse=True)
    focused_results = focused[:3]
    related_results = related[:max(0, 3 - len(focused_results))]
    if (len(focused_results) >= 3 and related
            and related[0][0].publication_date
            > focused_results[-1][0].publication_date):
        # Keep one very recent broad mention visible, while allowing the
        # relevance label to prevent it from displacing the two strongest
        # topic matches.
        focused_results = focused_results[:2]
        related_results = related[:1]
    if not focused_results and not related_results:
        return (f"I couldn't find dated papers with enough evidence about "
                f"'{topic}'. Try a more specific topic.", None, [])

    lines = ["Most recently published matching sources in the index:"]
    if focused:
        lines.append("Topic-focused matches:")
    rendered_records = []
    for category, group in (("focused", focused_results),
                            ("related", related_results)):
        if not group:
            continue
        if category == "related":
            lines.append("Recent related mentions (topic terms occur outside the title or opening abstract):")
        for item, document, abstract_text, sentences, title_coverage in group:
            excerpt = max(sentences, key=lambda sentence: (
                len(topic_terms & set(normalized_tokens(sentence))),
                -len(sentence))) if sentences else abstract_text
            if len(excerpt) > 320:
                excerpt = excerpt[:317].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
            source = (f"[{item.hit.document_id}]({item.hit.location})"
                      if item.hit.location else item.hit.document_id)
            if category == "focused":
                focus_basis = (f"title topic overlap {title_coverage:.0%}"
                               if title_coverage >= 0.5 else
                               "all topic terms in opening abstract")
                lines.append(
                    f"- {item.hit.title} (published {item.publication_date}; "
                    f"{focus_basis}). {excerpt} [Source: {source}]")
            else:
                lines.append(
                    f"- {item.hit.title} (published {item.publication_date}; "
                    f"related mention). {excerpt} [Source: {source}]")
            rendered_records.append(item)
    ordered_hits = rendered_records
    first_document = index.document(ordered_hits[0].hit.document_id)
    evidence = {"document_id": first_document.document_id,
                "citation": index.citation(ordered_hits[0].hit),
                "use_full_document": True,
                "latest_documents": [
                    {"document_id": record.hit.document_id,
                     "title": record.hit.title,
                     "citation": index.citation(record.hit)}
                    for record in ordered_hits]}
    return "\n".join(lines), evidence, [
        {"document_id": record.hit.document_id,
         "title": record.hit.title,
         "hit": record.hit}
        for record in ordered_hits]


def _paper_ordinal_followup(message: str) -> int | None:
    """Recognize a bounded ordinal reference to a recent paper list."""
    match = re.fullmatch(
        r"\s*(?:what\s+does|tell\s+me\s+about|summarize|summarise)\s+"
        r"(?:the\s+)?(first|second|third|1st|2nd|3rd)\s+paper(?:\s+say)?"
        r"[.!?]?\s*", message, flags=re.IGNORECASE)
    if match is None:
        return None
    return {"first": 0, "1st": 0, "second": 1, "2nd": 1,
            "third": 2, "3rd": 2}[match.group(1).casefold()]


def _is_paper_comparison_followup(message: str) -> bool:
    return bool(re.search(
        r"\b(?:these|those|the)\s+papers\b.*"
        r"\b(?:agree|differ|common|similar|compare|contrast)\b",
        message, flags=re.IGNORECASE))


def _natural_contrast_pair(message: str) -> tuple[str, str] | None:
    """Parse explicit two-concept comparison questions conservatively."""
    value = message.strip().rstrip(".!? ")
    patterns = (
        r"(?:what(?:\s+is|'s)?\s+)?(?:the\s+)?difference\s+between\s+"
        r"(.+?)\s+and\s+(.+)",
        r"how\s+does\s+(.+?)\s+differ\s+from\s+(.+)",
        r"compare\s+(.+?)\s+(?:and|with|to|against|versus|vs\.?)\s+(.+)",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, value, flags=re.IGNORECASE)
        if match:
            left, right = (part.strip(" \"'“”") for part in match.groups())
            if left and right:
                return left, right
    return None


def _answer_contrast_from_sources(
        index: CRMSSQLiteResearchIndex, left: str, right: str) -> str:
    """Quote a source contrast, or report co-mention without inferring one."""
    left_terms = set(normalized_tokens(left))
    right_terms = set(normalized_tokens(right))
    if not left_terms or not right_terms or left_terms == right_terms:
        return "Please name two distinct concepts for the comparison."
    query = f"{left} {right}"
    hits = index.search(query, limit=30, context_chars=240)
    co_mention = None
    contrast_cue = re.compile(
        r"\b(?:whereas|while|unlike|in\s+contrast|by\s+contrast|"
        r"compared\s+with|different\s+from|differs?\s+from|"
        r"as\s+opposed\s+to|rather\s+than|on\s+the\s+other\s+hand)\b",
        flags=re.IGNORECASE)
    for hit in hits:
        if _is_code_source(hit.location):
            continue
        document = index.document(hit.document_id)
        abstract_match = re.search(r"(?im)^Abstract:\s*(.+)$", document.text)
        source_text = abstract_match.group(1) if abstract_match else document.text
        cursor = 0
        for sentence in re.split(r"(?<=[.!?])\s+", source_text):
            sentence = sentence.strip()
            if not sentence:
                continue
            if _is_imported_structured_metadata(sentence):
                continue
            start = document.text.find(sentence, cursor)
            if start < 0:
                start = document.text.find(sentence)
            cursor = max(cursor, start + len(sentence))
            words = set(normalized_tokens(sentence))
            if not left_terms <= words or not right_terms <= words:
                continue
            if co_mention is None:
                co_mention = (hit, sentence)
            if not contrast_cue.search(sentence):
                continue
            sentence_hit = SearchHit(
                hit.document_id, hit.title, hit.location, hit.score,
                sentence, start, start + len(sentence),
                tuple(sorted((left_terms | right_terms) & words)))
            citation = index.citation(sentence_hit)
            return (f"The source states: “{sentence}” "
                    f"[Source: {hit.title}; {citation}]")
    if co_mention is not None:
        hit, sentence = co_mention
        return (f"I found both terms in {hit.title}, but its source text does "
                f"not directly contrast them: “{sentence}” [Source: "
                f"{index.citation(hit)}]. I can't establish their difference "
                "from this co-mention alone.")
    return (f"I couldn't find a source sentence that states both “{left}” and "
            f"“{right}”. I don't have direct evidence for their difference.")


_SUMMARY_COUNT_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _natural_summary_followup(message: str) -> tuple[str, int | None] | None:
    """Recognize bounded sentence-count refinements for the last summary."""
    for action, pattern in (
            ("more", r"(?:show|give)\s+(?:me\s+)?more\s+sentences?"),
            ("fewer", r"(?:show|give)\s+(?:me\s+)?(?:fewer|less)\s+sentences?")):
        if re.fullmatch(r"\s*(?:please\s+)?(?:can\s+you\s+)?"
                        + pattern + r"[.!?]*\s*", message,
                        flags=re.IGNORECASE):
            return action, None
    match = re.fullmatch(
        r"\s*(?:please\s+)?(?:can\s+you\s+)?(?:show|give)\s+(?:me\s+)?"
        r"(?:(?:(?:only\s+)?the\s+first|only)\s+)?"
        r"(?P<count>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"sentences?[.!?]*\s*", message, flags=re.IGNORECASE)
    if match is None:
        return None
    raw_count = match.group("count").casefold()
    count = (int(raw_count) if raw_count.isdigit()
             else _SUMMARY_COUNT_WORDS[raw_count])
    return "set", max(1, min(20, count))


def _natural_code_explanation_request(message: str) -> bool:
    return re.fullmatch(
        r"\s*(?:please\s+)?(?:(?:explain|describe)\s+"
        r"(?:(?:that|this)\s+|the\s+(?:generated\s+)?)"
        r"(?:python\s+)?code|what\s+does\s+"
        r"(?:(?:that|this|the\s+generated)\s+code|it(?:\s+code)?)\s+do)"
        r"[.!?]*\s*",
        message, flags=re.IGNORECASE) is not None


def _natural_code_evidence_request(message: str) -> bool:
    return re.fullmatch(
        r"\s*(?:please\s+)?(?:(?:show|list)(?:\s+me)?\s+"
        r"(?:the\s+)?(?:training\s+)?(?:examples|evidence)\s+"
        r"(?:for|behind|supporting)\s+(?:that|this|the\s+generated)\s+code|"
        r"what\s+(?:examples|evidence)\s+(?:support|was\s+used\s+for)\s+"
        r"(?:that|this|the\s+generated)\s+code)[.!?]*\s*",
        message, flags=re.IGNORECASE) is not None


def _natural_translation_teaching(message: str):
    """Parse explicit templates and bounded aligned pairs from ordinary prose."""
    match = _NATURAL_TRANSLATION_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(4).strip())
    if not 3 <= len(chunks) <= 9:
        return None
    template_pair = _NATURAL_TRANSLATION_PAIR_RE.fullmatch(chunks[0])
    if template_pair is None:
        return None
    examples = []
    for chunk in chunks[1:]:
        pair = _NATURAL_TRANSLATION_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        examples.append((pair.group(1), pair.group(2)))
    return (match.group(1).strip(), match.group(2).strip(),
            match.group(3).strip(), template_pair.group(1),
            template_pair.group(2), examples)


def _natural_translation_examples(message: str):
    """Parse parallel examples for conservative single-slot inference."""
    match = _NATURAL_TRANSLATION_EXAMPLES_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(4).strip())
    if not 2 <= len(chunks) <= 8:
        return None
    pairs = []
    for chunk in chunks:
        pair = _NATURAL_TRANSLATION_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        pairs.append((pair.group(1), pair.group(2)))
    return (match.group(1).strip(), match.group(2).strip(),
            match.group(3).strip(), pairs)


def _natural_translation_additional(message: str):
    """Parse one additional pair for an already licensed translation frame."""
    match = _NATURAL_TRANSLATION_ADDITIONAL_RE.fullmatch(message)
    if match is None:
        return None
    return tuple(value.strip() for value in match.groups())


def _natural_math_teaching(message: str):
    """Parse a bounded batch of quoted math questions and exact answers."""
    match = _NATURAL_MATH_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(1).strip())
    if not 2 <= len(chunks) <= 8:
        return None
    pairs = []
    for chunk in chunks:
        pair = _NATURAL_MATH_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        pairs.append((pair.group(1).strip(), pair.group(2).strip()))
    return pairs


def _natural_unit_teaching(message: str):
    """Parse a bounded natural-language batch of aligned unit quantities."""
    match = _NATURAL_UNIT_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(1).strip())
    if not 2 <= len(chunks) <= 8:
        return None
    pairs = []
    for chunk in chunks:
        pair = _NATURAL_UNIT_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        pairs.append((pair.group(1).strip(), pair.group(2).strip()))
    return pairs


def _natural_math_feedback(message: str) -> str | None:
    """Parse an exact numeric answer when a contrastive math example is pending."""
    match = _NATURAL_MATH_FEEDBACK_RE.fullmatch(message)
    return match.group(1) if match else None


def _unsupported_mathematical_proof_request(message: str) -> bool:
    """Recognize explicit mathematical proof requests outside exact arithmetic.

    This is a routing guard, not a proof solver. It prevents a theorem question
    from falling through to lexical research retrieval when CRMS has no
    proof-producing procedure for the requested claim.
    """
    text = " ".join(message.casefold().split())
    proof_request = re.search(
        r"\b(?:prove|proof|show\s+that|derive\s+why|demonstrate)\b", text)
    if proof_request is None:
        return False
    mathematical_topic = re.search(
        r"\b(?:sqrt|square\s+root|irrational|rational|prime|divisib\w*|"
        r"integer|number\s+theory|theorem|equation|congruen\w*|"
        r"polynomial|geometric\s+series)\b|\d\s*[=<>]\s*[-+]?\d",
        text)
    return mathematical_topic is not None


def _natural_about_teaching(message: str):
    """Parse a bounded batch of request/entity examples for sourced writing."""
    match = _NATURAL_ABOUT_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(1).strip())
    if not 2 <= len(chunks) <= 8:
        return None
    pairs = []
    for chunk in chunks:
        pair = _NATURAL_ABOUT_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        pairs.append((pair.group(1).strip(), pair.group(2).strip()))
    return pairs


def _natural_question_teaching(message: str):
    """Parse a bounded batch of explicit question/answer examples."""
    match = _NATURAL_QUESTION_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(1).strip())
    if not 2 <= len(chunks) <= 8:
        return None
    pairs = []
    for chunk in chunks:
        pair = _NATURAL_QUESTION_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        pairs.append((pair.group(1).strip(), pair.group(2).strip()))
    return pairs


def _natural_paired_question_teaching(message: str):
    """Parse explicit pairs of related fact-backed question frames."""
    match = _NATURAL_PAIRED_QUESTION_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(1).strip())
    if not 4 <= len(chunks) <= 8:
        return None
    pairs = []
    for chunk in chunks:
        pair = _NATURAL_QUESTION_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        pairs.append((pair.group(1).strip(), pair.group(2).strip()))
    return pairs


def _natural_question_additional(message: str):
    """Parse one example intended to extend an already licensed exact frame."""
    match = _NATURAL_QUESTION_ADDITIONAL_RE.fullmatch(message)
    if match is None:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _natural_qualified_question_additional(message: str):
    """Parse one qualified example to extend an already licensed frame."""
    match = _NATURAL_QUALIFIED_QUESTION_ADDITIONAL_RE.fullmatch(message)
    if match is None:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _natural_polar_teaching(message: str):
    """Parse a bounded batch of explicit yes/no question labels."""
    match = _NATURAL_POLAR_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(1).strip())
    if not 2 <= len(chunks) <= 8:
        return None
    pairs = []
    for chunk in chunks:
        pair = _NATURAL_POLAR_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        pairs.append((pair.group(1).strip(), pair.group(2).casefold() == "yes"))
    return pairs


def _natural_path_question_teaching(message: str):
    """Parse a bounded batch of explicit path-question examples."""
    match = _NATURAL_PATH_QUESTION_PREFIX_RE.fullmatch(message)
    if match is None:
        return None
    chunks = re.split(r"\s*;\s*", match.group(1).strip())
    if not 2 <= len(chunks) <= 8:
        return None
    pairs = []
    for chunk in chunks:
        pair = _NATURAL_QUESTION_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        pairs.append((pair.group(1).strip(), pair.group(2).strip()))
    return pairs


def _parse_natural_fact_examples(body: str):
    chunks = re.split(r"\s*;\s*", body.strip())
    if not 2 <= len(chunks) <= 8:
        return None
    examples = []
    for chunk in chunks:
        pair = _NATURAL_FACT_PAIR_RE.fullmatch(chunk)
        if pair is None:
            return None
        (sentence, subject, relation, obj, polarity, subject_phrase,
         predicate_phrase, object_phrase) = pair.groups()
        examples.append((sentence.strip(), subject.strip(), relation.strip(),
                         obj.strip(), (polarity or "positive").casefold(),
                         (subject_phrase or subject).strip(),
                         (predicate_phrase or relation).strip(),
                         (object_phrase or obj).strip()))
    return examples


def _natural_fact_teaching(message: str):
    """Parse a bounded batch of source sentences with explicit fact labels."""
    match = _NATURAL_FACT_PREFIX_RE.fullmatch(message)
    return None if match is None else _parse_natural_fact_examples(match.group(1))


def _natural_teacher_fact_teaching(message: str):
    """Parse explicitly teacher-labeled fact examples without source claims."""
    match = _NATURAL_TEACHER_FACT_PREFIX_RE.fullmatch(message)
    return None if match is None else _parse_natural_fact_examples(match.group(1))


def _natural_candidate_decision(message: str):
    """Parse explicit accept/reject language for the current review queue."""
    match = _NATURAL_CANDIDATE_DECISION_RE.fullmatch(message)
    if match is None:
        return None
    return (match.group("decision").casefold(), match.group("number"))


def _natural_practice_request(message: str) -> tuple[str, bool] | None:
    """Return (question, refers_to_previous_turn) for explicit practice requests."""
    normalized = message.strip()
    match = re.fullmatch(
        r"(?:please\s+)?(?:practice|learn from|store)\s+"
        r"(?:that|this|the last)\s+(?:answer|inference)[.!]?",
        normalized, flags=re.IGNORECASE)
    if match:
        return "", True
    match = re.fullmatch(
        r"(?:please\s+)?practice\s+(?:the\s+)?answer\s+to\s+(.+?)[.!]?",
        normalized, flags=re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip(), False
    return None


def _unique_source_hit_for_sentence(index: CRMSResearchIndex, sentence: str):
    """Find a single indexed citation containing one exact training sentence."""
    documents = index.documents()
    if not documents:
        raise ValueError("load the source documents before teaching a fact pattern")
    citations = {}
    for hit in index.search(sentence, limit=len(documents)):
        try:
            citation = index.citation(hit)
            excerpt = index.resolve_citation(citation)
            source_text = index.document(hit.document_id).text
        except (KeyError, ValueError):
            continue
        if sentence in excerpt and source_text.count(sentence) == 1:
            citations[citation] = hit
    if len(citations) != 1:
        raise ValueError(
            "each example must match one unique indexed source sentence exactly")
    citation, hit = next(iter(citations.items()))
    return hit, citation


def _resolve_question_example(knowledge: CRMSKnowledgeBase,
                              question: str, answer: str):
    """Infer one question slot from a unique direct fact match."""
    question_words = tuple(normalized_tokens(question))
    answer_words = tuple(normalized_tokens(answer))

    def occurs_once(span: tuple[str, ...]) -> bool:
        return (bool(span) and sum(
            question_words[index:index + len(span)] == span
            for index in range(len(question_words) - len(span) + 1)) == 1)

    matches = set()
    for fact in knowledge.facts():
        if fact.qualifiers:
            continue
        subject = tuple(normalized_tokens(fact.subject))
        obj = tuple(normalized_tokens(fact.object))
        relation = fact.relation
        if answer_words == subject and occurs_once(obj):
            matches.add((relation, "subject", fact.object))
        if answer_words == obj and occurs_once(subject):
            matches.add((relation, "object", fact.subject))
    return next(iter(matches)) if len(matches) == 1 else None


def _resolve_subject_pattern_question_example(
        knowledge: CRMSKnowledgeBase, question: str, answer: str):
    """Resolve an example whose named query entity is inside a fact endpoint.

    Proper-name spans are proposed only as candidate slots. A result is
    returned only when exactly one unconflicted direct fact supplies the
    answer and its endpoint contains that exact span once.
    """
    question_words = tuple(normalized_tokens(question))
    answer_words = tuple(normalized_tokens(answer))
    entity_pattern = re.compile(
        r"[A-Z][\w’'-]*(?:\s+(?:(?:van|von|de|del|da|di|la|le)\s+)?"
        r"[A-Z][\w’'-]*)*")
    excluded_heads = {"who", "what", "which", "where", "when", "why", "how"}
    spans = []
    for match in entity_pattern.finditer(question):
        surface = match.group().strip()
        tokens = tuple(normalized_tokens(surface))
        if not tokens or tokens[0] in excluded_heads:
            continue
        if (sum(question_words[index:index + len(tokens)] == tokens
                for index in range(len(question_words) - len(tokens) + 1)) == 1):
            spans.append((surface, tokens))
    if not spans:
        return None

    negative_keys = {
        (tuple(normalized_tokens(fact.subject)),
         tuple(normalized_tokens(fact.relation)),
         tuple(normalized_tokens(fact.object)),
         tuple((tuple(normalized_tokens(name)), tuple(normalized_tokens(value)))
               for name, value in fact.qualifiers))
        for fact in knowledge.negative_facts()
    }
    matches = {}
    for fact in knowledge.facts():
        if fact.qualifiers:
            continue
        fact_subject = tuple(normalized_tokens(fact.subject))
        fact_object = tuple(normalized_tokens(fact.object))
        if answer_words == fact_object:
            answer_field, endpoint_field, endpoint = (
                "object", "subject", fact_subject)
        elif answer_words == fact_subject:
            answer_field, endpoint_field, endpoint = (
                "subject", "object", fact_object)
        else:
            continue
        fact_key = (fact_subject, tuple(normalized_tokens(fact.relation)),
                    fact_object, ())
        if fact_key in negative_keys:
            continue
        for surface, bound in spans:
            question_positions = [index for index in range(
                len(question_words) - len(bound) + 1)
                if question_words[index:index + len(bound)] == bound]
            endpoint_positions = [index for index in range(
                len(endpoint) - len(bound) + 1)
                if endpoint[index:index + len(bound)] == bound]
            if len(question_positions) != 1 or len(endpoint_positions) != 1:
                continue
            q_start = question_positions[0]
            f_start = endpoint_positions[0]
            key = (
                fact.relation, answer_field, surface,
                question_words[:q_start],
                question_words[q_start + len(bound):], endpoint_field,
                endpoint[:f_start], endpoint[f_start + len(bound):])
            matches[key] = None
    if len(matches) != 1:
        return None
    (relation, answer_field, bound_entity, question_prefix, question_suffix,
     fact_bound_field, fact_prefix, fact_suffix) = next(iter(matches))
    return {
        "relation": relation, "answer_field": answer_field,
        "bound_entity": bound_entity,
        "question_prefix": question_prefix,
        "question_suffix": question_suffix,
        "fact_bound_field": fact_bound_field,
        "fact_prefix": fact_prefix, "fact_suffix": fact_suffix,
    }


def _resolve_qualified_question_example(knowledge: CRMSKnowledgeBase,
                                        question: str, answer: str):
    """Resolve one contextual question example to a unique stored fact."""
    question_words = tuple(normalized_tokens(question))
    answer_words = tuple(normalized_tokens(answer))

    def occurs_once(surface: str) -> bool:
        needle = tuple(normalized_tokens(surface))
        return (bool(needle) and sum(
            question_words[index:index + len(needle)] == needle
            for index in range(len(question_words) - len(needle) + 1)) == 1)

    matches = set()
    for fact in knowledge.facts():
        if not fact.qualifiers:
            continue
        subject = tuple(normalized_tokens(fact.subject))
        obj = tuple(normalized_tokens(fact.object))
        qualifier_values = tuple((name, value) for name, value in fact.qualifiers)
        if not all(occurs_once(value) for _name, value in qualifier_values):
            continue
        if answer_words == subject and occurs_once(fact.object):
            matches.add((fact.relation, "subject", fact.object, qualifier_values))
        if answer_words == obj and occurs_once(fact.subject):
            matches.add((fact.relation, "object", fact.subject, qualifier_values))
    return next(iter(matches)) if len(matches) == 1 else None


def _resolve_path_question_example(knowledge: CRMSKnowledgeBase,
                                   question: str, answer: str):
    """Find one unique, direct-fact path from a named question entity to answer."""
    words = tuple(normalized_tokens(question))
    target = tuple(normalized_tokens(answer))
    facts = knowledge.facts()

    def occurs_once(surface: str) -> bool:
        needle = tuple(normalized_tokens(surface))
        return (bool(needle) and sum(
            words[index:index + len(needle)] == needle
            for index in range(len(words) - len(needle) + 1)) == 1)

    starts = {fact.subject for fact in facts if occurs_once(fact.subject)}
    outgoing: dict[tuple[str, ...], set[tuple[tuple[str, ...], str]]] = {}
    for fact in facts:
        subject = tuple(normalized_tokens(fact.subject))
        relation = tuple(normalized_tokens(fact.relation))
        if subject and relation:
            outgoing.setdefault(subject, set()).add((relation, fact.object))

    matches = set()
    expansions = 0
    for start in starts:
        stack = [(tuple(normalized_tokens(start)), tuple(), 0)]
        while stack:
            current, path, depth = stack.pop()
            if depth >= 3:
                continue
            for relation, next_entity in outgoing.get(current, ()):
                expansions += 1
                if expansions > 20_000:
                    return None
                next_path = path + (relation,)
                if tuple(normalized_tokens(next_entity)) == target:
                    result = knowledge.ask_path(
                        start, [" ".join(item) for item in next_path])
                    if (result.status == "answered"
                            and tuple(normalized_tokens(result.answer or "")) == target):
                        matches.add((next_path, start))
                stack.append((tuple(normalized_tokens(next_entity)),
                              next_path, depth + 1))
    return next(iter(matches)) if len(matches) == 1 else None


def _resolve_polar_example(knowledge: CRMSKnowledgeBase,
                           question: str, answer: bool):
    """Resolve a label to explicit evidence or a verified positive proof."""
    words = tuple(normalized_tokens(question))

    def spans(needle: tuple[str, ...]):
        return [(start, start + len(needle))
                for start in range(len(words) - len(needle) + 1)
                if needle and words[start:start + len(needle)] == needle]

    facts = knowledge.facts() if answer else knowledge.negative_facts()
    matches = set()
    for fact in facts:
        subject = tuple(normalized_tokens(fact.subject))
        obj = tuple(normalized_tokens(fact.object))
        subject_spans, object_spans = spans(subject), spans(obj)
        relation = tuple(normalized_tokens(fact.relation))
        relation_spans = spans(relation)
        if (len(subject_spans) != 1 or len(object_spans) != 1
                or not relation_spans):
            continue
        subject_span, object_span = subject_spans[0], object_spans[0]
        if (subject_span[0] < object_span[1]
                and subject_span[1] > object_span[0]):
            continue
        if any(not (start < subject_span[1] and end > subject_span[0])
               and not (start < object_span[1] and end > object_span[0])
               for start, end in relation_spans):
            matches.add((fact.subject, fact.relation, fact.object))

    # A positive example may be licensed by a rule proof even when the
    # conclusion is not copied into the fact store. Candidate relation labels
    # come only from explicit rules, schema declarations, or stored relation
    # fields, and the question must contain the relation and both entities.
    # Negative labels deliberately remain closed to explicit negative facts.
    if answer:
        positive_facts = knowledge.facts()
        entities = sorted({value for fact in positive_facts
                           for value in (fact.subject, fact.object)})
        relations = {fact.relation for fact in positive_facts}
        relations.update(rule.conclusion_relation
                         for rule in knowledge._inference_rules.values())
        for fact in positive_facts:
            if tuple(normalized_tokens(fact.relation)) == ("has", "relation", "type"):
                relations.add(fact.subject)
        relation_matches = []
        for relation in sorted(relations):
            relation_tokens = tuple(normalized_tokens(relation))
            relation_spans = spans(relation_tokens)
            if relation_spans:
                relation_matches.append((relation, relation_spans))
        candidate_triples = set()
        for subject in entities:
            subject_spans = spans(tuple(normalized_tokens(subject)))
            if len(subject_spans) != 1:
                continue
            for obj in entities:
                if subject == obj:
                    continue
                object_spans = spans(tuple(normalized_tokens(obj)))
                if len(object_spans) != 1:
                    continue
                subject_span, object_span = subject_spans[0], object_spans[0]
                if (subject_span[0] < object_span[1]
                        and subject_span[1] > object_span[0]):
                    continue
                for relation, relation_spans in relation_matches:
                    if any(not (start < subject_span[1]
                                and end > subject_span[0])
                           and not (start < object_span[1]
                                    and end > object_span[0])
                           for start, end in relation_spans):
                        candidate_triples.add((subject, relation, obj))
        # Bound natural-language alignment work independently of inference's
        # own expansion and depth limits. If there are too many readings to
        # check, the example remains unresolved rather than sampling one.
        if len(candidate_triples) <= 32:
            for subject, relation, obj in sorted(candidate_triples):
                inferred = knowledge.infer_relation(
                    subject, relation, obj, max_expansions=1_000)
                if inferred.status == "answered" and inferred.proofs:
                    matches.add((subject, relation, obj))
    return next(iter(matches)) if len(matches) == 1 else None


def _natural_rule_demonstration(
    message: str,
) -> tuple[str, list[int], list[int]] | None:
    """Parse one of the explicit, bounded natural-language example forms."""
    match = None
    for pattern in _RULE_DEMONSTRATION_PATTERNS:
        match = pattern.fullmatch(message)
        if match is not None:
            break
    if match is None:
        return None
    instruction = _normalize_natural_rule_instruction(match.group("instruction"))
    if instruction is None:
        return None
    try:
        inputs = _parse_integer_list(match.group("input"), allow_empty=True)
        outputs = _parse_integer_list(match.group("output"), allow_empty=True)
    except ValueError:
        return None
    return instruction, inputs, outputs


def _natural_rule_demonstrations(
    message: str,
) -> tuple[str, list[tuple[list[int], list[int]]]] | None:
    """Parse one exact batch of examples or wrap the existing single form."""
    prefix = _RULE_BATCH_PREFIX_RE.fullmatch(message)
    if prefix is not None:
        instruction = _normalize_natural_rule_instruction(prefix.group("instruction"))
        examples_text = prefix.group("examples")
        matches = list(_RULE_EXAMPLE_PAIR_RE.finditer(examples_text))
        if matches:
            if len(matches) > 8 or examples_text[:matches[0].start()].strip():
                return None
            for previous, current in zip(matches, matches[1:]):
                if not _RULE_BATCH_SEPARATOR_RE.fullmatch(
                        examples_text[previous.end():current.start()]):
                    return None
            if examples_text[matches[-1].end():].strip():
                return None
            if instruction is None:
                return None
            examples = []
            try:
                for match in matches:
                    examples.append((
                        _parse_integer_list(match.group("input"), allow_empty=True),
                        _parse_integer_list(match.group("output"), allow_empty=True)))
            except ValueError:
                return None
            return instruction, examples
    single = _natural_rule_demonstration(message)
    if single is None:
        return None
    instruction, inputs, outputs = single
    return instruction, [(inputs, outputs)]


def _natural_rule_shared_phrases(
        message: str
        ) -> tuple[tuple[str, str], list[tuple[list[int], list[int]]]] | None:
    """Parse two independently grounded phrases sharing one example set."""
    match = _RULE_SHARED_PHRASES_RE.fullmatch(message)
    if match is None:
        return None
    phrases = tuple(value[1:-1].strip()
                    for value in (match.group("first"), match.group("second")))
    if (any(not _normalize_natural_rule_instruction(value) for value in phrases)
            or len({value.casefold() for value in phrases}) != 2):
        return None
    examples_text = match.group("examples")
    matches = list(_RULE_EXAMPLE_PAIR_RE.finditer(examples_text))
    if (len(matches) < 2 or len(matches) > 8
            or examples_text[:matches[0].start()].strip()
            or examples_text[matches[-1].end():].strip()):
        return None
    if any(not _RULE_BATCH_SEPARATOR_RE.fullmatch(
            examples_text[previous.end():current.start()])
           for previous, current in zip(matches, matches[1:])):
        return None
    examples = []
    try:
        for row in matches:
            examples.append((
                _parse_integer_list(row.group("input"), allow_empty=True),
                _parse_integer_list(row.group("output"), allow_empty=True)))
    except ValueError:
        return None
    if len({tuple(inputs) for inputs, _outputs in examples}) < 2:
        return None
    return (phrases[0], phrases[1]), examples


def _natural_rule_feedback(message: str) -> list[int] | None:
    """Parse an output-only reply when a contrastive input is pending."""
    match = re.fullmatch(
        r"\s*(?:(?:for\s+(?:that|this)\s+input\s*,?\s*)?"
        r"(?:the\s+)?(?:output|answer|result)\s*(?:is|:)|"
        r"it\s+(?:should\s+be|is|produces|returns)|then)?\s*"
        r"\[([^\[\]]*)\]\s*[.!?]*\s*",
        message, flags=re.IGNORECASE)
    if match is None:
        return None
    try:
        return _parse_integer_list(match.group(1), allow_empty=True)
    except ValueError:
        return None


def _natural_rule_request(message: str) -> tuple[str, list[int]] | None:
    """Read one bracketed integer list after an instruction phrase."""
    requests = _natural_rule_requests(message)
    if requests is None or len(requests[1]) != 1:
        return None
    return requests[0], requests[1][0]


def _natural_rule_requests(message: str) -> tuple[str, list[list[int]]] | None:
    """Read one instruction followed by a bounded list of input lists."""
    if _natural_rule_feedback(message) is not None:
        return None
    matches = list(re.finditer(r"\[([^\[\]]*)\]", message))
    if not 1 <= len(matches) <= 8:
        return None
    if len(matches) > 1:
        for previous, current in zip(matches, matches[1:]):
            separator = message[previous.end():current.start()]
            if not re.fullmatch(r"\s*(?:,\s*and\s*|\band\b|[,;])\s*",
                                separator, flags=re.IGNORECASE):
                return None
    if message[matches[-1].end():].strip(" \t.,;!?"):
        return None
    instruction = _normalize_natural_rule_instruction(
        message[:matches[0].start()])
    if instruction is None:
        return None
    try:
        values = [_parse_integer_list(match.group(1), allow_empty=True)
                  for match in matches]
    except ValueError:
        return None
    return instruction, values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-db", type=Path, default=None,
                        help="start from a portable CRMS SQLite learned-model database")
    parser.add_argument("--knowledge", type=Path, default=Path("crms_knowledge.json"),
                        help="knowledge store; .sqlite paths use canonical indexed SQLite memory (default: %(default)s)")
    parser.add_argument("--fact-db", type=Path, default=None,
                        help="use an indexed SQLite fact sidecar while loading knowledge JSON")
    parser.add_argument("--math", type=Path, default=Path("crms_math.json"),
                        help="learned exact-math examples (default: %(default)s)")
    parser.add_argument("--math-session", type=Path, default=None,
                        help="pending contrastive math example (default: next to --math)")
    parser.add_argument("--translations", type=Path,
                        default=Path("crms_translations.json"),
                        help="aligned translation frames (default: %(default)s)")
    parser.add_argument("--translation-session", type=Path, default=None,
                        help="pending translation clarification (default: next to --translations)")
    parser.add_argument("--index", type=Path, default=None,
                        help="research index to load and update (portable-model sidecar by default with --model-db)")
    parser.add_argument("--dialogue-state", type=Path,
                        default=Path("crms_dialogue.json"),
                        help="short-term context state (default: %(default)s)")
    parser.add_argument("--rules", type=Path, default=Path("crms_rules.json"),
                        help="learned transformation-rule memory; .sqlite paths use indexed SQLite storage (default: %(default)s)")
    parser.add_argument("--rule-depth", type=int, choices=(1, 2, 3, 4), default=2,
                        help="maximum rule-composition depth (default: %(default)s)")
    parser.add_argument("--rule-max-add", type=int, default=10,
                        help="largest learned add_k magnitude (default: %(default)s)")
    parser.add_argument("--rule-max-scale", type=int, default=5,
                        help="largest learned scale_k magnitude (default: %(default)s)")
    parser.add_argument("--rule-max-modulus", type=int, default=6,
                        help="largest searched divisibility modulus (default: %(default)s)")
    parser.add_argument("--rule-max-rotation", type=int, default=4,
                        help="largest searched rotation offset magnitude (default: %(default)s)")
    parser.add_argument("--rule-max-repeat", type=int, default=4,
                        help="largest searched repetition count (default: %(default)s)")
    parser.add_argument("--rule-max-position-stride", type=int, default=6,
                        help="largest searched positional stride (default: %(default)s)")
    parser.add_argument("--rule-enable-position-arithmetic", action="store_true",
                        help="include one-based position arithmetic candidates (expands search)")
    parser.add_argument("--rule-search-expansions", type=int, default=250_000,
                        help="maximum rule-search expansions (default: %(default)s)")
    parser.add_argument("--rule-vsa-alpha", type=float, default=0.5,
                        help="VSA similarity blend (default: %(default)s)")
    parser.add_argument("--rule-vsa-min-similarity", type=float, default=0.30,
                        help="minimum VSA phrase similarity (default: %(default)s)")
    parser.add_argument("--rule-vsa-min-margin", type=float, default=0.10,
                        help="minimum VSA retrieval margin (default: %(default)s)")
    parser.add_argument("--rule-session", type=Path,
                        default=None,
                        help="pending contrastive rule example (default: %(default)s)")
    parser.add_argument("--candidate-session", type=Path,
                        default=None,
                        help="persisted pending fact review candidates (default: next to --knowledge)")
    return parser


def _print_rule_learning_result(learned) -> None:
    print(f"Rule learning status: {learned.status}. {learned.message or ''}")
    if learned.request:
        print(f"CRMS> {learned.request}")
    for number, procedure in enumerate(learned.proposed_procedures or [], 1):
        steps = " then ".join(
            step["operation"]
            + (f" {step['parameters']}" if step.get("parameters") else "")
            for step in procedure)
        print(f"Advisory procedure {number} (not learned): {steps}")


def _format_derived_cases(cases: list[dict]) -> list[str]:
    if not cases:
        return ["No derived cases are stored."]
    lines = []
    for case in cases:
        conclusion = case["conclusion"]
        line = (f"Derived case [{case['status']}]: "
                f"{conclusion['subject']} — {conclusion['relation']} → "
                f"{conclusion['object']}")
        if case.get("qualifiers"):
            line += " [context: " + ", ".join(
                f"{name}={value}" for name, value in case["qualifiers"])
            line += "]"
        line += (f"; practice={case['practice_count']}, "
                 f"retrieval={case['retrieval_count']}; "
                 f"rules={', '.join(case['lineage']['rule_ids'])}; "
                 f"sources={', '.join(case['lineage']['sources'])}.")
        lines.append(line)
    return lines


def _print_scaffold_retrieval_evidence(prediction: Prediction) -> None:
    for trace in prediction.retrieval_evidence or []:
        if trace.get('kind') != 'parameterized_procedure_scaffold':
            continue
        frame_kind = trace.get('frame_type', 'grounded')
        print(f"Scaffold frame: {frame_kind}; {trace.get('query_frame', '')}")
        if trace.get('scaffold_id'):
            print(f"  validated scaffold: {trace['scaffold_id']}")
        for role in trace.get('role_evidence', []):
            sources = ', '.join(role.get('supporting_phrases', [])) or '(none)'
            print(f"  word role {role.get('position', 0) + 1}: "
                  f"{role.get('token')!r} supported by {sources}")
        for binding in trace.get('numeric_bindings', []):
            operation = binding.get('operation')
            step = binding.get('procedure_step', 0) + 1
            value = binding.get('surface_value')
            parameter_value = binding.get('parameter_value')
            evidence = '; '.join(
                f"{item.get('phrase')}: {item.get('surface_value')} → "
                f"{item.get('parameter_value')}"
                for item in binding.get('training_evidence', []))
            print(f"  number slot {binding.get('slot')}: {value} → "
                  f"step {step} {operation}.{binding.get('parameter')}="
                  f"{parameter_value}; grounded by {evidence}")


def _print_candidate_routes(prediction: Prediction) -> None:
    if not prediction.candidate_routes:
        return
    print("Competing grounded rule candidates:")
    for index, alternative in enumerate(prediction.candidate_routes, start=1):
        procedure = alternative.get('procedure', [])
        steps = " then ".join(
            step.get('operation', 'unknown')
            + (f" {step['parameters']}" if step.get('parameters') else "")
            for step in procedure)
        print(f"  {index}. {steps or '(empty procedure)'}")
        if prediction.contrastive_input is not None:
            print(f"     on {prediction.contrastive_input}: "
                  f"{alternative.get('probe_output')}")
        for route in alternative.get('routes', []):
            sources = ', '.join(route.get('evidence_phrases', [])) or '(none reported)'
            template = route.get('matched_template')
            suffix = f"; pattern: {template}" if template else ""
            print(f"     via {route.get('name', 'unknown route')}; "
                  f"evidence: {sources}{suffix}")


def _print_rule_explanation(rules: CRMSModel, instruction: str,
                            values: list[int]) -> None:
    prediction = rules.predict(instruction, values)
    print(f"Rule explanation status: {prediction.status}.")
    if prediction.status != "ok":
        print(f"CRMS> {prediction.request or prediction.message or prediction.status}")
        _print_candidate_routes(prediction)
        _print_scaffold_retrieval_evidence(prediction)
        if prediction.retrieval_score is not None:
            print(f"Retrieval score: {prediction.retrieval_score:.3f}; "
                  f"margin: {prediction.retrieval_margin:.3f}.")
        return
    print(f"Output: {prediction.output}")
    steps = " then ".join(
        step["operation"]
        + (f" {step['parameters']}" if step.get("parameters") else "")
        for step in prediction.procedure or [])
    print(f"Procedure: {steps}")
    print(f"Grounding phrases: {', '.join(prediction.evidence_phrases or []) or '(none reported)'}")
    if prediction.matched_templates:
        print(f"Matched patterns: {', '.join(prediction.matched_templates)}")
    _print_scaffold_retrieval_evidence(prediction)
    if prediction.matched_tokens or prediction.matched_bigrams:
        print(f"Matched tokens: {', '.join(prediction.matched_tokens or []) or '(none)'}")
        print(f"Matched word pairs: {', '.join(prediction.matched_bigrams or []) or '(none)'}")
    if prediction.retrieval_score is not None:
        print(f"Retrieval score: {prediction.retrieval_score:.3f}; "
              f"margin: {prediction.retrieval_margin:.3f}.")
    for phrase in prediction.evidence_phrases or []:
        demonstrations = rules._examples.get(phrase, [])
        procedure = rules._procedures.get(phrase)
        if not demonstrations:
            continue
        rendered = "; ".join(f"{inputs} -> {outputs}"
                              for inputs, outputs in demonstrations[:3])
        suffix = " …" if len(demonstrations) > 3 else ""
        source_steps = " then ".join(
            step.operation
            + (f" {step.parameters}" if step.parameters else "")
            for step in procedure or [])
        print(f"  {phrase}: {source_steps}; examples: {rendered}{suffix}")


def _load_pending_rule(path: Path, rules_path: Path) -> tuple[str, list[int]] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("stored pending rule session is malformed")
    if payload.get("format_version") != 1:
        raise ValueError("unsupported pending rule-session format")
    if payload.get("rules_path") != str(rules_path.resolve()):
        return None
    instruction, values = payload.get("instruction"), payload.get("input")
    if (not isinstance(instruction, str) or not instruction.strip()
            or not isinstance(values, list)
            or any(type(value) is not int for value in values)):
        raise ValueError("stored pending rule example is malformed")
    return instruction, values


def _save_pending_rule(path: Path, rules_path: Path,
                       pending: tuple[str, list[int]] | None) -> None:
    if pending is None and not path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "rules_path": str(rules_path.resolve()),
        "instruction": pending[0] if pending else None,
        "input": pending[1] if pending else None,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_stat_state(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _memory_file_state(path: Path) -> tuple[int, int, str] | None:
    """Detect learned-memory changes even when size and mtime are preserved."""
    stat_state = _file_stat_state(path)
    if stat_state is None:
        return None
    return (*stat_state, _file_sha256(path))


def _index_file_state(path: Path) -> tuple[tuple[int, int] | None, ...]:
    """Track the index and its SQLite WAL when deciding whether to repack."""
    return tuple(_file_stat_state(candidate) for candidate in (
        path, Path(str(path) + "-wal"), Path(str(path) + "-shm")))


def _load_pending_math(path: Path, math_path: Path,
                       model: CRMSMath) -> tuple[tuple[str, ...], tuple[int, int]] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or payload.get("format_version") != 1):
        raise ValueError("stored pending math session is malformed")
    if payload.get("math_path") != str(math_path.resolve()):
        return None
    phrase, left, right = (payload.get("phrase"), payload.get("left"),
                           payload.get("right"))
    if phrase is None and left is None and right is None:
        return None
    if (not isinstance(phrase, list) or not phrase
            or not all(isinstance(token, str) for token in phrase)
            or type(left) is not int or type(right) is not int):
        raise ValueError("stored pending math example is malformed")
    key = tuple(phrase)
    examples = model._examples.get(key, {})
    candidates = model._candidates(examples)
    pair = (left, right)
    if (len(candidates) < 2 or pair in examples
            or model._contrastive_pair(candidates, set(examples)) != pair):
        return None
    return key, pair


def _save_pending_math(path: Path, math_path: Path,
                       pending: tuple[tuple[str, ...], tuple[int, int]] | None) -> None:
    if pending is None and not path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "math_path": str(math_path.resolve()),
        "phrase": list(pending[0]) if pending else None,
        "left": pending[1][0] if pending else None,
        "right": pending[1][1] if pending else None,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _translation_memory_fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pending_translation(
        path: Path, translations_path: Path, model: CRMSTranslation
        ) -> tuple[str, str, str, tuple[str, ...], str] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict)
            or payload.get("format_version") != 1):
        raise ValueError("stored pending translation session is malformed")
    if (payload.get("translations_path") != str(translations_path.resolve())
            or payload.get("memory_sha256")
            != _translation_memory_fingerprint(translations_path)):
        return None
    kind, source, target = (payload.get("kind"), payload.get("source"),
                            payload.get("target"))
    choices, source_text = payload.get("choices"), payload.get("source_text")
    if (kind not in {"register", "source"}
            or not isinstance(source, str) or not isinstance(target, str)
            or not isinstance(choices, list) or not choices
            or len(choices) > 32
            or not all(isinstance(choice, str) and choice for choice in choices)
            or len(set(choices)) != len(choices)
            or not isinstance(source_text, str) or not source_text.strip()
            or len(source_text) > 4096):
        raise ValueError("stored pending translation choice is malformed")
    if kind == "register":
        check = model.translate(
            f"Translate from {source} to {target}: {source_text}")
        if (check is None or check.status != "ambiguous"
                or tuple(check.matched_registers) != tuple(choices)):
            return None
    else:
        check = model.translate(f"Translate ‘{source_text}’ into {target}.")
        if (check is None or check.status != "ambiguous"
                or tuple(check.matched_source_languages) != tuple(choices)):
            return None
    return kind, source, target, tuple(choices), source_text


def _save_pending_translation(
        path: Path, translations_path: Path,
        pending: tuple[str, str, str, tuple[str, ...], str] | None) -> None:
    if pending is None and not path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "translations_path": str(translations_path.resolve()),
        "memory_sha256": _translation_memory_fingerprint(translations_path),
        "kind": pending[0] if pending else None,
        "source": pending[1] if pending else None,
        "target": pending[2] if pending else None,
        "choices": list(pending[3]) if pending else [],
        "source_text": pending[4] if pending else None,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _load_pending_candidates(path: Path, knowledge_path: Path, index_path: Path,
                             knowledge: CRMSKnowledgeBase,
                             index: CRMSResearchIndex):
    if not path.exists():
        return [], "", []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict)
            or payload.get("format_version") not in {1, 2}):
        raise ValueError("stored candidate-session format is malformed or unsupported")
    question = payload.get("pending_question", "")
    rows = payload.get("candidates", [])
    invalidated = payload.get("invalidated_candidates", [])
    if (not isinstance(question, str) or not isinstance(rows, list)
            or len(rows) > 200 or not isinstance(invalidated, list)
            or len(invalidated) > 200):
        raise ValueError("stored candidate-session contents are malformed")
    invalidated = [item for item in invalidated
                   if isinstance(item, dict)
                   and isinstance(item.get("candidate"), dict)
                   and isinstance(item.get("reason"), str)]
    if (payload.get("knowledge_path") != str(knowledge_path.resolve())
            or payload.get("index_path") != str(index_path.resolve())):
        invalidated.extend({
            "candidate": row if isinstance(row, dict) else {"record": repr(row)},
            "reason": "the configured knowledge or source-index path changed",
        } for row in rows)
        return [], "", invalidated[-200:]
    candidates = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise ValueError("candidate record is malformed")
            row = dict(row)
            row["language_evidence"] = tuple(row.get("language_evidence", ()))
            row["qualifiers"] = tuple(tuple(pair) for pair in row.get("qualifiers", ()))
            candidate = FactCandidate(**row)
            if (type(candidate.polarity) is not bool
                    or any(not isinstance(value, str) or not value.strip()
                           for value in (candidate.subject, candidate.relation,
                                         candidate.object, candidate.source,
                                         candidate.template, candidate.sentence))):
                raise ValueError("candidate fields are malformed")
            knowledge._normalize_qualifiers(dict(candidate.qualifiers))
            excerpt = index.resolve_citation(candidate.source)
            if candidate.sentence not in excerpt:
                raise ValueError("candidate citation no longer matches the source")
            typed_match = next((item for item in candidate.language_evidence
                                if item.get("kind") in {
                                    "typed_relation_source_match",
                                    "explicit_type_source_match"}), None)
            if typed_match is not None:
                typed_query = _natural_typed_relation_question(
                    str(typed_match.get("question", question)))
                if typed_query is None:
                    raise ValueError(
                        "typed source candidate lost its question frame")
                refreshed = _natural_typed_relation_source_evidence(
                    index, typed_query)
                refreshed_candidates = [
                    fact for match in refreshed["matches"]
                    for fact in (*match["relation"], *match["type"])]
                valid = any(
                    (item.subject, item.relation, item.object, item.source,
                     item.polarity, item.sentence)
                    == (candidate.subject, candidate.relation, candidate.object,
                        candidate.source, candidate.polarity, candidate.sentence)
                    for item in refreshed_candidates)
            else:
                licensed = knowledge.propose_facts(candidate.sentence,
                                                   source=candidate.source)
                valid = any(
                    (item.subject, item.relation, item.object, item.polarity,
                     item.qualifiers)
                    == (candidate.subject, candidate.relation, candidate.object,
                        candidate.polarity, candidate.qualifiers)
                    for item in licensed)
            if not valid:
                raise ValueError(
                    "candidate is no longer licensed by its source frame")
            candidates.append(candidate)
        except (KeyError, TypeError, ValueError) as error:
            invalidated.append({
                "candidate": row if isinstance(row, dict) else {"record": repr(row)},
                "reason": str(error) or "candidate failed validation",
            })
    return candidates, question, invalidated[-200:]


def _save_pending_candidates(path: Path, knowledge_path: Path, index_path: Path,
                             candidates, question: str, invalidated=()) -> None:
    if not candidates and not invalidated:
        if path.exists():
            path.unlink()
        return
    if len(candidates) > 200 or len(invalidated) > 200:
        raise ValueError("candidate review state exceeds its 200-record storage bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 2,
        "knowledge_path": str(knowledge_path.resolve()),
        "index_path": str(index_path.resolve()),
        "pending_question": question,
        "candidates": [asdict(candidate) for candidate in candidates],
        "invalidated_candidates": list(invalidated),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    args = build_parser().parse_args()
    model_research_sidecar: Path | None = None
    if args.model_db is not None:
        memories = inspect_model_database(args.model_db)
        for name, value in model_database_rule_settings(
                args.model_db, validate=False).items():
            setattr(args, name, value)
        memory_dir = args.model_db.with_name(args.model_db.name + ".memories")
        knowledge_memory_name = (
            "knowledge.sqlite"
            if memories.get("knowledge", {}).get("storage") == "sqlite"
            else "knowledge.json")
        rule_memory_name = ("rules.sqlite"
                            if memories.get("rules", {}).get("storage") == "sqlite"
                            else "rules.json")
        expected_files = {
            memory_dir / (knowledge_memory_name if name == "knowledge"
                          else rule_memory_name if name == "rules"
                          else f"{name}.json")
            for name in memories
        }
        model_digest = _file_sha256(args.model_db)
        sidecar_marker = memory_dir / ".model.sha256"
        if memory_dir.exists():
            if not memory_dir.is_dir() or any(not path.is_file()
                                              for path in expected_files) \
                    or not sidecar_marker.is_file():
                raise ValueError(
                    f"model memory sidecar is incomplete: {memory_dir}")
            if sidecar_marker.read_text(encoding="ascii").strip() != model_digest:
                raise ValueError(
                    f"model memory sidecar was created from a different database: {memory_dir}")
        else:
            install_model_database(args.model_db, memory_dir, validated=True)
            sidecar_marker.write_text(model_digest + "\n", encoding="ascii")
        embedded_research = model_database_has_research(
            args.model_db, validate=False)
        research_sidecar = memory_dir / "research.sqlite"
        if (embedded_research and not research_sidecar.is_file()):
            install_model_database(args.model_db, memory_dir, validated=True)
        if embedded_research:
            model_research_sidecar = research_sidecar
        args.knowledge = memory_dir / knowledge_memory_name
        args.rules = memory_dir / rule_memory_name
        args.math = memory_dir / "math.json"
        args.translations = memory_dir / "translations.json"
        if (args.fact_db is None and knowledge_memory_name == "knowledge.json"):
            args.fact_db = memory_dir / "facts.sqlite"
        print(f"Loaded portable learned model: {args.model_db}")
        model_memory_paths = (args.knowledge, args.rules, args.math,
                              args.translations)
        initial_model_memory_state = {
            path: _memory_file_state(path) for path in model_memory_paths
        }
    else:
        model_memory_paths = ()
        initial_model_memory_state = {}
    if args.index is None:
        if args.model_db is not None:
            args.index = args.model_db.with_name(args.model_db.name + ".memories") / "research.sqlite"
        else:
            args.index = Path("crms_research.json")
    if args.candidate_session is None:
        args.candidate_session = args.knowledge.with_name(
            args.knowledge.stem + "_candidate_session.json")
    if args.math_session is None:
        args.math_session = args.math.with_name(args.math.stem + "_session.json")
    if args.translation_session is None:
        args.translation_session = args.translations.with_name(
            args.translations.stem + "_session.json")
    if args.rule_session is None:
        args.rule_session = (
            args.rules.with_name(args.rules.stem + "_session.json")
            if args.model_db is not None else Path("crms_rule_session.json"))
    if args.fact_db is not None and not args.knowledge.exists():
        raise ValueError("--fact-db requires an existing knowledge JSON store")
    if (args.fact_db is not None
            and args.fact_db.expanduser().resolve()
            == args.knowledge.expanduser().resolve()):
        raise ValueError("--fact-db must be a separate file from --knowledge")
    knowledge = (CRMSKnowledgeBase.load(args.knowledge, fact_db=args.fact_db)
                 if args.knowledge.exists() else CRMSKnowledgeBase())
    math_model = (CRMSMath.load(args.math)
                  if args.math.exists() else CRMSMath())
    pending_math = _load_pending_math(args.math_session, args.math, math_model)
    translation_model = (CRMSTranslation.load(args.translations)
                         if args.translations.exists() else CRMSTranslation())
    restored_translation_clarification = _load_pending_translation(
        args.translation_session, args.translations, translation_model)
    _save_pending_translation(args.translation_session, args.translations,
                              restored_translation_clarification)
    sqlite_index = args.index.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}
    index = (
        CRMSSQLiteResearchIndex.load(args.index)
        if sqlite_index
        else CRMSResearchIndex.load(args.index)
        if args.index.exists()
        else CRMSSQLiteResearchIndex(args.index)
        if sqlite_index
        else CRMSResearchIndex())
    initial_index_state = _index_file_state(args.index)
    dialogue = (CRMSDialogue.load(knowledge, str(args.dialogue_state))
                if args.dialogue_state.exists() else CRMSDialogue(knowledge))
    rules = CRMSModel(
        args.rules, max_composition_depth=args.rule_depth,
        max_add=args.rule_max_add, max_scale=args.rule_max_scale,
        max_modulus=args.rule_max_modulus,
        max_rotation=args.rule_max_rotation,
        max_repeat=args.rule_max_repeat,
        max_position_stride=args.rule_max_position_stride,
        max_search_expansions=args.rule_search_expansions,
        vsa_alpha=args.rule_vsa_alpha,
        vsa_min_similarity=args.rule_vsa_min_similarity,
        vsa_min_margin=args.rule_vsa_min_margin,
        enable_position_arithmetic=args.rule_enable_position_arithmetic)
    pending_rule = _load_pending_rule(args.rule_session, args.rules)
    if pending_rule and pending_rule[0] in rules._procedures:
        pending_rule = None
        _save_pending_rule(args.rule_session, args.rules, pending_rule)
    pending_candidates, pending_question, invalidated_candidates = (
        _load_pending_candidates(args.candidate_session, args.knowledge,
                                 args.index, knowledge, index))

    print("CRMS grounded chat. Try a question, /source PATH, or /teach-fact; "
          "type /help for a quick start and /help all for every command.")
    if pending_rule is not None:
        instruction, contrastive_input = pending_rule
        print(f"Still waiting for the intended output for {instruction} on "
              f"{contrastive_input}. Type the output list, or /cancel-rule "
              "to move on; other inputs are still processed separately.")
    if pending_candidates:
        print(f"Restored {len(pending_candidates)} pending cited fact candidate(s). "
              "You can say 'accept candidate N' or 'reject candidate N', "
              "or use /pending-candidates and /accept N.")
    if invalidated_candidates:
        print(f"Restored {len(invalidated_candidates)} invalidated candidate "
              "record(s) for inspection. Use /invalidated-candidates to review "
              "why they cannot currently be accepted.")
    if restored_translation_clarification is not None:
        _kind, _source, _target, choices, _text = restored_translation_clarification
        print("Restored a pending translation clarification. Choose one of: "
              + ", ".join(choices) + ".")
    auto_practice_questions = False
    last_generated_code = None
    pending_translation_clarification: tuple[
        str, str, str, tuple[str, ...], str] | None = (
            restored_translation_clarification)
    last_summary_query: str | None = None
    last_summary_licenses: tuple[dict, ...] = ()
    last_summary_limit = 5
    last_summary_scoped_hit = None
    last_research_evidence: dict | None = None
    latest_research_documents: list[dict] = []
    while True:
        try:
            line = input("you> ").strip()
        except EOFError:
            line = "/quit"
        if not line:
            continue
        previous_latest_documents = latest_research_documents
        latest_research_documents = []
        previous_translation_clarification = pending_translation_clarification
        if (pending_translation_clarification is not None
                and line != "/quit"):
            response = _NATURAL_TRANSLATION_REGISTER_RESPONSE_RE.fullmatch(line)
            if response is not None:
                kind, source_language, target_language, choices, source_text = (
                    pending_translation_clarification)
                selected_register = " ".join(normalized_tokens(
                    response.group("label")))
                if selected_register not in choices:
                    explicit_register_choice = (
                        line.casefold().endswith((
                            " register", " one", " option"))
                        or re.match(r"\s*(?:please\s+)?"
                                    r"(?:i\s+mean|(?:the\s+)?source\s+language\s+is|"
                                    r"go\s+with|use|choose|select|pick)\s+", line,
                                    re.IGNORECASE) is not None)
                    if explicit_register_choice:
                        label = "register" if kind == "register" else "source language"
                        print(f"Please choose a {label} from: "
                              + ", ".join(choices) + ".")
                        continue
                    pending_translation_clarification = None
                elif kind == "source":
                    line = (f"Translate from {selected_register} to "
                            f"{target_language}: {source_text}")
                    pending_translation_clarification = None
                else:
                    line = (f"Translate from {source_language} to {target_language} "
                            f"in {selected_register} register: {source_text}")
                    pending_translation_clarification = None
            else:
                pending_translation_clarification = None
        if previous_translation_clarification != pending_translation_clarification:
            _save_pending_translation(
                args.translation_session, args.translations,
                pending_translation_clarification)
        natural_decision = _natural_candidate_decision(line)
        if natural_decision is not None:
            decision, number = natural_decision
            if not pending_candidates:
                print("There are no fact candidates waiting for review.")
                continue
            if decision == "skip" and number is None:
                line = "/skip"
            else:
                if number is None:
                    if len(pending_candidates) != 1:
                        print("Several fact candidates are waiting; name a candidate number.")
                        continue
                    number = "1"
                line = (f"/accept {number}" if decision in {"accept", "approve"}
                        else f"/reject {number}")
        if line == "/quit":
            dialogue.save(str(args.dialogue_state))
            _save_pending_rule(args.rule_session, args.rules, pending_rule)
            _save_pending_math(args.math_session, args.math, pending_math)
            _save_pending_candidates(args.candidate_session, args.knowledge,
                                     args.index, pending_candidates, pending_question,
                                     invalidated_candidates)
            if args.model_db is not None:
                current_model_memory_state = {
                    path: _memory_file_state(path) for path in model_memory_paths
                }
                if (current_model_memory_state != initial_model_memory_state
                        or _index_file_state(args.index) != initial_index_state):
                    export_model_database(
                        args.model_db, knowledge=args.knowledge,
                        rules=args.rules,
                        math=args.math if args.math.is_file() else None,
                        translations=(args.translations
                                      if args.translations.is_file() else None),
                        research_index=(args.index if args.index.is_file()
                                        else model_research_sidecar
                                        if model_research_sidecar is not None
                                        and model_research_sidecar.is_file()
                                        else None))
                    marker_temporary = sidecar_marker.with_suffix(".sha256.tmp")
                    marker_temporary.write_text(
                        _file_sha256(args.model_db) + "\n", encoding="ascii")
                    marker_temporary.replace(sidecar_marker)
                    print("Updated portable model database with learned memories "
                          "and source text.")
            knowledge.close()
            print("CRMS state saved. Goodbye.")
            return 0
        if line in {"/help", "/help all"}:
            print(HELP if line == "/help all" else HELP_SHORT)
            continue
        if last_generated_code is not None:
            if _natural_code_evidence_request(line):
                print("CRMS> " + show_generated_code_evidence(last_generated_code))
                continue
            if _natural_code_explanation_request(line):
                print("CRMS> " + describe_generated_code(last_generated_code))
                continue
        if line == "/reset":
            dialogue.clear()
            pending_candidates = []
            pending_question = ""
            _save_pending_candidates(args.candidate_session, args.knowledge,
                                     args.index, pending_candidates, pending_question,
                                     invalidated_candidates)
            print("Dialogue context cleared.")
            continue
        if line == "/cancel-rule":
            pending_rule = None
            _save_pending_rule(args.rule_session, args.rules, pending_rule)
            print("Stopped waiting for a contrastive rule example. Stored examples remain available.")
            continue
        if line == "/cancel-math":
            pending_math = None
            _save_pending_math(args.math_session, args.math, pending_math)
            print("Stopped waiting for a contrastive math example. Stored examples remain available.")
            continue
        if line == "/skip":
            pending_candidates = []
            pending_question = ""
            _save_pending_candidates(args.candidate_session, args.knowledge,
                                     args.index, pending_candidates, pending_question,
                                     invalidated_candidates)
            print("Pending fact candidates dismissed.")
            continue
        if line == "/pending-candidates":
            if not pending_candidates:
                print("There are no fact candidates waiting for review.")
            for number, candidate in enumerate(pending_candidates, 1):
                polarity = "supports" if candidate.polarity else "opposes"
                print(f"{number}. {candidate.subject} — {candidate.relation} → "
                      f"{candidate.object} ({polarity})")
                print(f"   {candidate.source}\n   {candidate.sentence}")
            continue
        if line == "/invalidated-candidates":
            if not invalidated_candidates:
                print("There are no invalidated fact candidates to inspect.")
                continue
            for number, item in enumerate(invalidated_candidates, 1):
                candidate = item["candidate"]
                subject = candidate.get("subject", "<unknown subject>")
                relation = candidate.get("relation", "<unknown relation>")
                obj = candidate.get("object", "<unknown object>")
                print(f"{number}. {subject} — {relation} → {obj}")
                print(f"   Cannot accept: {item['reason']}")
                print(f"   {candidate.get('source', '<missing source>')}\n"
                      f"   {candidate.get('sentence', '<missing sentence>')}")
            print("These records are inspect-only. Re-run research against a valid "
                  "source and learned frame to create a reviewable candidate.")
            continue
        if line == "/clear-invalidated-candidates":
            invalidated_candidates = []
            _save_pending_candidates(args.candidate_session, args.knowledge,
                                     args.index, pending_candidates, pending_question,
                                     invalidated_candidates)
            print("Invalidated candidate history cleared.")
            continue
        if line.startswith("/source-dir "):
            corpus_value = line[len("/source-dir "):].strip()
            replace_existing = corpus_value.endswith(" --replace")
            verify_content = corpus_value.endswith(" --verify")
            if replace_existing and verify_content:
                print("Choose either --replace or --verify for a source directory scan.")
                continue
            if replace_existing:
                corpus_value = corpus_value[:-len(" --replace")].rstrip()
            elif verify_content:
                corpus_value = corpus_value[:-len(" --verify")].rstrip()
            corpus_path = Path(corpus_value).expanduser()
            if not corpus_path.is_dir():
                print(f"Corpus directory not found: {corpus_path}")
                continue
            try:
                result = index.add_directory(
                    corpus_path, replace=replace_existing,
                    verify_content=verify_content)
                index.save(args.index)
                print(f"Indexed {len(result.added)} source file(s); "
                      f"skipped {len(result.skipped)} existing file(s); "
                      f"{len(result.failures)} failure(s).")
                for document_id, error in result.failures[:20]:
                    print(f"Could not index {document_id}: {error}")
                if len(result.failures) > 20:
                    print(f"... {len(result.failures) - 20} additional failures omitted")
            except (OSError, RuntimeError, ValueError) as error:
                print(f"Could not index local corpus: {error}")
            continue
        if line.startswith("/source "):
            source_value = line[len("/source "):].strip()
            is_url = source_value.casefold().startswith(("http://", "https://"))
            source_path = None if is_url else Path(source_value).expanduser()
            if source_path is not None and not source_path.is_file():
                if "://" in source_value:
                    print("Only HTTP(S) page URLs are supported.")
                else:
                    print(f"Source file not found: {source_path}")
                continue
            document_id = (source_value if is_url
                           else str(source_path.resolve()))
            exists = index.contains_document(document_id)
            try:
                if is_url:
                    index.add_url(source_value, replace=exists)
                    label = index.document(document_id).title
                else:
                    index.add_file(source_path, document_id=document_id,
                                   title=source_path.name, location=document_id,
                                   replace=exists)
                    label = source_path.name
                index.save(args.index)
                print(f"Indexed {label}.")
            except (OSError, RuntimeError, ValueError) as error:
                print(f"Could not index source: {error}")
            continue
        if line.startswith("/retract-fact "):
            fields = [value.strip() for value in
                      line[len("/retract-fact "):].split("|")]
            if len(fields) < 5 or not all(fields[:5]):
                print("Use: /retract-fact POS/NEG|SUBJECT|RELATION|OBJECT|SOURCE[|KEY=VALUE...]")
                continue
            polarity, subject, relation, obj, source, *qualifier_fields = fields
            if polarity.casefold() not in {"pos", "neg"}:
                print("Polarity must be POS or NEG.")
                continue
            qualifiers = {}
            malformed = False
            for item in qualifier_fields:
                name, separator, value = item.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Qualifiers must use KEY=VALUE.")
                continue
            try:
                remove = (knowledge.remove_fact if polarity.casefold() == "pos"
                          else knowledge.remove_negative_fact)
                removed = remove(subject, relation, obj, source,
                                 qualifiers=qualifiers)
                if not removed:
                    print("No matching fact support from that source was found.")
                    continue
                knowledge.save(args.knowledge)
                remaining = (knowledge.facts() if polarity.casefold() == "pos"
                             else knowledge.negative_facts())
                target_key = knowledge._fact_key(
                    knowledge._canonicalize_entity(subject), relation,
                    knowledge._canonicalize_entity(obj),
                    knowledge._normalize_qualifiers(qualifiers))
                still_supported = any(
                    knowledge._fact_key(fact.subject, fact.relation, fact.object,
                                        fact.qualifiers) == target_key
                    for fact in remaining)
                print("Retracted source support; other citations remain."
                      if still_supported else
                      "Retracted the final source support; the fact is no longer stored.")
            except (TypeError, ValueError, OSError) as error:
                print(f"Could not retract fact support: {error}")
            continue
        if line.startswith("/crawl "):
            fields = [value.strip() for value in line[len("/crawl "):].split("|")]
            if len(fields) != 3 or not fields[0]:
                print("Use: /crawl HTTP(S) URL|MAX_PAGES|MAX_DEPTH")
                continue
            try:
                max_pages = int(fields[1])
                max_depth = int(fields[2])
                result = index.add_site(
                    fields[0], max_pages=max_pages, max_depth=max_depth)
                index.save(args.index)
                print(f"Crawl captured {len(result.captured)} new page(s); "
                      f"visited {len(result.visited)} URL(s).")
                for failed_url, reason in result.failures:
                    print(f"Could not capture {failed_url}: {reason}")
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                print(f"Could not crawl site: {error}")
            continue
        if line.startswith("/teach-context-fact "):
            fields = [value.strip() for value in
                      line[len("/teach-context-fact "):].split("|")]
            if len(fields) < 5 or not all(fields):
                print("Use: /teach-context-fact SUBJECT|RELATION|OBJECT|QUERY|KEY=VALUE[|KEY=VALUE...]")
                continue
            subject, relation, obj, query, *qualifier_fields = fields
            qualifiers = {}
            malformed = False
            for field in qualifier_fields:
                name, separator, value = field.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each fact qualifier must use KEY=VALUE.")
                continue
            subject_words = normalized_tokens(subject)
            object_words = normalized_tokens(obj)
            hit = None
            for candidate_hit in index.search(query, limit=5):
                words = normalized_tokens(candidate_hit.snippet)
                has_subject = any(words[i:i + len(subject_words)] == subject_words
                                  for i in range(len(words) - len(subject_words) + 1))
                has_object = any(words[i:i + len(object_words)] == object_words
                                 for i in range(len(words) - len(object_words) + 1))
                if subject_words and object_words and has_subject and has_object:
                    hit = candidate_hit
                    break
            if hit is None:
                print("No retrieved passage contained both fact entities.")
                continue
            try:
                fact = knowledge.add_fact_from_hit(
                    subject, relation, obj, index, hit, qualifiers=qualifiers)
                knowledge.save(args.knowledge)
                print(f"Stored cited fact: {fact.subject} — {fact.relation} → "
                      f"{fact.object} [context: "
                      f"{', '.join(f'{name}={value}' for name, value in fact.qualifiers)}].")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not teach contextual fact: {error}")
            continue
        if line.startswith("/teach-context-frame "):
            fields = [value.strip() for value in
                      line[len("/teach-context-frame "):].split("|")]
            if len(fields) < 7 or not all(fields):
                print("Use: /teach-context-frame SUBJECT|RELATION|OBJECT|QUERY|PREDICATE|SENTENCE|KEY=VALUE[|KEY=VALUE...]")
                continue
            subject, relation, obj, query, predicate, sentence, *pairs = fields
            qualifiers = {}
            malformed = False
            for pair in pairs:
                name, separator, value = pair.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each qualifier must use KEY=VALUE.")
                continue
            subject_words = normalized_tokens(subject)
            object_words = normalized_tokens(obj)
            hit = None
            for candidate_hit in index.search(query, limit=5):
                snippet_words = normalized_tokens(candidate_hit.snippet)
                has_subject = any(snippet_words[i:i + len(subject_words)] == subject_words
                                  for i in range(len(snippet_words) - len(subject_words) + 1))
                has_object = any(snippet_words[i:i + len(object_words)] == object_words
                                 for i in range(len(snippet_words) - len(object_words) + 1))
                if (subject_words and object_words and has_subject and has_object
                        and sentence in candidate_hit.snippet):
                    hit = candidate_hit
                    break
            if hit is None:
                print("No retrieved passage contained both entities and the exact training sentence.")
                continue
            try:
                knowledge.add_fact_from_hit(
                    subject, relation, obj, index, hit, qualifiers=qualifiers)
                licensed = knowledge.teach_context_fact_pattern_from_hit(
                    sentence, subject=subject, relation=relation, obj=obj,
                    qualifiers=qualifiers, research_index=index, hit=hit,
                    predicate_phrase=predicate)
                knowledge.save(args.knowledge)
                print("Context sentence frame licensed." if licensed else
                      "Context sentence example stored; another varied, cited example is required to license transfer.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not teach context sentence frame: {error}")
            continue
        if line.startswith("/teach-fact "):
            fields = [value.strip() for value in line[len("/teach-fact "):].split("|")]
            if len(fields) not in {6, 8} or not all(fields):
                print("Use: /teach-fact SUBJECT|RELATION|OBJECT|SOURCE QUERY|PREDICATE PHRASE|positive/negative[|SUBJECT SURFACE|OBJECT SURFACE]")
                continue
            subject, relation, obj, query, phrase, polarity_text = fields[:6]
            subject_phrase, object_phrase = fields[6:] if len(fields) == 8 else (None, None)
            if polarity_text.casefold() not in {"positive", "negative"}:
                print("Fact polarity must be positive or negative.")
                continue
            hit_sentence = None
            training_hit = None
            for hit in index.search(query, limit=5):
                sentence = _training_sentence(
                    hit, subject, obj, phrase, subject_phrase=subject_phrase,
                    object_phrase=object_phrase)
                if sentence is not None:
                    hit_sentence, training_hit = sentence, hit
                    break
            if training_hit is None or hit_sentence is None:
                print("No retrieved sentence uniquely contains the subject, object, and predicate phrase.")
                continue
            positive = polarity_text.casefold() == "positive"
            try:
                add = knowledge.add_fact_from_hit if positive else knowledge.add_negative_fact_from_hit
                add(subject, relation, obj, index, training_hit)
                licensed = knowledge.teach_fact_pattern_from_hit(
                    hit_sentence, subject=subject, relation=relation, obj=obj,
                    predicate_phrase=phrase, polarity=positive,
                    research_index=index, hit=training_hit,
                    subject_phrase=subject_phrase,
                    object_phrase=object_phrase)
                knowledge.save(args.knowledge)
                print(f"Stored cited {'positive' if positive else 'negative'} fact and sentence example.")
                print("Sentence pattern licensed." if licensed else
                      "More varied grounded examples are needed to license this pattern.")
                diagnostics = knowledge.fact_pattern_diagnostics(
                    hit_sentence, subject=subject, relation=relation, obj=obj,
                    polarity=positive, predicate_phrase=phrase,
                    subject_phrase=subject_phrase,
                    object_phrase=object_phrase)
                if diagnostics.get("status") in {"licensed", "unlicensed"}:
                    print("Frame support: "
                          f"{diagnostics['distinct_pairs']} distinct pair(s), "
                          f"{diagnostics['distinct_subjects']} subject(s), "
                          f"{diagnostics['distinct_objects']} object(s), "
                          f"{diagnostics['independent_sources']} source document(s).")
                    if diagnostics.get("reasons"):
                        print("Frame licensing: "
                              + "; ".join(diagnostics["reasons"]) + ".")
            except (OSError, ValueError) as error:
                print(f"Could not teach fact example: {error}")
            continue
        if line.startswith("/teach-question "):
            fields = [value.strip() for value in line[len("/teach-question "):].split("|")]
            if len(fields) != 5 or not all(fields):
                print("Use: /teach-question QUESTION|RELATION|subject/object|BOUND ENTITY|ANSWER")
                continue
            question, relation, answer_field, bound_entity, answer = fields
            if answer_field not in {"subject", "object"}:
                print("Question answer field must be subject or object.")
                continue
            try:
                licensed = knowledge.teach_question(
                    question, relation=relation, answer_field=answer_field,
                    bound_entity=bound_entity, answer=answer)
                knowledge.save(args.knowledge)
                print("Question frame licensed." if licensed else
                      "Question example stored; another distinct bound entity is needed to license the frame.")
            except (OSError, ValueError) as error:
                print(f"Could not teach question example: {error}")
            continue
        if line.startswith("/teach-question-pattern "):
            fields = [value.strip() for value in
                      line[len("/teach-question-pattern "):].split("|")]
            if len(fields) != 5 or not all(fields):
                print("Use: /teach-question-pattern QUESTION|RELATION|subject/object|BOUND ENTITY|ANSWER")
                continue
            question, relation, answer_field, bound_entity, answer = fields
            if answer_field not in {"subject", "object"}:
                print("Question answer field must be subject or object.")
                continue
            try:
                licensed = knowledge.teach_subject_pattern_question(
                    question, relation=relation, answer_field=answer_field,
                    bound_entity=bound_entity, answer=answer)
                knowledge.save(args.knowledge)
                print("Subject-pattern question frame licensed." if licensed else
                      "Question-pattern example stored; another distinct, "
                      "fact-backed entity is needed to license the frame.")
            except (OSError, ValueError) as error:
                print(f"Could not teach subject-pattern question: {error}")
            continue
        if _NATURAL_PREDICATE_FORM_REVIEW_RE.fullmatch(line):
            try:
                proposals = knowledge.propose_predicate_form_alignments(index)
                if not proposals:
                    print("No alternate predicate wording met the varied-fact "
                          "and independent-source gates.")
                for proposal in proposals:
                    print(f"CRMS> Predicate-form proposal: "
                          f"'{proposal['predicate_phrase']}' → "
                          f"'{proposal['relation']}' "
                          f"(facts={len(proposal['support'])}, "
                          f"sources={proposal['independent_documents']}).")
                    for row in proposal["support"]:
                        print(f"Evidence: {row['sentence']} "
                              f"[{row['source']}]")
                    print(f"Proposal ID: {proposal['proposal_id']}")
                if proposals:
                    print("These proposals are report-only. Accept one by its "
                          "exact ID to revalidate and save the alignment.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not propose predicate forms: {error}")
            continue
        natural_predicate_form_accept = (
            _NATURAL_PREDICATE_FORM_ACCEPT_RE.fullmatch(line))
        if natural_predicate_form_accept is not None:
            proposal_id = natural_predicate_form_accept.group(1).lower()
            try:
                accepted = knowledge.accept_predicate_form_alignment(
                    proposal_id, index)
                knowledge.save(args.knowledge)
                print(f"Accepted source-backed wording "
                      f"'{accepted['predicate_phrase']}' for relation "
                      f"'{accepted['relation']}' after revalidating its varied "
                      f"source examples; language evidence saved.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not accept predicate-form proposal: {error}")
            continue
        if _NATURAL_QUESTION_FRAME_REVIEW_RE.fullmatch(line):
            try:
                suggestions = (propose_analogical_question_frames(knowledge)
                              + propose_analogical_qualified_question_frames(knowledge)
                              + propose_analogical_multi_qualified_question_frames(knowledge)
                              + propose_active_role_alternation_frames(knowledge))
                if suggestions:
                    for proposal in suggestions:
                        lineage = proposal["lineage"]
                        qualifier = (
                            f"; qualifier={proposal['qualifier_name']}"
                            if "qualifier_name" in proposal else
                            "; qualifiers=" + ", ".join(proposal["qualifier_names"])
                            if "qualifier_names" in proposal else "")
                        print("CRMS> Question-frame proposal: "
                              f"{proposal['base_relation']} → "
                              f"{proposal['target_relation']}{qualifier}; "
                              f"answer={proposal['answer_field']}; "
                              f"training entities={proposal['training_entities']}; "
                              f"held-out entities={proposal['heldout_entities']}; "
                              f"source-separated="
                              f"{lineage['source_separation']}.")
                        print("Training sources: " + ", ".join(
                            lineage["training_source_documents"]))
                        print("Held-out sources: " + ", ".join(
                            lineage["holdout_source_documents"]))
                        print(f"Artifact ID: {proposal['artifact_id']}")
                    print("These proposals are report-only. Accept one by its "
                          "exact artifact ID to rerun the checks and retain it.")
                else:
                    print("No source-backed question-frame analogy passed the "
                          "current training and holdout checks.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not propose question frames: {error}")
            continue
        natural_question_frame_accept = (
            _NATURAL_QUESTION_FRAME_ACCEPT_RE.fullmatch(line))
        if natural_question_frame_accept is not None:
            artifact_id = natural_question_frame_accept.group(1).lower()
            try:
                if knowledge.accept_question_frame_proposal(artifact_id):
                    knowledge.save(args.knowledge)
                    print("Accepted the current source-separated question frame "
                          "after rerunning its held-out checks; lineage saved.")
                else:
                    print("That validated question frame is already active; "
                          "nothing changed.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not accept question-frame proposal: {error}")
            continue
        if _NATURAL_QUESTION_FRAME_TRAIN_RE.fullmatch(line):
            line = "/train-question-frames"
        if line == "/suggest-question-frames":
            try:
                suggestions = (propose_analogical_question_frames(knowledge)
                              + propose_analogical_qualified_question_frames(knowledge)
                              + propose_analogical_multi_qualified_question_frames(knowledge)
                              + propose_active_role_alternation_frames(knowledge))
                if suggestions:
                    print(json.dumps(suggestions, ensure_ascii=False, indent=2))
                else:
                    print("No source-backed question-frame analogy passed the "
                          "current training and holdout checks.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not propose question frames: {error}")
            continue
        if (line == "/suggest-corpus-frames"
                or line.startswith("/suggest-corpus-frames ")):
            try:
                value = line[len("/suggest-corpus-frames"):].strip()
                document_offset = int(value) if value else 0
                proposals = knowledge.propose_corpus_relation_frames(
                    index, document_offset=document_offset)
                if not proposals:
                    print("No repeated zero-frame relation pattern met the "
                          "distinct-entity and independent-source gates.")
                for number, proposal in enumerate(proposals, 1):
                    polarity = "positive" if proposal["polarity"] else "negative"
                    print(f"{number}. {proposal['relation']} "
                          f"({polarity}; examples={len(proposal['support'])}, "
                          f"subjects={proposal['distinct_subjects']}, "
                          f"objects={proposal['distinct_objects']}, "
                          f"sources={proposal['independent_documents']})")
                    print(f"   proposal ID: {proposal['proposal_id']}")
                    for row in proposal["support"]:
                        relation = row["predicate_phrase"]
                        print(f"   {row['subject']} — {relation} → "
                              f"{row['object']} [{row['document_id']}; "
                              f"{row['source']}]\n      {row['sentence']}")
                        morphology = row.get("morphology_support")
                        if isinstance(morphology, dict):
                            rule = morphology.get("rule", {})
                            rule_sources = ", ".join(
                                morphology.get("rule_sources", []))
                            lexical_sources = ", ".join(
                                item.get("document_id", "")
                                for item in morphology.get(
                                    "lexical_support", []))
                            print("      Morphology alignment: "
                                  f"{morphology.get('surface_form')} → "
                                  f"{morphology.get('canonical_form')} "
                                  f"({rule.get('context')} + "
                                  f"-{rule.get('ending')}; rule sources: "
                                  f"{rule_sources}; base-form sources: "
                                  f"{lexical_sources}).")
                if proposals:
                    print("Report only: no facts or frames changed. Review every "
                          "cited example, then accept with /accept-corpus-frame "
                          f"SELECTOR|{document_offset}.")
            except (OSError, TypeError, ValueError, AttributeError) as error:
                print(f"Could not discover corpus frames: {error}")
            continue
        if line.startswith("/accept-corpus-frame"):
            fields = line[len("/accept-corpus-frame"):].strip().split("|")
            try:
                if (not line.startswith("/accept-corpus-frame ")
                        or len(fields) not in {1, 2}
                        or not fields[0].strip()):
                    raise ValueError
                requested = fields[0].strip()
                document_offset = int(fields[1]) if len(fields) == 2 else 0
                proposals = knowledge.propose_corpus_relation_frames(
                    index, document_offset=document_offset)
                proposal = (proposals[int(requested) - 1]
                            if requested.isdigit()
                            and 1 <= int(requested) <= len(proposals)
                            else next((item for item in proposals
                                       if item["proposal_id"] == requested), None))
                if proposal is None:
                    raise ValueError("no current corpus-frame proposal matches that selection")
                accepted = knowledge.accept_corpus_relation_frame(
                    proposal["proposal_id"], index,
                    document_offset=document_offset)
                knowledge.save(args.knowledge)
                print(f"Accepted '{accepted['relation']}' from "
                      f"{len(accepted['support'])} reviewed source examples. "
                      "Cited facts and the reusable sentence frame were saved.")
            except (IndexError, OSError, TypeError, ValueError,
                    AttributeError) as error:
                print(f"Could not accept corpus frame: {error}")
                if len(fields) not in {1, 2}:
                    print("Use: /accept-corpus-frame "
                          "SELECTOR[|DOC_OFFSET]")
            continue
        if (line == "/suggest-corpus-alignments"
                or line.startswith("/suggest-corpus-alignments ")):
            try:
                value = line[len("/suggest-corpus-alignments"):].strip()
                document_offset = int(value) if value else 0
                proposals = knowledge.propose_corpus_predicate_alignments(
                    index, document_offset=document_offset)
                if not proposals:
                    print("No repeated corpus-only predicate alignment met the "
                          "shared-pair and independent-source gates.")
                for number, proposal in enumerate(proposals, 1):
                    print(f"{number}. '{proposal['predicate_phrase']}' → "
                          f"'{proposal['relation']}' "
                          f"(pairs={proposal['distinct_pairs']}, "
                          f"canonical sources={proposal['canonical_documents']}, "
                          f"alternate sources={proposal['alias_documents']})")
                    print(f"   proposal ID: {proposal['proposal_id']}")
                    for row in proposal["support"]:
                        print(f"   Pair: {row['subject']} ↔ {row['object']}")
                        print(f"      canonical: {row['canonical_sentence']} "
                              f"[{row['canonical_document_id']}; "
                              f"{row['canonical_source']}]")
                        print(f"      alternate: {row['alias_sentence']} "
                              f"[{row['alias_document_id']}; "
                              f"{row['alias_source']}]")
                if proposals:
                    print("Report only: no facts or language frames changed. "
                          "Review each cited pair, then accept with "
                          f"/accept-corpus-alignment SELECTOR|{document_offset}.")
            except (OSError, TypeError, ValueError, AttributeError) as error:
                print(f"Could not discover corpus predicate alignments: {error}")
            continue
        if line.startswith("/accept-corpus-alignment"):
            fields = line[len("/accept-corpus-alignment"):].strip().split("|")
            try:
                if (not line.startswith("/accept-corpus-alignment ")
                        or len(fields) not in {1, 2}
                        or not fields[0].strip()):
                    raise ValueError
                requested = fields[0].strip()
                document_offset = int(fields[1]) if len(fields) == 2 else 0
                proposals = knowledge.propose_corpus_predicate_alignments(
                    index, document_offset=document_offset)
                proposal = (proposals[int(requested) - 1]
                            if requested.isdigit()
                            and 1 <= int(requested) <= len(proposals)
                            else next((item for item in proposals
                                       if item["proposal_id"] == requested), None))
                if proposal is None:
                    raise ValueError("no current corpus alignment matches that selection")
                accepted = knowledge.accept_corpus_predicate_alignment(
                    proposal["proposal_id"], index,
                    document_offset=document_offset)
                knowledge.save(args.knowledge)
                print(f"Accepted '{accepted['predicate_phrase']}' as wording for "
                      f"'{accepted['relation']}' from "
                      f"{accepted['distinct_pairs']} reviewed entity pairs. "
                      "Cited facts and the reusable language pattern were saved.")
            except (IndexError, OSError, TypeError, ValueError,
                    AttributeError) as error:
                print(f"Could not accept corpus predicate alignment: {error}")
                if len(fields) not in {1, 2}:
                    print("Use: /accept-corpus-alignment "
                          "SELECTOR[|DOC_OFFSET]")
            continue
        if (line == "/suggest-predicate-forms"
                or line.startswith("/suggest-predicate-forms ")):
            try:
                value = line[len("/suggest-predicate-forms"):].strip()
                bounds = value.split("|") if value else []
                if len(bounds) > 2:
                    raise ValueError
                fact_offset = int(bounds[0]) if bounds and bounds[0] else 0
                maximum_hits = int(bounds[1]) if len(bounds) == 2 else 100
                proposals = knowledge.propose_predicate_form_alignments(
                    index, fact_offset=fact_offset,
                    maximum_hits_per_fact=maximum_hits)
                if not proposals:
                    print("No alternate predicate wording met the varied-fact "
                          "and independent-source gates.")
                for number, proposal in enumerate(proposals, 1):
                    print(f"{number}. {proposal['predicate_phrase']} → "
                          f"{proposal['relation']} "
                          f"(facts={len(proposal['support'])}, "
                          f"subjects={proposal['distinct_subjects']}, "
                          f"objects={proposal['distinct_objects']}, "
                          f"sources={proposal['independent_documents']})")
                    print(f"   proposal ID: {proposal['proposal_id']}")
                    for row in proposal["support"]:
                        print(f"   {row['subject']} — {proposal['predicate_phrase']} → "
                              f"{row['object']} [{row['document_id']}; "
                              f"{row['source']}]")
                if proposals:
                    print("Report only: no predicate form or fact changed. "
                          "Accept with /accept-predicate-form SELECTOR|"
                          f"{fact_offset}|{maximum_hits}.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not propose predicate forms: {error}")
            continue
        if line.startswith("/accept-predicate-form"):
            fields = line[len("/accept-predicate-form"):].strip().split("|")
            try:
                if (not line.startswith("/accept-predicate-form ")
                        or len(fields) not in {1, 3}
                        or not fields[0].strip()):
                    raise ValueError
                requested = fields[0].strip()
                fact_offset = int(fields[1]) if len(fields) == 3 else 0
                maximum_hits = int(fields[2]) if len(fields) == 3 else 100
                proposals = knowledge.propose_predicate_form_alignments(
                    index, fact_offset=fact_offset,
                    maximum_hits_per_fact=maximum_hits)
                proposal = (proposals[int(requested) - 1]
                            if requested.isdigit()
                            and 1 <= int(requested) <= len(proposals)
                            else next((item for item in proposals
                                       if item["proposal_id"] == requested), None))
                if proposal is None:
                    raise ValueError("no current predicate-form proposal matches that selection")
                accepted = knowledge.accept_predicate_form_alignment(
                    proposal["proposal_id"], index,
                    maximum_hits_per_fact=maximum_hits,
                    fact_offset=fact_offset)
                knowledge.save(args.knowledge)
                print(f"Accepted source-backed wording "
                      f"'{accepted['predicate_phrase']}' for relation "
                      f"'{accepted['relation']}' using {len(accepted['support'])} "
                      "reviewed examples. Language evidence saved.")
            except (IndexError, OSError, TypeError, ValueError) as error:
                print(f"Could not accept predicate form: {error}")
                if len(fields) not in {1, 3}:
                    print("Use: /accept-predicate-form "
                          "SELECTOR[|FACT_OFFSET|MAX_HITS_PER_FACT]")
            continue
        if line == "/suggest-question-role-rules":
            try:
                proposals = propose_active_role_alternation_frames(knowledge)
                if not proposals:
                    print("No source-separated active question role alternation "
                          "passed the training and held-out checks.")
                for proposal in proposals:
                    lineage = proposal["lineage"]
                    print("CRMS> Active question role alternation: "
                          f"{proposal['base_relation']}; "
                          f"target relation={proposal['target_relation']}; "
                          f"training relations={proposal['training_relations']}; "
                          f"held-out relations={proposal['heldout_relations']}; "
                          f"target entities={proposal['target_entities']}; "
                          f"source-separated={lineage['source_separation']}.")
                    print("Training sources: " + ", ".join(
                        lineage["training_source_documents"]))
                    print("Held-out sources: " + ", ".join(
                        lineage["holdout_source_documents"]))
                    print("Target sources: " + ", ".join(
                        lineage["target_source_documents"]))
                    print("Target held-out answers verified: "
                          + ", ".join(row["expected_answer"]
                                       for row in lineage["target_validation"]))
                    print(f"Artifact ID: {proposal['artifact_id']}")
                if proposals:
                    print("These grammar-rule proposals are report-only; no "
                          "question frame or rule was activated.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not propose question role rules: {error}")
            continue
        if line == "/train-question-frames":
            try:
                suggestions = (propose_analogical_question_frames(knowledge)
                              + propose_analogical_qualified_question_frames(knowledge)
                              + propose_analogical_multi_qualified_question_frames(knowledge)
                              + propose_active_role_alternation_frames(knowledge))
                accepted = [proposal["artifact_id"] for proposal in suggestions
                            if knowledge.accept_question_frame_proposal(
                                str(proposal["artifact_id"]))]
                if accepted:
                    knowledge.save(args.knowledge)
                    print(f"Accepted {len(accepted)} source-backed question frame(s) "
                          "after independent held-out checks; lineage saved.")
                else:
                    print("No new question frame passed the current mechanical "
                          "training and holdout checks.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not train question frames: {error}")
            continue
        if line.startswith("/teach-math "):
            fields = line[len("/teach-math "):].split("|")
            if len(fields) != 2 or not all(value.strip() for value in fields):
                print("Use: /teach-math QUESTION|ANSWER")
                continue
            try:
                learned_math = math_model.teach(fields[0].strip(), fields[1].strip())
                math_model.save(args.math)
                phrase = " ".join(learned_math.expression.operator_phrase)
                if learned_math.status == "licensed":
                    pending_math = None
                    print(f"Math phrase licensed as exact {learned_math.operation}: '{phrase}'.")
                else:
                    pending_math = (
                        (learned_math.expression.operator_phrase,
                         learned_math.contrastive_input)
                        if learned_math.contrastive_input is not None else None)
                    print(learned_math.request or
                          "Math example stored, but the phrase is not uniquely licensed yet.")
                _save_pending_math(args.math_session, args.math, pending_math)
            except (OSError, ValueError) as error:
                print(f"Could not teach math example: {error}")
            continue
        if line.startswith("/teach-unit-equivalence "):
            example = line[len("/teach-unit-equivalence "):]
            try:
                learned_unit = math_model.teach_unit_equivalence(example)
                math_model.save(args.math)
                if learned_unit.status == "licensed":
                    print("Unit ratio licensed from two consistent examples: "
                          + str(learned_unit.unit) + ".")
                else:
                    print("Unit example stored; provide a second distinct quantity "
                          "pair to license conversion.")
            except (OSError, ValueError) as error:
                print(f"Could not teach unit equivalence: {error}")
            continue
        if line.startswith("/teach-translation "):
            fields = [value.strip() for value in
                      line[len("/teach-translation "):].split("|")]
            if len(fields) != 9 or not all(fields):
                print("Use: /teach-translation SL|TL|REGISTER|SRC TEMPLATE|TGT TEMPLATE|SRC1|TGT1|SRC2|TGT2")
                continue
            try:
                learned_translation = translation_model.teach(
                    fields[0], fields[1], fields[2], fields[3], fields[4],
                    [(fields[5], fields[6]), (fields[7], fields[8])])
                translation_model.save(args.translations)
                print("Translation frame licensed for "
                      f"{fields[0]} to {fields[1]} ({fields[2]} register), "
                      "with two aligned examples.")
            except (OSError, ValueError) as error:
                print(f"Could not teach translation frame: {error}")
            continue
        if line.startswith("/teach-about "):
            fields = [value.strip() for value in
                      line[len("/teach-about "):].split("|")]
            if len(fields) != 2 or not all(fields):
                print("Use: /teach-about REQUEST|STORED ENTITY")
                continue
            question, entity = fields
            try:
                licensed = knowledge.teach_about_frame(question, entity=entity)
                knowledge.save(args.knowledge)
                print("About-request frame licensed." if licensed else
                      "Example stored; another distinct stored entity is needed to license the frame.")
            except (OSError, ValueError) as error:
                print(f"Could not teach about-request frame: {error}")
            continue
        if line.startswith("/teach-qualified-question "):
            fields = [value.strip() for value in
                      line[len("/teach-qualified-question "):].split("|")]
            if len(fields) < 6 or not all(fields):
                print("Use: /teach-qualified-question QUESTION|RELATION|subject/object|BOUND ENTITY|ANSWER|KEY=VALUE[|KEY=VALUE...]")
                continue
            question, relation, answer_field, bound_entity, answer = fields[:5]
            qualifiers = {}
            malformed = False
            for qualifier_text in fields[5:]:
                name, separator, value = qualifier_text.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each qualifier must use KEY=VALUE.")
                continue
            try:
                licensed = knowledge.teach_qualified_question(
                    question, relation=relation, answer_field=answer_field,
                    bound_entity=bound_entity, answer=answer,
                    qualifier=qualifiers)
                knowledge.save(args.knowledge)
                print("Qualified question frame licensed." if licensed else
                      "Example stored; vary the entity and every qualifier value to license the frame.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not teach qualified question: {error}")
            continue
        if line.startswith("/teach-alias "):
            fields = [value.strip() for value in line[len("/teach-alias "):].split("|")]
            if len(fields) != 3 or not all(fields):
                print("Use: /teach-alias ALIAS|CANONICAL ENTITY|SOURCE QUERY")
                continue
            alias, entity, query = fields
            hits = index.search(query, limit=5)
            taught = False
            failure = None
            for hit in hits:
                try:
                    knowledge.teach_entity_alias_from_hit(
                        alias, entity, research_index=index, hit=hit)
                except ValueError as error:
                    failure = error
                    continue
                try:
                    knowledge.save(args.knowledge)
                except OSError as error:
                    print(f"Alias was learned but could not be saved: {error}")
                    break
                print(f"Learned cited alias: {alias} → {entity}.")
                taught = True
                break
            if not taught:
                if failure:
                    print(f"Could not teach alias: {failure}")
                else:
                    print("No retrieved passage contained both the alias and a stored canonical entity.")
            continue
        if line.startswith("/forget-alias "):
            fields = [value.strip() for value in
                      line[len("/forget-alias "):].split("|", 1)]
            if not fields or not all(fields):
                print("Use: /forget-alias ALIAS[|SOURCE]")
                continue
            alias = fields[0]
            if len(fields) == 2:
                removed = knowledge.remove_entity_alias_source(alias, fields[1])
                description = f"source {fields[1]} from alias {alias}"
            else:
                removed = knowledge.forget_entity_alias(alias)
                description = f"entity alias: {alias}"
            if removed:
                knowledge.save(args.knowledge)
                print(f"Forgot {description}.")
            else:
                print(f"No matching learned {description} found.")
            continue
        if line.startswith("/ask-context "):
            fields = [value.strip() for value in
                      line[len("/ask-context "):].split("|")]
            if len(fields) < 2 or not all(fields):
                print("Use: /ask-context QUESTION|KEY=VALUE[|KEY=VALUE...]")
                continue
            question, *qualifier_fields = fields
            qualifiers = {}
            malformed = False
            for field in qualifier_fields:
                name, separator, value = field.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each fact qualifier must use KEY=VALUE.")
                continue
            try:
                result, response = knowledge.respond(
                    question, qualifiers=qualifiers)
                print(f"CRMS> {response}")
                if (auto_practice_questions and result.status == "answered"
                        and result.inference_proofs):
                    _answer, retained = knowledge.practice_question(
                        question, qualifiers=qualifiers)
                    if retained:
                        knowledge.save(args.knowledge)
                        print("Auto-practice stored the verified inference as a "
                              "separate derived case.")
                    else:
                        print("Auto-practice skipped: the answer did not resolve "
                              "to one unique, proof-backed conclusion.")
            except (TypeError, ValueError) as error:
                print(f"Could not answer with that context: {error}")
            continue
        if line.startswith("/ask-path-between "):
            fields = [value.strip() for value in
                      line[len("/ask-path-between "):].split("|")]
            if len(fields) < 3 or not all(fields):
                print("Use: /ask-path-between START|TARGET|RELATION1>RELATION2[|KEY=VALUE...]")
                continue
            start, target, path_text, *qualifier_fields = fields
            relations = [value.strip() for value in path_text.split(">")]
            qualifiers = {}
            malformed = False
            for field in qualifier_fields:
                name, separator, value = field.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each path qualifier must use KEY=VALUE.")
                continue
            try:
                result = knowledge.ask_path_between(
                    start, target, relations, qualifiers=qualifiers)
                print(f"CRMS> {knowledge.render(result)}")
            except (TypeError, ValueError) as error:
                print(f"Could not check that path: {error}")
            continue
        natural_typed_rule_teach = (
            _NATURAL_TYPED_INFERENCE_RULE_TEACH_RE.fullmatch(line))
        natural_rule_teach = _NATURAL_INFERENCE_RULE_TEACH_RE.fullmatch(line)
        if natural_typed_rule_teach is not None or natural_rule_teach is not None:
            match = natural_typed_rule_teach or natural_rule_teach
            try:
                common = (
                    match.group("rule_id").strip(),
                    match.group("first").strip(),
                    match.group("second").strip(),
                )
                if natural_typed_rule_teach is not None:
                    rule = knowledge.add_inference_rule(
                        *common, match.group("conclusion").strip(),
                        third_relation=match.group("third").strip(),
                        middle_kind=match.group("middle_kind").strip(),
                        second_middle_kind=match.group(
                            "second_middle_kind").strip())
                else:
                    rule = knowledge.add_inference_rule(
                        *common, match.group("conclusion").strip())
                knowledge.save(args.knowledge)
                premise_relations = [rule.first_relation, rule.second_relation]
                if rule.third_relation is not None:
                    premise_relations.append(rule.third_relation)
                typed_text = (
                    f" with middle kinds {rule.middle_kind} and "
                    f"{rule.second_middle_kind}"
                    if rule.third_relation is not None else "")
                print(f"Stored explicit rule {rule.rule_id}: "
                      f"{' then '.join(premise_relations)} entails "
                      f"{rule.conclusion_relation}{typed_text}.")
            except (TypeError, ValueError, OSError) as error:
                print(f"Could not teach inference rule: {error}")
            continue
        if line.startswith("/teach-inference-rule "):
            fields = [value.strip() for value in
                      line[len("/teach-inference-rule "):].split("|")]
            binary = (len(fields) in {4, 5} and all(fields[:4])
                      and (len(fields) == 4
                           or fields[4].startswith("middle_kind=")))
            ternary = (len(fields) == 7 and all(fields[:5])
                       and fields[5].startswith("middle_kind=")
                       and fields[6].startswith("second_middle_kind="))
            if not (binary or ternary):
                print("Use: /teach-inference-rule ID|R1|R2|CONCLUSION[|middle_kind=KIND], or ID|R1|R2|R3|CONCLUSION|middle_kind=K1|second_middle_kind=K2")
                continue
            try:
                if ternary:
                    middle_kind = fields[5].partition("=")[2].strip()
                    second_middle_kind = fields[6].partition("=")[2].strip()
                    if not middle_kind or not second_middle_kind:
                        raise ValueError("both middle kinds must be non-empty")
                    rule = knowledge.add_inference_rule(
                        fields[0], fields[1], fields[2], fields[4],
                        third_relation=fields[3], middle_kind=middle_kind,
                        second_middle_kind=second_middle_kind)
                else:
                    middle_kind = fields[4].partition("=")[2].strip() if len(fields) == 5 else None
                    if len(fields) == 5 and not middle_kind:
                        raise ValueError("middle_kind must name a non-empty kind")
                    rule = knowledge.add_inference_rule(
                        *fields[:4], middle_kind=middle_kind)
                knowledge.save(args.knowledge)
                premise_relations = [rule.first_relation, rule.second_relation]
                if rule.third_relation is not None:
                    premise_relations.append(rule.third_relation)
                if rule.third_relation is not None:
                    typed_text = (" with middle kinds: " + ", ".join(
                        kind for kind in
                        (rule.middle_kind, rule.second_middle_kind) if kind))
                elif rule.middle_kind:
                    typed_text = f" with middle kind {rule.middle_kind}"
                else:
                    typed_text = ""
                print(f"Stored explicit rule {rule.rule_id}: "
                      f"{' then '.join(premise_relations)} "
                      f"entails {rule.conclusion_relation}{typed_text}.")
            except (TypeError, ValueError) as error:
                print(f"Could not store inference rule: {error}")
            continue
        if line.startswith("/teach-relation-type "):
            fields = [value.strip() for value in
                      line[len("/teach-relation-type "):].split("|")]
            if len(fields) != 3 or not all(fields):
                print("Use: /teach-relation-type RELATION|transitive/symmetric/irreflexive/asymmetric/functional/closed-world|SOURCE")
                continue
            try:
                fact = knowledge.add_relation_type(*fields)
                knowledge.save(args.knowledge)
                print(f"Stored relation type: {fact.subject} is {fact.object} "
                      f"[source: {', '.join(fact.sources)}].")
            except (TypeError, ValueError) as error:
                print(f"Could not store relation type: {error}")
            continue
        natural_rule_review = _NATURAL_INFERENCE_RULE_REVIEW_RE.fullmatch(line)
        if natural_rule_review is not None:
            source_prefix = natural_rule_review.group(1).strip()
            if (len(source_prefix) >= 2
                    and (source_prefix[0], source_prefix[-1]) in {
                        ('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")}):
                source_prefix = source_prefix[1:-1].strip()
            try:
                reviews = knowledge.review_inference_rules(source_prefix)
                print(f"CRMS> {knowledge.render_rule_reviews(reviews)}")
            except (TypeError, ValueError) as error:
                print(f"Could not review inference-rule candidates: {error}")
            continue
        natural_rule_accept = _NATURAL_INFERENCE_RULE_ACCEPT_RE.fullmatch(line)
        if natural_rule_accept is not None:
            try:
                result = knowledge.accept_inference_rule_candidate(
                    int(natural_rule_accept.group("number")),
                    natural_rule_accept.group("rule_id").strip(),
                    natural_rule_accept.group("prefix").strip(),
                    max_arity=int(natural_rule_accept.group("arity") or "2"))
                if result.accepted:
                    knowledge.save(args.knowledge)
                    assert result.rule is not None
                    validation = result.review.validation if result.review else None
                    checked = len(validation.positive_examples) if validation else 0
                    sources = len(validation.independent_sources) if validation else 0
                    premises = [result.rule.first_relation,
                                result.rule.second_relation]
                    if result.rule.third_relation is not None:
                        premises.append(result.rule.third_relation)
                    typed = (f" (middle kinds: {result.rule.middle_kind}, "
                             f"{result.rule.second_middle_kind})"
                             if result.rule.third_relation is not None else "")
                    print(f"Accepted validated rule {result.rule.rule_id}: "
                          f"{' then '.join(premises)} entails "
                          f"{result.rule.conclusion_relation}{typed} "
                          f"({checked} held-out positive examples from "
                          f"{sources} independent sources).")
                else:
                    print(f"Rule not accepted: {result.request}")
                    if result.review:
                        print(knowledge.render_rule_reviews(
                            RuleReviewResult(True, (result.review,), 0)))
            except (TypeError, ValueError) as error:
                print(f"Could not accept inference rule: {error}")
            continue
        if line == "/suggest-inference-rules" or line.startswith("/suggest-inference-rules "):
            fields = [value.strip() for value in
                      line[len("/suggest-inference-rules"):].strip().split("|")]
            try:
                max_arity = 2
                if fields and fields[-1].startswith("arity="):
                    max_arity = int(fields.pop().partition("=")[2])
                if max_arity not in {2, 3}:
                    raise ValueError("arity must be 2 or 3")
                if fields == [""] or not fields:
                    discovery = knowledge.discover_inference_rules(max_arity=max_arity)
                    print(f"CRMS> {knowledge.render_rule_discovery(discovery)}")
                elif len(fields) == 1:
                    discovery = knowledge.discover_inference_rules(
                        min_support=int(fields[0]), max_arity=max_arity)
                    print(f"CRMS> {knowledge.render_rule_discovery(discovery)}")
                elif len(fields) == 2 and fields[1]:
                    reviews = knowledge.review_inference_rules(
                        fields[1], min_support=int(fields[0]),
                        max_arity=max_arity)
                    print(f"CRMS> {knowledge.render_rule_reviews(reviews)}")
                else:
                    print("Use: /suggest-inference-rules [MIN_SUPPORT|HOLDOUT_SOURCE_PREFIX][|arity=3]")
            except (TypeError, ValueError) as error:
                print(f"Could not discover inference-rule candidates: {error}")
            continue
        if line.startswith("/accept-inference-rule "):
            fields = [value.strip() for value in
                      line[len("/accept-inference-rule "):].split("|")]
            max_arity = 2
            if fields and fields[-1].startswith("arity="):
                try:
                    max_arity = int(fields.pop().partition("=")[2])
                except ValueError:
                    max_arity = 0
            if len(fields) != 3 or not all(fields) or max_arity not in {2, 3}:
                print("Use: /accept-inference-rule N|RULE_ID|HOLDOUT_SOURCE_PREFIX[|arity=3]")
                continue
            try:
                result = knowledge.accept_inference_rule_candidate(
                    int(fields[0]), fields[1], fields[2], max_arity=max_arity)
                if result.accepted:
                    knowledge.save(args.knowledge)
                    assert result.rule is not None
                    validation = result.review.validation if result.review else None
                    checked = len(validation.positive_examples) if validation else 0
                    sources = len(validation.independent_sources) if validation else 0
                    premises = [result.rule.first_relation,
                                result.rule.second_relation]
                    if result.rule.third_relation is not None:
                        premises.append(result.rule.third_relation)
                    typed = (f" (middle kinds: {result.rule.middle_kind}, "
                             f"{result.rule.second_middle_kind})"
                             if result.rule.third_relation is not None else "")
                    print(f"Accepted validated rule {result.rule.rule_id}: "
                          f"{' then '.join(premises)} entails "
                          f"{result.rule.conclusion_relation}{typed} "
                          f"({checked} held-out positive examples from "
                          f"{sources} independent sources).")
                else:
                    print(f"Rule not accepted: {result.request}")
                    if result.review:
                        print(knowledge.render_rule_reviews(
                            RuleReviewResult(True, (result.review,), 0)))
            except (TypeError, ValueError) as error:
                print(f"Could not accept inference rule: {error}")
            continue
        if line.startswith("/infer-relation "):
            fields = [value.strip() for value in
                      line[len("/infer-relation "):].split("|")]
            if (len(fields) not in {3, 4} or not all(fields[:3])
                    or (len(fields) == 4 and not fields[3])):
                print("Use: /infer-relation SUBJECT|RELATION|OBJECT[|name=value,...]")
                continue
            try:
                qualifiers = {}
                if len(fields) == 4:
                    for item in fields[3].split(","):
                        name, separator, value = item.partition("=")
                        if not separator or not name.strip() or not value.strip():
                            raise ValueError("context must use name=value pairs")
                        qualifiers[name.strip()] = value.strip()
                result = knowledge.infer_relation(
                    *fields[:3], qualifiers=qualifiers)
                rendered = knowledge.render_inference(result)
                if qualifiers:
                    rendered += " [context: " + ", ".join(
                        f"{name}={value}" for name, value in sorted(qualifiers.items())) + "]"
                print(f"CRMS> {rendered}")
            except (TypeError, ValueError) as error:
                print(f"Could not check that inference: {error}")
            continue
        if line.startswith("/abduce "):
            fields = [value.strip() for value in line[len("/abduce "):].split("|")]
            if (len(fields) not in {3, 4} or not all(fields[:3])
                    or (len(fields) == 4 and not fields[3])):
                print("Use: /abduce SUBJECT|RELATION|OBJECT[|name=value,...]")
                continue
            if not pending_candidates:
                print("There are no pending fact candidates from a research query.")
                continue
            try:
                qualifiers = {}
                if len(fields) == 4:
                    for item in fields[3].split(","):
                        name, separator, value = item.partition("=")
                        if not separator or not name.strip() or not value.strip():
                            raise ValueError("context must use name=value pairs")
                        qualifiers[name.strip()] = value.strip()
                result = knowledge.abduce_relation(
                    *fields[:3], candidates=pending_candidates,
                    research_index=index, qualifiers=qualifiers)
                if result.status == "already_provable":
                    print(f"CRMS> {result.request}")
                    continue
                if result.status == "contested":
                    print(f"CRMS> {result.request}")
                    continue
                if not result.hypotheses:
                    message = ("No hypothesis found within the completed bounded search."
                               if result.complete else
                               "Abduction search incomplete; no conclusion can be drawn.")
                    print(f"CRMS> {message}"
                          + (f" {result.request}" if result.request else ""))
                    continue
                prefix = ("Abduction search incomplete; these are proof witnesses, "
                          "not guaranteed minimal." if not result.complete else
                          "Minimal cited hypotheses:")
                print(f"CRMS> {prefix}")
                for number, hypothesis in enumerate(result.hypotheses, 1):
                    print(f"Hypothesis {number} "
                          f"({'minimal' if hypothesis.minimal else 'minimality unverified'}):")
                    for candidate in hypothesis.candidates:
                        polarity = "supports" if candidate.polarity else "opposes"
                        print(f"  {candidate.subject} — {candidate.relation} → "
                              f"{candidate.object} ({polarity})")
                        print(f"  Citation: {candidate.source}\n  {candidate.sentence}")
                    print(knowledge.render_inference(hypothesis.result))
                print(f"Checked {result.subsets_checked} candidate subsets using "
                      f"{result.expansions} proof-search expansions. Nothing was accepted.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not search pending hypotheses: {error}")
            continue
        if line.startswith("/practice-inference "):
            fields = [value.strip() for value in
                      line[len("/practice-inference "):].split("|")]
            if (len(fields) not in {3, 4} or not all(fields[:3])
                    or (len(fields) == 4 and not fields[3])):
                print("Use: /practice-inference SUBJECT|RELATION|OBJECT[|name=value,...]")
                continue
            try:
                qualifiers = {}
                if len(fields) == 4:
                    for item in fields[3].split(","):
                        name, separator, value = item.partition("=")
                        if not separator or not name.strip() or not value.strip():
                            raise ValueError("context must use name=value pairs")
                        qualifiers[name.strip()] = value.strip()
                result = knowledge.practice_relation(
                    *fields[:3], qualifiers=qualifiers)
                rendered = knowledge.render_inference(result)
                if qualifiers:
                    rendered += " [context: " + ", ".join(
                        f"{name}={value}" for name, value in sorted(qualifiers.items())) + "]"
                print(f"CRMS> {rendered}")
                if result.status == "answered" and result.complete:
                    if any(proof.get("kind") in {"rule", "schema"}
                           for proof in result.proofs):
                        knowledge.save(args.knowledge)
                        print("Verified derivation stored as a separate derived case.")
                    else:
                        print("No derived case stored: this result is directly taught.")
            except (TypeError, ValueError) as error:
                print(f"Could not practice that inference: {error}")
            continue
        if line.startswith("/practice-question "):
            question = line[len("/practice-question "):].strip()
            if not question:
                print("Use: /practice-question QUESTION")
                continue
            try:
                result, retained = knowledge.practice_question(question)
                print(f"CRMS> {knowledge.render(result)}")
                if retained:
                    knowledge.save(args.knowledge)
                    print("Verified answer stored as a separate derived case.")
                else:
                    print("No derived case stored: the answer was not one unique, "
                          "proof-backed inference.")
            except (TypeError, ValueError) as error:
                print(f"Could not practice that question: {error}")
            continue
        natural_practice = _natural_practice_request(line)
        if natural_practice is not None:
            question, refers_to_previous = natural_practice
            if refers_to_previous:
                question = dialogue.last_question or ""
            if not question:
                print("Ask a question first, or say 'practice the answer to QUESTION'.")
                continue
            try:
                result, retained = knowledge.practice_question(question)
                print(f"CRMS> {knowledge.render(result)}")
                if retained:
                    knowledge.save(args.knowledge)
                    print("Verified answer stored as a separate derived case.")
                else:
                    print("No derived case stored: the answer was not one unique, "
                          "proof-backed inference.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Could not practice that answer: {error}")
            continue
        natural_auto_practice = _NATURAL_AUTO_PRACTICE_RE.fullmatch(line)
        if natural_auto_practice is not None:
            action = natural_auto_practice.group(1) or (
                "on" if natural_auto_practice.group(2).casefold() == "enable"
                else "off")
            auto_practice_questions = action.casefold() == "on"
            if auto_practice_questions:
                print("Auto-practice enabled for this chat session. Only unique, "
                      "proof-backed inferred answers can be retained.")
            else:
                print("Auto-practice disabled for this chat session.")
            continue
        if line.startswith("/auto-practice"):
            fields = line.split()
            if len(fields) != 2 or fields[0] != "/auto-practice" \
                    or fields[1].casefold() not in {"on", "off"}:
                print("Use: /auto-practice on|off")
                continue
            auto_practice_questions = fields[1].casefold() == "on"
            if auto_practice_questions:
                print("Auto-practice enabled for this chat session. Only unique, "
                      "proof-backed inferred answers can be retained.")
            else:
                print("Auto-practice disabled for this chat session.")
            continue
        if (_NATURAL_DERIVED_CASES_RE.fullmatch(line)
                or line == "/derived-cases"):
            for formatted_case in _format_derived_cases(
                    knowledge.derived_cases()):
                print(formatted_case)
            continue
        if line.startswith("/counterfactual-path-without-source "):
            fields = [value.strip() for value in line[
                len("/counterfactual-path-without-source "):].split("|")]
            if len(fields) < 4 or not all(fields):
                print("Use: /counterfactual-path-without-source START|TARGET|RELATION1>RELATION2|SOURCE[|KEY=VALUE...]")
                continue
            start, target, path_text, source, *qualifier_fields = fields
            relations = [value.strip() for value in path_text.split(">")]
            qualifiers = {}
            malformed = False
            for field in qualifier_fields:
                name, separator, value = field.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each path qualifier must use KEY=VALUE.")
                continue
            try:
                result = knowledge.counterfactual_path_without_source(
                    start, target, relations, source=source,
                    qualifiers=qualifiers)
                if result.status == "supported":
                    summary = f"The path remains supported without source {source}."
                elif result.status == "unsupported":
                    summary = f"The path is no longer supported without source {source}."
                elif result.status == "ambiguous":
                    summary = f"The path is ambiguous without source {source}."
                elif result.status == "source_not_in_proof":
                    summary = f"Source {source} does not support the baseline proof."
                else:
                    summary = "The baseline path is not proven, so no source counterfactual was run."
                print(f"CRMS> {summary}")
                if result.counterfactual is not None:
                    print(f"CRMS> {knowledge.render(result.counterfactual)}")
                elif result.baseline.status != "answered":
                    print(f"CRMS> {knowledge.render(result.baseline)}")
            except (TypeError, ValueError) as error:
                print(f"Could not evaluate that source counterfactual: {error}")
            continue
        if line.startswith("/teach-polar "):
            fields = [value.strip() for value in line[len("/teach-polar "):].split("|")]
            if len(fields) != 5 or not all(fields):
                print("Use: /teach-polar QUESTION|SUBJECT|RELATION|OBJECT|yes/no")
                continue
            question, subject, relation, obj, answer_text = fields
            if answer_text.casefold() not in {"yes", "no"}:
                print("Polar answer must be yes or no.")
                continue
            try:
                licensed = knowledge.teach_polar_question(
                    question, subject=subject, relation=relation, obj=obj,
                    answer=answer_text.casefold() == "yes")
                knowledge.save(args.knowledge)
                print("Yes/no question frame licensed." if licensed else
                      "Example stored; another distinct subject/object pair is needed to license the frame.")
            except (OSError, ValueError) as error:
                print(f"Could not teach yes/no question: {error}")
            continue
        if line.startswith("/teach-path-question "):
            fields = [value.strip() for value in
                      line[len("/teach-path-question "):].split("|")]
            if len(fields) != 4 or not all(fields):
                print("Use: /teach-path-question QUESTION|RELATION1>RELATION2|BOUND ENTITY|ANSWER")
                continue
            question, path_text, bound_entity, answer = fields
            relations = [value.strip() for value in path_text.split(">")]
            try:
                licensed = knowledge.teach_path_question(
                    question, relations=relations,
                    bound_entity=bound_entity, answer=answer)
                knowledge.save(args.knowledge)
                print("Path question frame licensed." if licensed else
                      "Example stored; another distinct bound entity is needed to license the frame.")
            except (OSError, ValueError) as error:
                print(f"Could not teach path question: {error}")
            continue
        if line.startswith("/teach-counterfactual-source-question "):
            fields = [value.strip() for value in line[
                len("/teach-counterfactual-source-question "):].split("|")]
            if len(fields) < 5 or not all(fields):
                print("Use: /teach-counterfactual-source-question QUESTION|RELATION1>RELATION2|START|TARGET|SOURCE[|KEY=VALUE...]")
                continue
            question, path_text, start, target, source, *qualifier_fields = fields
            relations = [value.strip() for value in path_text.split(">")]
            qualifiers = {}
            malformed = False
            for field in qualifier_fields:
                name, separator, value = field.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each counterfactual qualifier must use KEY=VALUE.")
                continue
            try:
                licensed = knowledge.teach_counterfactual_source_question(
                    question, start=start, target=target,
                    relations=relations, source=source,
                    qualifiers=qualifiers)
                knowledge.save(args.knowledge)
                print("Counterfactual source frame licensed." if licensed else
                      "Example stored; another distinct cited source is needed to license the frame.")
            except (OSError, ValueError) as error:
                print(f"Could not teach counterfactual source frame: {error}")
            continue
        if line.startswith("/teach-counterfactual-path-question "):
            fields = [value.strip() for value in line[
                len("/teach-counterfactual-path-question "):].split("|")]
            if len(fields) < 5 or not all(fields):
                print("Use: /teach-counterfactual-path-question QUESTION|RELATION1>RELATION2|START|TARGET|SOURCE[|KEY=VALUE...]")
                continue
            question, path_text, start, target, source, *qualifier_fields = fields
            relations = [value.strip() for value in path_text.split(">")]
            qualifiers = {}
            malformed = False
            for field in qualifier_fields:
                name, separator, value = field.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each counterfactual qualifier must use KEY=VALUE.")
                continue
            try:
                licensed = knowledge.teach_counterfactual_path_question(
                    question, start=start, target=target,
                    relations=relations, source=source,
                    qualifiers=qualifiers)
                knowledge.save(args.knowledge)
                print("Counterfactual path frame licensed." if licensed else
                      "Example stored; another grounded example varying start, target, and source is needed.")
            except (OSError, ValueError) as error:
                print(f"Could not teach counterfactual path frame: {error}")
            continue
        if line.startswith("/write-fact "):
            fields = [value.strip() for value in line[len("/write-fact "):].split("|")]
            if len(fields) != 4 or not all(fields):
                print("Use: /write-fact SUBJECT|RELATION|OBJECT|positive/negative")
                continue
            subject, relation, obj, polarity_text = fields
            if polarity_text.casefold() not in {"positive", "negative"}:
                print("Fact polarity must be positive or negative.")
                continue
            sentences = knowledge.write_fact(
                subject, relation, obj, polarity=polarity_text.casefold() == "positive")
            if sentences:
                for sentence in sentences:
                    print(f"CRMS> {sentence}")
            else:
                print("No stored fact has a licensed sentence frame yet.")
            continue
        if line.startswith("/write-about "):
            fields = [value.strip() for value in
                      line[len("/write-about "):].split("|")]
            if not fields[0]:
                print("Use: /write-about ENTITY[|KEY=VALUE...]")
                continue
            qualifiers = {}
            malformed = False
            for field in fields[1:]:
                name, separator, value = field.partition("=")
                if not separator or not name.strip() or not value.strip():
                    malformed = True
                    break
                qualifiers[name.strip()] = value.strip()
            if malformed:
                print("Each writing qualifier must use KEY=VALUE.")
                continue
            try:
                result = knowledge.write_about(fields[0], qualifiers=qualifiers)
                print(f"CRMS> {result.text}")
            except (TypeError, ValueError) as error:
                print(f"Could not write about {fields[0]}: {error}")
            continue
        if line == "/facts":
            facts = [(True, fact) for fact in knowledge.facts()]
            facts.extend((False, fact) for fact in knowledge.negative_facts())
            if not facts:
                print("No facts are stored yet.")
            for positive, fact in facts:
                polarity = "FACT" if positive else "NOT"
                qualifiers = ("; context: " + ", ".join(
                    f"{name}={value}" for name, value in fact.qualifiers)
                    if fact.qualifiers else "")
                print(f"{polarity}: {fact.subject} — {fact.relation} → "
                      f"{fact.object}{qualifiers} "
                      f"[sources: {', '.join(fact.sources)}]")
            continue
        if line == "/aliases":
            aliases = knowledge.entity_aliases()
            if not aliases:
                print("No entity aliases are learned yet.")
            for alias in aliases:
                print(f"{alias['alias']} → {alias['entity']} "
                      f"[sources: {', '.join(alias['sources'])}]")
            continue
        if line == "/alias-rules":
            plural_rules = knowledge.entity_plural_rules()
            if not plural_rules:
                print("No productive entity plural rules are licensed yet.")
            for rule in plural_rules:
                roles = ", ".join(
                    f"{item['relation']} {item['role']}"
                    for item in rule["shared_roles"])
                support = "; ".join(
                    f"{item['entity']} → {', '.join(item['surface_forms'])} "
                    f"[sources: {', '.join(item['sources'])}]"
                    for item in rule["support"])
                forms = "; ".join(
                    f"{item['entity']} → {item['plural']} "
                    f"[role sources: {', '.join(item['role_sources'])}]"
                    for item in rule["forms"])
                print(f"Plural rule [{rule['context']}; role {roles}]: {support}")
                print(f"  Active query forms: {forms}")
            continue
        if line == "/sources" or line.startswith("/sources "):
            parts = line.split()
            try:
                if len(parts) > 2:
                    raise ValueError
                page = int(parts[1]) if len(parts) == 2 else 1
                if page < 1:
                    raise ValueError
            except ValueError:
                print("Use /sources or /sources PAGE with a positive page number.")
                continue
            source_count, source_bytes = index.corpus_stats()
            page_size = 50
            page_count = (source_count + page_size - 1) // page_size
            if source_count == 0:
                print("No sources are indexed yet.")
                continue
            if page > page_count:
                print(f"Only {page_count} source page(s) are available.")
                continue
            print(f"Local corpus: {source_count} source document(s), "
                  f"{source_bytes / (1024 * 1024):.2f} MiB of source text; "
                  f"page {page}/{page_count}.")
            documents = index.source_list(
                limit=page_size, offset=(page - 1) * page_size)
            for document_id, title, location_value in documents:
                location = f" ({location_value})" if location_value else ""
                print(f"{document_id}: {title}{location}")
            continue
        if line.startswith("/teach-rule "):
            fields = [value.strip() for value in line[len("/teach-rule "):].split("|")]
            if len(fields) != 3 or not fields[0]:
                print("Use: /teach-rule INSTRUCTION|INPUT INTEGER CSV|OUTPUT INTEGER CSV")
                continue
            try:
                inputs = _parse_integer_list(fields[1], allow_empty=True)
                outputs = _parse_integer_list(fields[2], allow_empty=True)
                learned = rules.teach(fields[0], [(inputs, outputs)])
                rules.save(args.rules)
                _print_rule_learning_result(learned)
            except ValueError as error:
                print(f"Could not teach rule: {error}")
            continue
        natural_rule_retry = _NATURAL_RULE_RETRY_RE.fullmatch(line)
        if natural_rule_retry is not None:
            instruction = natural_rule_retry.group(1).strip().rstrip(".!? ")
            if not instruction:
                print("Name the stored instruction whose rule should be relearned.")
                continue
            learned = rules.retry(instruction)
            rules.save(args.rules)
            pending_rule = (
                (instruction, learned.contrastive_input)
                if learned.status in {"need_more_examples", "no_fit"}
                and learned.contrastive_input is not None else None)
            _save_pending_rule(args.rule_session, args.rules, pending_rule)
            _print_rule_learning_result(learned)
            continue
        if line.startswith("/retry-rule "):
            instruction = line[len("/retry-rule "):].strip()
            if not instruction:
                print("Use: /retry-rule INSTRUCTION")
                continue
            learned = rules.retry(instruction)
            rules.save(args.rules)
            pending_rule = (
                (instruction, learned.contrastive_input)
                if learned.status in {"need_more_examples", "no_fit"}
                and learned.contrastive_input is not None else None)
            _save_pending_rule(args.rule_session, args.rules, pending_rule)
            _print_rule_learning_result(learned)
            continue
        if (line == "/procedure-scaffolds"
                or line.startswith("/procedure-scaffolds ")):
            fields = line.split()
            if len(fields) > 2 or (len(fields) == 2
                                   and not fields[1].isdigit()):
                print("Use: /procedure-scaffolds [MIN_SUPPORT]")
                continue
            minimum_support = int(fields[1]) if len(fields) == 2 else 3
            try:
                proposals = rules.propose_procedure_scaffolds(
                    minimum_supporting_phrases=minimum_support)
            except ValueError as error:
                print(f"Could not propose procedure scaffolds: {error}")
                continue
            if not proposals:
                print("No successful procedure scaffold met the support and "
                      "reconstruction checks.")
                continue
            for number, proposal in enumerate(proposals, 1):
                print(f"{number}. {proposal['descriptor']}")
                print(f"   artifact ID: {proposal['artifact_id']}")
                print(f"   supporting: {', '.join(proposal['supporting_instructions'])}")
                print(f"   held out: {', '.join(proposal['held_out_instructions'])} "
                      f"({proposal['held_out_validation_examples']} demonstrations reconstructed)")
                print("   lineage: " + "; ".join(
                    f"{item['phrase']} [{item['role']}; "
                    f"sha256:{item['fingerprint'][:12]}]"
                    for item in proposal['lineage']))
                print(f"   varying slots: {proposal['varying_parameter_slots']} | "
                      f"training values: {proposal['training_parameter_values']}")
                print(f"   procedure MDL: {proposal['description_length_bits_baseline']} → "
                      f"{proposal['description_length_bits_candidate']} bits "
                      f"(gain {proposal['description_length_gain_bits']})")
            print("Report only: no rules or grammar changed.")
            continue
        if _NATURAL_PRIMITIVE_PROPOSAL_REQUEST_RE.fullmatch(line):
            try:
                proposals = rules.propose_primitive_candidates()
            except ValueError as error:
                print(f"Could not propose primitives: {error}")
                continue
            if not proposals:
                print("No current operation proposal passed its training MDL and "
                      "held-out checks.")
                continue
            for number, proposal in enumerate(proposals, 1):
                print(f"CRMS> Primitive proposal {number}: "
                      f"{proposal['descriptor']}; supported by "
                      f"{', '.join(proposal['supporting_instructions'])}; "
                      f"held-out examples={proposal['held_out_examples']}; "
                      f"description-length gain="
                      f"{proposal['description_length_gain_bits']} bits.")
                print(f"Artifact ID: {proposal['artifact_id']}")
            print("These proposals are report-only. To add one, say "
                  "'Accept primitive proposal ID' with its exact artifact ID.")
            continue
        natural_primitive_accept = _NATURAL_PRIMITIVE_ACCEPT_RE.fullmatch(line)
        if natural_primitive_accept is not None:
            artifact_id = natural_primitive_accept.group(1).lower()
            try:
                rules.accept_primitive_proposal(artifact_id)
                rules.save(args.rules)
                print("Accepted the current validated primitive proposal into "
                      "this model's search grammar. Say 'Try to learn the rule "
                      "for INSTRUCTION' to apply it to stored examples.")
            except (OSError, ValueError) as error:
                print(f"Could not accept primitive proposal: {error}")
            continue
        natural_primitive_learn = _NATURAL_PRIMITIVE_LEARN_RE.fullmatch(line)
        if natural_primitive_learn is not None:
            artifact_id = natural_primitive_learn.group(1).lower()
            try:
                result = rules.learn_primitive_proposal(artifact_id)
                print("Learned validated primitive "
                      f"{result['descriptor']} from "
                      f"{len(result['learned_phrases'])} supported phrases; "
                      f"replayed {result['replayed_examples']} examples.")
            except (OSError, ValueError) as error:
                print(f"Could not learn from primitive proposal: {error}")
            continue
        if _NATURAL_PRIMITIVE_SELF_LEARN_RE.fullmatch(line):
            try:
                result = rules.learn_best_primitive_proposal()
                if result is None:
                    print("No current primitive proposal passed validation and "
                          "example replay.")
                else:
                    print("Learned validated primitive "
                          f"{result['descriptor']} from "
                          f"{len(result['learned_phrases'])} supported phrases; "
                          f"replayed {result['replayed_examples']} examples; "
                          f"rechecked {len(result['rechecked_phrases'])} pending "
                          f"tasks and learned {len(result['newly_learned_phrases'])} "
                          "new composed rule(s).")
            except (OSError, ValueError) as error:
                print(f"Could not learn a primitive rule: {error}")
            continue
        if (line == "/primitive-proposals"
                or line.startswith("/primitive-proposals ")):
            fields = line.split()
            if len(fields) > 2 or (len(fields) == 2
                                   and not fields[1].isdigit()):
                print("Use: /primitive-proposals [MIN_SUPPORT]")
                continue
            minimum_support = int(fields[1]) if len(fields) == 2 else 2
            try:
                proposals = rules.propose_primitive_candidates(
                    minimum_supporting_phrases=minimum_support)
            except ValueError as error:
                print(f"Could not propose primitives: {error}")
                continue
            if not proposals:
                print("No current proposal passed training MDL and held-out checks.")
                continue
            for number, proposal in enumerate(proposals, 1):
                cost = proposal["search_cost_estimate"]
                print(f"{number}. {proposal['descriptor']} | "
                      f"artifact={proposal['artifact_id']} | "
                      f"support={proposal['supporting_instructions']} | "
                      f"MDL gain={proposal['description_length_gain_bits']} bits | "
                      f"held-out={proposal['held_out_examples']}")
                print("   raw unpruned procedure sequences: "
                      f"{cost['raw_procedure_sequences_before']} → "
                      f"{cost['raw_procedure_sequences_after']} "
                      f"(upper-bound growth +{cost['raw_sequence_growth_upper_bound']}; "
                      f"depth {cost['max_composition_depth']}; not runtime)")
            print("Accept the exact reviewed artifact with /accept-primitive ID.")
            continue
        if line.startswith("/accept-primitive"):
            fields = line.split()
            if (len(fields) != 2 or fields[0] != "/accept-primitive"
                    or (not fields[1].isdigit()
                        and not fields[1].startswith('primitive-proposal-v1-'))
                    or (fields[1].isdigit() and int(fields[1]) < 1)):
                print("Use: /accept-primitive ID|N")
                continue
            try:
                if fields[1].isdigit():
                    proposals = rules.propose_primitive_candidates()
                    number = int(fields[1])
                    if number > len(proposals):
                        print("That proposal number is not in the current validated proposal list.")
                        continue
                    rules.accept_primitive_candidate(
                        proposals[number - 1]["descriptor"],
                        artifact_id=proposals[number - 1]["artifact_id"])
                else:
                    rules.accept_primitive_proposal(fields[1])
                rules.save(args.rules)
                print("Accepted primitive into this model's search grammar. "
                      "Say 'Try to learn the rule for INSTRUCTION' to apply it "
                      "to stored examples.")
            except (OSError, ValueError) as error:
                print(f"Could not accept primitive: {error}")
            continue
        if line == "/accepted-primitives":
            accepted = rules.accepted_primitive_candidates()
            if not accepted:
                print("No primitive proposals have been explicitly accepted.")
            for number, descriptor in enumerate(accepted, 1):
                print(f"{number}. {descriptor}")
            continue
        if line == "/accepted-primitive-artifacts":
            artifacts = rules.accepted_primitive_artifacts()
            audits = {item['artifact_id']: item
                      for item in rules.audit_accepted_primitive_artifacts()}
            if not artifacts:
                print("No accepted primitive has retained proposal provenance.")
            for number, artifact in enumerate(artifacts, 1):
                sources = ", ".join(
                    f"{item['instruction']} (sha256:{item['fingerprint']})"
                    for item in artifact['lineage'])
                audit = audits.get(artifact['artifact_id'], {})
                print(f"{number}. {artifact['artifact_id']} | "
                      f"{artifact['descriptor']} | evidence="
                      f"{audit.get('evidence_status', 'unknown')} | "
                      f"changed={audit.get('changed_sources', [])} | "
                      f"sources: {sources}")
            continue
        if line.startswith("/revoke-primitive"):
            fields = line.split()
            if (len(fields) != 2 or fields[0] != "/revoke-primitive"
                    or not fields[1].isdigit() or int(fields[1]) < 1):
                print("Use: /revoke-primitive N")
                continue
            accepted = rules.accepted_primitive_candidates()
            number = int(fields[1])
            if number > len(accepted):
                print("That number is not in the accepted primitive list.")
                continue
            try:
                rules.revoke_primitive_candidate(accepted[number - 1])
                rules.save(args.rules)
                print("Primitive removed from this model's search grammar. "
                      "Stored phrase examples are preserved.")
            except (OSError, ValueError) as error:
                print(f"Could not revoke primitive: {error}")
            continue
        if line.startswith("/apply-rule "):
            fields = [value.strip() for value in line[len("/apply-rule "):].split("|")]
            if len(fields) != 2 or not fields[0]:
                print("Use: /apply-rule INSTRUCTION|INPUT INTEGER CSV")
                continue
            try:
                inputs = _parse_integer_list(fields[1], allow_empty=True)
                prediction = rules.predict(fields[0], inputs)
                if prediction.status == "ok":
                    if (pending_rule is not None
                            and rules._clean_instruction(pending_rule[0])
                            == rules._clean_instruction(fields[0])):
                        pending_rule = None
                        _save_pending_rule(args.rule_session, args.rules, pending_rule)
                    print(f"CRMS> {prediction.output}")
                else:
                    pending_rule = (
                        (fields[0], prediction.contrastive_input)
                        if prediction.contrastive_input is not None else None)
                    _save_pending_rule(args.rule_session, args.rules, pending_rule)
                    print(f"CRMS> {prediction.request or prediction.message or prediction.status}")
                    _print_candidate_routes(prediction)
            except ValueError as error:
                print(f"Could not apply rule: {error}")
            continue
        if line.startswith("/explain-rule "):
            fields = [value.strip() for value in line[len("/explain-rule "):].split("|")]
            if len(fields) != 2 or not fields[0]:
                print("Use: /explain-rule INSTRUCTION|INPUT INTEGER CSV")
                continue
            try:
                inputs = _parse_integer_list(fields[1], allow_empty=True)
                _print_rule_explanation(rules, fields[0], inputs)
            except ValueError as error:
                print(f"Could not explain rule: {error}")
            continue
        if line == "/rules":
            learned_rules = rules.list_rules()
            if not learned_rules:
                print("No transformation rules are committed yet.")
            for instruction, procedure in learned_rules.items():
                steps = " then ".join(
                    step["operation"]
                    + (f" {step['parameters']}" if step.get("parameters") else "")
                    for step in procedure)
                print(f"{instruction}: {steps}")
            continue
        if line.startswith("/accept"):
            parts = line.split()
            if not pending_candidates:
                print("There are no fact candidates waiting for review.")
                continue
            try:
                number = int(parts[1]) if len(parts) > 1 else 1
                if not 1 <= number <= len(pending_candidates):
                    raise ValueError
            except ValueError:
                print(f"Choose a candidate number from 1 to {len(pending_candidates)}.")
                continue
            candidate = pending_candidates[number - 1]
            try:
                fact = knowledge.accept_fact_candidate(candidate, index)
                knowledge.save(args.knowledge)
                print(f"Accepted {'positive' if candidate.polarity else 'negative'} fact: "
                      f"{fact.subject} — {fact.relation} → {fact.object}.")
                pending_candidates.pop(number - 1)
                if pending_question:
                    if pending_candidates:
                        print(f"{len(pending_candidates)} candidate(s) remain "
                              "in the review queue:")
                        for next_number, next_candidate in enumerate(
                                pending_candidates, 1):
                            polarity = ("positive" if next_candidate.polarity
                                        else "negative")
                            print(f"{next_number}. {next_candidate.subject} — "
                                  f"{next_candidate.relation} → "
                                  f"{next_candidate.object} ({polarity})")
                            print(f"   {next_candidate.source}\n   "
                                  f"{next_candidate.sentence}")
                            print(f"   Say 'accept candidate {next_number}' "
                                  f"or 'reject candidate {next_number}'.")
                    else:
                        # Re-run only the learned-fact route. The broad
                        # research fallback can rank a lexical decoy after an
                        # accepted candidate, replacing the cited answer.
                        result = dialogue.turn(
                            pending_question, research_index=index)
                        if (result.response is not None
                                and result.response.status == "answered"):
                            source_answer = None
                            if not result.response.inference_proofs:
                                for evidence in result.response.evidence or []:
                                    for citation in evidence.get("sources", ()):
                                        try:
                                            excerpt = index.resolve_citation(citation)
                                            source_document = index.document(
                                                citation.split("#", 1)[0])
                                        except (KeyError, ValueError):
                                            continue
                                        source_answer = (
                                            f"{excerpt} [Source: "
                                            f"{source_document.title}; accepted fact]")
                                        break
                                    if source_answer is not None:
                                        break
                            print(f"CRMS> {source_answer or result.text}")
                        pending_question = ""
                else:
                    pending_question = ""
                _save_pending_candidates(args.candidate_session, args.knowledge,
                                         args.index, pending_candidates, pending_question,
                                         invalidated_candidates)
            except (OSError, ValueError) as error:
                print(f"Could not accept candidate: {error}")
            continue
        if line.startswith("/reject"):
            parts = line.split()
            if not pending_candidates:
                print("There are no fact candidates waiting for review.")
                continue
            try:
                if len(parts) != 2:
                    raise ValueError
                number = int(parts[1])
                if not 1 <= number <= len(pending_candidates):
                    raise ValueError
            except ValueError:
                print(f"Choose a candidate number from 1 to {len(pending_candidates)}.")
                continue
            candidate = pending_candidates.pop(number - 1)
            print(f"Rejected candidate {number}; it remains uncommitted: "
                  f"{candidate.subject} — {candidate.relation} → {candidate.object}.")
            if not pending_candidates:
                pending_question = ""
                print("No candidates remain in the review queue.")
            else:
                print(f"{len(pending_candidates)} candidate(s) remain in the review queue:")
                for remaining_number, remaining in enumerate(pending_candidates, 1):
                    polarity = "positive" if remaining.polarity else "negative"
                    print(f"{remaining_number}. {remaining.subject} — "
                          f"{remaining.relation} → {remaining.object} ({polarity})")
                    print(f"   {remaining.source}\n   {remaining.sentence}")
                    print(f"   Say 'accept candidate {remaining_number}' or "
                          f"'reject candidate {remaining_number}'.")
            _save_pending_candidates(args.candidate_session, args.knowledge,
                                     args.index, pending_candidates, pending_question,
                                     invalidated_candidates)
            continue
        if line.startswith("/") and not line.startswith("/summarize "):
            print("Unknown command. Type /help for available commands.")
            continue

        pending_candidates_before_turn = bool(pending_candidates)
        if pending_rule is not None and _natural_rule_feedback(line) is None:
            instruction, contrastive_input = pending_rule
            print(f"The rule lesson is still waiting for the output for "
                  f"{instruction} on {contrastive_input}; this input will be "
                  "handled separately. Type /cancel-rule to stop waiting.")
        shared_phrases = _natural_rule_shared_phrases(line)
        if shared_phrases is not None:
            phrases, examples = shared_phrases
            candidate_rules = copy.deepcopy(rules)
            # Teaching normally autosaves. Keep a rejected phrase group fully
            # isolated from the live rules file until both independent fits pass.
            candidate_rules.memory_path = None
            results = [candidate_rules.teach(
                phrase, examples, _use_language_prior=False)
                       for phrase in phrases]
            procedures = [result.procedure for result in results]
            if (all(result.status == "learned" for result in results)
                    and procedures[0] is not None
                    and procedures[0] == procedures[1]):
                try:
                    candidate_rules.memory_path = args.rules
                    candidate_rules.save(args.rules)
                    rules = candidate_rules
                    pending_rule = None
                    _save_pending_rule(args.rule_session, args.rules, pending_rule)
                    print("Both phrases are grounded to the same learned procedure: "
                          + " and ".join(f"'{phrase}'" for phrase in phrases) + ".")
                except (OSError, ValueError) as error:
                    print(f"Could not save the shared phrase learning: {error}")
            else:
                statuses = ", ".join(result.status for result in results)
                print("The phrases did not independently learn the same unique "
                      f"procedure ({statuses}); no rules were changed. Provide "
                      "more examples or teach the phrases separately.")
            continue
        natural_demonstrations = _natural_rule_demonstrations(line)
        if natural_demonstrations is not None:
            instruction, examples = natural_demonstrations
            learned = rules.teach(instruction, examples)
            rules.save(args.rules)
            pending_rule = (
                (instruction, learned.contrastive_input)
                if learned.status in {"need_more_examples", "no_fit"}
                and learned.contrastive_input is not None else None)
            _save_pending_rule(args.rule_session, args.rules, pending_rule)
            _print_rule_learning_result(learned)
            continue
        if pending_rule is not None:
            expected_output = _natural_rule_feedback(line)
            if expected_output is not None:
                instruction, contrastive_input = pending_rule
                learned = rules.teach(
                    instruction, [(contrastive_input, expected_output)])
                rules.save(args.rules)
                pending_rule = (
                    (instruction, learned.contrastive_input)
                    if learned.status in {"need_more_examples", "no_fit"}
                    and learned.contrastive_input is not None else None)
                _save_pending_rule(args.rule_session, args.rules, pending_rule)
                _print_rule_learning_result(learned)
                continue
        natural_math_examples = _natural_math_teaching(line)
        if natural_math_examples is not None:
            candidate_math_model = copy.deepcopy(math_model)
            try:
                for question, answer in natural_math_examples:
                    learned_math = candidate_math_model.teach(question, answer)
                candidate_math_model.save(args.math)
                math_model = candidate_math_model
                if learned_math.status == "licensed":
                    pending_math = None
                    phrase = " ".join(learned_math.expression.operator_phrase)
                    print(f"Math phrase licensed as exact {learned_math.operation}: '{phrase}'.")
                else:
                    pending_math = (
                        (learned_math.expression.operator_phrase,
                         learned_math.contrastive_input)
                        if learned_math.contrastive_input is not None else None)
                    print(learned_math.request or
                          "Math examples stored, but the phrase is not uniquely licensed yet.")
                _save_pending_math(args.math_session, args.math, pending_math)
            except (OSError, ValueError) as error:
                print(f"Could not teach math examples: {error}")
            continue
        natural_unit_examples = _natural_unit_teaching(line)
        if natural_unit_examples is not None:
            candidate_math_model = copy.deepcopy(math_model)
            licensed_pairs = set()
            try:
                for left_quantity, right_quantity in natural_unit_examples:
                    learned_unit = candidate_math_model.teach_unit_equivalence(
                        f"{left_quantity}|{right_quantity}")
                    if learned_unit.status == "licensed":
                        licensed_pairs.add(learned_unit.unit)
                candidate_math_model.save(args.math)
                math_model = candidate_math_model
                if licensed_pairs:
                    print("Unit conversion batch stored; licensed ratio(s): "
                          + "; ".join(sorted(licensed_pairs)) + ".")
                else:
                    print("Unit examples stored; provide another distinct aligned "
                          "quantity pair for each conversion you want to license.")
            except (OSError, ValueError) as error:
                print(f"Could not teach unit conversion examples: {error}")
            continue
        if pending_math is not None:
            answer = _natural_math_feedback(line)
            if answer is not None:
                phrase, (left, right) = pending_math
                question = f"What is {left} {' '.join(phrase)} {right}?"
                try:
                    learned_math = math_model.teach(question, answer)
                    math_model.save(args.math)
                    if learned_math.status == "licensed":
                        pending_math = None
                        print(f"Math phrase licensed as exact {learned_math.operation}: "
                              f"'{ ' '.join(phrase) }'.")
                    else:
                        pending_math = (
                            (learned_math.expression.operator_phrase,
                             learned_math.contrastive_input)
                            if learned_math.contrastive_input is not None else None)
                        print(learned_math.request or
                              "That example did not resolve the remaining operation.")
                    _save_pending_math(args.math_session, args.math, pending_math)
                except (OSError, ValueError) as error:
                    print(f"Could not use that math example: {error}")
                    print("The pending contrastive math example is still waiting for its intended answer.")
                continue
        natural_relation_type = _NATURAL_RELATION_TYPE_TEACH_RE.fullmatch(line)
        if natural_relation_type is not None:
            relation, relation_type = natural_relation_type.groups()
            try:
                fact = knowledge.add_relation_type(
                    relation.strip(), relation_type.casefold(),
                    "conversation:natural-language-relation-schema")
                knowledge.save(args.knowledge)
                print(f"Stored explicit relation schema: {fact.subject} is "
                      f"{fact.object} [source: user-taught].")
            except (TypeError, ValueError, OSError) as error:
                print(f"Could not teach relation schema: {error}")
            continue
        natural_fact_examples = _natural_fact_teaching(line)
        natural_teacher_examples = _natural_teacher_fact_teaching(line)
        if natural_teacher_examples is not None:
            relations = {tuple(normalized_tokens(example[2]))
                         for example in natural_teacher_examples}
            polarities = {example[4] for example in natural_teacher_examples}
            if len(relations) != 1 or len(polarities) != 1:
                print("CRMS> All labeled examples must use one canonical relation "
                      "and one polarity; nothing was stored.")
                continue
            candidate_knowledge = copy.deepcopy(knowledge)
            source = "teacher:conversation"
            licensed = False
            try:
                for (sentence, subject, relation, obj, polarity, subject_phrase,
                     predicate_phrase, object_phrase) in natural_teacher_examples:
                    qualifiers = ()
                    key = candidate_knowledge._fact_key(
                        subject, relation, obj, qualifiers)
                    same_store = (candidate_knowledge._facts if polarity == "positive"
                                  else candidate_knowledge._negative_facts)
                    other_store = (candidate_knowledge._negative_facts
                                   if polarity == "positive"
                                   else candidate_knowledge._facts)
                    if key in other_store:
                        raise ValueError(
                            f"the example conflicts with existing evidence for "
                            f"{subject} — {relation} → {obj}")
                    add = (candidate_knowledge.add_fact
                           if polarity == "positive"
                           else candidate_knowledge.add_negative_fact)
                    add(subject, relation, obj, source)
                    licensed |= candidate_knowledge.teach_fact_pattern(
                        sentence, subject=subject, relation=relation, obj=obj,
                        source=source, polarity=polarity == "positive",
                        subject_phrase=subject_phrase,
                        predicate_phrase=predicate_phrase,
                        object_phrase=object_phrase)
                candidate_knowledge.save(args.knowledge)
                knowledge = candidate_knowledge
                dialogue.knowledge = knowledge
                print(f"CRMS> Stored {len(natural_teacher_examples)} "
                      f"teacher-labeled {next(iter(polarities))} facts "
                      f"[source: {source}]. "
                      + ("The fact pattern is licensed."
                         if licensed else
                         "More varied examples are needed to license the pattern."))
            except (OSError, TypeError, ValueError) as error:
                print(f"CRMS> Could not teach the fact pattern; nothing was saved: {error}")
            continue
        natural_user_fact = _NATURAL_USER_FACT_TEACH_RE.fullmatch(line)
        if natural_user_fact is not None:
            sentence, source = (value.strip()
                                for value in natural_user_fact.groups())
            try:
                proposals = knowledge.propose_facts(sentence, source=source)
                unique = {
                    (tuple(normalized_tokens(item.subject)),
                     tuple(normalized_tokens(item.relation)),
                     tuple(normalized_tokens(item.object)),
                     tuple((tuple(normalized_tokens(name)),
                            tuple(normalized_tokens(value)))
                           for name, value in item.qualifiers),
                     item.polarity): item
                    for item in proposals
                }
                if len(unique) != 1:
                    print("CRMS> " + (
                        "That sentence matches multiple learned fact patterns; "
                        "please clarify its meaning."
                        if unique else
                        "I cannot ground that sentence in a learned fact pattern yet. "
                        "Teach examples or index a cited source first."))
                    continue
                proposal = next(iter(unique.values()))
                candidate_knowledge = copy.deepcopy(knowledge)
                add = (candidate_knowledge.add_fact if proposal.polarity else
                       candidate_knowledge.add_negative_fact)
                add(proposal.subject, proposal.relation, proposal.object, source,
                    qualifiers=dict(proposal.qualifiers))
                candidate_knowledge.save(args.knowledge)
                knowledge = candidate_knowledge
                dialogue.knowledge = knowledge
                polarity = "positive" if proposal.polarity else "negative"
                print(f"CRMS> Stored {polarity} fact: {proposal.subject} — "
                      f"{proposal.relation} → {proposal.object} "
                      f"[source: {source}].")
            except (OSError, TypeError, ValueError) as error:
                print(f"CRMS> Could not store the taught fact: {error}")
            continue
        natural_retraction = _NATURAL_FACT_RETRACTION_RE.fullmatch(line)
        if natural_retraction is not None:
            polarity_label, sentence, source, context_text = (
                value.strip() if value else None
                for value in natural_retraction.groups())
            polarity = polarity_label.casefold() == "positive"
            requested_scope = None
            if context_text:
                scope = {}
                malformed_scope = False
                for item in context_text.split(";"):
                    name, separator, value = item.partition("=")
                    if not separator or not name.strip() or not value.strip():
                        print("CRMS> Context qualifiers must use KEY=VALUE "
                              "separated by semicolons.")
                        malformed_scope = True
                        break
                    scope[name.strip()] = value.strip()
                if malformed_scope:
                    continue
                try:
                    requested_scope = knowledge._normalize_qualifiers(scope)
                except (TypeError, ValueError) as error:
                    print(f"CRMS> Invalid context scope: {error}")
                    continue
            fact_rows = (knowledge.facts() if polarity
                         else knowledge.negative_facts())
            sentence_key = tuple(normalized_tokens(sentence))
            matches = {}
            for fact in fact_rows:
                if source not in fact.sources:
                    continue
                if (requested_scope is not None
                        and fact.qualifiers != requested_scope):
                    continue
                realizations = knowledge._realize_fact_patterns(
                    fact.subject, fact.relation, fact.object, polarity=polarity)
                if not any(tuple(normalized_tokens(item["sentence"]))
                           == sentence_key for item in realizations):
                    continue
                key = knowledge._fact_key(
                    fact.subject, fact.relation, fact.object, fact.qualifiers)
                matches[key] = fact
            if len(matches) != 1:
                print("CRMS> " + (
                    "That sentence and source match multiple scoped facts; use "
                    "/retract-fact with the exact qualifier scope."
                    if matches else
                    "No stored fact with that learned sentence and source was found."))
                continue
            fact = next(iter(matches.values()))
            remove_fact = (knowledge.remove_fact if polarity
                           else knowledge.remove_negative_fact)
            try:
                removed = remove_fact(
                    fact.subject, fact.relation, fact.object, source,
                    qualifiers=dict(fact.qualifiers))
                if not removed:
                    print("CRMS> That source no longer supports the stored fact.")
                    continue
                knowledge.save(args.knowledge)
                dialogue.knowledge = knowledge
                remaining_rows = (knowledge.facts() if polarity
                                  else knowledge.negative_facts())
                key = knowledge._fact_key(
                    fact.subject, fact.relation, fact.object, fact.qualifiers)
                still_supported = any(
                    knowledge._fact_key(row.subject, row.relation, row.object,
                                        row.qualifiers) == key
                    for row in remaining_rows)
                print("CRMS> Retracted that source's support; other citations remain."
                      if still_supported else
                      "CRMS> Retracted the final source support; the fact is no longer stored.")
            except (OSError, TypeError, ValueError) as error:
                print(f"CRMS> Could not retract fact support: {error}")
            continue
        if natural_fact_examples is not None:
            relations = {tuple(normalized_tokens(example[2]))
                         for example in natural_fact_examples}
            polarities = {example[4] for example in natural_fact_examples}
            if len(relations) != 1 or len(polarities) != 1:
                print("All examples in a sourced fact-pattern batch must use "
                      "the same canonical relation and polarity; no change was saved.")
                continue
            candidate_knowledge = copy.deepcopy(knowledge)
            citations = []
            licensed = False
            try:
                for (sentence, subject, relation, obj, polarity, subject_phrase,
                     predicate_phrase, object_phrase) in natural_fact_examples:
                    hit, citation = _unique_source_hit_for_sentence(index, sentence)
                    add_fact = (candidate_knowledge.add_fact_from_hit
                                if polarity == "positive" else
                                candidate_knowledge.add_negative_fact_from_hit)
                    add_fact(subject, relation, obj, index, hit)
                    example_licensed = candidate_knowledge.teach_fact_pattern_from_hit(
                        sentence, subject=subject, relation=relation, obj=obj,
                        research_index=index, hit=hit,
                        subject_phrase=subject_phrase,
                        predicate_phrase=predicate_phrase,
                        object_phrase=object_phrase,
                        polarity=polarity == "positive")
                    licensed = licensed or example_licensed
                    citations.append(citation)
                candidate_knowledge.save(args.knowledge)
                knowledge = candidate_knowledge
                dialogue.knowledge = knowledge
                if licensed:
                    print("Sourced fact pattern licensed from "
                          f"{len(natural_fact_examples)} examples.")
                else:
                    print("Sourced facts and aligned examples stored; more varied "
                          "entities and objects are needed to license the pattern.")
                print("Sources: " + "; ".join(citations))
            except (OSError, ValueError) as error:
                print(f"Could not teach sourced fact pattern: {error}")
            continue
        natural_about_examples = _natural_about_teaching(line)
        if natural_about_examples is not None:
            candidate_knowledge = copy.deepcopy(knowledge)
            try:
                entity_keys = [normalized_tokens(entity)
                               for _request, entity in natural_about_examples]
                signatures = []
                for request, entity in natural_about_examples:
                    request_words = tuple(normalized_tokens(request))
                    entity_words = tuple(normalized_tokens(entity))
                    positions = [index for index in range(
                        len(request_words) - len(entity_words) + 1)
                        if request_words[index:index + len(entity_words)] == entity_words]
                    if len(positions) != 1:
                        raise ValueError(
                            "each entity must occur exactly once in its about request")
                    start = positions[0]
                    end = start + len(entity_words)
                    signatures.append((request_words[:start], request_words[end:]))
                if (len(set(entity_keys)) != len(entity_keys)
                        or any(signature != signatures[0]
                               for signature in signatures)):
                    raise ValueError(
                        "examples must use distinct entities in one shared request frame")
                licensed = False
                for request, entity in natural_about_examples:
                    licensed = candidate_knowledge.teach_about_frame(
                        request, entity=entity)
                if not licensed:
                    print("The examples do not yet license one shared "
                          "about-request frame; no change was saved.")
                else:
                    candidate_knowledge.save(args.knowledge)
                    knowledge = candidate_knowledge
                    dialogue.knowledge = knowledge
                    print("About-request frame licensed from "
                          f"{len(natural_about_examples)} stored entities.")
            except (OSError, ValueError) as error:
                print(f"Could not teach about-request frame: {error}")
            continue
        natural_question_additional = _natural_question_additional(line)
        if natural_question_additional is not None:
            question, answer = natural_question_additional
            candidate_knowledge = copy.deepcopy(knowledge)
            resolved = _resolve_question_example(
                candidate_knowledge, question, answer)
            if resolved is None:
                question_words = tuple(normalized_tokens(question))
                expected_answer = tuple(normalized_tokens(answer))
                proof_matches = []
                for frame_key, examples in candidate_knowledge._question_examples.items():
                    if (len(examples) < 2
                            or not candidate_knowledge._question_frame_is_licensed(
                                frame_key, examples)):
                        continue
                    relation = tuple(json.loads(frame_key[0]))
                    answer_field = frame_key[1]
                    prefix, suffix = frame_key[2], frame_key[3]
                    if (question_words[:len(prefix)] != prefix
                            or (suffix and question_words[-len(suffix):] != suffix)):
                        continue
                    bound_end = len(question_words) - len(suffix) if suffix else len(question_words)
                    bound_words = question_words[len(prefix):bound_end]
                    if not bound_words or bound_words in examples:
                        continue
                    bound_entity = candidate_knowledge._canonicalize_query_entity(
                        " ".join(bound_words))
                    subject, obj = ((answer, bound_entity)
                                    if answer_field == "subject"
                                    else (bound_entity, answer))
                    inference = candidate_knowledge.infer_relation(
                        subject, " ".join(relation), obj)
                    if (inference.status != "answered" or not inference.complete
                            or inference.conclusion is None):
                        continue
                    inferred_answer = inference.conclusion[
                        "subject" if answer_field == "subject" else "object"]
                    if tuple(normalized_tokens(inferred_answer)) == expected_answer:
                        proof_matches.append((" ".join(relation), answer_field,
                                              bound_entity))
                if len(proof_matches) == 1:
                    resolved = proof_matches[0]
            if resolved is None:
                print("The example does not identify one directly supported fact "
                      "or uniquely verified inference; "
                      "no change was saved.")
                continue
            relation, answer_field, bound_entity = resolved
            question_words = tuple(normalized_tokens(question))
            entity_words = tuple(normalized_tokens(bound_entity))
            positions = [index for index in range(
                len(question_words) - len(entity_words) + 1)
                if question_words[index:index + len(entity_words)] == entity_words]
            if len(positions) != 1:
                print("The example does not contain its bound entity exactly once; "
                      "no change was saved.")
                continue
            start = positions[0]
            frame_key = (
                json.dumps(list(normalized_tokens(relation)), ensure_ascii=False),
                answer_field, question_words[:start],
                question_words[start + len(entity_words):])
            existing = candidate_knowledge._question_examples.get(frame_key)
            if (existing is None or len(existing) < 2
                    or not candidate_knowledge._question_frame_is_licensed(
                        frame_key, existing)):
                print("No already licensed exact question frame matches this "
                      "example; teach a frame from multiple examples first.")
                continue
            if entity_words in existing:
                print("That entity is already represented in the licensed frame; "
                      "no new example was added.")
                continue
            try:
                candidate_knowledge.teach_question(
                    question, relation=relation, answer_field=answer_field,
                    bound_entity=bound_entity, answer=answer)
                candidate_knowledge.save(args.knowledge)
                knowledge = candidate_knowledge
                dialogue.knowledge = knowledge
                print("Additional question example added to the licensed frame "
                      f"(relation: {relation}; answer: {answer_field}).")
            except (OSError, ValueError) as error:
                print(f"Could not add question example: {error}")
            continue

        natural_qualified_question_additional = (
            _natural_qualified_question_additional(line))
        if natural_qualified_question_additional is not None:
            question, answer = natural_qualified_question_additional
            candidate_knowledge = copy.deepcopy(knowledge)
            resolved = _resolve_qualified_question_example(
                candidate_knowledge, question, answer)
            if resolved is None:
                print("The example does not identify one directly supported "
                      "qualified fact; no change was saved.")
                continue
            relation, answer_field, bound_entity, qualifier_values = resolved
            words = tuple(normalized_tokens(question))
            entity_words = tuple(normalized_tokens(bound_entity))

            def spans(needle: tuple[str, ...]) -> list[tuple[int, int]]:
                return [(index, index + len(needle))
                        for index in range(len(words) - len(needle) + 1)
                        if needle and words[index:index + len(needle)] == needle]

            slot_rows = [("\x00entity", entity_words, spans(entity_words))]
            slot_rows.extend(("\x00q" + str(index),
                              tuple(normalized_tokens(value)),
                              spans(tuple(normalized_tokens(value))))
                             for index, (_name, value) in enumerate(qualifier_values))
            if any(len(matches) != 1 for _marker, _tokens, matches in slot_rows):
                print("The entity and qualifier values must each occur exactly once; "
                      "no change was saved.")
                continue
            ordered_slots = sorted(
                ((marker, matches[0]) for marker, _needle, matches in slot_rows),
                key=lambda row: row[1][0])
            if any(start < other_end and end > other_start
                   for index, (_marker, (start, end)) in enumerate(ordered_slots)
                   for _other, (other_start, other_end) in ordered_slots[index + 1:]):
                print("The entity and qualifier spans overlap; no change was saved.")
                continue
            qualifier_names = tuple(
                tuple(normalized_tokens(name)) for name, _value in qualifier_values)
            if len(qualifier_values) == 1:
                entity_start, entity_end = spans(entity_words)[0]
                _marker, value_words, value_matches = slot_rows[1]
                value_start, value_end = value_matches[0]
                entity_first = entity_start < value_start
                if entity_first:
                    prefix, middle, suffix = (words[:entity_start],
                                              words[entity_end:value_start],
                                              words[value_end:])
                else:
                    prefix, middle, suffix = (words[:value_start],
                                              words[value_end:entity_start],
                                              words[entity_end:])
                key = (tuple(normalized_tokens(relation)), answer_field,
                       qualifier_names[0], entity_first, prefix, middle, suffix)
                existing = candidate_knowledge._qualified_question_examples.get(key)
                value_pair = value_words
            else:
                template = list(words)
                values_by_slot: list[tuple[str, ...]] = [()] * (len(qualifier_values) + 1)
                for marker, (start, end) in reversed(ordered_slots):
                    if marker == "\x00entity":
                        values_by_slot[0] = entity_words
                    else:
                        slot_index = int(marker[2:])
                        values_by_slot[slot_index + 1] = slot_rows[slot_index + 1][1]
                    template[start:end] = [marker]
                key = (tuple(normalized_tokens(relation)), answer_field,
                       qualifier_names, tuple(template))
                existing = candidate_knowledge._multi_qualified_question_examples.get(key)
                value_pair = tuple(values_by_slot[1:])
            if existing is None:
                print("No already licensed exact qualified question frame "
                      "matches this example; no change was saved.")
                continue
            entities = {entity for entity, _values in existing}
            if len(existing) < 2 or len(entities) < 2:
                print("The matching qualified frame is not already licensed; "
                      "no change was saved.")
                continue
            if len(qualifier_values) == 1:
                qualifier_values_seen = {value for _entity, value in existing}
                licensed = len(qualifier_values_seen) >= 2
            else:
                licensed = all(
                    len({values[index] for _entity, values in existing}) >= 2
                    for index in range(len(qualifier_values)))
            if not licensed:
                print("The matching qualified frame is not already licensed; "
                      "no change was saved.")
                continue
            pair = (entity_words, value_pair)
            if pair in existing:
                print("That entity and qualifier pair is already represented; "
                      "no new example was added.")
                continue
            try:
                candidate_knowledge.teach_qualified_question(
                    question, relation=relation, answer_field=answer_field,
                    bound_entity=bound_entity, answer=answer,
                    qualifier=dict(qualifier_values))
                candidate_knowledge.save(args.knowledge)
                knowledge = candidate_knowledge
                dialogue.knowledge = knowledge
                print("Additional qualified question example added to the "
                      f"licensed frame (relation: {relation}; "
                      f"qualifiers: {', '.join(name for name, _ in qualifier_values)}; "
                      f"answer: {answer_field}).")
            except (OSError, ValueError) as error:
                print(f"Could not add qualified question example: {error}")
            continue

        paired_question_examples = _natural_paired_question_teaching(line)
        if paired_question_examples is not None:
            candidate_knowledge = copy.deepcopy(knowledge)
            try:
                resolved = [
                    _resolve_question_example(candidate_knowledge, question, answer)
                    for question, answer in paired_question_examples]
                if any(item is None for item in resolved):
                    print("Each paired question example must match one unique "
                          "stored fact; no change was saved.")
                    continue
                relation = resolved[0][0]
                if any(item[0] != relation for item in resolved):
                    print("Paired question frames must address the same stored "
                          "relation; no change was saved.")
                    continue
                groups: dict[tuple[Any, ...], list[int]] = {}
                for example_index, ((question, _answer), item) in enumerate(
                        zip(paired_question_examples, resolved)):
                    answer_field, bound = item[1], item[2]
                    question_words = tuple(normalized_tokens(question))
                    bound_words = tuple(normalized_tokens(bound))
                    positions = [position for position in range(
                        len(question_words) - len(bound_words) + 1)
                        if question_words[position:position + len(bound_words)]
                        == bound_words]
                    if len(positions) != 1:
                        raise ValueError(
                            "each bound entity must occur once in its question")
                    start = positions[0]
                    end = start + len(bound_words)
                    key = (tuple(normalized_tokens(relation)), answer_field,
                           question_words[:start], question_words[end:])
                    groups.setdefault(key, []).append(example_index)
                directions = {key[1] for key in groups}
                if (len(groups) < 2 or directions != {"subject", "object"}
                        or any(len(indices) < 2 for indices in groups.values())
                        or any(len({tuple(normalized_tokens(resolved[index][2]))
                                    for index in indices}) != len(indices)
                               for indices in groups.values())):
                    print("Each question direction needs at least two distinct "
                          "fact-backed entities; no change was saved.")
                    continue
                licensed_groups = set()
                for (question, answer), item in zip(
                        paired_question_examples, resolved):
                    licensed = candidate_knowledge.teach_question(
                        question, relation=item[0], answer_field=item[1],
                        bound_entity=item[2], answer=answer)
                    if licensed:
                        licensed_groups.add(item[1])
                if licensed_groups != directions:
                    print("The paired examples did not license every question "
                          "direction; no change was saved.")
                    continue
                candidate_knowledge.save(args.knowledge)
                knowledge = candidate_knowledge
                dialogue.knowledge = knowledge
                print("Paired question frames licensed from "
                      f"{len(paired_question_examples)} fact-backed examples "
                      f"({len(groups)} wording patterns; relation: {relation}; "
                      "answers: subject and object).")
            except (OSError, ValueError) as error:
                print(f"Could not teach paired question frames: {error}")
            continue

        natural_question_examples = _natural_question_teaching(line)
        if natural_question_examples is not None:
            candidate_knowledge = copy.deepcopy(knowledge)
            try:
                resolved_examples = [
                    _resolve_question_example(candidate_knowledge, question, answer)
                    for question, answer in natural_question_examples]
                simple = (
                    all(item is not None for item in resolved_examples)
                    and all(item[:2] == resolved_examples[0][:2]
                            for item in resolved_examples)
                    and len({normalized_tokens(item[2])
                             for item in resolved_examples})
                    == len(resolved_examples))
                licensed = False
                if simple:
                    relation, answer_field, _first_bound = resolved_examples[0]
                    for (question, answer), item in zip(
                            natural_question_examples, resolved_examples):
                        licensed = candidate_knowledge.teach_question(
                            question, relation=relation, answer_field=answer_field,
                            bound_entity=item[2], answer=answer)
                    frame_kind = "fact-backed"
                else:
                    qualified = [
                        _resolve_qualified_question_example(
                            candidate_knowledge, question, answer)
                        for question, answer in natural_question_examples]
                    qualified_ok = all(item is not None for item in qualified)
                    if qualified_ok:
                        first = qualified[0]
                        first_names = tuple(normalized_tokens(name)
                                            for name, _value in first[3])
                        distinct_entities = {
                            normalized_tokens(item[2]) for item in qualified}
                        qualified_ok = (
                            all(item[:2] == first[:2] for item in qualified)
                            and all(tuple(normalized_tokens(name)
                                          for name, _value in item[3]) == first_names
                                    for item in qualified)
                            and len(distinct_entities) == len(qualified)
                            and all(len({normalized_tokens(item[3][index][1])
                                         for item in qualified}) >= 2
                                    for index in range(len(first_names))))
                    if qualified_ok:
                        relation, answer_field = first[:2]
                        for (question, answer), item in zip(
                                natural_question_examples, qualified):
                            licensed = candidate_knowledge.teach_qualified_question(
                                question, relation=relation,
                                answer_field=answer_field, bound_entity=item[2],
                                answer=answer, qualifier=dict(item[3]))
                        frame_kind = "qualified"
                    else:
                        pattern_examples = [
                            _resolve_subject_pattern_question_example(
                                candidate_knowledge, question, answer)
                            for question, answer in natural_question_examples]
                        pattern_ok = all(item is not None
                                         for item in pattern_examples)
                        if pattern_ok:
                            first_pattern = pattern_examples[0]
                            signature = tuple(first_pattern[key] for key in (
                                "relation", "answer_field", "question_prefix",
                                "question_suffix", "fact_bound_field",
                                "fact_prefix", "fact_suffix"))
                            pattern_ok = (
                                all(tuple(item[key] for key in (
                                    "relation", "answer_field", "question_prefix",
                                    "question_suffix", "fact_bound_field",
                                    "fact_prefix", "fact_suffix")) == signature
                                    for item in pattern_examples)
                                and len({tuple(normalized_tokens(item["bound_entity"]))
                                         for item in pattern_examples})
                                == len(pattern_examples))
                        if not pattern_ok:
                            print("The examples do not uniquely identify one shared "
                                  "fact-backed question pattern across distinct entities "
                                  "and contexts; no change was saved.")
                            continue
                        relation = first_pattern["relation"]
                        answer_field = first_pattern["answer_field"]
                        for (question, answer), item in zip(
                                natural_question_examples, pattern_examples):
                            licensed = candidate_knowledge.teach_subject_pattern_question(
                                question, relation=relation,
                                answer_field=answer_field,
                                bound_entity=item["bound_entity"], answer=answer)
                        frame_kind = "subject-pattern"
                if not licensed:
                    print("The examples do not share one licensed question frame; "
                          "no change was saved.")
                else:
                    candidate_knowledge.save(args.knowledge)
                    knowledge = candidate_knowledge
                    dialogue.knowledge = knowledge
                    detail = (f"relation: {relation}; answer: {answer_field}")
                    if frame_kind == "qualified":
                        detail += "; qualifiers: " + ", ".join(
                            name for name, _value in qualified[0][3])
                    print(f"Question frame licensed from "
                          f"{len(natural_question_examples)} {frame_kind} examples "
                          f"({detail}).")
            except (OSError, ValueError) as error:
                print(f"Could not teach question frame: {error}")
            continue
        natural_path_examples = _natural_path_question_teaching(line)
        if natural_path_examples is not None:
            candidate_knowledge = copy.deepcopy(knowledge)
            try:
                resolved_paths = [
                    _resolve_path_question_example(
                        candidate_knowledge, question, answer)
                    for question, answer in natural_path_examples]
                if (any(item is None for item in resolved_paths)
                        or any(item[0] != resolved_paths[0][0]
                               for item in resolved_paths)
                        or len({normalized_tokens(item[1])
                                for item in resolved_paths})
                        != len(resolved_paths)):
                    print("The examples do not each resolve to one shared "
                          "fact-backed path over two distinct starting entities; "
                          "no change was saved.")
                    continue
                path = resolved_paths[0][0]
                licensed = False
                for (question, answer), (_path, bound_entity) in zip(
                        natural_path_examples, resolved_paths):
                    licensed = candidate_knowledge.teach_path_question(
                        question, relations=[" ".join(item) for item in path],
                        bound_entity=bound_entity, answer=answer)
                if not licensed:
                    print("The examples do not share one licensed path-question "
                          "frame; no change was saved.")
                else:
                    candidate_knowledge.save(args.knowledge)
                    knowledge = candidate_knowledge
                    dialogue.knowledge = knowledge
                    rendered_path = " -> ".join(" ".join(item) for item in path)
                    print(f"Path-question frame licensed from "
                          f"{len(natural_path_examples)} fact-backed "
                          f"examples (path: {rendered_path}).")
            except (OSError, ValueError) as error:
                print(f"Could not teach path-question frame: {error}")
            continue
        natural_polar_examples = _natural_polar_teaching(line)
        if natural_polar_examples is not None:
            candidate_knowledge = copy.deepcopy(knowledge)
            try:
                facts = [
                    _resolve_polar_example(candidate_knowledge, question, answer)
                    for question, answer in natural_polar_examples]
                if (any(fact is None for fact in facts)
                        or any(normalized_tokens(fact[1])
                               != normalized_tokens(facts[0][1])
                               for fact in facts)
                        or len({normalized_tokens(fact[0]) for fact in facts})
                        != len(facts)
                        or len({normalized_tokens(fact[2]) for fact in facts})
                        != len(facts)):
                    print("The examples do not uniquely match explicit facts with "
                          "one shared relation and varying entities; no change was saved.")
                    continue
                relation = facts[0][1]
                licensed = False
                for (question, answer), (subject, _relation, obj) in zip(
                        natural_polar_examples, facts):
                    licensed = candidate_knowledge.teach_polar_question(
                        question, subject=subject, relation=relation, obj=obj,
                        answer=answer)
                if not licensed:
                    print("The examples do not yet license one shared yes/no "
                          "frame; no change was saved.")
                else:
                    candidate_knowledge.save(args.knowledge)
                    knowledge = candidate_knowledge
                    dialogue.knowledge = knowledge
                    print(f"Yes/no frame licensed from "
                          f"{len(natural_polar_examples)} explicit fact examples "
                          f"(relation: {relation}).")
            except (OSError, ValueError) as error:
                print(f"Could not teach yes/no question frame: {error}")
            continue
        natural_translation_additional = _natural_translation_additional(line)
        if natural_translation_additional is not None:
            source_language, target_language, register, source_text, target_text = (
                natural_translation_additional)
            try:
                translation_model.teach_additional_example(
                    source_language, target_language, register,
                    source_text, target_text)
                translation_model.save(args.translations)
                print("Additional aligned translation example licensed for "
                      f"{source_language} to {target_language} ({register} register).")
            except (OSError, ValueError) as error:
                print(f"Could not add translation example: {error}")
            continue
        natural_translation = _natural_translation_teaching(line)
        if natural_translation is not None:
            source_language, target_language, register, source_template, target_template, examples = natural_translation
            try:
                if source_language.casefold() == target_language.casefold():
                    translation_model.teach_rewrite(
                        source_language, register, source_template,
                        target_template, examples)
                else:
                    translation_model.teach(
                        source_language, target_language, register,
                        source_template, target_template, examples)
                translation_model.save(args.translations)
                if source_language.casefold() == target_language.casefold():
                    print("Rewrite frame licensed for "
                          f"{source_language} ({register} register), with "
                          f"{len(examples)} aligned examples.")
                else:
                    print("Translation frame licensed for "
                          f"{source_language} to {target_language} "
                          f"({register} register), with "
                          f"{len(examples)} aligned examples.")
            except (OSError, ValueError) as error:
                print(f"Could not teach translation frame: {error}")
            continue
        natural_translation_examples = _natural_translation_examples(line)
        if natural_translation_examples is not None:
            source_language, target_language, register, examples = natural_translation_examples
            try:
                source_template, target_template = (
                    infer_shared_slot_templates(examples))
                if source_language.casefold() == target_language.casefold():
                    translation_model.teach_rewrite(
                        source_language, register, source_template,
                        target_template, examples)
                else:
                    translation_model.teach(
                        source_language, target_language, register,
                        source_template, target_template, examples)
                translation_model.save(args.translations)
                if source_language.casefold() == target_language.casefold():
                    print("Rewrite frame licensed for "
                          f"{source_language} ({register} register), with "
                          f"{len(examples)} aligned examples.")
                else:
                    print("Translation frame licensed for "
                          f"{source_language} to {target_language} "
                          f"({register} register), with "
                          f"{len(examples)} aligned examples.")
                print(f"Inferred copied slot templates: {source_template} => "
                      f"{target_template}")
            except (OSError, ValueError) as error:
                print(f"Could not infer a safe translation frame: {error}")
            continue
        translation_result = translation_model.translate(line)
        if translation_result is not None:
            print(f"CRMS> {render_translation(translation_result)}")
            if (translation_result.status == "ambiguous"
                    and translation_result.register is None
                    and len(translation_result.matched_registers) > 1
                    and translation_result.language_pair
                    and translation_result.source_text):
                pending_translation_clarification = (
                    "register",
                    translation_result.language_pair[0],
                    translation_result.language_pair[1],
                    translation_result.matched_registers,
                    translation_result.source_text)
                print("Which register should I use? Reply with one of: "
                      + ", ".join(translation_result.matched_registers) + ".")
            elif (translation_result.status == "ambiguous"
                  and translation_result.matched_source_languages
                  and translation_result.source_text
                  and translation_result.target_language):
                pending_translation_clarification = (
                    "source", "", translation_result.target_language,
                    translation_result.matched_source_languages,
                    translation_result.source_text)
                print("Which source language should I use? Reply with one of: "
                      + ", ".join(
                          translation_result.matched_source_languages) + ".")
            _save_pending_translation(
                args.translation_session, args.translations,
                pending_translation_clarification)
            continue
        if (_natural_research_explanation_request(line)
                and last_research_evidence is not None):
            print("CRMS> " + _render_research_explanation(
                index, last_research_evidence, translation_model,
                question=line))
            continue
        paper_authors_reference = _natural_paper_authors_request(line)
        if paper_authors_reference is not None:
            dialogue.clear()
            authors_text, last_research_evidence = _render_paper_authors(
                index, paper_authors_reference)
            if authors_text:
                print("CRMS> " + authors_text)
                continue
        main_result_reference = _natural_main_result_request(line)
        if main_result_reference is not None:
            dialogue.clear()
            main_result_text, last_research_evidence = _render_main_result(
                index, main_result_reference)
            print("CRMS> " + main_result_text)
            continue
        if _natural_corpus_topics_request(line):
            dialogue.clear()
            print("CRMS> " + _render_corpus_topics(index))
            continue
        described_paper_topic = _natural_paper_description_request(line)
        if described_paper_topic is not None:
            dialogue.clear()
            list_text, latest_research_documents = _render_research_list(
                index, described_paper_topic)
            print("CRMS> " + list_text)
            continue
        research_list_topic = _natural_research_list_request(line)
        if research_list_topic is not None:
            dialogue.clear()
            list_text, latest_research_documents = _render_research_list(
                index, research_list_topic)
            print("CRMS> " + list_text)
            continue
        source_lookup_topic = _natural_source_lookup_topic(line)
        if source_lookup_topic is not None:
            dialogue.clear()
            print("CRMS> " + _render_source_lookup(index, source_lookup_topic))
            last_research_evidence = None
            latest_research_documents = []
            continue
        code_instruction = natural_language_request(line)
        if code_instruction is not None:
            generated_code = generate_python(rules, code_instruction)
            if generated_code is None:
                generated_code = generate_math_python(
                    math_model, code_instruction,
                    grounded_cardinals=rules.grounded_cardinal_phrases())
            if generated_code is None:
                generated_code = generate_unit_conversion_python(
                    math_model, code_instruction)
            if generated_code is not None:
                last_generated_code = generated_code
            print(f"CRMS> {render_codegen(generated_code, code_instruction)}")
            continue
        latest_topic = _natural_latest_research_request(line)
        if latest_topic is not None:
            # This route bypasses CRMSDialogue, so explicitly end any prior
            # entity focus before starting a new research topic. Paper ordinal
            # follow-ups keep their separate source-list context below.
            dialogue.clear()
            latest_text, last_research_evidence, latest_research_documents = (
                _render_latest_research(index, latest_topic))
            print(f"CRMS> {latest_text}")
            continue
        paper_ordinal = _paper_ordinal_followup(line)
        if paper_ordinal is not None:
            if paper_ordinal >= len(previous_latest_documents):
                if previous_latest_documents:
                    print("CRMS> The most recent result contains only "
                          f"{len(previous_latest_documents)} paper(s). Ask about "
                          "one of the listed titles or request another topic.")
                else:
                    print("CRMS> I don't have a recent paper list to resolve "
                          "that reference. Name the paper or ask for the latest "
                          "research in a topic first.")
                continue
            selected_paper = previous_latest_documents[paper_ordinal]
            paper_hit = next((hit for hit in index.search(
                selected_paper["title"], limit=50, context_chars=240)
                if hit.document_id == selected_paper["document_id"]), None)
            if paper_hit is None:
                print("CRMS> I can no longer verify that paper in the current "
                      "source index. Ask for the latest result again.")
                continue
            selected_document = index.document(selected_paper["document_id"])
            abstract_match = re.search(
                r"(?im)^Abstract:\s*(.+)$", selected_document.text)
            if abstract_match is None:
                print("CRMS> I found the selected paper, but its indexed "
                      "record has no abstract to summarize. Ask for its "
                      "authors or title instead.")
                continue
            abstract = abstract_match.group(1).strip()
            sentences = [part.strip() for part in
                         re.split(r"(?<=[.!?])\s+", abstract) if part.strip()]
            summary_lines = [f"Extractive summary for: "
                             f"{selected_paper['title']}"]
            for sentence in sentences[:3]:
                start = selected_document.text.find(
                    sentence, abstract_match.start(1))
                if start < 0:
                    continue
                sentence_hit = SearchHit(
                    paper_hit.document_id, paper_hit.title,
                    paper_hit.location, paper_hit.score, sentence, start,
                    start + len(sentence), tuple(normalized_tokens(sentence)))
                try:
                    citation = index.citation(sentence_hit)
                except (KeyError, ValueError):
                    continue
                summary_lines.append(
                    f"- {sentence} [Source: {selected_paper['title']}; "
                    f"{citation}]")
            if len(summary_lines) == 1:
                print("CRMS> I found the selected paper, but couldn't "
                      "produce a citable summary from its abstract.")
            else:
                print("CRMS> " + "\n".join(summary_lines))
            continue
        if _is_paper_comparison_followup(line):
            if previous_latest_documents:
                titles = "; ".join(
                    item["title"] for item in previous_latest_documents)
                print("CRMS> I have the recent paper list, but I can't establish "
                      "agreement from the abstracts without comparing their "
                      "claims. I can summarize them individually; to compare, "
                      "name the papers and the claim you want checked. Papers: "
                      + titles)
            else:
                print("CRMS> Which papers do you mean? Name them or ask for a "
                      "topic first. I won't infer agreement from unrelated "
                      "matching words.")
            continue
        math_result = math_model.ask(line)
        if (math_result is not None and math_result.status == "unknown"
                and (math_result.request or "").startswith(
                    "I have no grounded cardinal value")):
            math_result = math_model.ask(
                line, grounded_cardinals=rules.grounded_cardinal_phrases())
        if math_result is not None:
            print(f"CRMS> {render_math(math_result)}")
            continue
        if _unsupported_mathematical_proof_request(line):
            print("CRMS> I don't have a verified proof rule for that "
                  "mathematical claim. My current math route handles exact "
                  "arithmetic and learned operations; it cannot establish "
                  "general theorem proofs yet. I won't use a loosely matching "
                  "paper as a proof.")
            continue
        contrast_pair = _natural_contrast_pair(line)
        if contrast_pair is not None:
            dialogue.clear()
            print("CRMS> " + _answer_contrast_from_sources(
                index, *contrast_pair))
            continue
        summary_followup = _natural_summary_followup(line)
        if summary_followup is not None and last_summary_query is not None:
            action, requested_count = summary_followup
            previous_limit = last_summary_limit
            if action == "set":
                last_summary_limit = requested_count or previous_limit
            elif action == "more":
                last_summary_limit = min(20, previous_limit + 2)
            else:
                last_summary_limit = max(1, previous_limit - 1)
            terms = tuple(sorted({record["text"]
                                  for record in last_summary_licenses}))
            summary = index.summarize(
                last_summary_query, limit=last_summary_limit,
                retrieval_terms=terms,
                expansion_licenses=last_summary_licenses,
                precomputed_hits=([last_summary_scoped_hit]
                                  if last_summary_scoped_hit is not None else None))
            if action == "more" and len(summary.sentences) <= previous_limit:
                print("CRMS> No additional matching source sentences are available "
                      "within the summary limit.")
            print(f"CRMS> {summary.render()}")
            continue
        summary_query = (line[len("/summarize "):].strip()
                         if line.startswith("/summarize ") else
                         _natural_summary_request(line))
        if summary_query:
            research_result = knowledge.research(summary_query, index)
            expansion_records = {}
            for record in research_result.query_expansions or []:
                key = (record.get("kind"), record.get("evidence"),
                       record.get("text"),
                       tuple(record.get("sources", ())),
                       tuple(record.get("rules", ())))
                expansion_records[key] = {
                    "kind": key[0], "evidence": key[1], "text": key[2],
                    "sources": key[3], "rules": key[4],
                }
            expansion_licenses = tuple(
                expansion_records[key] for key in sorted(expansion_records))
            retrieval_terms = tuple(sorted({record["text"]
                                            for record in expansion_licenses}))
            last_summary_query = summary_query
            last_summary_licenses = expansion_licenses
            last_summary_limit = 5
            last_summary_scoped_hit = _paper_scoped_summary_hit(
                index, summary_query)
            if last_summary_scoped_hit is None:
                last_summary_scoped_hit = _acronym_scoped_summary_hit(
                    index, summary_query)
            if last_summary_scoped_hit is False:
                if re.search(r"\b(?:paper|article|study|publication)\b",
                             summary_query, flags=re.IGNORECASE):
                    print("CRMS> Give me more of the paper's title. I need "
                          "enough detail to identify one source.")
                else:
                    print("CRMS> I couldn't identify one source that covers "
                          "the requested topic. Name a source or add a more "
                          "specific topic.")
                last_summary_query = None
                last_summary_scoped_hit = None
                continue
            summary = index.summarize(
                summary_query, retrieval_terms=retrieval_terms,
                expansion_licenses=expansion_licenses,
                precomputed_hits=([last_summary_scoped_hit]
                                  if last_summary_scoped_hit is not None else None))
            print(f"CRMS> {summary.render()}")
            continue
        natural_rule = _natural_rule_requests(line)
        if natural_rule is not None:
            instruction, input_lists = natural_rule
            predictions = [rules.predict(instruction, values)
                           for values in input_lists]
            unresolved = next((prediction for prediction in predictions
                              if prediction.status != "ok"), None)
            if unresolved is None:
                for prediction in predictions:
                    print(f"CRMS> {prediction.output}")
            else:
                pending_rule = (
                    (instruction, unresolved.contrastive_input)
                    if unresolved.contrastive_input is not None else None)
                _save_pending_rule(args.rule_session, args.rules, pending_rule)
                print(f"CRMS> {unresolved.request or unresolved.message or unresolved.status}")
            continue
        timeline_request = _NATURAL_TIMELINE_REQUEST_RE.fullmatch(line)
        if timeline_request is not None:
            subject, order_by = (value.strip()
                                 for value in timeline_request.groups())
            result = knowledge.write_timeline(subject, order_by=order_by)
            print(f"CRMS> {result.text}")
            if result.statements:
                dialogue.last_question = None
                dialogue.last_selected_answer = None
                dialogue.last_writing_subject = None
                dialogue.last_writing_request = None
                dialogue.last_timeline_subject = result.subject or subject
                dialogue.last_timeline_order_by = order_by
            else:
                dialogue.clear()
            continue
        turn = dialogue.turn(line, research_index=index)
        retrieved_source_sentences = (
            list(turn.research.source_sentences or [])
            if turn.research is not None else [])
        irregular_form_candidate = None
        irregular_form_route_used = False
        if (turn.status in {"unknown", "sources_found"}
                and not (turn.response is not None
                         and turn.response.status in {"answered", "ambiguous"})
                and not (turn.research is not None
                         and turn.research.realized_answer is not None)):
            irregular_form_candidate = _natural_object_wh_form_candidate(
                index, line)
            if irregular_form_candidate is not None and turn.research is not None:
                irregular_form_route_used = True
                evidence = next((item for item in
                                 irregular_form_candidate.language_evidence
                                 if item.get("kind")
                                 == "surface_relation_discovery"), {})
                source_title = index.document(
                    irregular_form_candidate.source.split("#", 1)[0]).title
                surface = str(evidence.get("predicate_phrase", ""))
                base = irregular_form_candidate.relation
                turn.text = (
                    f"I found a possible wording match on {source_title}: "
                    f"“{irregular_form_candidate.sentence}” The source uses "
                    f"'{surface}' where your question uses '{base}'. I haven't "
                    "learned that these forms share a relation; review the "
                    "claim before I use it.")
                turn.research.candidates = [irregular_form_candidate]
                turn.research.status = "needs_review"
                turn.research.source_sentences = [{
                    "document_id": irregular_form_candidate.source.split("#", 1)[0],
                    "title": source_title,
                    "text": irregular_form_candidate.sentence,
                    "citation": irregular_form_candidate.source,
                    "context_kind": "assertion",
                }]
        typed_relation_query = _natural_typed_relation_question(line)
        typed_relation_route_used = False
        if (typed_relation_query is not None
                and turn.status in {"unknown", "sources_found", "needs_review"}
                and not (turn.response is not None
                         and turn.response.status in {"answered", "ambiguous"})):
            typed_relation_route_used = True
            requested_phrase = tuple(normalized_tokens(
                " ".join(typed_relation_query[1:3])))
            expansions = (turn.research.query_expansions
                         if turn.research is not None else [])
            active_families = {
                str(item.get("evidence", ""))
                for item in expansions
                if item.get("kind") == "licensed_predicate"
                and tuple(normalized_tokens(item.get("text", "")))
                    == requested_phrase
                and item.get("evidence")}
            licensed_families: dict[str, set[str]] = {}
            # One learned surface phrase mapping to multiple canonical
            # relations is ambiguous. Do not broaden retrieval through that
            # mapping; the direct wording can still be searched on its own.
            if len(active_families) == 1:
                for item in expansions:
                    family = str(item.get("evidence", ""))
                    if (item.get("kind") == "licensed_predicate"
                            and family in active_families
                            and item.get("text")):
                        licensed_families.setdefault(family, set()).add(
                            str(item["text"]))
            typed_result = _natural_typed_relation_source_evidence(
                index, typed_relation_query, line, licensed_families)
            all_candidates: list[FactCandidate] = []
            evidence_candidates: list[FactCandidate] = []
            stored_positive = {
                (tuple(normalized_tokens(fact.subject)),
                 tuple(normalized_tokens(fact.relation)),
                 tuple(normalized_tokens(fact.object)))
                for fact in knowledge.facts()}
            stored_negative = {
                (tuple(normalized_tokens(fact.subject)),
                 tuple(normalized_tokens(fact.relation)),
                 tuple(normalized_tokens(fact.object)))
                for fact in knowledge.negative_facts()}
            supported = []
            type_conflicts = []
            for item in typed_result["matches"]:
                relations = item["relation"]
                types = item["type"]
                evidence_candidates.extend(relations)
                evidence_candidates.extend(types)

                def known_polarity(candidate: FactCandidate,
                                   store: set[tuple[tuple[str, ...], ...]]) -> bool:
                    key = (tuple(normalized_tokens(candidate.subject)),
                           tuple(normalized_tokens(candidate.relation)),
                           tuple(normalized_tokens(candidate.object)))
                    return key in store

                for candidate in (*relations, *types):
                    same_polarity = (stored_positive if candidate.polarity
                                     else stored_negative)
                    if not known_polarity(candidate, same_polarity):
                        all_candidates.append(candidate)
                positive_relations = [
                    fact for fact in relations
                    if fact.polarity or known_polarity(fact, stored_positive)]
                negative_relations = [
                    fact for fact in relations
                    if not fact.polarity or known_polarity(fact, stored_negative)]
                positive_types = [
                    fact for fact in types
                    if fact.polarity or known_polarity(fact, stored_positive)]
                negative_types = [
                    fact for fact in types
                    if not fact.polarity or known_polarity(fact, stored_negative)]
                if ((positive_types and negative_types)
                        or (positive_relations and negative_relations)):
                    type_conflicts.append(item)
                elif positive_relations and positive_types:
                    supported.append((item, positive_relations[0],
                                      positive_types[0], None))
                elif positive_relations:
                    # A requested type may be established through an accepted
                    # taxonomy, for example Serein River is-a river and river
                    # is-a waterway. Require the explicit transitive schema
                    # and keep its independently checked proof for rendering.
                    inferred_types = [
                        knowledge.infer_relation(
                            relation_fact.subject, "is-a",
                            typed_result["requested_type"])
                        for relation_fact in positive_relations]
                    contradictory_type = any(
                        result.status in {"ambiguous", "contradicted"}
                        for result in inferred_types)
                    inferred_positive = next((result for result in inferred_types
                                              if result.status == "answered"
                                              and result.conclusion is not None
                                              and result.conclusion.get("object", "").casefold()
                                                  == typed_result["requested_type"].casefold()
                                              and result.proofs), None)
                    # A direct negative type claim is relevant even when the
                    # accepted taxonomy can derive the requested type. Never
                    # let that positive proof silently override source evidence.
                    if contradictory_type or negative_types:
                        type_conflicts.append(item)
                    elif inferred_positive is not None:
                        supported.append((
                            item, positive_relations[0], None,
                            inferred_positive.proofs[0]))
            if type_conflicts:
                names = ", ".join(item["entity"] for item in type_conflicts)
                conflict_sources = []
                for item in type_conflicts:
                    for candidate in (*item["relation"], *item["type"]):
                        document_id = candidate.source.split("#", 1)[0]
                        try:
                            title = index.document(document_id).title
                        except (KeyError, ValueError):
                            continue
                        if title not in conflict_sources:
                            conflict_sources.append(title)
                    for relation_fact in item["relation"]:
                        if not relation_fact.polarity:
                            continue
                        inferred = knowledge.infer_relation(
                            relation_fact.subject, "is-a",
                            typed_result["requested_type"])
                        for proof in inferred.proofs:
                            proof_sources = []

                            def collect_proof_sources(node: dict[str, Any]) -> None:
                                for key in ("relation_type_fact", "fact"):
                                    fact = node.get(key)
                                    if isinstance(fact, dict):
                                        proof_sources.extend(
                                            fact.get("sources", ()))
                                for premise in node.get("premises", ()):
                                    if isinstance(premise, dict):
                                        collect_proof_sources(premise)

                            collect_proof_sources(proof)
                            for source_id in proof_sources:
                                document_id = source_id.split("#", 1)[0]
                                try:
                                    title = index.document(document_id).title
                                except (KeyError, ValueError):
                                    continue
                                if title not in conflict_sources:
                                    conflict_sources.append(title)
                    for fact in knowledge.negative_facts():
                        if (tuple(normalized_tokens(fact.subject))
                                == tuple(normalized_tokens(item["entity"]))
                                and tuple(normalized_tokens(fact.relation))
                                == tuple(normalized_tokens("is-a"))
                                and tuple(normalized_tokens(fact.object))
                                == tuple(normalized_tokens(
                                    typed_result["requested_type"]))):
                            for source_id in fact.sources:
                                document_id = source_id.split("#", 1)[0]
                                try:
                                    title = index.document(document_id).title
                                except (KeyError, ValueError):
                                    continue
                                if title not in conflict_sources:
                                    conflict_sources.append(title)
                source_suffix = (f" [Sources: {'; '.join(conflict_sources)}]"
                                 if conflict_sources else "")
                turn.text = (
                    f"Sources conflict about whether {names} is a "
                    f"{typed_result['requested_type']}; review the cited "
                    f"claims before I use it as an answer.{source_suffix}")
            elif len(supported) == 1:
                item, relation_fact, type_fact, type_proof = supported[0]
                source_ids = [relation_fact.source]
                if type_fact is not None:
                    source_ids.append(type_fact.source)

                def add_proof_sources(proof: dict[str, Any]) -> None:
                    relation_type_fact = proof.get("relation_type_fact")
                    if isinstance(relation_type_fact, dict):
                        source_ids.extend(relation_type_fact.get("sources", ()))
                    fact = proof.get("fact")
                    if isinstance(fact, dict):
                        source_ids.extend(fact.get("sources", ()))
                    for premise in proof.get("premises", ()):
                        if isinstance(premise, dict):
                            add_proof_sources(premise)

                if type_proof is not None:
                    add_proof_sources(type_proof)
                source_titles = []
                for source_id in source_ids:
                    document_id = source_id.split("#", 1)[0]
                    try:
                        title = index.document(document_id).title
                    except (KeyError, ValueError):
                        continue
                    if title not in source_titles:
                        source_titles.append(title)
                relation_key = (tuple(normalized_tokens(relation_fact.subject)),
                                tuple(normalized_tokens(relation_fact.relation)),
                                tuple(normalized_tokens(relation_fact.object)))
                type_key = ((tuple(normalized_tokens(type_fact.subject)),
                             tuple(normalized_tokens(type_fact.relation)),
                             tuple(normalized_tokens(type_fact.object)))
                            if type_fact is not None else None)
                relation_accepted = relation_key in stored_positive
                type_accepted = (type_key in stored_positive
                                 if type_key is not None
                                 else type_proof is not None)
                source_label = ("; ".join(source_titles)
                                if source_titles else "accepted knowledge")
                source_predicate = next((str(evidence.get("predicate_phrase"))
                                          for evidence in
                                          relation_fact.language_evidence
                                          if evidence.get("kind")
                                          == "surface_relation_discovery"
                                          and evidence.get("predicate_phrase")),
                                         relation_fact.relation)
                requested_predicate = f"{typed_result['predicate']} {typed_result['preposition']}"
                alignment_note = (
                    f"; source wording '{source_predicate}' is linked to "
                    f"the question wording '{requested_predicate}'"
                    if tuple(normalized_tokens(source_predicate))
                    != tuple(normalized_tokens(requested_predicate)) else "")
                if relation_accepted and type_accepted:
                    type_basis = ("accepted facts" if type_fact is not None
                                  else "an accepted transitive is-a proof")
                    turn.text = (
                        f"{item['entity']} is a {typed_result['requested_type']} "
                        f"that {typed_result['predicate']} "
                        f"{typed_result['preposition']} {typed_result['object']}. "
                        f"[Sources: {source_label}; supported by {type_basis}"
                        f"{alignment_note}]")
                else:
                    if type_proof is not None:
                        type_basis = ("an accepted transitive is-a proof"
                                      if type_accepted else
                                      "a possible type derivation that needs review")
                    else:
                        type_basis = "direct source class evidence"
                    if alignment_note:
                        turn.text = (
                            f"Source sentence: “{relation_fact.sentence}” "
                            f"A reviewed relation alignment links "
                            f"'{source_predicate}' with the question wording "
                            f"'{requested_predicate}'. The type evidence is "
                            f"{type_basis} for a "
                            f"{typed_result['requested_type']}. "
                            f"[Sources: {source_label}; quoted evidence, "
                            "candidate facts still need review]")
                    else:
                        turn.text = (
                            f"{item['entity']} fits: the sources say it "
                            f"{typed_result['predicate']} "
                            f"{typed_result['preposition']} {typed_result['object']} "
                            f"and {type_basis} classifies it as a "
                            f"{typed_result['requested_type']}. "
                            f"[Sources: {source_label}; quoted evidence, not yet "
                            "fully accepted]")
            elif len(supported) > 1:
                names = ", ".join(item[0]["entity"] for item in supported)
                turn.text = (
                    f"The sources support multiple matches: {names}. "
                    "Review the cited relation and type claims to choose "
                    "among them.")
            else:
                relation_only = [
                    (item, fact) for item in typed_result["matches"]
                    for fact in item["relation"] if fact.polarity]
                if relation_only:
                    item, fact = relation_only[0]
                    source_title = index.document(
                        fact.source.split("#", 1)[0]).title
                    turn.text = (
                        f"I found this source sentence: “{fact.sentence}” "
                        f"It supports the relation to {typed_result['object']}, "
                        f"but I couldn't independently verify that the "
                        f"subject is a {typed_result['requested_type']}. "
                        f"[Source: {source_title}; quoted evidence, not an "
                        "accepted fact]")
                else:
                    object_terms = tuple(normalized_tokens(
                        typed_result["object"]))
                    query_content_terms = (
                        set(_research_query_terms(line))
                        - set(object_terms) - _RESEARCH_STOPWORDS)

                    def shares_bounded_word_family(text: str) -> bool:
                        source_terms = normalized_tokens(text)
                        for query_term in query_content_terms:
                            for source_term in source_terms:
                                if source_term == query_term:
                                    return True
                                if (len(query_term) >= 5
                                        and source_term.startswith(query_term)
                                        and source_term[len(query_term):]
                                        in {"er", "ers", "or", "ors",
                                            "ed", "ing", "s"}):
                                    return True
                        return False

                    query_words_for_event = normalized_tokens(line)
                    event_nominal_shape = (
                        query_words_for_event[:1] == ("what",)
                        and typed_result["predicate"]
                        in {"happened", "occurred"})
                    related = None
                    if event_nominal_shape:
                        related = next((
                            row for row in retrieved_source_sentences
                            if row.get("text")
                            and row.get("context_kind", "assertion") == "assertion"
                            and object_terms
                            and shares_bounded_word_family(row["text"])
                            and any(
                                tuple(normalized_tokens(row["text"])[
                                    i:i + len(object_terms)]) == object_terms
                                for i in range(
                                    len(normalized_tokens(row["text"]))
                                    - len(object_terms) + 1))), None)
                    if related is not None:
                        source_title = related.get("title")
                        if not source_title and related.get("citation"):
                            try:
                                source_title = index.document(
                                    related["citation"].split("#", 1)[0]).title
                            except (KeyError, ValueError):
                                source_title = "source"
                        turn.text = (
                            f"The closest related source says: “{related['text']}” "
                            f"It mentions {typed_result['object']}, but it does "
                            f"not establish the requested relation "
                            f"'{typed_result['predicate']} "
                            f"{typed_result['preposition']}'. "
                            f"[Source: {source_title or 'source'}; quoted "
                            "evidence, not an answer to that relation]")
                    else:
                        turn.text = (
                            f"I couldn't find source sentences that support a "
                            f"{typed_result['requested_type']} "
                            f"{typed_result['predicate']} "
                            f"{typed_result['preposition']} "
                            f"{typed_result['object']}; I don't have a grounded "
                            "answer for that question.")
            if turn.research is not None:
                unique_candidates = {}
                for candidate in all_candidates:
                    key = (tuple(normalized_tokens(candidate.subject)),
                           tuple(normalized_tokens(candidate.relation)),
                           tuple(normalized_tokens(candidate.object)),
                           candidate.polarity)
                    unique_candidates.setdefault(key, candidate)
                all_candidates = list(unique_candidates.values())
                turn.research.candidates = all_candidates
                turn.research.status = ("needs_review" if all_candidates
                                        else "unknown")
                exact_sentences = []
                for candidate in evidence_candidates:
                    key = (candidate.source, candidate.sentence)
                    if key in {(item.get("citation"), item.get("text"))
                               for item in exact_sentences}:
                        continue
                    exact_sentences.append({
                        "document_id": candidate.source.split("#", 1)[0],
                        "title": index.document(
                            candidate.source.split("#", 1)[0]).title,
                        "text": candidate.sentence,
                        "citation": candidate.source,
                        "context_kind": "assertion" if candidate.polarity
                        else "ambiguous",
                    })
                turn.research.source_sentences = exact_sentences
        polar_claim = _natural_polar_claim(line)
        polar_route_used = False
        polar_evidence: list[FactCandidate] = []
        if (polar_claim is not None
                and turn.status in {"unknown", "sources_found", "needs_review"}
                and not (turn.response is not None
                         and (turn.response.status in {"answered", "ambiguous"}
                              or turn.response.reason_code
                                 == "missing_premise"))):
            polar_route_used = True
            polar_evidence = _natural_polar_evidence(
                knowledge, index, polar_claim)
            if polar_evidence:
                polar_truths = {candidate.polarity
                                for candidate in polar_evidence}
                turn.research.candidates = polar_evidence
                turn.research.status = "needs_review"
                if len(polar_truths) > 1:
                    turn.text = (
                        "The indexed sources conflict on this exact "
                        "proposition; review the cited claims before I choose "
                        "yes or no.")
                else:
                    candidate = polar_evidence[0]
                    title = index.document(
                        candidate.source.split("#", 1)[0]).title
                    verdict = "yes" if candidate.polarity else "no"
                    turn.text = (
                        f"The source states {verdict}: “{candidate.sentence}” "
                        f"[Source: {title}; quoted evidence, not an accepted fact]")
            else:
                turn.text = (
                    "I don't have a direct source statement for this exact "
                    "proposition, so I can't answer yes or no from the sources "
                    "I have.")
                if turn.research is not None:
                    turn.research.candidates = []
                    turn.research.status = "unknown"
        where_query = _natural_where_lookup(line)
        where_evidence = None
        where_route_used = False
        if (where_query is not None
                and turn.status in {"unknown", "sources_found"}
                and not (turn.response is not None
                         and turn.response.status in {"answered", "ambiguous"})
                and not (turn.response is not None
                         and turn.response.candidates)):
            where_route_used = True
            entity, predicate = where_query
            where_evidence = _exact_title_location_evidence(
                index, entity, predicate)
            if where_evidence is not None:
                turn.text = (
                    f"The source says: {where_evidence['text']} "
                    f"[Source: {where_evidence['title']}; quoted evidence, "
                    "not an accepted fact]")
            else:
                location_labels = {
                    "work": "workplace", "live": "residence",
                    "born": "birthplace", "located": "location",
                    "based": "base",
                }
                location_label = location_labels.get(predicate, "location")
                turn.text = (
                    f"I couldn't find a {location_label} statement for "
                    f"{entity} in the indexed sources.")
        who_question = bool(
            re.match(r"\s*(?:who|whom)\b", line, flags=re.IGNORECASE)
            or re.fullmatch(
                r"\s*.+?\s+(?:was|were|is|are|has\s+been|have\s+been|had\s+been)\s+"
                r"[a-z][\w’'-]*\s+by\s+whom\s*[?!.]?\s*",
                line, flags=re.IGNORECASE))
        who_evidence = None
        realized = None
        who_route_used = False
        conjunctive_who_route_used = False
        coordinated_who = re.fullmatch(
            r"\s*who\s+(?:(?:did|do|does)\s+)?"
            r"(?P<predicate>[a-z][\w’'-]*)\s+"
            r"(?P<first>.+?)\s+and\s+(?P<second>.+?)\s*[?!.]?\s*",
            line, flags=re.IGNORECASE)
        if (coordinated_who is not None
                and coordinated_who.group("predicate").casefold()
                not in {"is", "are", "was", "were", "has", "have", "had"}
                and turn.status in {"unknown", "sources_found", "needs_review"}):
            predicate = coordinated_who.group("predicate")
            objects = [coordinated_who.group("first").strip(),
                       coordinated_who.group("second").strip()]
            evidence_by_object = [
                _natural_who_evidence(
                    index, f"Who {predicate} {object_}?",
                    (turn.research.query_expansions
                     if turn.research is not None else []))
                for object_ in objects
            ]
            found = [(object_, evidence)
                     for object_, evidence in zip(objects, evidence_by_object)
                     if evidence is not None]
            if found:
                rendered = []
                for object_, evidence in found:
                    realized_part = evidence.get("realized_answer") or {}
                    sentence = realized_part.get("text") or evidence.get("text")
                    title = (realized_part.get("source_title")
                             or evidence.get("title") or "source")
                    if sentence:
                        rendered.append(
                            f"{object_}: “{sentence}” [Source: {title}]")
                missing = [object_ for object_, evidence in
                           zip(objects, evidence_by_object)
                           if evidence is None]
                if missing:
                    turn.text = (
                        "Partial source evidence: " + "; ".join(rendered)
                        + ". I couldn't find evidence for "
                        + " and ".join(missing)
                        + ", so this does not answer every part of your question.")
                else:
                    turn.text = "Source evidence: " + "; ".join(rendered)
                conjunctive_who_route_used = True
                who_route_used = True
        if (who_question and not conjunctive_who_route_used
                and turn.status in {"unknown", "sources_found", "needs_review"}
                and not (turn.response is not None
                         and turn.response.status in {"answered", "ambiguous"})
                and (turn.status != "needs_review"
                     or (turn.research is not None
                         and turn.research.candidates))):
            who_evidence = _natural_who_evidence(
                index, line,
                (turn.research.query_expansions
                 if turn.research is not None else []))
            normalized_who_question = str(
                who_evidence.get("normalized_question", line)
                if who_evidence is not None else line)
            if who_evidence is None and turn.research is not None:
                passive_match = re.fullmatch(
                    r"\s*(?P<object>.+?)\s+(?:was|were|is|are|has\s+been|have\s+been|had\s+been)\s+"
                    r"(?P<predicate>[a-z][\w’'-]*)\s+by\s+whom\s*[?!.]?\s*",
                    line, flags=re.IGNORECASE)
                if passive_match is not None:
                    object_text = re.sub(
                        r"^(?:a|an|the)\s+", "",
                        passive_match.group("object").strip(),
                        flags=re.IGNORECASE)
                    normalized_who_question = (
                        f"Who {passive_match.group('predicate')} "
                        f"{object_text}?")
                    source_sentences = turn.research.source_sentences or []
                    passive_realization = (
                        CRMSKnowledgeBase._realize_question_from_passive_source(
                            normalized_who_question, source_sentences,
                            turn.research.query_expansions))
                    if passive_realization is not None:
                        source = next((item for item in source_sentences
                                       if item.get("citation")
                                       == passive_realization.get("citation")),
                                      None)
                        if source is not None:
                            who_evidence = dict(source)
                            who_evidence["normalized_question"] = normalized_who_question
                            who_evidence["realized_answer"] = passive_realization
            if (who_evidence is not None
                    and not who_evidence.get("ambiguous_pages")
                    and not who_evidence.get("realized_answer")):
                realization_question = str(
                    who_evidence.get("normalized_question", line))
                realization_source = dict(who_evidence)
                realization_source.setdefault("context_kind", "assertion")
                expansions = (turn.research.query_expansions
                             if turn.research is not None else [])
                realized_from_evidence = (
                    CRMSKnowledgeBase._realize_question_from_passive_source(
                        realization_question, [realization_source], expansions))
                if realized_from_evidence is not None:
                    who_evidence["realized_answer"] = realized_from_evidence
            realized = (who_evidence.get("realized_answer")
                        if who_evidence is not None else None)
            if (realized is None and turn.research is not None):
                realized = turn.research.realized_answer
            if realized is not None:
                realized_citation = realized.get("citation")
                matching_source = next((item for item in
                                        (turn.research.source_sentences or [])
                                        if item.get("citation")
                                        == realized_citation), None)
                if matching_source is not None:
                    who_evidence = dict(matching_source)
            if (who_evidence is not None
                    and who_evidence.get("ambiguous_pages")):
                who_route_used = True
                page_names = ", ".join(who_evidence["ambiguous_pages"][:4])
                turn.text = (
                    f"I found more than one exact-title source for "
                    f"'{line.strip()}': {page_names}. Which page do you mean?")
            elif who_evidence is not None:
                reviewable = _reviewable_who_candidates(
                    knowledge, index,
                    str(who_evidence.get("normalized_question", line)),
                    who_evidence)
                if (not reviewable and realized is not None
                        and realized.get("method")
                        == "exact-title page-subject passive realization"
                        and who_evidence.get("text")
                        and who_evidence.get("citation")):
                    relation = str(realized["predicate"])
                    subject = str(realized["agent"])
                    object_ = str(realized["object"])
                    reviewable = [FactCandidate(
                        subject, relation, object_,
                        str(who_evidence["citation"]),
                        f"<subject> {relation} <object>",
                        str(who_evidence["text"]), True,
                        language_evidence=({
                            "kind": "page_title_coreference",
                            "method": "exact-title page-subject passive realization",
                            "predicate_phrase": relation,
                            "page_title": who_evidence.get("title", ""),
                            "question": line,
                            "review_required": True,
                            "warning": ("The pronoun is resolved to the exact "
                                        "source page title; confirm the relation "
                                        "and agent against the cited sentence."),
                        },),
                    )]
                if reviewable and turn.research is not None:
                    who_route_used = True
                    if realized is not None:
                        turn.text = (
                            f"{realized['text']} [Source: "
                            f"{realized['source_title']}; quoted evidence, "
                            "not an accepted fact]")
                    else:
                        turn.text = (
                            f"The source identifies: {who_evidence['text']} "
                            f"[Source: {who_evidence['title']}; quoted evidence, "
                            "not an accepted fact]")
                    turn.research.candidates = reviewable
                    turn.research.status = "needs_review"
                elif realized is not None:
                    who_route_used = True
                    turn.text = (
                        f"{realized['text']} [Source: "
                        f"{realized['source_title']}; quoted evidence, "
                        "not an accepted fact]")
                elif turn.status != "needs_review":
                    who_route_used = True
                    turn.text = (
                        f"The source identifies: {who_evidence['text']} "
                        f"[Source: {who_evidence['title']}; quoted evidence, "
                        "not an accepted fact]")
            elif realized is not None and turn.status != "needs_review":
                who_route_used = True
                turn.text = (
                    f"{realized['text']} [Source: "
                    f"{realized['source_title']}; quoted evidence, "
                    "not an accepted fact]")
            elif turn.status != "needs_review":
                who_route_used = True
                turn.text = (
                    "I couldn't find one source sentence that states who "
                    "answers that question.")
        object_wh_evidence = None
        object_wh_route_used = False
        if (irregular_form_candidate is None
                and turn.status in {"unknown", "sources_found"}
                and not (turn.response is not None
                         and turn.response.status in {"answered", "ambiguous"})):
            known_relations = {
                tuple(normalized_tokens(fact.relation))
                for fact in (*knowledge.facts(), *knowledge.negative_facts())
            }
            object_wh_evidence = _natural_object_wh_source_evidence(
                index, line, known_relations=known_relations)
            if object_wh_evidence is not None:
                object_wh_route_used = True
                title = object_wh_evidence.get("title") or "source"
                if turn.research is not None:
                    turn.research.source_sentences = [object_wh_evidence]
                    candidate = object_wh_evidence.get("candidate")
                    if isinstance(candidate, FactCandidate):
                        turn.research.candidates = [candidate]
                        turn.research.status = "needs_review"
                        discovery = next((item for item in
                                          candidate.language_evidence
                                          if item.get("kind")
                                          == "surface_relation_discovery"), {})
                        if (discovery.get("method")
                                == "reviewed relation-alignment hypothesis"):
                            turn.text = (
                                f"Possible relation alignment for review: "
                                f"your question uses '{candidate.relation}', "
                                f"while the source uses "
                                f"'{discovery.get('predicate_phrase', '')}'. "
                                "I haven't learned that they share a relation.\n"
                                f"Candidate: {candidate.subject} — "
                                f"{candidate.relation} → {candidate.object}.\n"
                                f"Evidence: {candidate.sentence}\nSource: {title}")
                        else:
                            turn.text = (
                                f"{candidate.sentence} [Source: {title}; "
                                "source claim awaiting review, not yet an "
                                "accepted fact]")
                    else:
                        turn.text = (
                            f"The source sentence says: “{object_wh_evidence['text']}” "
                            f"[Source: {title}; quoted evidence, not an accepted fact]")
        why_question = bool(re.match(r"\s*why\b", line, flags=re.IGNORECASE))
        why_evidence = None
        why_route_used = False
        if (why_question and turn.status in {"unknown", "sources_found"}
                and not (turn.response is not None
                         and turn.response.status in {"answered", "ambiguous"})
                and not (turn.response is not None
                         and turn.response.candidates)):
            why_route_used = True
            why_evidence = _natural_why_evidence(index, line)
            if why_evidence is not None:
                turn.text = (
                    f"The source gives this reason: {why_evidence['text']} "
                    f"[Source: {why_evidence['title']}; quoted evidence, "
                    "not an accepted fact]")
            else:
                turn.text = (
                    "I found topic matches, but no retrieved sentence states "
                    "a cause. Try a more specific question or add a source.")
        definition_topic = _natural_definition_topic(line)
        definition_evidence = None
        if (definition_topic is not None
                and turn.status in {"unknown", "sources_found"}
                and not (turn.response is not None
                         and turn.response.status in {"answered", "ambiguous"})
                and not (turn.response is not None
                         and turn.response.candidates)):
            definition_title_hits = _exact_title_hits(index, definition_topic)
            definition_evidence = (_exact_title_definition(
                index, definition_topic) if len(definition_title_hits) == 1
                else None)
            if definition_evidence is not None:
                turn.text = (
                    f"{definition_evidence['text']} [Source: "
                    f"{definition_evidence['title']}; quoted evidence, "
                    "not an accepted fact]")
            elif len(definition_title_hits) > 1:
                turn.text = (
                    f"I found several exact-title sources for "
                    f"{definition_topic}. Which one should I use?")
        source_realization = (
            turn.research.realized_answer
            if turn.research is not None else None)
        stored_fact_source_answer = None
        if (turn.response is not None
                and turn.response.status == "answered"
                and turn.response.truth is None
                and not turn.response.inference_proofs
                and not who_route_used and not typed_relation_route_used
                and not polar_route_used and not where_route_used
                and not why_route_used and definition_topic is None):
            for fact_evidence in turn.response.evidence or []:
                for citation in fact_evidence.get("sources", ()):
                    try:
                        excerpt = index.resolve_citation(citation)
                        source_document = index.document(
                            citation.split("#", 1)[0])
                    except (KeyError, ValueError):
                        continue
                    stored_fact_source_answer = (
                        f"{excerpt} [Source: {source_document.title}; "
                        "accepted fact]")
                    break
                if stored_fact_source_answer is not None:
                    break
        if stored_fact_source_answer is not None:
            turn.text = stored_fact_source_answer
        if (source_realization is not None and not who_route_used
                and not typed_relation_route_used and not polar_route_used
                and not where_route_used and not why_route_used
                and not object_wh_route_used
                and definition_topic is None):
            turn.text = (
                f"{source_realization['text']} [Source: "
                f"{source_realization.get('source_title') or 'source'}; "
                "quoted evidence, not an accepted fact]")
        print(f"CRMS> {turn.text}")
        if typed_relation_route_used:
            source_rows = (turn.research.source_sentences
                           if turn.research is not None else [])
            last_research_evidence = (dict(source_rows[0])
                                      if source_rows else None)
        elif polar_route_used:
            if polar_evidence:
                candidate = polar_evidence[0]
                last_research_evidence = {
                    "document_id": candidate.source.split("#", 1)[0],
                    "citation": candidate.source,
                    "text": candidate.sentence,
                }
            else:
                last_research_evidence = None
        elif where_route_used:
            last_research_evidence = where_evidence
        elif who_route_used:
            last_research_evidence = who_evidence
        elif object_wh_route_used:
            last_research_evidence = object_wh_evidence
        elif why_route_used:
            last_research_evidence = why_evidence
        elif definition_evidence is not None:
            last_research_evidence = definition_evidence
        elif irregular_form_route_used and irregular_form_candidate is not None:
            last_research_evidence = {
                "document_id": irregular_form_candidate.source.split("#", 1)[0],
                "citation": irregular_form_candidate.source,
                "text": irregular_form_candidate.sentence,
                "title": index.document(
                    irregular_form_candidate.source.split("#", 1)[0]).title,
            }
        elif source_realization is not None:
            last_research_evidence = {
                "document_id": source_realization.get("document_id"),
                "citation": source_realization.get("citation"),
                "text": source_realization.get("text"),
                "title": source_realization.get("source_title"),
            }
        elif stored_fact_source_answer is not None:
            fact_evidence = next((item for item in
                                  (turn.response.evidence or [])
                                  if item.get("sources")), {})
            citation = next(iter(fact_evidence.get("sources", ())), None)
            last_research_evidence = ({
                "document_id": citation.split("#", 1)[0],
                "citation": citation,
                "text": index.resolve_citation(citation),
                "title": index.document(
                    citation.split("#", 1)[0]).title,
            } if citation else None)
        elif (turn.research is not None
                and turn.research.status in {"sources_found", "answered"}):
            source_rows = turn.research.source_sentences or []
            if source_rows:
                last_research_evidence = dict(source_rows[0])
            elif turn.research.passages:
                passage = turn.research.passages[0]
                citation = passage.get("citation", "")
                last_research_evidence = {
                    "document_id": citation.split("#", 1)[0],
                    "citation": citation,
                }
            else:
                last_research_evidence = None
        else:
            last_research_evidence = None
        if (auto_practice_questions and turn.status == "answered"
                and turn.response is not None
                and turn.response.inference_proofs):
            try:
                _answer, retained = knowledge.practice_question(
                    turn.resolved_question)
                if retained:
                    knowledge.save(args.knowledge)
                    print("Auto-practice stored the verified inference as a "
                          "separate derived case.")
                else:
                    print("Auto-practice skipped: the answer did not resolve to "
                          "one unique, proof-backed conclusion.")
            except (OSError, TypeError, ValueError) as error:
                print(f"Auto-practice could not retain this answer: {error}")
        if (turn.research and turn.research.status == "needs_review"
                and turn.research.candidates):
            new_candidates = list(turn.research.candidates)
            # A source proposal can coexist with a direct accepted answer
            # because retrieval searches more broadly than the answer route.
            # Keep only candidates tied to at least two meaningful query terms
            # in that case; unrelated proposals should not interrupt the
            # answer or enter the conversational review queue.
            if (turn.response is not None
                    and turn.response.status == "answered"):
                new_candidates = _candidates_relevant_to_answer(
                    turn.resolved_question or line, new_candidates)
            existing_keys = set()
            if pending_candidates_before_turn:
                existing_keys = {
                    (candidate.source,
                     tuple(normalized_tokens(candidate.subject)),
                     tuple(normalized_tokens(candidate.relation)),
                     tuple(normalized_tokens(candidate.object)),
                     candidate.polarity)
                    for candidate in pending_candidates}
                new_keys = {
                    (candidate.source,
                     tuple(normalized_tokens(candidate.subject)),
                     tuple(normalized_tokens(candidate.relation)),
                     tuple(normalized_tokens(candidate.object)),
                     candidate.polarity)
                    for candidate in new_candidates}
                merged = {}
                for candidate in (*pending_candidates, *new_candidates):
                    key = (candidate.source,
                           tuple(normalized_tokens(candidate.subject)),
                           tuple(normalized_tokens(candidate.relation)),
                           tuple(normalized_tokens(candidate.object)),
                           candidate.polarity)
                    merged.setdefault(key, candidate)
                pending_candidates = list(merged.values())
                # Several questions contributed to this queue, so there is no
                # single query to rerun after its final candidate is accepted.
                pending_question = ""
            else:
                pending_candidates = new_candidates
                pending_question = turn.resolved_question
            _save_pending_candidates(args.candidate_session, args.knowledge,
                                     args.index, pending_candidates, pending_question,
                                     invalidated_candidates)
            review_to_show = [
                (number, candidate)
                for number, candidate in enumerate(pending_candidates, 1)
                if not pending_candidates_before_turn
                or (candidate.source,
                    tuple(normalized_tokens(candidate.subject)),
                    tuple(normalized_tokens(candidate.relation)),
                    tuple(normalized_tokens(candidate.object)),
                    candidate.polarity) not in existing_keys]
            has_direct_answer = (
                turn.status == "answered"
                or (who_route_used and realized is not None))
            if review_to_show and has_direct_answer:
                count = len(review_to_show)
                noun = "claim" if count == 1 else "claims"
                print(f"{count} source {noun} available for review; "
                      "use /pending-candidates to inspect.")
            elif (review_to_show and turn.research is not None
                  and turn.research.status == "needs_review"):
                rendered_sources = {
                    candidate.source for _, candidate in review_to_show
                    if candidate.sentence
                    and candidate.sentence in (turn.text or "")
                }
                if rendered_sources:
                    count = len(rendered_sources)
                    noun = "claim" if count == 1 else "claims"
                    print(f"{count} source {noun} awaiting review; "
                          "use /pending-candidates to inspect.")
                else:
                    for number, candidate in review_to_show:
                        polarity = "positive" if candidate.polarity else "negative"
                        print(f"Review candidate {number}: {candidate.subject} — "
                              f"{candidate.relation} → {candidate.object} ({polarity}); "
                              f"say 'accept candidate {number}' or "
                              f"'reject candidate {number}'.")
            elif review_to_show:
                for number, candidate in review_to_show:
                    polarity = "positive" if candidate.polarity else "negative"
                    print(f"Review candidate {number}: {candidate.subject} — "
                          f"{candidate.relation} → {candidate.object} ({polarity}); "
                          f"say 'accept candidate {number}' or "
                          f"'reject candidate {number}'.")


if __name__ == "__main__":
    raise SystemExit(main())
