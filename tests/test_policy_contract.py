import json
from pathlib import Path


POLICY_DIR = Path(__file__).parents[1] / "policy"
TAXONOMY_PATH = POLICY_DIR / "taxonomy_v1.json"
EXAMPLES_PATH = POLICY_DIR / "synthetic_decision_examples_v1.json"
POLICY_PATH = POLICY_DIR / "research_policy_v1.md"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_policy_artifacts_share_a_version_and_are_referenced_by_the_policy() -> None:
    taxonomy = load_json(TAXONOMY_PATH)
    examples = load_json(EXAMPLES_PATH)
    policy = POLICY_PATH.read_text(encoding="utf-8")

    assert taxonomy["policy_version"] == "1.0.0"
    assert examples["policy_version"] == taxonomy["policy_version"]
    assert "taxonomy_v1.json" in policy
    assert "synthetic_decision_examples_v1.json" in policy
    assert "FOO-10" in policy


def test_controlled_values_match_the_v1_contract() -> None:
    controlled = load_json(TAXONOMY_PATH)["controlled_values"]

    assert [item["value"] for item in controlled["effect_category"]] == [
        "refund",
        "duty_drawback",
        "exclusion_or_waiver",
        "reimbursement_or_offset",
        "other_explicit_benefit",
        "tariff_effect_not_benefit",
        "unclassified",
    ]
    assert [item["value"] for item in controlled["assertion_strength"]] == [
        "explicit",
        "explicit_amount_link_ambiguous",
        "qualitative_explicit",
        "not_sufficient",
    ]
    assert controlled["research_case_status"] == [
        "not_started",
        "in_progress",
        "candidate_found",
        "no_qualifying_disclosure_found",
        "needs_review",
        "complete",
        "stale",
    ]
    assert controlled["review_decision"] == [
        "approved",
        "rejected",
        "needs_clarification",
        "superseded",
    ]
    assert controlled["ambiguity_flag"] == [
        "entity_ambiguous",
        "mechanism_ambiguous",
        "amount_ambiguous",
        "period_ambiguous",
        "tariff_connection_ambiguous",
        "contradictory_source",
        "rights_unresolved",
    ]


def test_taxonomy_encodes_the_non_inference_and_publication_gates() -> None:
    taxonomy = load_json(TAXONOMY_PATH)
    categories = {item["value"]: item for item in taxonomy["controlled_values"]["effect_category"]}
    strengths = {item["value"]: item for item in taxonomy["controlled_values"]["assertion_strength"]}

    assert categories["refund"]["public_eligible"] is True
    assert categories["refund"]["aggregation_eligible"] is False
    assert categories["unclassified"]["public_eligible"] is False
    assert categories["tariff_effect_not_benefit"]["benefit"] is False
    assert strengths["explicit_amount_link_ambiguous"]["public_eligible"] is False
    assert taxonomy["publication_rules"]["automatic_publication"] is False
    assert taxonomy["publication_rules"]["refund_requires_explicit_repayment_or_return"] is True
    assert taxonomy["publication_rules"]["missing_disclosure_is_not_a_negative_claim"] is True
    assert taxonomy["rights_default"] == "reference_only"
    assert "No qualifying disclosure found" in taxonomy["no_qualifying_disclosure_wording"]


def test_examples_are_synthetic_labeled_and_cover_the_required_decision_surface() -> None:
    examples = load_json(EXAMPLES_PATH)["examples"]
    taxonomy = load_json(TAXONOMY_PATH)["controlled_values"]
    allowed = {
        key: {item["value"] if isinstance(item, dict) else item for item in values}
        for key, values in taxonomy.items()
    }

    assert len(examples) >= 12
    assert len({example["id"] for example in examples}) == len(examples)
    assert all(example["synthetic"] is True for example in examples)
    assert all(example["source_excerpt"] for example in examples)
    assert all(example["source_boundary"] for example in examples)
    assert all(example["claim_boundary"] for example in examples)
    assert all(example["effect_category"] in allowed["effect_category"] for example in examples)
    assert all(example["assertion_strength"] in allowed["assertion_strength"] for example in examples)
    assert all(example["research_case_status"] in allowed["research_case_status"] for example in examples)
    assert all(example["review_decision"] in allowed["review_decision"] for example in examples)
    assert all(
        flag in allowed["ambiguity_flag"]
        for example in examples
        for flag in example["ambiguity_flags"]
    )


def test_examples_enforce_the_strict_refund_boundary() -> None:
    examples = load_json(EXAMPLES_PATH)["examples"]
    refunds = [example for example in examples if example["effect_category"] == "refund"]

    assert refunds
    assert all(
        any(word in example["source_excerpt"].casefold() for word in ("return", "repaid", "repayment"))
        for example in refunds
    )
    assert all(
        "exclusion" not in example["source_excerpt"].casefold()
        and "price" not in example["source_excerpt"].casefold()
        and "drawback" not in example["source_excerpt"].casefold()
        for example in refunds
    )

    by_id = {example["id"]: example for example in examples}
    assert by_id["EX-03"]["effect_category"] == "exclusion_or_waiver"
    assert by_id["EX-07"]["effect_category"] == "tariff_effect_not_benefit"
    assert by_id["EX-08"]["effect_category"] == "unclassified"
    assert by_id["EX-08"]["public_eligible"] is False


def test_source_class_boundaries_and_public_dispositions_are_explicit() -> None:
    taxonomy = load_json(TAXONOMY_PATH)
    examples = load_json(EXAMPLES_PATH)["examples"]
    allowed_source_classes = {
        source_class
        for source_classes in taxonomy["source_classes"].values()
        for source_class in source_classes
    }

    assert all(example["source_class"] in allowed_source_classes for example in examples)
    assert all(example["public_disposition"] for example in examples)
    assert all(
        not example["public_eligible"]
        for example in examples
        if example["source_class"] in taxonomy["source_classes"]["lead_only"]
        or example["source_class"] in taxonomy["source_classes"]["scope_input_not_claim_evidence"]
    )
    assert any(example["source_class"] == "issuer_authorized_vendor_transcript" for example in examples)
    assert any("rights" in example["claim_boundary"].casefold() for example in examples)
