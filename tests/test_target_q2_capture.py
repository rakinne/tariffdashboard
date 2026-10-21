import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tariff_dashboard.evidence import (
    AccessibilityStatus,
    EvidenceExcerpt,
    EvidenceLocator,
    EvidenceRepository,
    ExtractionMethod,
    RightsError,
    RightsDecision,
    RightsRecord,
    RetentionClass,
    SourceClass,
    SourceDocument,
    fingerprint_bytes,
)
from tariff_dashboard.projection import project_claim
from tariff_dashboard.research import (
    AssertionStrength,
    DisclosureClaim,
    EffectCategory,
    PublicationGateError,
    ResearchCaseStatus,
    ResearchRepository,
    ReviewAction,
    ReviewDecision,
)
from test_research import NOW, make_case_repository


CAPTURE = Path(__file__).parents[1] / "docs" / "research" / "target-q2-2026-capture.json"


def load_capture() -> dict:
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def pending_target_evidence(capture: dict) -> EvidenceRepository:
    source = capture["source"]
    repository = EvidenceRepository()
    repository.capture_source(
        SourceDocument(
            document_id=source["document_id"],
            source_key=source["source_key"],
            version=source["version"],
            source_class=SourceClass(source["source_class"]),
            publisher=source["publisher"],
            original_url=source["original_url"],
            canonical_url=source["canonical_url"],
            title=source["title"],
            published_at=datetime.fromisoformat(source["filed_at"]).replace(tzinfo=timezone.utc),
            # This synthetic timestamp exercises the domain gate; it is not
            # persisted as a fact about when the filing was retrieved.
            retrieved_at=NOW,
            content_fingerprint=fingerprint_bytes(b"synthetic metadata-only Target fixture"),
            accessibility=AccessibilityStatus.ACCESSIBLE,
            extraction_method=ExtractionMethod.NONE,
            content_type="text/html",
            rights=RightsRecord(
                decision=RightsDecision.NEEDS_REVIEW,
                retention_class=RetentionClass.REFERENCE_ONLY,
            ),
        )
    )
    return repository


def target_claim(repository: ResearchRepository, record: dict) -> DisclosureClaim:
    return repository.add_claim(
        DisclosureClaim(
            claim_id=record["record_id"],
            case_id="case-target-synthetic",
            membership_id="synthetic-target-membership",
            company_id="synthetic-target",
            source_language_summary=record["summary"],
            effect_category=EffectCategory(record["effect_category"]),
            assertion_strength=AssertionStrength(record["assertion_strength"]),
            submitted_by="researcher-1",
            submitted_at=NOW,
            source_document_id="target-sec-10q-2026-q2-v1",
            event_period=record["event_period"],
            amount_as_quoted=record["amount_as_quoted"],
            currency=record["currency"],
            unit=record["unit"],
            tariff_program=record["tariff_program"],
        )
    )


def test_target_q2_capture_keeps_recognized_and_unresolved_claims_separate() -> None:
    capture = load_capture()
    records = {record["record_id"]: record for record in capture["records"]}

    recognized = records["target-q2-2026-refund-recognized"]
    outstanding = records["target-q2-2026-refund-claims-outstanding"]

    assert recognized["amount_as_quoted"] == "$994 million"
    assert recognized["assertion_strength"] == "explicit"
    assert outstanding["amount_as_quoted"] is None
    assert outstanding["assertion_strength"] == "not_sufficient"
    assert outstanding["record_id"] != recognized["record_id"]
    assert recognized["source_locator"] == outstanding["source_locator"]
    assert outstanding["claim_boundary"].startswith("Do not infer an amount")


def test_target_q2_capture_preserves_source_provenance_and_pending_rights() -> None:
    capture = load_capture()
    source = capture["source"]

    assert source["accession"] in source["source_key"]
    assert source["accession"].replace("-", "") in source["canonical_url"]
    assert source["period_of_report"] == "2026-08-01"
    assert source["filed_at"] == "2026-08-28"
    assert source["rights"] == {
        "decision": "needs_review",
        "public_quote_permission": False,
        "raw_artifact_permission": False,
        "retention_class": "reference_only",
    }
    assert all(record["review_status"] == "needs_review" for record in capture["records"])
    assert all(record["publication_status"].startswith("blocked_") for record in capture["records"])


@pytest.mark.parametrize("record_index", [0, 1])
def test_target_q2_pending_records_cannot_cross_the_public_projection_gate(record_index: int) -> None:
    capture = load_capture()
    research = make_case_repository()
    evidence = pending_target_evidence(capture)
    research.transition_case("case-target-synthetic", ResearchCaseStatus.IN_PROGRESS, at=NOW)
    research.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.CANDIDATE_FOUND,
        at=NOW,
        rationale="Target metadata-only fixture candidate",
    )
    research.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.NEEDS_REVIEW,
        at=NOW,
        rationale="Target source and claim remain pending independent review",
    )
    claim = target_claim(research, capture["records"][record_index])

    assert research.get_case("case-target-synthetic").freshness_recheck_at == NOW + timedelta(days=30)

    with pytest.raises(RightsError, match="public-quote permission"):
        evidence.capture_excerpt(
            EvidenceExcerpt(
                excerpt_id=f"{claim.claim_id}-excerpt",
                source_document_id="target-sec-10q-2026-q2-v1",
                exact_quote="Synthetic fixture quote; not archived Target source text.",
                locator=EvidenceLocator(section="Note 3 — Tariff Refunds"),
                surrounding_context="Synthetic fixture context.",
                captured_at=NOW,
                extraction_method=ExtractionMethod.HTML_TEXT,
            )
        )

    with pytest.raises(PublicationGateError):
        research.record_review_decision(
            ReviewDecision(
                decision_id=f"{claim.claim_id}-approval",
                claim_id=claim.claim_id,
                decision=ReviewAction.APPROVED,
                rationale="Target capture is still pending source and claim review",
                reviewer="reviewer-2",
                decided_at=NOW,
                submitter=claim.submitted_by,
            ),
            evidence_repository=evidence,
        )

    with pytest.raises(PublicationGateError):
        project_claim(
            claim,
            research_repository=research,
            evidence_repository=evidence,
            at=NOW,
        )

    assert research.review_history(claim.claim_id) == ()
