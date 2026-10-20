"""Exercise example-learned math phrases through ordinary CRMS-language input."""
from __future__ import annotations

from fractions import Fraction
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_math import CRMSMath, MathBinary, MathLiteral, MathVariable, render as render_math
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def teach_add(model: CRMSModel, phrase: str, amount: int) -> None:
    examples = [([1, -2], [1 + amount, -2 + amount]),
                ([4, 3], [4 + amount, 3 + amount])]
    result = model.teach(phrase, examples)
    require(result.status == "learned",
            f"could not learn grounded numeral source {phrase!r}: {result}")


def evaluate_terms(terms: tuple[dict[str, object], ...],
                  bindings: dict[str, int]) -> Fraction:
    """Independent exact substitution check over the exposed polynomial terms."""
    total = Fraction(0)
    for term in terms:
        value = Fraction(str(term["coefficient"]))
        for name, power in term["powers"]:
            value *= Fraction(bindings[str(name)]) ** int(power)
        total += value
    return total


def evaluate_expression(node: object, bindings: dict[str, int]) -> Fraction:
    """Reference evaluator for original expression trees, separate from polynomials."""
    if isinstance(node, MathLiteral):
        return Fraction(node.value)
    if isinstance(node, MathVariable):
        return Fraction(bindings[node.name])
    if not isinstance(node, MathBinary):
        raise TypeError(f"not an arithmetic expression: {node!r}")
    left = evaluate_expression(node.left, bindings)
    right = evaluate_expression(node.right, bindings)
    if node.operation == "add":
        return left + right
    if node.operation == "subtract":
        return left - right
    if node.operation == "multiply":
        return left * right
    if node.operation == "divide":
        return left / right
    if node.operation == "modulo":
        return left % right
    raise ValueError(f"unknown operation in expression: {node.operation}")


def main() -> None:
    math = CRMSMath()
    require(math.ask("What is causal forgetting in CRMS?") is None,
            "a non-numeric definition question was claimed by unit conversion")
    require(math.ask("What is 2 meters in centimeters?").status == "unknown",
            "unit conversion was accepted without grounding")
    math.teach_unit_equivalence("2 meters|200 centimeters")
    require(math.ask("What is 2 meters in centimeters?").status == "unknown",
            "one unit example licensed a conversion")
    licensed_units = math.teach_unit_equivalence("3 meters|300 centimeters")
    require(licensed_units.status == "licensed",
            "consistent distinct quantity examples did not license a unit ratio")
    converted = math.ask("What is 2 meters in centimeters?")
    require(converted.status == "answered" and converted.value == Fraction(200)
            and converted.unit == "centimeters"
            and len(converted.unit_evidence) == 2,
            f"grounded unit conversion failed or lost evidence: {converted}")
    for wording, expected in (("Convert 0 meters to centimeters", Fraction(0)),
                              ("Convert -2 meters to centimeters", Fraction(-200))):
        signed_conversion = math.ask(wording)
        require(signed_conversion and signed_conversion.status == "answered"
                and signed_conversion.value == expected
                and signed_conversion.unit == "centimeters"
                and signed_conversion.unit_evidence == converted.unit_evidence,
                f"signed exact conversion failed or lost evidence: {signed_conversion}")
    for wording in ("Convert 2 meters to centimeters.",
                    "Could you please convert 2 meters into centimeters?"):
        alternate_conversion = math.ask(wording)
        require(alternate_conversion
                and alternate_conversion.status == "answered"
                and alternate_conversion.value == Fraction(200)
                and alternate_conversion.unit == "centimeters"
                and alternate_conversion.unit_evidence == converted.unit_evidence,
                f"natural conversion wording lost its evidence: {alternate_conversion}")
    require(math.ask("What is 2 meters in kilograms?").status == "unknown",
            "conversion across unconnected dimensions was guessed")
    math.teach_unit_equivalence("100 centimeters|1000 millimeters")
    math.teach_unit_equivalence("200 centimeters|2000 millimeters")
    transitive = math.ask("What is 2 meters in millimeters?")
    require(transitive.status == "answered" and transitive.value == Fraction(2000)
            and transitive.unit == "millimeters",
            f"composed grounded unit path failed: {transitive}")
    try:
        math.teach_unit_equivalence("4 meters|500 centimeters")
    except ValueError:
        pass
    else:
        raise SystemExit("conflicting unit example was accepted")
    require(math.ask("What is 2 meters in centimeters?").value == Fraction(200),
            "rejected conflicting unit example changed the learned ratio")
    try:
        math.teach_unit_equivalence("1 meter|999 millimeters")
        math.teach_unit_equivalence("2 meters|1998 millimeters")
    except ValueError:
        pass
    else:
        raise SystemExit("inconsistent conversion cycle was accepted")
    require(math.ask("What is 2 meters in millimeters?").value == Fraction(2000),
            "rejected inconsistent cycle damaged the existing conversion graph")
    first = math.teach("What is 2 plus 3?", "5")
    require(first.status == "needs_more_examples",
            "consistent examples did not remain visible as learning evidence")
    standard_plus = math.ask("What is 7 plus 4?")
    require(standard_plus is not None and standard_plus.status == "answered"
            and standard_plus.value == Fraction(11)
            and standard_plus.operation == "add",
            "a conventional arithmetic word required redundant teaching")
    unknown_phrase = math.ask("What is 8 glorp 1?")
    require(unknown_phrase and unknown_phrase.status == "unknown"
            and "Teach math from examples" in (unknown_phrase.request or ""),
            "an unknown operator did not return a targeted language-learning prompt")
    ambiguous_phrase = CRMSMath()
    unresolved = ambiguous_phrase.teach("What is 2 glorp 2?", "4")
    require(unresolved.status == "needs_more_examples"
            and unresolved.candidate_operations == ("add", "multiply")
            and unresolved.contrastive_input is not None,
            f"ambiguous arithmetic examples did not yield a separating input: {unresolved}")
    left, right = unresolved.contrastive_input
    resolved = ambiguous_phrase.teach(
        f"What is {left} glorp {right}?", str(left + right))
    require(resolved.status == "licensed" and resolved.operation == "add",
            "contrastive math example did not resolve and license addition")
    second = math.teach("What is 5 plus 3?", "8")
    require(second.status == "licensed" and second.operation == "add",
            "varied examples did not isolate addition")
    held_out = math.ask("What is 17 plus -6?")
    require(held_out and held_out.status == "answered"
            and held_out.value == Fraction(11) and held_out.operation == "add",
            f"learned phrase failed on a held-out pair: {held_out}")
    for wording in ("How much is 17 plus -6?", "Calculate 17 plus -6.",
                    "Please compute 17 plus -6!",
                    "What does 17 plus -6 equal?",
                    "What is the result of 17 plus -6?",
                    "Could you calculate 17 plus -6?",
                    "Would you please compute 17 plus -6?"):
        alternate = math.ask(wording)
        require(alternate and alternate.status == "answered"
                and alternate.value == Fraction(11)
                and alternate.operation == "add"
                and alternate.examples == held_out.examples,
                f"bounded math wording lost learned semantics or evidence: {alternate}")
    for wording, expected in (
            ("What is 2 + 3?", Fraction(5)),
            ("What is 2 + 3 * 4?", Fraction(14)),
            ("What is (2 + 3) × 4?", Fraction(20)),
            ("What is 2(3 + 4)?", Fraction(14)),
            ("What is 0.1 + 0.2?", Fraction(3, 10)),
            ("What is 1e-1 + 2e-1?", Fraction(3, 10)),
            ("What is -2 * 3?", Fraction(-6)),
            ("What is -1.25 * 2?", Fraction(-5, 2)),
            ("What is 7 ÷ 2?", Fraction(7, 2))):
        symbolic = math.ask(wording)
        require(symbolic and symbolic.status == "answered"
                and symbolic.value == expected,
                f"standard arithmetic notation failed for {wording}: {symbolic}")
    for wording, expected in (("What is 17 % 5?", Fraction(2)),
                              ("What is -7 % 3?", Fraction(2)),
                              ("What is 7 % -3?", Fraction(-2)),
                              ("What is (17 % 5) + 1?", Fraction(3))):
        symbolic_remainder = math.ask(wording)
        require(symbolic_remainder and symbolic_remainder.status == "answered"
                and symbolic_remainder.value == expected,
                f"exact standard remainder failed for {wording}: {symbolic_remainder}")
    remainder_math = CRMSMath()
    first_remainder = remainder_math.teach("What is 17 remainder 5?", "2")
    require(first_remainder.status == "needs_more_examples"
            and len(first_remainder.examples) == 1,
            "one remainder example licensed a learned operation too early")
    learned_remainder = remainder_math.teach("What is 13 remainder 5?", "3")
    require(learned_remainder.status == "licensed"
            and learned_remainder.operation == "modulo"
            and remainder_math.ask("What is -7 remainder 3?").value == Fraction(2),
            "aligned examples did not license exact, negative-aware remainder")
    before_remainder = dict(remainder_math._examples[("remainder",)])
    try:
        remainder_math.teach("What is 13 remainder 5?", "4")
    except ValueError:
        pass
    else:
        raise SystemExit("contradictory remainder example was accepted")
    require(remainder_math._examples[("remainder",)] == before_remainder,
            "rejected remainder example changed learned operator evidence")
    zero_remainder = remainder_math.ask("What is 7 remainder 0?")
    require(zero_remainder and zero_remainder.status == "unknown"
            and "zero" in (zero_remainder.request or ""),
            "learned remainder did not abstain on zero divisor")
    negative_variable = math.ask("What is -x?")
    require(negative_variable and negative_variable.status == "answered"
            and negative_variable.value == "-x",
            f"unary negative did not apply to a variable: {negative_variable}")
    negative_group = math.ask("What is -(x + 1)?")
    require(negative_group and negative_group.status == "answered"
            and negative_group.value == "-x - 1",
            f"unary negative did not apply to a parenthesized expression: {negative_group}")
    symbolic_equation = math.ask("Solve 2 * x + 3 = 11 for x.")
    require(symbolic_equation and symbolic_equation.status == "answered"
            and symbolic_equation.value == Fraction(4)
            and evaluate_expression(symbolic_equation.expression.left, {"x": 4})
            == evaluate_expression(symbolic_equation.expression.right, {"x": 4}),
            f"symbolic equation was not solved and substitution-checked: {symbolic_equation}")
    implicit_equation = math.ask("Solve 2x + 3 = 11 for x.")
    require(implicit_equation and implicit_equation.status == "answered"
            and implicit_equation.value == Fraction(4)
            and evaluate_expression(implicit_equation.expression.left, {"x": 4})
            == evaluate_expression(implicit_equation.expression.right, {"x": 4}),
            f"implicit algebraic multiplication failed or was not checked: {implicit_equation}")
    decimal_equation = math.ask("Solve 0.5x = 1.5 for x.")
    require(decimal_equation and decimal_equation.status == "answered"
            and decimal_equation.value == Fraction(3)
            and evaluate_expression(decimal_equation.expression.left, {"x": 3})
            == evaluate_expression(decimal_equation.expression.right, {"x": 3}),
            f"exact decimal equation failed substitution verification: {decimal_equation}")
    negative_equation = math.ask("Solve -x + 3 = 1 for x.")
    require(negative_equation and negative_equation.status == "answered"
            and negative_equation.value == Fraction(2)
            and evaluate_expression(negative_equation.expression.left, {"x": 2})
            == evaluate_expression(negative_equation.expression.right, {"x": 2}),
            f"negative-variable equation failed substitution verification: {negative_equation}")
    implicit_product = math.ask("What is (x + 1)(x + 1)?")
    require(implicit_product and implicit_product.status == "answered"
            and implicit_product.value == "x^2 + 2*x + 1",
            f"adjacent parenthesized factors were not multiplied: {implicit_product}")
    malformed_adjacency = math.ask("What is 2 3?")
    require(malformed_adjacency is None or malformed_adjacency.status != "answered",
            "two adjacent numeric literals were silently treated as multiplication")
    math.teach("What is 2 times 3?", "6")
    math.teach("What is 4 times 3?", "12")
    math.teach("What is 6 divided by 3?", "2")
    math.teach("What is 5 divided by 2?", "5/2")
    unit_sum = math.ask("What is 2 meters plus 200 centimeters?")
    require(unit_sum.status == "answered" and unit_sum.value == Fraction(4)
            and unit_sum.unit == "meters"
            and "unit evidence" in render_math(unit_sum),
            f"equivalent-unit addition failed or lost lineage: {unit_sum}")
    scaled_quantity = math.ask("What is 2 times 3 meters?")
    require(scaled_quantity.status == "answered"
            and scaled_quantity.value == Fraction(6)
            and scaled_quantity.unit == "meters",
            f"scalar multiplication did not preserve units: {scaled_quantity}")
    divided_quantity = math.ask("What is 6 meters divided by 2?")
    require(divided_quantity.status == "answered"
            and divided_quantity.value == Fraction(3)
            and divided_quantity.unit == "meters",
            f"scalar division did not preserve units: {divided_quantity}")
    math.teach_unit_equivalence("2 kilograms|2000 grams")
    math.teach_unit_equivalence("3 kilograms|3000 grams")
    incompatible_sum = math.ask("What is 2 meters plus 3 kilograms?")
    require(incompatible_sum.status == "unknown",
            "addition silently combined incompatible learned dimensions")
    quantity_product = math.ask("What is 2 meters times 3 meters?")
    require(quantity_product.status == "unknown",
            "multiplication silently combined two unitful quantities")
    precedence = math.ask("What is 2 plus 3 times 4?")
    require(precedence and precedence.status == "answered"
            and precedence.value == Fraction(14)
            and precedence.operation == "composed",
            f"declared precedence was not applied: {precedence}")
    mixed_notation = math.ask("What is 2 + 3 times 4?")
    require(mixed_notation and mixed_notation.status == "answered"
            and mixed_notation.value == Fraction(14)
            and len(mixed_notation.examples) == 2,
            f"symbolic and example-learned operators did not compose: {mixed_notation}")
    grouped = math.ask("What is (2 plus 3) times 4?")
    require(grouped and grouped.status == "answered"
            and grouped.value == Fraction(20),
            f"parentheses did not override precedence: {grouped}")
    rational_composition = math.ask(
        "What is 5 divided by 2 plus 3 times 4?")
    require(rational_composition
            and rational_composition.status == "answered"
            and rational_composition.value == Fraction(29, 2),
            f"exact rational composition failed: {rational_composition}")
    math.teach("What is 5 minus 2?", "3")
    math.teach("What is 8 minus 3?", "5")
    symbolic = math.ask("What is x plus 2?")
    require(symbolic and symbolic.status == "answered"
            and symbolic.value == "x + 2",
            f"symbolic variable expression failed: {symbolic}")
    expanded = math.ask("What is (x plus 1) times (x plus 1)?")
    require(expanded and expanded.status == "answered"
            and expanded.value == "x^2 + 2*x + 1",
            f"exact polynomial expansion failed: {expanded}")
    for x in (-5, -1, 0, 2, 19):
        require(evaluate_terms(expanded.symbolic_terms, {"x": x})
                == Fraction((x + 1) ** 2),
                f"symbolic coefficients failed substitution at x={x}: {expanded}")
    two_variables = math.ask("What is x times y plus x?")
    require(two_variables and two_variables.status == "answered"
            and two_variables.value == "x*y + x",
            f"multiple symbolic variables failed: {two_variables}")
    for x, y in ((0, 3), (2, -4), (5, 7)):
        require(evaluate_terms(two_variables.symbolic_terms, {"x": x, "y": y})
                == Fraction(x * y + x),
                f"two-variable polynomial failed substitution at x={x}, y={y}")
    cancelled = math.ask("What is x minus x?")
    require(cancelled and cancelled.status == "answered"
            and cancelled.value == Fraction(0),
            f"like-term cancellation failed: {cancelled}")
    rational_variable = math.ask("What is x divided by 2?")
    require(rational_variable and rational_variable.status == "answered"
            and rational_variable.value == "1/2*x",
            f"rational polynomial coefficient failed: {rational_variable}")
    unsupported_division = math.ask("What is 1 divided by (x plus 1)?")
    require(unsupported_division and unsupported_division.status == "unknown"
            and "division by a variable" in (unsupported_division.request or ""),
            f"unsupported symbolic division did not abstain: {unsupported_division}")
    equation = math.ask("Solve 2 times x plus 3 equals 11 for x.")
    require(equation and equation.status == "answered"
            and equation.value == Fraction(4)
            and equation.expression.variable == "x",
            f"linear equation solving failed: {equation}")
    require(evaluate_expression(equation.expression.left, {"x": 4})
            == evaluate_expression(equation.expression.right, {"x": 4}),
            "original equation sides disagree at the proposed solution")
    require(evaluate_terms(equation.symbolic_terms, {"x": 4}) == Fraction(0),
            "equation solution failed independent substitution")
    both_sides = math.ask("Solve 2 times x plus 1 equals x plus 4 for x.")
    require(both_sides and both_sides.status == "answered"
            and both_sides.value == Fraction(3),
            f"linear variable terms on both sides failed: {both_sides}")
    scalar_equation = math.ask("Solve x divided by 2 plus 1 equals 3 for x.")
    require(scalar_equation and scalar_equation.status == "answered"
            and scalar_equation.value == Fraction(4),
            f"rational linear equation failed: {scalar_equation}")
    quadratic = math.ask("Solve x times x equals 9 for x.")
    require(quadratic and quadratic.status == "answered"
            and quadratic.solutions == (Fraction(-3), Fraction(3))
            and quadratic.value is None,
            f"exact quadratic roots were not returned: {quadratic}")
    for root in quadratic.solutions:
        require(evaluate_expression(quadratic.expression.left, {"x": root})
                == evaluate_expression(quadratic.expression.right, {"x": root})
                and evaluate_terms(quadratic.symbolic_terms, {"x": root})
                == Fraction(0),
                f"quadratic root failed independent substitution: {root}")
    mixed_quadratic = math.ask(
        "Solve x times x equals 2 times x plus 3 for x.")
    require(mixed_quadratic and mixed_quadratic.status == "answered"
            and mixed_quadratic.solutions == (Fraction(-1), Fraction(3)),
            f"quadratic with variable terms on both sides failed: {mixed_quadratic}")
    repeated_root = math.ask(
        "Solve (x minus 2) times (x minus 2) equals 0 for x.")
    require(repeated_root and repeated_root.status == "answered"
            and repeated_root.solutions == (Fraction(2),),
            f"repeated quadratic root was not deduplicated: {repeated_root}")
    rational_roots = math.ask("Solve x times x equals 1 divided by 4 for x.")
    require(rational_roots and rational_roots.status == "answered"
            and rational_roots.solutions == (Fraction(-1, 2), Fraction(1, 2)),
            f"rational quadratic roots were not exact: {rational_roots}")
    irrational = math.ask("Solve x times x equals 2 for x.")
    require(irrational and irrational.status == "unknown"
            and "irrational" in (irrational.request or ""),
            f"irrational roots were approximated or guessed: {irrational}")
    complex_roots = math.ask("Solve x times x plus 1 equals 0 for x.")
    require(complex_roots and complex_roots.status == "unknown"
            and "no real solutions" in (complex_roots.request or ""),
            f"complex roots were silently treated as real: {complex_roots}")
    higher_degree = math.ask("Solve x times x times x equals 1 for x.")
    require(higher_degree and higher_degree.status == "unknown"
            and "exceeds quadratic degree" in (higher_degree.request or ""),
            f"higher-degree equation exceeded the solver bound: {higher_degree}")
    non_unique = math.ask("Solve x plus 1 equals x plus 1 for x.")
    require(non_unique and non_unique.status == "unknown"
            and "unique" in (non_unique.request or ""),
            f"non-unique equation was assigned a solution: {non_unique}")
    inconsistent = math.ask("Solve x plus 1 equals x plus 2 for x.")
    require(inconsistent and inconsistent.status == "unknown"
            and "no solution" in (inconsistent.request or ""),
            f"inconsistent equation was assigned a solution: {inconsistent}")
    left_associative = math.ask("What is 10 minus 3 minus 2?")
    require(left_associative and left_associative.status == "answered"
            and left_associative.value == Fraction(5),
            f"equal-precedence operators were not left-associative: {left_associative}")
    unknown_composition = math.ask("What is 2 plus 3 zarg 4?")
    require(unknown_composition and unknown_composition.status == "unknown"
            and "zarg" in (unknown_composition.request or ""),
            f"unknown inner operation did not abstain: {unknown_composition}")
    unlearned_zarg = math.ask("What is 2 zarg 3?")
    require(unlearned_zarg and unlearned_zarg.status == "unknown"
            and "Teach math from examples" in (unlearned_zarg.request or ""),
            "an unlearned operator did not request grounded examples")
    large_expression = "What is " + " times ".join(["9" * 100] * 20) + "?"
    bounded = math.ask(large_expression)
    require(bounded and bounded.status == "unknown"
            and "bound" in (bounded.request or ""),
            "oversized exact result did not stop at the arithmetic bound")

    ambiguous = CRMSMath()
    ambiguous.teach("What is 0 florp 0?", "0")
    ambiguous.teach("What is 2 florp 2?", "4")
    require(ambiguous.ask("What is 8 florp 8?").status == "unknown",
            "operation ambiguity was silently resolved")
    ambiguous.teach("What is 3 florp 3?", "6")
    disambiguated = ambiguous.ask("What is 8 florp 8?")
    require(disambiguated and disambiguated.status == "answered"
            and disambiguated.value == Fraction(16),
            f"contrastive demonstration did not resolve the phrase: {disambiguated}")

    division = CRMSMath()
    division.teach("What is 6 divided by 3?", "2")
    division.teach("What is 5 divided by 2?", "5/2")
    quotient = division.ask("What is 7 divided by 2?")
    require(quotient and quotient.status == "answered"
            and quotient.value == Fraction(7, 2),
            f"exact rational division failed: {quotient}")
    zero = division.ask("What is 7 divided by 0?")
    require(zero and zero.status == "unknown"
            and "zero" in (zero.request or ""),
            f"division by zero was not rejected: {zero}")

    state_before = dict(math._examples[("plus",)])
    try:
        math.teach("What is 2 plus 3?", "6")
    except ValueError:
        pass
    else:
        raise SystemExit("contradictory training label was accepted")
    require(math._examples[("plus",)] == state_before,
            "rejected example partially changed learned state")
    require(math.ask("What is 3 plus 2?") is not None
            and math.ask("What is 3 plus 2?").value == Fraction(5),
            "commutative arithmetic did not generalize beyond training pairs")
    require(math.ask("Tell me the answer to 3 plus 2") is None,
            "the declared grammar silently accepted unlicensed question syntax")

    number_rules = CRMSModel(max_composition_depth=1, max_add=30, max_workers=1)
    for amount, word in ((3, "three"), (21, "twenty one")):
        teach_add(number_rules, f"add {amount} to every value", amount)
        teach_add(number_rules, f"add {word} to every value", amount)
    grounded_cardinals = number_rules.grounded_cardinal_phrases()
    require(grounded_cardinals.get(("twenty", "one"), (None,))[0] == 21
            and grounded_cardinals.get(("three",), (None,))[0] == 3,
            f"CRMS rule learning did not expose grounded cardinals: {grounded_cardinals}")
    ungrounded_unit_numeral = math.ask(
        "What is twenty one meters in centimeters?")
    require(ungrounded_unit_numeral.status == "unknown"
            and (ungrounded_unit_numeral.request or "").startswith(
                "I have no grounded cardinal value"),
            "unit conversion accepted a number word without language evidence")
    word_quantity = math.ask(
        "What is twenty one meters in centimeters?",
        grounded_cardinals=grounded_cardinals)
    require(word_quantity.status == "answered"
            and word_quantity.value == Fraction(2100)
            and word_quantity.number_evidence[0]["sources"]
            == ["add 21 to every value", "add twenty one to every value"],
            f"unit conversion failed to reuse grounded numeral evidence: {word_quantity}")
    word_unit_sum = math.ask(
        "What is twenty one meters plus three meters?",
        grounded_cardinals=grounded_cardinals)
    require(word_unit_sum.status == "answered"
            and word_unit_sum.value == Fraction(24)
            and word_unit_sum.unit == "meters"
            and len(word_unit_sum.number_evidence) == 2,
            f"grounded number words failed inside a unit expression: {word_unit_sum}")
    word_sum = math.ask("What is twenty one plus three?",
                        grounded_cardinals=grounded_cardinals)
    require(word_sum and word_sum.status == "answered"
            and word_sum.value == Fraction(24)
            and {item["phrase"] for item in word_sum.number_evidence}
            == {"twenty one", "three"},
            f"grounded numerals did not transfer into exact math: {word_sum}")
    word_equation = math.ask(
        "Solve x plus twenty one equals 23 for x.",
        grounded_cardinals=grounded_cardinals)
    require(word_equation and word_equation.status == "answered"
            and word_equation.value == Fraction(2)
            and word_equation.number_evidence,
            f"grounded numerals did not transfer into equation solving: {word_equation}")
    require(evaluate_expression(word_equation.expression.left, {"x": 2})
            == evaluate_expression(word_equation.expression.right, {"x": 2}),
            "word-numeral equation failed original-expression substitution")
    ungrounded_sum = math.ask("What is twenty four plus three?",
                              grounded_cardinals=grounded_cardinals)
    require(ungrounded_sum and ungrounded_sum.status == "unknown"
            and "grounded cardinal" in (ungrounded_sum.request or ""),
            "unknown number words were treated as built-in numerals")

    ordinal_rules = CRMSModel(max_composition_depth=1,
                              max_position_stride=5, max_workers=1)
    ordinal_examples = {
        3: [([1, 2, 3, 4, 5, 6, 7, 8], [3, 6]),
            ([9, 8, 7, 6, 5, 4, 3, 2, 1], [7, 4, 1])],
        4: [([1, 2, 3, 4, 5, 6, 7, 8, 9], [4, 8]),
            ([9, 8, 7, 6, 5, 4, 3, 2, 1], [6, 2])],
    }
    for number, word in ((3, "third"), (4, "fourth")):
        for form in (f"select every {number}th value",
                     f"select every {word} value"):
            result = ordinal_rules.teach(form, ordinal_examples[number])
            require(result.status == "learned",
                    f"could not learn ordinal control {form!r}: {result}")
    ordinals = ordinal_rules.grounded_cardinal_phrases()
    require(("third",) not in ordinals and ("fourth",) not in ordinals,
            f"ordinal forms leaked into cardinal arithmetic: {ordinals}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        math_path = root / "math.json"
        math.save(math_path)
        restored = CRMSMath.load(math_path)
        persisted = restored.ask("What is 17 plus -6?")
        require(persisted and persisted.status == "answered"
                and persisted.value == Fraction(11),
                "learned operator did not survive persistence")
        persisted_conversion = restored.ask("What is 2 meters in centimeters?")
        require(persisted_conversion and persisted_conversion.status == "answered"
                and persisted_conversion.value == Fraction(200),
                "learned unit ratio did not survive persistence")
        persisted_unit_sum = restored.ask(
            "What is 2 meters plus 200 centimeters?")
        require(persisted_unit_sum and persisted_unit_sum.status == "answered"
                and persisted_unit_sum.value == Fraction(4)
                and persisted_unit_sum.unit == "meters",
                "unit-aware expression did not survive persistence")
        persisted_composition = restored.ask("What is (2 plus 3) times 4?")
        require(persisted_composition
                and persisted_composition.status == "answered"
                and persisted_composition.value == Fraction(20),
                "composed operators did not survive persistence")
        persisted_symbolic = restored.ask("What is (x plus 1) times (x plus 1)?")
        require(persisted_symbolic and persisted_symbolic.status == "answered"
                and persisted_symbolic.value == "x^2 + 2*x + 1",
                "symbolic evaluation did not survive operation-memory reload")

        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json",
            "session.json", "math_session.json")}
        number_rules.save(paths["rules.json"])
        CRMSResearchIndex().save(paths["index.json"])
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(paths["knowledge.json"]),
               "--index", str(paths["index.json"]),
               "--dialogue-state", str(paths["dialogue.json"]),
               "--rules", str(paths["rules.json"]),
               "--rule-session", str(paths["session.json"]),
               "--math-session", str(paths["math_session.json"]),
               "--rule-depth", "1", "--rule-max-add", "30",
               "--math", str(math_path)]
        pending_start = subprocess.run(
            cli, input="/teach-math What is 2 pending 2?|4\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20)
        require("For '-1 pending 0', they predict add=-1, multiply=0"
                in pending_start.stdout,
                f"math learner did not present the separating input:\n{pending_start.stdout}")
        pending_resume = subprocess.run(
            cli, input="The result is 999\nThe result is -1\n"
                       "What is 17 pending -6?\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20)
        require("Math phrase licensed as exact add: 'pending'." in pending_resume.stdout
                and "11 (learned 'pending' as exact add; checked against 2 examples)"
                in pending_resume.stdout
                and "Could not use that math example" in pending_resume.stdout,
                f"pending math feedback did not survive restart and resolve:\n{pending_resume.stdout}")
        commands = [
            ('Teach math from examples: "What is 2 blip 3?" -> 6; '
             '"What is 5 blip 3?" -> 9.'),
            "What is 8 blip 1?",
            ('Teach math from examples: "What is 2 blip 3?" -> 5; '
             '"What is 5 blip 3?" -> 8.'),
            "What is 17 blip -6?",
            ('Teach math from examples: "What is 2 glorp 3?" -> 5; '
             '"What is 5 glorp 3?" -> 8; '
             '"What is 7 glorp 4?" -> 11.'),
            "What is 17 glorp -6?",
            "/teach-math What is 2 plus 3?|5",
            "/teach-math What is 5 plus 3?|8",
            "/teach-math What is 2 times 3?|6",
            "/teach-math What is 4 times 3?|12",
            ('Teach math from examples: "What is 17 remainder 5?" -> 2; '
             '"What is 13 remainder 5?" -> 3.'),
            "What is -7 remainder 3?",
            "What is -7 % 3?",
            "/teach-unit-equivalence 2 meters|200 centimeters",
            "/teach-unit-equivalence 3 meters|300 centimeters",
            "What is 17 plus -6?",
            "How much is 17 plus -6?",
            "Calculate 17 plus -6.",
            "Please compute 17 plus -6!",
            "What is 2 plus 3 times 4?",
            "What is (x plus 1) times (x plus 1)?",
            "What is 2 meters in centimeters?",
            "Convert 0 meters to centimeters.",
            "Convert -2 meters to centimeters.",
            "Convert 2 meters to centimeters.",
            "Could you please convert 2 meters into centimeters?",
            "What is twenty one meters in centimeters?",
            "What is 2 meters plus 200 centimeters?",
            "Solve 2 times x plus 3 equals 11 for x.",
            "Solve x times x equals 9 for x.",
            "Solve x plus twenty one equals 23 for x.",
            "What is twenty one plus three?",
            "What is 17 plus 3 zarg -6?",
            "/quit",
        ]
        run = subprocess.run(cli, input="\n".join(commands) + "\n", text=True,
                             capture_output=True, check=True, timeout=20)
        require("Math phrase licensed as exact add" in run.stdout
                and "Could not teach math examples" in run.stdout
                and "I have no verified math meaning for 'blip'. Teach 2 to 8 aligned examples"
                in run.stdout
                and "Math phrase licensed as exact modulo: 'remainder'." in run.stdout
                and "2 (learned 'remainder' as exact modulo; checked against 2 examples)"
                in run.stdout
                and "2 (exact arithmetic using '%' for modulo)" in run.stdout
                and "Math phrase licensed as exact add: 'blip'." in run.stdout
                and "11 (learned 'blip' as exact add; checked against 2 examples)"
                in run.stdout
                and "Math phrase licensed as exact add: 'glorp'." in run.stdout
                and "11 (learned 'glorp' as exact add; checked against 3 examples)"
                in run.stdout
                and "11 (learned 'plus' as exact add" in run.stdout
                and "14 (composed operations" in run.stdout
                and "x^2 + 2*x + 1 (composed operations" in run.stdout
                and "x = 4 (exact linear solution; substitution verified" in run.stdout
                and "x = 2 (exact linear solution; substitution verified" in run.stdout
                and "x ∈ {-3, 3} (exact quadratic solutions; substitution verified"
                in run.stdout
                and "200 centimeters (exact conversion; grounded by 2 meters|200 centimeters; 3 meters|300 centimeters)" in run.stdout
                and "2100 centimeters (exact conversion; grounded by 2 meters|200 centimeters; 3 meters|300 centimeters; grounded numeral: 'twenty one'=21 from add 21 to every value, add twenty one to every value)" in run.stdout
                and "4 (learned 'plus' as exact add; checked against 2 examples) meters (unit evidence:" in run.stdout
                and "24 (learned 'plus' as exact add" in run.stdout
                and "'twenty one'=21 from add 21 to every value, add twenty one to every value"
                in run.stdout
                and "I have no verified math meaning for 'zarg'" in run.stdout,
                f"ordinary chat did not route math language correctly:\n{run.stdout}")
        require(run.stdout.count(
            "11 (learned 'plus' as exact add; checked against 2 examples)") >= 4,
            "alternate natural math question forms were not routed consistently")
        require("0 centimeters (exact conversion; grounded by 2 meters|200 centimeters; 3 meters|300 centimeters)"
                in run.stdout
                and "-200 centimeters (exact conversion; grounded by 2 meters|200 centimeters; 3 meters|300 centimeters)"
                in run.stdout,
                "chat conversion did not support signed amounts with the same proof")

    print("grounded math language diagnostic: PASS")
    print("learned phrase, exact arithmetic, ambiguity, contrastive disambiguation, "
          "rational division, symbolic polynomials, linear/quadratic equations, variables, "
          "unit equivalence, conversion evidence, size bounds, abstention, "
          "persistence, and natural-chat routing: PASS")


if __name__ == "__main__":
    main()
