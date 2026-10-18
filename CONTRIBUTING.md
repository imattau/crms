# Contributing to CRMS

Thanks for your interest in CRMS. Contributions of all kinds are welcome:
code, experiments, bug reports, documentation, and ideas.

## AI-assisted contributions are welcome, and encouraged

CRMS is developed largely with AI coding tools, and we want it to stay that
way. Using an AI assistant (Claude, Copilot, Codex, Cursor, Gemini, local
models, or anything else) to write, refactor, test, or document code is
explicitly welcome, and we encourage it.

A few ground rules keep AI-assisted work useful for everyone:

- **You are responsible for what you submit.** Read and understand the change,
  run it, and be ready to explain it, whether a person or a tool wrote it.
- **Verify, don't assume.** Run the relevant experiments (see below) and check
  the behaviour in the chat. Generated code that "looks right" is not enough.
- **Disclosure is optional but appreciated.** A line in the pull request such
  as "written with Claude" helps reviewers, but is not required. Do not hide
  or apologise for it either.
- **Keep changes focused.** Small, reviewable pull requests are easier to
  merge than large generated rewrites. Match the surrounding code style and
  avoid unrelated reformatting.
- **No invented facts.** If you write documentation or README text, make sure
  every claim matches what the code and experiments actually show.
- **Mind licensing.** Only submit code you have the right to contribute under
  the project's MIT license. Do not paste in code from other projects or from
  sources with incompatible licenses, however it was produced.

## Project principles

CRMS is a deterministic, evidence-grounded system. Changes should respect
these principles:

- **Evidence over assumption.** Learned rules, language patterns, and facts
  should be licensed by examples or cited sources, not hard-coded meanings.
- **Abstain when unsure.** An honest "I don't know" is better than a
  plausible but unsupported answer. New features must not make wrong answers
  more likely in exchange for more answers.
- **Provenance everywhere.** Answers and learned items should trace back to
  their sources, and be inspectable, correctable, and revocable.
- **Propose, then verify.** Fuzzy or heuristic methods may propose candidates;
  exact checks (held-out validation, citation checks, proofs) decide what is
  accepted.
- **Deterministic by default.** The same inputs should produce the same
  outputs, including when work runs in parallel.
- **CPU-friendly.** Prefer approaches that run well on ordinary CPUs and keep
  memory use bounded.

## Getting started

CRMS is plain Python and uses only the standard library, with one optional
exception: reading PDFs uses `pypdf` (or Poppler's `pdftotext` if it is
installed). You need Python 3; install `pypdf` only if you work with PDFs.

```sh
git clone https://github.com/imattau/crms.git
cd crms
python3 crms_chat.py        # interactive chat; type /help
```

The chat reads and writes state files (such as `crms_knowledge.json`) in the
working directory. To avoid changing your own state while experimenting, run it
from a scratch directory and pass explicit paths, for example:

```sh
mkdir /tmp/crms-scratch && cd /tmp/crms-scratch
python3 /path/to/crms/crms_chat.py --knowledge k.json --math m.json \
  --rules r.json --dialogue-state d.json --rule-session rs.json
```

Large data files and indexes live in `data/` and are not part of the
repository.

## Running the experiments

The `experiments/` directory holds standalone diagnostics, which act as the
project's regression checks. Each one runs in a fresh temporary directory, so
your local state is not touched.

```sh
python3 run_experiments.py                 # run all current experiments
python3 run_experiments.py --match 241     # run one by number
python3 run_experiments.py --stop-on-failure
```

Before opening a pull request, run the experiments related to what you changed
and, where practical, the full set.

## Adding or changing behaviour

- **Add an experiment** for new behaviour under `experiments/`, named like the
  existing ones (`v1_NNN_short_description.py`). It should check the intended
  behaviour and the cases that must still abstain or fail safely.
- **Include negative cases.** Show that near-misses, reordered input, and
  unsupported questions are refused, not just that the happy path works.
- **Update the README** (`CRMS_README.md`) when you change what CRMS does,
  and state limits plainly.
- **Report what you measured.** If a change affects accuracy, coverage, or
  speed, include numbers in the pull request.

## Reporting bugs

Open an issue with:

- what you typed or ran, and the exact output;
- what you expected instead;
- whether it is a wrong answer, a crash, or a missing capability (a wrong
  answer matters most);
- any relevant sources or teaching steps used before the failure.

## Pull requests

1. Fork the repository and create a branch.
2. Make a focused change with its experiment(s).
3. Run the experiments and note the results in the description.
4. Open a pull request describing what changed and why.

By contributing, you agree that your contribution is licensed under the
[MIT License](LICENSE).
