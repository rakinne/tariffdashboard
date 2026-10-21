"""Public approved-claim projection for the dashboard boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from .evidence import EvidenceRepository
from .research import DisclosureClaim, ResearchCaseStatus, ResearchRepository


PUBLIC_NO_RESULT_WORDING = (
    "No qualifying disclosure found under the documented search scope and date range. "
    "This does not mean no benefit exists."
)


@dataclass(frozen=True, slots=True)
class ApprovedClaim:
    """Only fields permitted to cross from reviewed research into the UI."""

    claim_id: str
    company_id: str
    category: str
    assertion: str
    summary: str
    amount_as_quoted: str | None
    currency: str | None
    unit: str | None
    period_as_stated: str | None
    tariff_program: str | None
    jurisdiction: str | None
    source_title: str
    source_publisher: str
    source_url: str
    source_published_at: datetime | None
    source_retrieved_at: datetime
    source_locator: dict[str, object]
    policy_version: str
    as_of: datetime
    membership_id: str | None = None
    snapshot_id: str | None = None
    exact_quote: str | None = None
    surrounding_context: str | None = None
    review_status: str = "approved"
    reviewed_at: datetime | None = None
    rights_status: str = "public_quote_permitted"
    source_accessibility: str | None = None
    source_class: str | None = None
    source_fingerprint: str | None = None
    ambiguity_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _locator_fields(locator) -> dict[str, object]:
    return {
        name: value
        for name in ("page", "section", "line_start", "line_end", "timestamp_seconds", "anchor")
        if (value := getattr(locator, name)) is not None
    }


def project_claim(
    claim: DisclosureClaim,
    *,
    research_repository: ResearchRepository,
    evidence_repository: EvidenceRepository,
    at: datetime,
) -> ApprovedClaim:
    """Validate and project one claim; no unapproved field can be returned."""

    research_repository.assert_publication_eligible(
        claim.claim_id,
        at=at,
        evidence_repository=evidence_repository,
    )
    assert claim.source_document_id is not None
    assert claim.evidence_excerpt_id is not None
    source = evidence_repository.sources.get(claim.source_document_id)
    excerpt = evidence_repository.assert_public_projection_eligible(claim.evidence_excerpt_id, at)
    return ApprovedClaim(
        claim_id=claim.claim_id,
        company_id=claim.company_id,
        category=claim.effect_category.value,
        assertion=claim.assertion_strength.value,
        summary=claim.source_language_summary,
        amount_as_quoted=claim.amount_as_quoted,
        currency=claim.currency,
        unit=claim.unit,
        period_as_stated=claim.event_period,
        tariff_program=claim.tariff_program,
        jurisdiction=claim.jurisdiction,
        source_title=source.title,
        source_publisher=source.publisher,
        source_url=source.canonical_url or source.original_url,
        source_published_at=source.published_at,
        source_retrieved_at=source.retrieved_at,
        source_locator=_locator_fields(excerpt.locator),
        policy_version=claim.policy_version,
        as_of=at,
        membership_id=claim.membership_id,
        snapshot_id=research_repository.get_case(claim.case_id).snapshot_id,
        exact_quote=excerpt.exact_quote,
        surrounding_context=excerpt.surrounding_context,
        reviewed_at=research_repository.latest_review_decision(claim.claim_id).decided_at,
        rights_status="public_quote_permitted",
        source_accessibility=source.accessibility.value,
        source_class=source.source_class.value,
        source_fingerprint=source.content_fingerprint,
        ambiguity_flags=tuple(flag.value for flag in claim.ambiguity_flags),
    )


@dataclass(frozen=True, slots=True)
class PublicCaseSummary:
    """A public coverage state that is not itself a claim."""

    case_id: str
    company_id: str
    membership_id: str
    snapshot_id: str
    status: str
    policy_version: str
    completed_at: datetime
    wording: str = PUBLIC_NO_RESULT_WORDING

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def project_no_result_case(case, *, at: datetime) -> PublicCaseSummary:
    """Project a completed no-result case without turning absence into a claim."""

    if case.status is not ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND:
        raise ValueError("only completed no-result cases can cross the public boundary")
    if case.completed_at is None:
        raise ValueError("no-result cases require completed_at")
    if case.completed_at > at:
        raise ValueError("no-result case cannot be projected before completion")
    return PublicCaseSummary(
        case_id=case.case_id,
        company_id=case.company_id,
        membership_id=case.membership_id,
        snapshot_id=case.snapshot_id,
        status=case.status.value,
        policy_version=case.policy_version,
        completed_at=case.completed_at,
    )


def project_approved_claims(
    claims: tuple[DisclosureClaim, ...] | list[DisclosureClaim],
    *,
    research_repository: ResearchRepository,
    evidence_repository: EvidenceRepository,
    at: datetime,
) -> tuple[ApprovedClaim, ...]:
    """Project a deterministic company-then-claim ordered public collection."""

    return tuple(
        project_claim(
            claim,
            research_repository=research_repository,
            evidence_repository=evidence_repository,
            at=at,
        )
        for claim in sorted(claims, key=lambda item: (item.company_id, item.claim_id))
    )


__all__ = [
    "ApprovedClaim",
    "PUBLIC_NO_RESULT_WORDING",
    "PublicCaseSummary",
    "project_approved_claims",
    "project_claim",
    "project_no_result_case",
]
