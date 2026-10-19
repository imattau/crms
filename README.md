# CRMS

**An experiment in building a language system that can show its work.**

CRMS is an early-stage research project. It asks a simple question: could a
computer understand and answer questions in plain language, and learn new
things, *without* being a giant neural network, and in a way where every answer
can be traced back to where it came from?

> **Status: very early.** CRMS is a working prototype, not a finished product.
> It does some things well, many things not at all, and is changing quickly.

## The idea in one minute

Today's AI chat assistants are impressive, but they work like a black box. They
absorb enormous amounts of text into billions of numbers, and when they answer,
nobody can point to *why*. They can sound confident and be wrong, and fixing
one wrong belief is hard.

CRMS takes the opposite approach:

- **It keeps what it knows in a form you can read.** Facts, rules, and
  language patterns are stored as explicit, inspectable records, not buried in
  numbers.
- **It cites its sources.** If CRMS tells you something, it can show the
  sentence it came from.
- **It says "I don't know."** If the evidence isn't there, it says so, instead
  of guessing something plausible.
- **It learns from examples and evidence.** You can teach it new words, rules,
  and ways of asking questions, and it checks what it learned before trusting
  it.
- **It runs on an ordinary computer.** No graphics card, no cloud service, and
  no external AI model is required or downloaded. An inspectable learned
  sentence-ranker pilot exists, but normal chat does not use it.

## What it can do today

Give CRMS some documents, and then ask questions about them:

> **You:** Who created Python?
> **CRMS:** Guido van Rossum created Python. *[Source: computing.txt; quoted evidence, not an accepted fact]*

> **You:** Is Sydney the capital of Australia?
> **CRMS:** The source states no: "Canberra is the capital of Australia, not Sydney."

> **You:** What is 2 + 3 * 4?
> **CRMS:** 14

Other things it can currently do:

- Quote and summarise relevant sentences from your own documents.
- Do exact arithmetic and solve simple equations.
- Follow chains of facts, such as working out that someone is a grandparent
  from two "parent of" facts, and show each step of the reasoning.
- Learn small rules from examples, such as how to reverse or reshape a list of
  numbers.
- Learn new ways of phrasing questions, with your approval.
- Compose a short, template-based fictional story from a topic. Its details
  are explicitly labelled as invented.
- Experiment with an inspectable sentence-ranker pilot. It is not enabled in
  normal chat and does not replace source checks.
- Hold simple conversations that remember what you were just talking about.

## What it can't do (yet)

Being honest about limits is part of the project:

- It is **not** a general-purpose chatbot. It will not write essays, hold
  open-ended conversations, or know things you haven't given it.
- Its story writing uses a small fixed narrative grammar; it cannot yet write
  varied fiction, plans, poems, songs, or revise prose broadly.
- Its understanding of wording is **narrow**. It can miss a question that a
  person would find obviously similar to one it handled.
- It sometimes picks the **wrong sentence** from a document. It labels these
  as quoted evidence, but it is a known weakness.
- Long creative writing, long reasoning, and broad general knowledge remain
  well beyond what it does now.

## What it aspires to

The long-term goal is a system that does much of what a large language model
does, **but built differently**, so that it is:

- **Trustworthy** - answers come with evidence, and unsupported answers don't
  appear.
- **Correctable** - if it believes something wrong, you can find that belief
  and fix or remove it, without retraining anything.
- **Inspectable** - you can see what it knows and why it behaves as it does.
- **Lightweight** - useful on everyday hardware, with knowledge stored on disk
  and looked up when needed, not loaded all at once.
- **Able to grow** - able to learn new language patterns and rules from
  evidence on its own, and keep only what holds up when checked.

Some directions we'd like to explore:

- Understanding many more ways of asking the same question.
- Reading large collections of text (papers, encyclopedias, your own notes) and
  turning them into checked, cited knowledge.
- Stronger step-by-step reasoning, with warnings when facts contradict each
  other.
- Writing that stays tied to the facts, from short summaries to carefully
  labelled creative text.
- Measuring all of this honestly: how often it is right, wrong, or says
  "I don't know".

We don't know yet how far this approach can go. That is the experiment.

## Try it

You need Python 3 and nothing else (reading PDFs also needs the optional
`pypdf` package).

```sh
git clone https://github.com/imattau/crms.git
cd crms
python3 crms_chat.py
```

Then type `/help` for a short guide. A good first session:

1. Add some text files: `/source-dir path/to/your/documents`
2. Ask questions about them in plain English.
3. Type `why?` after an answer to see where it came from.

After an evidence-backed answer, use `/right` or `/wrong` to record feedback
against its cited fact, source, or inference rule. Use `/feedback` to inspect
recent signals, fact propositions, and source references. Feedback is saved in
`crms_feedback.sqlite3` for review. Marking a proof-based answer wrong temporarily
suspends validated learned rules used in that proof until they pass held-out
revalidation; facts and teacher-supplied rules are not changed automatically.
For a direct fact, `/feedback` gives numbered source support; retract only the
selected citation with `/retract-feedback FEEDBACK|FACT|SOURCE`. CRMS then
rechecks the original question against the remaining accepted facts.

## Learn more

- [CRMS_README.md](CRMS_README.md) - the detailed technical documentation.
- [docs/design_domain_expansion.md](docs/design_domain_expansion.md) - the staged roadmap for natural-language math, coding, translation, cross-domain tasks, and capability comparisons.
- [CONTRIBUTING.md](CONTRIBUTING.md) - how to help.

## Contributing

Contributions are welcome, including code written with the help of AI tools,
which we actively encourage. You don't have to be a programmer to help: bug
reports, tricky test questions, and ideas are all valuable. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
