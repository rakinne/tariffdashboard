from datetime import datetime, timezone
from dataclasses import replace

import pytest

from tariff_dashboard.cohort import (
    AuthenticatedActor,
    AuthenticationError,
    CohortError,
    CohortIntake,
    CohortRepository,
    Company,
    CompanyRegistry,
    DuplicateImportError,
    Eligibility,
    ExclusionReason,
    IssuerListing,
    MappingConfidence,
    MappingMethod,
    MarketCapMembership,
    MarketCapSnapshot,
    ReviewState,
    SnapshotStatus,
)


ACTOR = AuthenticatedActor("researcher-1", frozenset({"cohort_admin"}))
AS_OF = datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)


def make_snapshot(version: str = "synthetic-v1") -> MarketCapSnapshot:
    return MarketCapSnapshot(
        snapshot_id=f"snapshot-{version}",
        version=version,
        as_of_market_close=AS_OF,
        as_of_timezone="UTC",
        provider="synthetic-fixture",
        source_url="https://synthetic.example.test/market-cap/snapshot.csv",
        retrieved_at=datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc),
        source_version="fixture-2026-10-20",
        method_version="cohort-method-v1",
        terms_record="synthetic-fixture-terms-v1",
        currency="USD",
        listing_scope="us_listed_operating_companies",
        corporate_action_treatment="provider-adjusted; fixture only",
        ranking_metric="market_cap_at_close",
    )


def make_company(company_id: str = "company-acme") -> Company:
    return Company(
        company_id=company_id,
        legal_name="Acme Holdings, Inc.",
        display_name="Acme",
        aliases=("Acme Incorporated",),
        listings=(IssuerListing("ACME", "NYSE"),),
        source_identifiers=("synthetic:acme",),
    )


def make_membership(
    snapshot_id: str,
    rank: int,
    *,
    name: str = "Acme",
    ticker: str = "ACME",
    exchange: str = "NYSE",
    source_identifier: str = "synthetic:acme",
    company_id: str | None = None,
    mapping_method: MappingMethod = MappingMethod.UNRESOLVED,
    mapping_confidence: MappingConfidence = MappingConfidence.NONE,
    review_state: ReviewState = ReviewState.NEEDS_REVIEW,
    eligibility: Eligibility = Eligibility.ELIGIBLE,
    exclusion_reason: ExclusionReason | None = None,
    share_class_key: str | None = None,
) -> MarketCapMembership:
    return MarketCapMembership(
        membership_id=f"{snapshot_id}-membership-{rank}",
        snapshot_id=snapshot_id,
        rank=rank,
        published_name=name,
        ticker=ticker,
        exchange=exchange,
        source_identifier=source_identifier,
        company_id=company_id,
        mapping_method=mapping_method,
        mapping_confidence=mapping_confidence,
        review_state=review_state,
        eligibility=eligibility,
        exclusion_reason=exclusion_reason,
        share_class_key=share_class_key,
    )


def make_ready_candidates(snapshot_id: str, count: int = 100) -> list[MarketCapMembership]:
    return [
        make_membership(
            snapshot_id,
            rank,
            name=f"Company {rank}",
            ticker=f"C{rank:03d}",
            exchange="NYSE",
            source_identifier=f"synthetic:company-{rank}",
            company_id=f"company-{rank}",
            mapping_method=MappingMethod.EXACT_SOURCE_IDENTIFIER,
            mapping_confidence=MappingConfidence.HIGH,
            review_state=ReviewState.APPROVED,
        )
        for rank in range(1, count + 1)
    ]


def make_ready_registry(count: int = 100) -> CompanyRegistry:
    return CompanyRegistry(
        Company(
            company_id=f"company-{rank}",
            legal_name=f"Company {rank} Holdings, Inc.",
            display_name=f"Company {rank}",
            listings=(IssuerListing(f"C{rank:03d}", "NYSE"),),
            source_identifiers=(f"synthetic:company-{rank}",),
        )
        for rank in range(1, count + 1)
    )


def test_snapshot_requires_complete_provenance_and_timezone() -> None:
    with pytest.raises(CohortError, match="timezone-aware"):
        replace(make_snapshot(), as_of_market_close=datetime(2026, 10, 19, 16, 0))


def test_intake_requires_authenticated_cohort_admin() -> None:
    with pytest.raises(AuthenticationError, match="cohort_admin"):
        AuthenticatedActor("researcher-1", frozenset())


def test_alias_resolution_is_retained_as_a_reviewable_mapping() -> None:
    snapshot = make_snapshot()
    registry = CompanyRegistry([make_company()])
    intake = CohortIntake(ACTOR, registry, CohortRepository())
    membership = make_membership(
        snapshot.snapshot_id,
        1,
        name="Acme Incorporated",
        ticker="UNKNOWN",
        exchange="NASDAQ",
        source_identifier="synthetic:alias-row",
    )

    record = intake.create_snapshot(snapshot, [membership])

    resolved = record.memberships[0]
    assert resolved.company_id == "company-acme"
    assert resolved.mapping_method is MappingMethod.ALIAS
    assert resolved.mapping_confidence is MappingConfidence.MEDIUM
    assert resolved.review_state is ReviewState.NEEDS_REVIEW


def test_unresolved_mapping_cannot_make_snapshot_research_ready() -> None:
    snapshot = make_snapshot()
    intake = CohortIntake(ACTOR, CompanyRegistry(), CohortRepository())
    record = intake.create_snapshot(
        snapshot,
        [make_membership(snapshot.snapshot_id, 1, name="Unknown Company", ticker="UNK")],
    )

    assert record.memberships[0].company_id is None
    with pytest.raises(CohortError, match="exactly 100"):
        intake.mark_research_ready(snapshot.snapshot_id)


def test_ambiguous_alias_is_preserved_as_unresolved() -> None:
    snapshot = make_snapshot()
    registry = CompanyRegistry(
        [
            Company(
                company_id="company-a",
                legal_name="Shared Name A, Inc.",
                display_name="Shared Name",
                listings=(IssuerListing("SHRA", "NYSE"),),
                source_identifiers=("synthetic:a",),
            ),
            Company(
                company_id="company-b",
                legal_name="Shared Name B, Inc.",
                display_name="Shared Name",
                listings=(IssuerListing("SHRB", "NYSE"),),
                source_identifiers=("synthetic:b",),
            ),
        ]
    )
    intake = CohortIntake(ACTOR, registry, CohortRepository())
    membership = make_membership(
        snapshot.snapshot_id,
        1,
        name="Shared Name",
        ticker="UNKNOWN",
        exchange="NASDAQ",
        source_identifier="synthetic:ambiguous",
    )

    record = intake.create_snapshot(snapshot, [membership])

    assert record.memberships[0].company_id is None
    assert record.memberships[0].mapping_method is MappingMethod.UNRESOLVED
    assert record.memberships[0].mapping_confidence is MappingConfidence.NONE


def test_excluded_security_is_retained_but_not_selected() -> None:
    snapshot = make_snapshot()
    intake = CohortIntake(ACTOR, CompanyRegistry(), CohortRepository())
    excluded = make_membership(
        snapshot.snapshot_id,
        1,
        name="Synthetic ETF",
        ticker="FUND",
        source_identifier="synthetic:fund",
        eligibility=Eligibility.EXCLUDED,
        exclusion_reason=ExclusionReason.ETF,
    )

    record = intake.create_snapshot(snapshot, [excluded])

    assert record.memberships[0].eligibility is Eligibility.EXCLUDED
    assert record.cohort_memberships == ()


def test_duplicate_imports_are_rejected() -> None:
    snapshot = make_snapshot()
    repository = CohortRepository()
    intake = CohortIntake(ACTOR, CompanyRegistry(), repository)
    candidates = [make_membership(snapshot.snapshot_id, 1, name="Unknown", ticker="UNK", source_identifier="synthetic:unknown")]
    intake.create_snapshot(snapshot, candidates)

    with pytest.raises(DuplicateImportError, match="snapshot already imported"):
        intake.create_snapshot(snapshot, candidates)


def test_research_ready_requires_exactly_100_reviewed_resolved_members() -> None:
    snapshot = make_snapshot()
    repository = CohortRepository()
    intake = CohortIntake(ACTOR, make_ready_registry(), repository)
    intake.create_snapshot(snapshot, make_ready_candidates(snapshot.snapshot_id, 99))

    with pytest.raises(CohortError, match="exactly 100"):
        intake.mark_research_ready(snapshot.snapshot_id)


def test_research_ready_rejects_later_ranks_even_when_count_is_100() -> None:
    snapshot = make_snapshot()
    repository = CohortRepository()
    intake = CohortIntake(ACTOR, make_ready_registry(200), repository)
    intake.create_snapshot(snapshot, make_ready_candidates(snapshot.snapshot_id, 200)[100:])

    with pytest.raises(CohortError, match="ranks 1 through 100"):
        intake.mark_research_ready(snapshot.snapshot_id)


def test_research_ready_transition_freezes_memberships_and_allows_new_version() -> None:
    repository = CohortRepository()
    intake = CohortIntake(ACTOR, make_ready_registry(), repository)
    first = make_snapshot("synthetic-v1")
    intake.create_snapshot(first, make_ready_candidates(first.snapshot_id))
    ready = intake.mark_research_ready(first.snapshot_id)

    second = make_snapshot("synthetic-v2")
    second_record = intake.create_snapshot(second, make_ready_candidates(second.snapshot_id))

    assert ready.snapshot.status is SnapshotStatus.RESEARCH_READY
    assert repository.get(first.snapshot_id).memberships == ready.memberships
    assert repository.get(first.snapshot_id).snapshot.version == "synthetic-v1"
    assert second_record.snapshot.version == "synthetic-v2"
    assert repository.get(second.snapshot_id).memberships != ready.memberships


def test_duplicate_company_and_duplicate_listing_are_rejected() -> None:
    snapshot = make_snapshot()
    intake = CohortIntake(
        ACTOR,
        CompanyRegistry(
            [
                Company(
                    company_id="company-1",
                    legal_name="Company One Holdings, Inc.",
                    display_name="Company One",
                    listings=(IssuerListing("ONE", "NYSE"),),
                    source_identifiers=("synthetic:one",),
                )
            ]
        ),
        CohortRepository(),
    )
    first = make_membership(
        snapshot.snapshot_id,
        1,
        company_id="company-1",
        mapping_method=MappingMethod.MANUAL_REVIEW,
        mapping_confidence=MappingConfidence.HIGH,
        review_state=ReviewState.APPROVED,
        ticker="ONE",
        source_identifier="synthetic:one",
    )
    duplicate_company = make_membership(
        snapshot.snapshot_id,
        2,
        company_id="company-1",
        mapping_method=MappingMethod.MANUAL_REVIEW,
        mapping_confidence=MappingConfidence.HIGH,
        review_state=ReviewState.APPROVED,
        ticker="TWO",
        source_identifier="synthetic:two",
    )

    with pytest.raises(DuplicateImportError, match="company appears"):
        intake.create_snapshot(snapshot, [first, duplicate_company])
