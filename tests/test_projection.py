from datetime import datetime, timezone

import pytest

from tariff_dashboard.projection import project_claim
from tariff_dashboard.research import (
    PublicationGateError,
    ResearchCaseStatus,
    ReviewAction,
    ReviewDecision,
)
from test_research import NOW, evidence_repository, make_case_repository, make_claim


def reviewed_claim_fixture():
    research = make_case_repository()
    evidence = evidence_repository()
    research.transition_case("case-target-synthetic", ResearchCaseStatus.IN_PROGRESS, at=NOW)
    research.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.CANDIDATE_FOUND,
        at=NOW,
        rationale="synthetic candidate",
    )
    research.transition_case(
        "case-target-synthetic",
        ResearchCaseStatus.NEEDS_REVIEW,
        at=NOW,
        rationale="ready for independent review",
    )
    claim = make_claim(research)
    research.record_review_decision(
        ReviewDecision(
            decision_id="decision-1",
            claim_id=claim.claim_id,
            decision=ReviewAction.APPROVED,
            rationale="independent synthetic review",
            reviewer="reviewer-2",
            decided_at=NOW,
            submitter=claim.submitted_by,
        ),
        evidence_repository=evidence,
    )
    return claim, research, evidence


def test_projection_requires_the_existing_publication_gate():
    claim, research, evidence = reviewed_claim_fixture()
    projected = project_claim(
        claim,
        research_repository=research,
        evidence_repository=evidence,
        at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert projected.company_id == claim.company_id
    assert projected.amount_as_quoted == claim.amount_as_quoted
    assert projected.source_locator
    assert "evidence_excerpt_id" not in projected.to_dict()


def test_projection_rejects_unapproved_claim():
    claim, research, evidence = reviewed_claim_fixture()
    research._decisions[claim.claim_id].clear()

    with pytest.raises(PublicationGateError):
        project_claim(
            claim,
            research_repository=research,
            evidence_repository=evidence,
            at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
