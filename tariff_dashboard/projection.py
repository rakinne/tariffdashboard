"""Public approved-claim projection for the dashboard boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from .evidence import EvidenceRepository
from .research import DisclosureClaim, ResearchRepository


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
    )


def project_approved_claims(
    claims: tuple[DisclosureClaim, ...] | list[DisclosureClaim],
    *,
    research_repository: ResearchRepository,
    evidence_repository: EvidenceRepository,
    at: datetime,
) -> tuple[ApprovedClaim, ...]:
    """Project a deterministic, claim-id ordered public collection."""

    return tuple(
        project_claim(
            claim,
            research_repository=research_repository,
            evidence_repository=evidence_repository,
            at=at,
        )
        for claim in sorted(claims, key=lambda item: item.claim_id)
    )


__all__ = ["ApprovedClaim", "project_approved_claims", "project_claim"]
