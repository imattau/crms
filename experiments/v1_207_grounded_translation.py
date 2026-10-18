"""Validate the example-grounded translation frame and terminal language route."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_translation import (
    CRMSTranslation, infer_shared_slot_templates, render,
)
from crms_chat import (
    _natural_translation_additional, _natural_translation_examples,
    _natural_translation_teaching,
)


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    model = CRMSTranslation()
    examples = [("Hello, Ada.", "Bonjour, Ada."),
                ("Hello, Malik.", "Bonjour, Malik.")]
    try:
        model.teach("English", "French", "formal", "Hello, {name}.",
                    "Bonjour, {name}.", examples[:1])
    except ValueError:
        pass
    else:
        raise SystemExit("one aligned example licensed a translation frame")
    licensed = model.teach("English", "French", "formal", "Hello, {name}.",
                           "Bonjour, {name}.", examples)
    require(licensed.status == "licensed",
            "two aligned examples did not license the declared frame")
    translated = model.translate(
        "Translate from English to French in formal register: Hello, Rowan.")
    require(translated and translated.status == "translated"
            and translated.output == "Bonjour, Rowan."
            and len(translated.evidence) == 2,
            f"held-out slot value was not translated with evidence: {translated}")
    punctuation_omitted = model.translate(
        "Translate from English to French in formal register: Hello, Rowan")
    require(punctuation_omitted and punctuation_omitted.status == "translated"
            and punctuation_omitted.output == "Bonjour, Rowan."
            and punctuation_omitted.evidence == translated.evidence,
            "omitted terminal punctuation prevented a licensed frame match")
    punctuation_changed = model.translate(
        "Translate from English to French in formal register: Hello, Rowan!")
    require(punctuation_changed and punctuation_changed.status == "unknown",
            "a different terminal punctuation mark was silently normalized")
    require("Rowan" in render(translated) and "Hello, Ada." in render(translated),
            "answer did not expose slot preservation and aligned evidence")
    register_inferred = model.translate(
        "Please translate from English to French: Hello, Rowan.")
    require(register_inferred and register_inferred.status == "translated"
            and register_inferred.output == "Bonjour, Rowan."
            and register_inferred.matched_registers == ("formal",),
            "a unique learned register was not usable when omitted")
    inline_request = model.translate(
        "Please translate 'Hello, Rowan.' from English into French.")
    require(inline_request and inline_request.status == "translated"
            and inline_request.output == "Bonjour, Rowan."
            and inline_request.matched_registers == ("formal",),
            "sentence-first translation wording was not routed through learned frames")
    inferred_source = model.translate("Translate ‘Hello, Rowan.’ into French.")
    require(inferred_source and inferred_source.status == "translated"
            and inferred_source.output == "Bonjour, Rowan."
            and inferred_source.language_pair == ("english", "french")
            and inferred_source.evidence == translated.evidence,
            "a quoted target-only request did not infer its uniquely grounded source language")
    how_say = model.translate('How do you say “Hello, Rowan.” in French?')
    require(how_say and how_say.status == "translated"
            and how_say.output == "Bonjour, Rowan."
            and how_say.language_pair == ("english", "french")
            and how_say.evidence == translated.evidence,
            "a natural how-do-you-say request bypassed learned-frame evidence")
    how_would_i_say = model.translate(
        "How would I say 'Hello, Rowan.' in French?")
    require(how_would_i_say and how_would_i_say.status == "translated"
            and how_would_i_say.output == "Bonjour, Rowan."
            and how_would_i_say.evidence == translated.evidence,
            "a natural how-would-I-say request missed the learned frame")
    unquoted_how_say = model.translate("How do you say Hello, Rowan. in French?")
    require(unquoted_how_say and unquoted_how_say.status == "translated"
            and unquoted_how_say.output == "Bonjour, Rowan."
            and unquoted_how_say.evidence == translated.evidence,
            "an unquoted how-do-you-say request did not use the learned frame")
    in_phrase = CRMSTranslation()
    in_phrase.teach(
        "English", "French", "neutral", "I live in {place}.",
        "J'habite à {place}.",
        [("I live in Rome.", "J'habite à Rome."),
         ("I live in Paris.", "J'habite à Paris.")])
    internal_in = in_phrase.translate("How do you say I live in Rome in French?")
    require(internal_in and internal_in.status == "translated"
            and internal_in.output == "J'habite à Rome.",
            "request routing split unquoted source text at an internal 'in'")
    how_say_registered = model.translate(
        "How do I say 'Hello, Rowan.' in French in formal register?")
    require(how_say_registered and how_say_registered.status == "translated"
            and how_say_registered.output == "Bonjour, Rowan."
            and how_say_registered.register == "formal",
            "how-do-I-say request did not preserve its explicit register")
    polite_source_first = model.translate(
        "Could you please translate from English to French in formal register: "
        "Hello, Rowan.")
    require(polite_source_first and polite_source_first.status == "translated"
            and polite_source_first.output == "Bonjour, Rowan."
            and polite_source_first.evidence == translated.evidence,
            "polite source-first translation wording lost frame evidence")
    polite_sentence_first = model.translate(
        "Would you translate 'Hello, Rowan.' from English into French?")
    require(polite_sentence_first and polite_sentence_first.status == "translated"
            and polite_sentence_first.output == "Bonjour, Rowan."
            and polite_sentence_first.evidence == translated.evidence,
            "polite sentence-first translation wording lost frame evidence")

    reordered = CRMSTranslation()
    role_examples = [
        ("Alex sends X17 to Sam.", "Sam reçoit X17 de Alex."),
        ("Mira sends Q4 to Noah.", "Noah reçoit Q4 de Mira."),
    ]
    role_frame = reordered.teach(
        "English", "French", "neutral",
        "{sender} sends {item} to {recipient}.",
        "{recipient} reçoit {item} de {sender}.", role_examples)
    require(role_frame.status == "licensed",
            "multi-role reordered template did not license")
    role_result = reordered.translate(
        "Translate from English to French: Rowan sends B2 to Lee.")
    require(role_result and role_result.status == "translated"
            and role_result.output == "Lee reçoit B2 de Rowan."
            and len(role_result.evidence) == 2,
            f"held-out role reordering failed: {role_result}")
    require(model.translate(
        "Translate from English to French in informal register: Hello, Rowan.").status
            == "unknown",
            "translation frame leaked across registers")
    require(model.translate(
        "Translate from French to English in formal register: Bonjour, Rowan.").status
            == "unknown",
            "translation frame was used in an unlearned direction")
    require(model.translate(
        "Translate from English to French in formal register: Good morning, Rowan.").status
            == "unknown",
            "unmatched source wording was guessed")

    ambiguous_source = CRMSTranslation()
    ambiguous_source.teach(
        "English", "French", "neutral", "Hello, {name}.",
        "Bonjour, {name}.", [("Hello, Ada.", "Bonjour, Ada."),
                              ("Hello, Malik.", "Bonjour, Malik.")])
    ambiguous_source.teach(
        "Spanish", "French", "neutral", "Hello, {name}.",
        "Bonjour, {name}.", [("Hello, Ana.", "Bonjour, Ana."),
                             ("Hello, Luis.", "Bonjour, Luis.")])
    unresolved_source = ambiguous_source.translate(
        "Translate ‘Hello, Rowan.’ into French.")
    require(unresolved_source and unresolved_source.status == "ambiguous"
            and unresolved_source.matched_source_languages == ("english", "spanish")
            and unresolved_source.source_text == "Hello, Rowan."
            and unresolved_source.target_language == "french",
            "target-only translation did not expose a source-language choice")
    resolved_source = ambiguous_source.translate(
        "Translate from Spanish to French: Hello, Rowan.")
    require(resolved_source and resolved_source.status == "translated"
            and resolved_source.output == "Bonjour, Rowan.",
            "explicit source-language clarification did not resolve the request")

    for bad_examples, source_template, target_template in (
            (examples, "Hello, {name}.", "Bonjour, {person}."),):
        try:
            CRMSTranslation().teach("English", "French", "formal",
                                    source_template, target_template, bad_examples)
        except ValueError:
            pass
        else:
            raise SystemExit("misaligned translation example/template was accepted")

    ambiguous = CRMSTranslation()
    ambiguous.teach("English", "French", "formal", "Hello, {name}.",
                    "Bonjour, {name}.", examples)
    ambiguous.teach("English", "French", "formal", "{greeting}, {name}.",
                    "Salut, {greeting} {name}.",
                    [("Hello, Ada.", "Salut, Hello Ada."),
                     ("Hello, Malik.", "Salut, Hello Malik.")])
    require(ambiguous.translate(
        "Translate from English to French in formal register: Hello, Rowan.").status
            == "ambiguous",
            "conflicting matching translations were silently selected")
    ambiguous_before_extension = repr(ambiguous._frames)
    try:
        ambiguous.teach_additional_example(
            "English", "French", "formal", "Hello, Rowan.",
            "Bonjour, Rowan.")
    except ValueError as error:
        require("more than one licensed frame matches" in str(error),
                f"ambiguous frame extension failed for an unrelated reason: {error}")
    else:
        raise SystemExit("additional example selected between overlapping frames")
    require(repr(ambiguous._frames) == ambiguous_before_extension,
            "ambiguous additional example changed translation memory")

    register_ambiguous = CRMSTranslation()
    register_ambiguous.teach(
        "English", "French", "formal", "Hello, {name}.",
        "Bonjour, {name}.", examples)
    register_ambiguous.teach(
        "English", "French", "informal", "Hello, {name}.",
        "Salut, {name}.",
        [("Hello, Ada.", "Salut, Ada."),
         ("Hello, Malik.", "Salut, Malik.")])
    missing_register = register_ambiguous.translate(
        "Translate from English to French: Hello, Rowan.")
    require(missing_register and missing_register.status == "ambiguous"
            and missing_register.matched_registers == ("formal", "informal")
            and "specify a register" in (missing_register.request or ""),
            "register-sensitive output ambiguity did not ask for clarification")
    selected_register = register_ambiguous.translate(
        "Translate from English to French in formal register: Hello, Rowan.")
    require(selected_register and selected_register.output == "Bonjour, Rowan.",
            "explicit register did not resolve the translation")

    copied_examples = [("Hello, Ada.", "Bonjour, Ada."),
                       ("Hello, Malik.", "Bonjour, Malik.")]
    inferred_templates = infer_shared_slot_templates(copied_examples)
    require(inferred_templates == ("Hello, {value1}.", "Bonjour, {value1}."),
            f"aligned copied-name slot was not inferred: {inferred_templates}")
    inferred_model = CRMSTranslation()
    inferred_model.teach("English", "French", "formal", *inferred_templates,
                         copied_examples)
    inferred_result = inferred_model.translate(
        "Translate from English to French in formal register: Hello, Rowan.")
    require(inferred_result and inferred_result.status == "translated"
            and inferred_result.output == "Bonjour, Rowan."
            and len(inferred_result.evidence) == 2,
            "mechanically inferred slot failed to transfer with both examples")
    bilingual_slot = CRMSTranslation()
    bilingual_examples = [("I like tea.", "J'aime le thé."),
                          ("I like coffee.", "J'aime le café.")]
    bilingual_slot.teach("English", "French", "neutral",
                         "I like {food}.", "J'aime le {food}.",
                         bilingual_examples)
    mapped_translation = bilingual_slot.translate(
        "Translate from English to French: I like tea.")
    require(mapped_translation and mapped_translation.status == "translated"
            and mapped_translation.output == "J'aime le thé."
            and mapped_translation.evidence == tuple(
                {"source": source, "target": target}
                for source, target in bilingual_examples),
            "explicit aligned bilingual slot values were not mapped")
    unseen_translation = bilingual_slot.translate(
        "Translate from English to French: I like sugar.")
    require(unseen_translation and unseen_translation.status == "unknown"
            and "no aligned target examples" in (unseen_translation.request or ""),
            "an unseen translated slot was guessed")
    additional = bilingual_slot.teach_additional_example(
        "English", "French", "neutral", "I like sugar.",
        "J'aime le sucre.")
    require(additional.status == "licensed"
            and bilingual_slot.translate(
                "Translate from English to French: I like sugar.").output
            == "J'aime le sucre.",
            "one additional aligned pair did not extend the licensed frame")
    before_conflict = repr(bilingual_slot._frames)
    try:
        bilingual_slot.teach_additional_example(
            "English", "French", "neutral", "I like sugar.",
            "J'aime le sirop.")
    except ValueError:
        pass
    else:
        raise SystemExit("conflicting additional slot mapping was accepted")
    require(repr(bilingual_slot._frames) == before_conflict,
            "rejected additional pair partially changed translation memory")
    multi_slot_examples = [
        ("Ada sent book to Bo.", "Ada a envoyé book à Bo."),
        ("Mira sent pen to Lee.", "Mira a envoyé pen à Lee."),
    ]
    multi_slot_templates = infer_shared_slot_templates(multi_slot_examples)
    require(multi_slot_templates == (
        "{value1} sent {value2} to {value3}.",
        "{value1} a envoyé {value2} à {value3}."),
        f"multiple copied roles were not aligned: {multi_slot_templates}")
    multi_slot_model = CRMSTranslation()
    multi_slot_model.teach("English", "French", "neutral",
                           *multi_slot_templates, multi_slot_examples)
    multi_slot_result = multi_slot_model.translate(
        "Translate from English to French: Tess sent box to Uma.")
    require(multi_slot_result and multi_slot_result.status == "translated"
            and multi_slot_result.output == "Tess a envoyé box à Uma."
            and len(multi_slot_result.evidence) == 2,
            "multi-slot role transfer failed or lost its aligned evidence")
    try:
        infer_shared_slot_templates([
            ("I like tea.", "J'aime le thé."),
            ("I like coffee.", "J'aime le café.")])
    except ValueError:
        pass
    else:
        raise SystemExit("translation inference copied a nonidentical bilingual slot")
    try:
        infer_shared_slot_templates(multi_slot_examples + [
            ("Ari sent cup to Bea.", "Ari a envoyé tasse à Bea.")])
    except ValueError:
        pass
    else:
        raise SystemExit("third aligned example contradicted the inferred slot copy")
    natural_examples = _natural_translation_examples(
        'Teach translation examples from English to French in formal register: '
        '"Hello, Ada." -> "Bonjour, Ada."; '
        '"Hello, Malik." -> "Bonjour, Malik."')
    require(natural_examples == ("English", "French", "formal", copied_examples),
            f"natural aligned-example teaching form was misparsed: {natural_examples}")
    natural_additional = _natural_translation_additional(
        'Teach an additional translation example from English to French in neutral register: '
        '"I like sugar." -> "J\'aime le sucre."')
    require(natural_additional == (
        "English", "French", "neutral", "I like sugar.", "J'aime le sucre."),
        f"incremental translation example was misparsed: {natural_additional}")
    natural_template_examples = _natural_translation_teaching(
        'Teach a translation frame from English to French in neutral register: '
        '"I like {food}." => "J\'aime le {food}."; '
        '"I like tea." -> "J\'aime le thé."; '
        '"I like coffee." -> "J\'aime le café."; '
        '"I like cocoa." -> "J\'aime le cacao."')
    require(natural_template_examples == (
        "English", "French", "neutral", "I like {food}.",
        "J'aime le {food}.", bilingual_examples + [
            ("I like cocoa.", "J'aime le cacao.")]),
        "three aligned bilingual mappings were not parsed as a batch")
    same_output_registers = CRMSTranslation()
    for style in ("formal", "informal"):
        same_output_registers.teach(
            "English", "French", style, "Hello, {name}.",
            "Bonjour, {name}.", examples)
    shared_output = same_output_registers.translate(
        "Translate from English to French: Hello, Rowan.")
    require(shared_output and shared_output.status == "translated"
            and shared_output.output == "Bonjour, Rowan."
            and shared_output.matched_registers == ("formal", "informal")
            and shared_output.register is None,
            "equivalent outputs across registers were not safely combined")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        translation_path = root / "translations.json"
        model.save(translation_path)
        restored = CRMSTranslation.load(translation_path)
        require(restored.translate(
            "Translate from English to French in formal register: Hello, Rowan.").output
                == "Bonjour, Rowan.",
                "translation frame did not survive persistence")
        bilingual_path = root / "bilingual_translations.json"
        bilingual_slot.save(bilingual_path)
        restored_bilingual = CRMSTranslation.load(bilingual_path)
        restored_mapping = restored_bilingual.translate(
            "Translate from English to French: I like coffee.")
        require(restored_mapping and restored_mapping.status == "translated"
                and restored_mapping.output == "J'aime le café."
                and len(restored_mapping.evidence) == 3,
                "aligned slot mappings did not reconstruct from saved examples")
        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json",
            "session.json", "math.json")}
        cli_translation_path = root / "cli_translations.json"
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(paths["knowledge.json"]),
               "--index", str(paths["index.json"]),
               "--dialogue-state", str(paths["dialogue.json"]),
               "--rules", str(paths["rules.json"]),
               "--rule-session", str(paths["session.json"]),
               "--rule-depth", "1", "--rule-max-add", "30",
               "--math", str(paths["math.json"]),
               "--translations", str(cli_translation_path)]
        teach = ("/teach-translation English|French|formal|Hello, {name}.|"
                 "Bonjour, {name}.|Hello, Ada.|Bonjour, Ada.|"
                 "Hello, Malik.|Bonjour, Malik.")
        conversational_teach = (
            'Teach a translation frame from English to French in formal register: '
            '"Goodbye, {name}." => "Au revoir, {name}."; '
            '"Goodbye, Ada." -> "Au revoir, Ada."; '
            '"Goodbye, Malik." -> "Au revoir, Malik."')
        inferred_teach = (
            'Teach translation examples from English to French in formal register: '
            '"Good night, Ada." -> "Bonne nuit, Ada."; '
            '"Good night, Malik." -> "Bonne nuit, Malik."')
        bilingual_teach = (
            'Teach a translation frame from English to French in neutral register: '
            '"I like {food}." => "J\'aime le {food}."; '
            '"I like tea." -> "J\'aime le thé."; '
            '"I like coffee." -> "J\'aime le café."; '
            '"I like cocoa." -> "J\'aime le cacao."')
        additional_bilingual_teach = (
            'Teach an additional translation example from English to French in neutral register: '
            '"I like sugar." -> "J\'aime le sucre."')
        unsafe_inferred_teach = (
            'Teach translation examples from English to French in formal register: '
            '"I like tea." -> "J\'aime le thé."; '
            '"I like coffee." -> "J\'aime le café."')
        informal_teach = (
            'Teach a translation frame from English to French in informal register: '
            '"Hello, {name}." => "Salut, {name}."; '
            '"Hello, Ada." -> "Salut, Ada."; '
            '"Hello, Malik." -> "Salut, Malik."')
        run = subprocess.run(
            cli, input="\n".join((teach, conversational_teach, inferred_teach,
                bilingual_teach,
                additional_bilingual_teach,
                unsafe_inferred_teach,
                informal_teach,
                "Translate ‘Hello, Uma.’ into French in formal register.",
                "How do you say 'Hello, Rowan.' in French in formal register?",
                "How do you say Hello, Rowan. in French in formal register?",
                "Translate from English to French in formal register: Hello, Rowan.",
                "Could you please translate from English to French in formal register: Hello, Mira.",
                "Translate from English to French: Hello, Mira.",
                "neutral register",
                "go with the informal one",
                "Please translate 'Hello, Ada.' from English into French.",
                "formal register",
                "Would you translate 'Hello, Rowan.' from English into French?",
                "formal register",
                "Translate from English to French: Hello, Zoe.",
                "What is 2 plus 2?",
                "Translate from English to French: Goodbye, Rowan.",
                "Translate from English to French: Good night, Rowan.",
                "Translate from English to French in neutral register: I like coffee.",
                "Translate from English to French in neutral register: I like cocoa.",
                "Translate from English to French in neutral register: I like sugar.",
                "Translate from English to French in neutral register: I like honey.",
                "/quit")) + "\n", text=True, capture_output=True,
            check=True, timeout=20)
        require("Translation frame licensed" in run.stdout
                and "Translation frame licensed for English to French (neutral register), "
                    "with 3 aligned examples." in run.stdout
                and "Additional aligned translation example licensed for English to French (neutral register)."
                    in run.stdout
                and "Bonjour, Rowan. (matched learned english to french, formal register" in run.stdout,
                f"ordinary CRMS chat did not route translation:\n{run.stdout}")
        require("Bonjour, Mira. (matched learned english to french, formal register"
                in run.stdout and run.stdout.count(
                    "CRMS> Bonjour, Mira. (matched learned english to french, "
                    "formal register") == 1,
                "explicit register was not honored for the direct request")
        require("Which register should I use? Reply with one of: formal, informal."
                in run.stdout
                and "Salut, Mira. (matched learned english to french, informal register"
                in run.stdout,
                "one-turn register clarification did not resolve the pending translation")
        require(run.stdout.count("Please choose a register from: formal, informal.") == 1,
                "an unavailable explicit register did not preserve the pending clarification")
        require("Bonjour, Ada. (matched learned english to french, formal register"
                in run.stdout,
                "sentence-first translation request missed the natural-chat route")
        require("Bonjour, Uma. (matched learned english to french, formal register"
                in run.stdout,
                "target-only translation request missed the natural-chat route")
        require(run.stdout.count(
            "Bonjour, Rowan. (matched learned english to french, formal register") == 4,
            "ordinary and sentence-first translation wordings did not share routing:\n"
            + run.stdout)
        require("Au revoir, Rowan. (matched learned english to french, formal register"
                in run.stdout,
                "conversationally taught translation frame did not translate a held-out value")
        require("Bonne nuit, Rowan. (matched learned english to french, formal register"
                in run.stdout
                and "Inferred copied slot templates: Good night, {value1}. => "
                "Bonne nuit, {value1}." in run.stdout,
                "natural aligned examples did not induce and apply a copied slot")
        require("Could not infer a safe translation frame: the differing source and target spans are not identical"
                in run.stdout,
                "unsafe nonidentical cross-language spans were accepted")
        require("J'aime le café. (matched learned english to french, neutral register"
                in run.stdout
                and "J'aime le cacao. (matched learned english to french, neutral register"
                in run.stdout
                and "J'aime le sucre. (matched learned english to french, neutral register"
                in run.stdout
                and "these slot values have no aligned target examples: {food}"
                in run.stdout,
                "natural translation teaching did not learn exact bilingual slot values")

        ambiguous_paths = {name: root / f"ambiguous_{name}" for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json",
            "session.json", "math.json", "translations.json")}
        ambiguity_cli = [sys.executable, str(PROJECT / "crms_chat.py"),
                         "--knowledge", str(ambiguous_paths["knowledge.json"]),
                         "--index", str(ambiguous_paths["index.json"]),
                         "--dialogue-state", str(ambiguous_paths["dialogue.json"]),
                         "--rules", str(ambiguous_paths["rules.json"]),
                         "--rule-session", str(ambiguous_paths["session.json"]),
                         "--rule-depth", "1", "--rule-max-add", "30",
                         "--math", str(ambiguous_paths["math.json"]),
                         "--translations", str(ambiguous_paths["translations.json"])]
        ambiguity_run = subprocess.run(
            ambiguity_cli, input="\n".join((
                'Teach a translation frame from English to French in neutral register: '
                '"No, {name}." => "Non, {name}."; '
                '"No, Ada." -> "Non, Ada."; "No, Malik." -> "Non, Malik."',
                'Teach a translation frame from Spanish to French in neutral register: '
                '"No, {name}." => "Non, {name}."; '
                '"No, Ana." -> "Non, Ana."; "No, Luis." -> "Non, Luis."',
                "Translate ‘No, Rowan.’ into French.",
                "The source language is German",
                "I mean Spanish",
                "/quit")) + "\n", text=True, capture_output=True,
            check=True, timeout=20)
        require("Which source language should I use? Reply with one of: english, spanish."
                in ambiguity_run.stdout,
                "ambiguous target-only translation did not ask for its source language")
        require(ambiguity_run.stdout.count(
            "Please choose a source language from: english, spanish.") == 1,
                "unsupported source choice did not preserve the pending clarification")
        require("Non, Rowan. (matched learned spanish to french, neutral register"
                in ambiguity_run.stdout,
                "source-language clarification did not resume the original translation")

    print("grounded translation frame diagnostic: PASS")
    print("multi-slot inference, incremental aligned-pair learning and conflict rejection, "
          "explicit slot alignment, "
          "register and direction bounds, ambiguity abstention and follow-up "
          "clarification, provenance, "
          "persistence, and natural-chat routing: PASS")


if __name__ == "__main__":
    main()
