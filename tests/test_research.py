from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tariff_dashboard.cohort import (
    Eligibility,
    MappingConfidence,
    MappingMethod,
    MarketCapMembership,
    ReviewState,
)
from tariff_dashboard.evidence import (
    AccessibilityStatus,
    EvidenceExcerpt,
    EvidenceLocator,
    EvidenceRepository,
    ExtractionMethod,
    RightsBasis,
    RightsDecision,
    RightsRecord,
    RetentionClass,
    SourceClass,
    SourceDocument,
    fingerprint_bytes,
)
from tariff_dashboard.research import (
    AmbiguityFlag,
    AssertionStrength,
    DisclosureClaim,
    EffectCategory,
    DuplicateResearchError,
    PublicationGateError,
    ResearchCaseStatus,
    ResearchError,
    ResearchRepository,
    ReviewAction,
    ReviewDecision,
    ReviewError,
    SearchLogEntry,
)


NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def membership(*, membership_id: str = "synthetic-target-membership") -> MarketCapMembership:
    return MarketCapMembership(
        membership_id=membership_id,
        snapshot_id="synthetic-cohort-v1",
        rank=1,
        published_name="Target (synthetic fixture)",
        ticker="SYNTH",
        exchange="NYSE",
        source_identifier="synthetic:target",
        company_id="synthetic-target",
        mapping_method=MappingMethod.MANUAL_REVIEW,
        mapping_confidence=MappingConfidence.HIGH,
        review_state=ReviewState.APPROVED,
        eligibility=Eligibility.ELIGIBLE,
    )


def quote_rights() -> RightsRecord:
    return RightsRecord(
        basis=RightsBasis.COUNSEL_APPROVAL,
        decision=RightsDecision.ALLOWED,
        retention_class=RetentionClass.COUNSEL_APPROVED_QUOTE,
        public_quote_permission=True,
        usage_scope=("public quoted evidence excerpt",),
        permission_reference="https://rights.example.test/decision/quote-1",
        reviewer="governance-reviewer",
        decided_at=NOW,
    )


def evidence_repository() -> EvidenceRepository:
    repository = EvidenceRepository()
    repository.capture_source(
        SourceDocument(
            document_id="synthetic-doc-1",
            source_key="issuer:synthetic-target-release",
            version=1,
            source_class=SourceClass.ISSUER_HOSTED_IR_MATERIAL,
            publisher="Synthetic issuer",
            original_url="https://issuer.example.test/releases/1",
            canonical_url="https://issuer.example.test/releases/1",
            title="Synthetic issuer release",
            published_at=NOW - timedelta(days=1),
            retrieved_at=NOW,
            content_fingerprint=fingerprint_bytes(b"synthetic source"),
            accessibility=AccessibilityStatus.ACCESSIBLE,
            extraction_method=ExtractionMethod.HTML_TEXT,
            content_type="text/html",
            rights=quote_rights(),
        )
    )
    repository.capture_excerpt(
        EvidenceExcerpt(
            excerpt_id="synthetic-excerpt-1",
            source_document_id="synthetic-doc-1",
            exact_quote="Synthetic quote: duties already paid were returned.",
            locator=EvidenceLocator(page=2, section="Tariffs"),
            surrounding_context="Synthetic surrounding context.",
            captured_at=NOW,
            extraction_method=ExtractionMethod.HTML_TEXT,
        )
    )
    repository.verify_excerpt("synthetic-excerpt-1", "independent-reviewer", NOW)
    return repository


def make_case_repository() -> ResearchRepository:
    repository = ResearchRepository()
    repository.create_case(
        membership(),
        case_id="case-target-synthetic",
        scope_version="synthetic-scope-v1",
        owner="researcher-1",
        freshness_recheck_at=NOW + timedelta(days=30),
    )
    return repository


def make_claim(
    repository: ResearchRepository,
    *,
    category: EffectCategory = EffectCategory.REFUND,
    strength: AssertionStrength = AssertionStrength.EXPLICIT,
    flags: tuple[AmbiguityFlag, ...] = (),
    submitted_by: str = "researcher-1",
) -> DisclosureClaim:
    return repository.add_claim(
        DisclosureClaim(
            claim_id="claim-1",
            case_id="case-target-synthetic",
            membership_id="synthetic-target-membership",
            company_id="synthetic-target",
            source_language_summary="The issuer states that duties already paid were returned.",
            effect_category=category,
            assertion_strength=strength,
            submitted_by=submitted_by,
            submitted_at=NOW,
            evidence_excerpt_id="synthetic-excerpt-1",
            source_document_id="synthetic-doc-1",
            mechanism="return of duties already paid",
            ambiguity_flags=flags,
        )
    )


def test_one_case_per_reviewed_membership_and_lifecycle_includes_no_result() -> None:
    repository = ResearchRepository()
    case = repository.create_case(
        membership(),
        case_id="case-target-synthetic",
        scope_version="synthetic-scope-v1",
        owner="researcher-1",
        freshness_recheck_at=NOW + timedelta(days=30),
    )
    repository.add_search_log(
        case.case_id,
        SearchLogEntry(
            query="synthetic tariff disclosure query",
            searched_at=NOW,
            source_scope=("issuer IR", "SEC"),
            date_from="2026-01-01",
            date_to="2026-10-20",
            result_summary="No qualifying synthetic disclosure found.",
        ),
    )
    repository.transition_case(case.case_id, ResearchCaseStatus.IN_PROGRESS, at=NOW)
    completed = repository.transition_case(
        case.case_id,
        ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND,
        at=NOW + timedelta(hours=1),
        rationale="documented synthetic search completed",
        no_result_rationale=(
            "No qualifying disclosure found under the documented search scope and date range. "
            "This does not mean no benefit exists."
        ),
    )

    assert completed.status is ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND
    assert len(repository.case_for_membership(case.membership_id).search_log) == 1
    with pytest.raises(DuplicateResearchError):
        repository.create_case(
            membership(),
            case_id="case-duplicate",
            scope_version="synthetic-scope-v1",
            owner="researcher-1",
        )


def test_invalid_case_membership_is_rejected() -> None:
    unresolved = membership()
    unresolved = replace(
        unresolved,
        company_id=None,
        mapping_method=MappingMethod.UNRESOLVED,
        mapping_confidence=MappingConfidence.NONE,
        review_state=ReviewState.NEEDS_REVIEW,
    )
    with pytest.raises(ResearchError, match="resolved"):
        ResearchRepository().create_case(
            unresolved,
            case_id="case-unresolved",
            scope_version="synthetic-scope-v1",
            owner="researcher-1",
        )


def test_self_approval_and_non_public_categories_are_blocked() -> None:
    repository = make_case_repository()
    repository.transition_case("case-target-synthetic", ResearchCaseStatus.IN_PROGRESS, at=NOW)
    repository.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.CANDIDATE_FOUND,
        at=NOW + timedelta(minutes=1),
    )
    repository.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.NEEDS_REVIEW,
        at=NOW + timedelta(minutes=2),
    )
    claim = make_claim(repository)
    with pytest.raises(ReviewError, match="cannot approve"):
        repository.record_review_decision(
            ReviewDecision(
                decision_id="decision-self",
                claim_id=claim.claim_id,
                decision=ReviewAction.APPROVED,
                rationale="self approval is invalid",
                reviewer="researcher-1",
                decided_at=NOW,
            ),
            evidence_repository=evidence_repository(),
        )

    rejected_claim = repository.add_claim(
        DisclosureClaim(
            claim_id="claim-not-benefit",
            case_id="case-target-synthetic",
            membership_id="synthetic-target-membership",
            company_id="synthetic-target",
            source_language_summary="Synthetic tariff exposure statement.",
            effect_category=EffectCategory.TARIFF_EFFECT_NOT_BENEFIT,
            assertion_strength=AssertionStrength.EXPLICIT,
            submitted_by="researcher-1",
            submitted_at=NOW,
        )
    )
    with pytest.raises(PublicationGateError, match="category"):
        repository.record_review_decision(
            ReviewDecision(
                decision_id="decision-not-benefit",
                claim_id=rejected_claim.claim_id,
                decision=ReviewAction.APPROVED,
                rationale="not a public benefit claim",
                reviewer="reviewer-2",
                decided_at=NOW,
            ),
            evidence_repository=evidence_repository(),
        )


def test_approval_requires_primary_rights_provenance_policy_and_no_ambiguity() -> None:
    repository = make_case_repository()
    repository.transition_case("case-target-synthetic", ResearchCaseStatus.IN_PROGRESS, at=NOW)
    repository.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.CANDIDATE_FOUND,
        at=NOW + timedelta(minutes=1),
    )
    repository.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.NEEDS_REVIEW,
        at=NOW + timedelta(minutes=2),
    )
    claim = make_claim(repository, flags=(AmbiguityFlag.TARIFF_CONNECTION_AMBIGUOUS,))
    with pytest.raises(PublicationGateError, match="ambiguity"):
        repository.record_review_decision(
            ReviewDecision(
                decision_id="decision-ambiguous",
                claim_id=claim.claim_id,
                decision=ReviewAction.APPROVED,
                rationale="ambiguous tariff linkage",
                reviewer="reviewer-2",
                decided_at=NOW,
            ),
            evidence_repository=evidence_repository(),
        )

    clean = DisclosureClaim(
        **{
            field: getattr(claim, field)
            for field in DisclosureClaim.__dataclass_fields__
            if field not in {"claim_id", "ambiguity_flags"}
        },
        claim_id="claim-clean",
        ambiguity_flags=(),
    )
    repository.add_claim(clean)
    decision = repository.record_review_decision(
        ReviewDecision(
            decision_id="decision-approved",
            claim_id="claim-clean",
            decision=ReviewAction.APPROVED,
            rationale="independent review passed all publication gates",
            reviewer="reviewer-2",
            decided_at=NOW,
        ),
        evidence_repository=evidence_repository(),
    )

    assert decision.decision is ReviewAction.APPROVED
    assert repository.latest_review_decision("claim-clean") == decision
    assert repository.get_case("case-target-synthetic").status is ResearchCaseStatus.COMPLETE
    assert len(repository.review_history("claim-clean")) == 1
    assert repository.assert_publication_eligible(
        "claim-clean",
        at=NOW,
        evidence_repository=evidence_repository(),
    ) == clean

    repository.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.STALE,
        at=NOW + timedelta(minutes=3),
        rationale="freshness recheck is due",
    )
    with pytest.raises(PublicationGateError, match="stale research cases"):
        repository.assert_publication_eligible(
            "claim-clean",
            at=NOW + timedelta(minutes=3),
            evidence_repository=evidence_repository(),
        )


def test_review_history_is_append_only_and_corrections_retain_prior_decision() -> None:
    repository = make_case_repository()
    repository.transition_case("case-target-synthetic", ResearchCaseStatus.IN_PROGRESS, at=NOW)
    repository.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.CANDIDATE_FOUND,
        at=NOW + timedelta(minutes=1),
    )
    repository.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.NEEDS_REVIEW,
        at=NOW + timedelta(minutes=2),
    )
    claim = make_claim(repository)
    first = repository.record_review_decision(
        ReviewDecision(
            decision_id="decision-return",
            claim_id=claim.claim_id,
            decision=ReviewAction.NEEDS_CLARIFICATION,
            rationale="confirm the source period",
            reviewer="reviewer-2",
            decided_at=NOW,
        )
    )
    second = repository.record_review_decision(
        ReviewDecision(
            decision_id="decision-reject",
            claim_id=claim.claim_id,
            decision=ReviewAction.REJECTED,
            rationale="period could not be confirmed",
            reviewer="reviewer-3",
            decided_at=NOW + timedelta(minutes=1),
        )
    )
    assert repository.review_history(claim.claim_id) == (first, second)
