"""Phase 11: the generation + intake path runs from a copied folder.

Copies only the modules and seed the `/compose` intake path needs into an empty
folder, runs a request there, and checks the output matches the in-repo run, that
no research index, chat, network, or LLM module is needed, and that the pattern
rules reload from the seed.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_generate import request_from_mapping  # noqa: E402
from crms_generation import GenerationEngine  # noqa: E402
from crms_generation_rules import load_rules  # noqa: E402

MODULES = ("crms_generate.py", "crms_generation.py", "crms_generation_rules.py",
           "crms_generation_checks.py", "crms_source_intake.py", "crms_pattern_defaults.py",
           "crms_pattern_memory.py", "crms_pattern_rewrite.py", "crms_patterns.py",
           "crms_pattern_ranker.py", "crms_pattern_transforms.py", "crms_relation_specs.py",
           "crms_spec_verifier.py")
DATA = ("crms_generation_rules.json", "crms_pattern_seed.json")

REQUEST = {
    "prompt": "Summarise the sources on Lantern Bay, Binago Works and Aldo Press.",
    "genre": "summary", "audience": "general", "style": "plain",
    "source_documents": [
        {"name": "film.txt", "text": "Lantern Bay is a film directed by Rafe Ostin. It was released in 1999."},
        {"name": "firm.txt", "text": "Binago Works was founded in 1934 by Anna Rossi. Binago Works is a toolmaker in Como."},
        {"name": "press.txt", "text": "Aldo Press is a publisher. Aldo Press was established in 1960."}],
    "intake": {"questions": [{"question": "Who directed Lantern Bay?", "role": "main"},
                             {"question": "When was Binago Works founded?", "role": "support"},
                             {"question": "When was Aldo Press established?", "role": "support"}]},
}

RUNNER = """
import json, sys
sys.path.insert(0, '.')                     # only the copied folder
sys.modules['crms_research'] = None          # the research index must not be needed
for blocked in ('crms_chat', 'requests'):
    sys.modules[blocked] = None
from crms_generate import request_from_mapping
from crms_generation import GenerationEngine
from crms_generation_rules import load_rules
raw = json.load(open('request.json'))
result = GenerationEngine(load_rules()).generate(request_from_mapping(raw))
print(json.dumps({'status': result.status, 'text': result.text}))
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    expected = GenerationEngine(load_rules()).generate(request_from_mapping(REQUEST))
    require(expected.status == "ok", f"in-repo run failed: {expected.status}")
    source = "\n".join((PROJECT / name).read_text(encoding="utf-8") for name in MODULES)
    for forbidden in ("import requests", "import urllib", "http://", "https://", "openai", "anthropic"):
        require(forbidden not in source, f"intake path contains forbidden dependency: {forbidden}")
    with tempfile.TemporaryDirectory(prefix="crms-pattern-clean-") as folder:
        root = Path(folder)
        for name in MODULES:
            shutil.copy2(PROJECT / name, root / name)
        for name in DATA:
            shutil.copy2(PROJECT / name, root / name)
        (root / "request.json").write_text(json.dumps(REQUEST), encoding="utf-8")
        (root / "run.py").write_text(RUNNER, encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", "run.py"], cwd=root, text=True,
                              capture_output=True, check=False)
        require(done.returncode == 0, f"clean-room run failed:\n{done.stderr[-800:]}")
        got = json.loads(done.stdout.strip().splitlines()[-1])
    require(got["status"] == "ok" and got["text"] == expected.text,
            f"clean-room output differs: {got!r} vs {expected.text!r}")
    print("Phase 11 pattern clean-room contract passed")


if __name__ == "__main__":
    main()
