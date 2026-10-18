"""Check canonical Unicode equivalence across QA, inference, and research."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_chat import _training_sentence
from crms_inference import _key as inference_key
from crms_knowledge import CRMSKnowledgeBase, _tokens as knowledge_tokens
from crms_proof import _key as fact_proof_key
from crms_research import CRMSResearchIndex
from crms_rule_proof import _key as rule_proof_key


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    composed = 'café'
    decomposed = 'cafe\u0301'
    for tokenizer in (knowledge_tokens, inference_key,
                      fact_proof_key, rule_proof_key):
        require(tokenizer(composed) == tokenizer(decomposed),
                f'{tokenizer.__module__} did not normalize canonical forms')

    kb = CRMSKnowledgeBase()
    for person, project in (('Anaïs', 'Café Engine'),
                            ('Benoît', 'Thé Engine')):
        kb.add_fact(person, 'designed', project, f'source:{project}')
        kb.teach_question(
            f'Who designed the {project}?', relation='designed',
            answer_field='subject', bound_entity=project, answer=person)
    dialogue = CRMSDialogue(kb)
    answer = dialogue.turn('Who designed the Cafe\u0301 Engine?')
    require(answer.status == 'answered' and answer.response is not None
            and answer.response.answer == 'Anaïs',
            f'Unicode-normalized fact question failed: {answer}')
    correction = dialogue.turn('Actually, I meant The\u0301 Engine.')
    require(correction.status == 'answered' and correction.response is not None
            and correction.response.answer == 'Benoît'
            and correction.resolved_question.endswith('The\u0301 Engine?'),
            f'Unicode-normalized dialogue repair failed: {correction}')

    inference_kb = CRMSKnowledgeBase()
    inference_kb.add_fact('Ada', 'café links', 'Bridge', 'source:a')
    inference_kb.add_fact('Bridge', 'connects', 'Cedar', 'source:b')
    inference_kb.add_inference_rule(
        'chain', 'cafe\u0301 links', 'connects', 'reaches')
    inference = inference_kb.infer_relation('Ada', 'reaches', 'Cedar')
    require(inference.status == 'answered' and inference.proofs,
            f'proof-checked inference failed across Unicode forms: {inference}')

    research = CRMSResearchIndex()
    source_text = 'Anaïs designed the Café Engine for research.'
    research.add_document('cafe-source', 'Café project', source_text)
    hits = research.search('Cafe\u0301 Engine')
    require(hits and hits[0].document_id == 'cafe-source'
            and hits[0].matched_terms == ('café', 'engine')
            and source_text[hits[0].match_start:hits[0].match_end]
            == 'Café Engine',
            f'Unicode-normalized research retrieval or offsets failed: {hits}')
    training_sentence = _training_sentence(
        SimpleNamespace(snippet=source_text), 'Anaïs',
        'Cafe\u0301 Engine', 'designed')
    require(training_sentence == source_text,
            'terminal fact teaching could not align canonical entity spellings')

    # Sentence-frame extraction compares canonical entities after matching
    # learned relative-clause frames. Verify that a decomposed surface spelling
    # still agrees with the composed canonical entity in the resulting claims.
    relative_kb = CRMSKnowledgeBase()
    for subject, relation, obj, source in (
            ('Zoë', 'designed', 'Café Engine', 'frame:design-a'),
            ('René', 'designed', 'Thé Engine', 'frame:design-b'),
            ('Ada', 'built', 'Compiler', 'frame:build-a'),
            ('Mia', 'built', 'Table', 'frame:build-b'),
            ('Café Engine', 'passed', 'alpha', 'frame:pass-a'),
            ('Thé Engine', 'passed', 'beta', 'frame:pass-b')):
        sentence = f'{subject} {relation} {obj}.'
        relative_kb.add_fact(subject, relation, obj, source)
        relative_kb.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj,
            source=source, predicate_phrase=relation)
    relative_sentence = (
        'Zoe\u0308, who designed Cafe\u0301 Engine, built Compiler.')
    relative_proposals = relative_kb.propose_facts(
        relative_sentence, source='review:unicode-relative')
    relative_claims = {
        (knowledge_tokens(item.subject), item.relation,
         knowledge_tokens(item.object))
        for item in relative_proposals
    }
    require(relative_claims == {
        (('zoë',), 'designed', ('café', 'engine')),
        (('zoë',), 'built', ('compiler',)),
    }, f'Unicode-normalized relative-clause extraction failed: {relative_claims}')
    require(len(relative_kb.facts()) == 6,
            'Unicode relative-clause proposal committed evidence automatically')
    object_relative_sentence = (
        'Cafe\u0301 Engine that Zoe\u0308 designed passed certification.')
    object_relative_proposals = relative_kb.propose_facts(
        object_relative_sentence, source='review:unicode-object-relative')
    object_relative_claims = {
        (knowledge_tokens(item.subject), item.relation,
         knowledge_tokens(item.object))
        for item in object_relative_proposals
    }
    require(object_relative_claims == {
        (('café', 'engine'), 'passed', ('certification',)),
        (('zoë',), 'designed', ('café', 'engine')),
    }, 'Unicode-normalized object-relative extraction failed: '
       f'{object_relative_claims}')
    require(len(relative_kb.facts()) == 6
            and all(item.sentence == object_relative_sentence
                    for item in object_relative_proposals),
            'object-relative proposals committed facts or lost source text')

    print('cross-system Unicode canonical language: PASS')
    print('fact question/dialogue repair, independently verified inference, '
          'research token match, and original-text offsets: PASS')


if __name__ == '__main__':
    main()
