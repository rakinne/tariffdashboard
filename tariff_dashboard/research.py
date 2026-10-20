"""Research cases, atomic disclosure claims, and independent review gates.

The models in this module are deliberately small and immutable.  They provide
the workflow contract for the internal research queue; persistence, HTTP, and
UI concerns belong to later tickets.  A claim can be retained as a candidate
without publishable evidence, but approval always resolves through the
existing cohort and evidence boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .cohort import Eligibility, MarketCapMembership, ReviewState
from .evidence import EvidenceError, EvidenceRepository


V1_POLICY_VERSION = "1.0.0"


class ResearchError(ValueError):
    """Base error for research workflow and claim validation."""


class DuplicateResearchError(ResearchError):
    """Raised when an immutable research record would be duplicated."""


class InvalidResearchTransitionError(ResearchError):
    """Raised when a case lifecycle transition is not allowed."""


class ReviewError(ResearchError):
    """Raised when a review decision violates the review contract."""


class PublicationGateError(ResearchError):
    """Raised when a claim cannot enter the approved/public state."""


class ResearchCaseStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    CANDIDATE_FOUND = "candidate_found"
    NO_QUALIFYING_DISCLOSURE_FOUND = "no_qualifying_disclosure_found"
    NEEDS_REVIEW = "needs_review"
    COMPLETE = "complete"
    STALE = "stale"


class EffectCategory(StrEnum):
    REFUND = "refund"
    DUTY_DRAWBACK = "duty_drawback"
    EXCLUSION_OR_WAIVER = "exclusion_or_waiver"
    REIMBURSEMENT_OR_OFFSET = "reimbursement_or_offset"
    OTHER_EXPLICIT_BENEFIT = "other_explicit_benefit"
    TARIFF_EFFECT_NOT_BENEFIT = "tariff_effect_not_benefit"
    UNCLASSIFIED = "unclassified"

    @property
    def public_eligible(self) -> bool:
        return self in {
            self.REFUND,
            self.DUTY_DRAWBACK,
            self.EXCLUSION_OR_WAIVER,
            self.REIMBURSEMENT_OR_OFFSET,
            self.OTHER_EXPLICIT_BENEFIT,
        }


class AssertionStrength(StrEnum):
    EXPLICIT = "explicit"
    EXPLICIT_AMOUNT_LINK_AMBIGUOUS = "explicit_amount_link_ambiguous"
    QUALITATIVE_EXPLICIT = "qualitative_explicit"
    NOT_SUFFICIENT = "not_sufficient"

    @property
    def public_eligible(self) -> bool:
        return self in {self.EXPLICIT, self.QUALITATIVE_EXPLICIT}


class AmbiguityFlag(StrEnum):
    ENTITY_AMBIGUOUS = "entity_ambiguous"
    MECHANISM_AMBIGUOUS = "mechanism_ambiguous"
    AMOUNT_AMBIGUOUS = "amount_ambiguous"
    PERIOD_AMBIGUOUS = "period_ambiguous"
    TARIFF_CONNECTION_AMBIGUOUS = "tariff_connection_ambiguous"
    CONTRADICTORY_SOURCE = "contradictory_source"
    RIGHTS_UNRESOLVED = "rights_unresolved"


class ReviewAction(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CLARIFICATION = "needs_clarification"
    SUPERSEDED = "superseded"


# Friendly aliases for callers that use the vocabulary from the policy.
ResearchStatus = ResearchCaseStatus
ClaimCategory = EffectCategory
ClaimAssertionStrength = AssertionStrength
ReviewDecisionType = ReviewAction


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchError(f"{field} is required")
    return value.strip()


def _require_aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ResearchError(f"{field} must be timezone-aware")


def _coerce_enum(value, enum_type, field: str):
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ResearchError(f"invalid {field}: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class SearchLogEntry:
    """One reproducible search action in a research case."""

    query: str
    searched_at: datetime
    source_scope: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    result_summary: str = ""

    def __post_init__(self) -> None:
        _require_text(self.query, "query")
        _require_aware(self.searched_at, "searched_at")
        for source in self.source_scope:
            _require_text(source, "source_scope value")
        if self.date_from is not None:
            _require_text(self.date_from, "date_from")
        if self.date_to is not None:
            _require_text(self.date_to, "date_to")
        if self.result_summary:
            _require_text(self.result_summary, "result_summary")


_ALLOWED_TRANSITIONS: dict[ResearchCaseStatus, frozenset[ResearchCaseStatus]] = {
    ResearchCaseStatus.NOT_STARTED: frozenset({ResearchCaseStatus.IN_PROGRESS}),
    ResearchCaseStatus.IN_PROGRESS: frozenset(
        {
            ResearchCaseStatus.CANDIDATE_FOUND,
            ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND,
            ResearchCaseStatus.STALE,
        }
    ),
    ResearchCaseStatus.CANDIDATE_FOUND: frozenset(
        {ResearchCaseStatus.NEEDS_REVIEW, ResearchCaseStatus.IN_PROGRESS, ResearchCaseStatus.STALE}
    ),
    ResearchCaseStatus.NEEDS_REVIEW: frozenset(
        {ResearchCaseStatus.COMPLETE, ResearchCaseStatus.IN_PROGRESS, ResearchCaseStatus.STALE}
    ),
    ResearchCaseStatus.COMPLETE: frozenset({ResearchCaseStatus.STALE}),
    ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND: frozenset({ResearchCaseStatus.STALE}),
    ResearchCaseStatus.STALE: frozenset({ResearchCaseStatus.IN_PROGRESS}),
}


@dataclass(frozen=True, slots=True)
class ResearchCase:
    """One dated research pass for one reviewed cohort membership."""

    case_id: str
    membership_id: str
    snapshot_id: str
    company_id: str
    scope_version: str
    policy_version: str
    owner: str
    created_at: datetime | None = None
    status: ResearchCaseStatus = ResearchCaseStatus.NOT_STARTED
    status_rationale: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    search_log: tuple[SearchLogEntry, ...] = ()
    no_result_rationale: str | None = None
    exclusion_rationale: str | None = None
    freshness_recheck_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, field in (
            (self.case_id, "case_id"),
            (self.membership_id, "membership_id"),
            (self.snapshot_id, "snapshot_id"),
            (self.company_id, "company_id"),
            (self.scope_version, "scope_version"),
            (self.policy_version, "policy_version"),
            (self.owner, "owner"),
        ):
            _require_text(value, field)
        object.__setattr__(self, "status", _coerce_enum(self.status, ResearchCaseStatus, "status"))
        for value, field in (
            (self.created_at, "created_at"),
            (self.started_at, "started_at"),
            (self.completed_at, "completed_at"),
            (self.freshness_recheck_at, "freshness_recheck_at"),
        ):
            if value is not None:
                _require_aware(value, field)
        if self.status_rationale is not None:
            _require_text(self.status_rationale, "status_rationale")
        if self.no_result_rationale is not None:
            _require_text(self.no_result_rationale, "no_result_rationale")
        if self.exclusion_rationale is not None:
            _require_text(self.exclusion_rationale, "exclusion_rationale")
        if self.status in {
            ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND,
            ResearchCaseStatus.STALE,
        } and not self.status_rationale:
            raise ResearchError(f"{self.status.value} requires a status_rationale")
        if self.status is ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND:
            if not self.no_result_rationale:
                raise ResearchError("no_qualifying_disclosure_found requires no_result_rationale")
            if self.completed_at is None:
                raise ResearchError("completed research cases require completed_at")
        if self.status is ResearchCaseStatus.COMPLETE and self.completed_at is None:
            raise ResearchError("complete research cases require completed_at")
        for entry in self.search_log:
            if not isinstance(entry, SearchLogEntry):
                raise ResearchError("search_log must contain SearchLogEntry records")

    @classmethod
    def from_membership(
        cls,
        membership: MarketCapMembership,
        *,
        case_id: str,
        scope_version: str,
        policy_version: str = V1_POLICY_VERSION,
        owner: str,
        created_at: datetime | None = None,
        freshness_recheck_at: datetime | None = None,
    ) -> "ResearchCase":
        _validate_reviewed_membership(membership)
        return cls(
            case_id=case_id,
            membership_id=membership.membership_id,
            snapshot_id=membership.snapshot_id,
            company_id=membership.company_id or "",
            scope_version=scope_version,
            policy_version=policy_version,
            owner=owner,
            created_at=created_at,
            freshness_recheck_at=freshness_recheck_at,
        )

    def transition(
        self,
        status: ResearchCaseStatus,
        *,
        at: datetime,
        rationale: str | None = None,
        no_result_rationale: str | None = None,
    ) -> "ResearchCase":
        _require_aware(at, "at")
        next_status = _coerce_enum(status, ResearchCaseStatus, "status")
        if next_status is not self.status and next_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidResearchTransitionError(
                f"cannot transition research case from {self.status.value} to {next_status.value}"
            )
        if next_status is self.status:
            raise InvalidResearchTransitionError(f"research case is already {next_status.value}")
        if next_status is ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND and not no_result_rationale:
            raise ResearchError("no_qualifying_disclosure_found requires no_result_rationale")
        if next_status in {ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND, ResearchCaseStatus.STALE} and not rationale:
            raise ResearchError(f"{next_status.value} requires a rationale")
        started_at = self.started_at or (at if next_status is ResearchCaseStatus.IN_PROGRESS else None)
        completed_at = at if next_status in {
            ResearchCaseStatus.COMPLETE,
            ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND,
        } else (None if next_status is ResearchCaseStatus.IN_PROGRESS else self.completed_at)
        return replace(
            self,
            status=next_status,
            status_rationale=rationale or self.status_rationale,
            no_result_rationale=no_result_rationale or self.no_result_rationale,
            started_at=started_at,
            completed_at=completed_at,
        )


@dataclass(frozen=True, slots=True)
class DisclosureClaim:
    """One atomic, source-scoped economic effect candidate."""

    claim_id: str
    case_id: str
    membership_id: str
    company_id: str
    source_language_summary: str
    effect_category: EffectCategory
    assertion_strength: AssertionStrength
    submitted_by: str
    submitted_at: datetime
    evidence_excerpt_id: str | None = None
    source_document_id: str | None = None
    event_period: str | None = None
    amount_as_quoted: str | None = None
    currency: str | None = None
    unit: str | None = None
    amount_precision: str | None = None
    tariff_program: str | None = None
    jurisdiction: str | None = None
    mechanism: str | None = None
    ambiguity_flags: tuple[AmbiguityFlag, ...] = ()
    policy_version: str = V1_POLICY_VERSION

    def __post_init__(self) -> None:
        for value, field in (
            (self.claim_id, "claim_id"),
            (self.case_id, "case_id"),
            (self.membership_id, "membership_id"),
            (self.company_id, "company_id"),
            (self.source_language_summary, "source_language_summary"),
            (self.submitted_by, "submitted_by"),
            (self.policy_version, "policy_version"),
        ):
            _require_text(value, field)
        _require_aware(self.submitted_at, "submitted_at")
        object.__setattr__(self, "effect_category", _coerce_enum(self.effect_category, EffectCategory, "effect_category"))
        object.__setattr__(self, "assertion_strength", _coerce_enum(self.assertion_strength, AssertionStrength, "assertion_strength"))
        flags = tuple(_coerce_enum(flag, AmbiguityFlag, "ambiguity_flag") for flag in self.ambiguity_flags)
        if len(flags) != len(set(flags)):
            raise ResearchError("ambiguity_flags must be unique")
        object.__setattr__(self, "ambiguity_flags", flags)
        for value, field in (
            (self.evidence_excerpt_id, "evidence_excerpt_id"),
            (self.source_document_id, "source_document_id"),
            (self.event_period, "event_period"),
            (self.amount_as_quoted, "amount_as_quoted"),
            (self.currency, "currency"),
            (self.unit, "unit"),
            (self.amount_precision, "amount_precision"),
            (self.tariff_program, "tariff_program"),
            (self.jurisdiction, "jurisdiction"),
            (self.mechanism, "mechanism"),
        ):
            if value is not None:
                _require_text(value, field)
        if self.evidence_excerpt_id and not self.source_document_id:
            raise ResearchError("evidence_excerpt_id requires source_document_id")


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """An append-only decision on one claim."""

    decision_id: str
    claim_id: str
    decision: ReviewAction
    rationale: str
    reviewer: str
    decided_at: datetime
    policy_version: str = V1_POLICY_VERSION
    submitter: str | None = None

    def __post_init__(self) -> None:
        for value, field in (
            (self.decision_id, "decision_id"),
            (self.claim_id, "claim_id"),
            (self.rationale, "rationale"),
            (self.reviewer, "reviewer"),
            (self.policy_version, "policy_version"),
        ):
            _require_text(value, field)
        _require_aware(self.decided_at, "decided_at")
        object.__setattr__(self, "decision", _coerce_enum(self.decision, ReviewAction, "decision"))
        if self.submitter is not None:
            _require_text(self.submitter, "submitter")


def _validate_reviewed_membership(membership: MarketCapMembership) -> None:
    if membership.eligibility is not Eligibility.ELIGIBLE:
        raise ResearchError("research cases require an eligible cohort membership")
    if membership.company_id is None:
        raise ResearchError("research cases require a resolved cohort membership")
    if membership.review_state is not ReviewState.APPROVED:
        raise ResearchError("research cases require a reviewed cohort membership")


class ResearchRepository:
    """In-memory immutable workflow store for the first vertical slice."""

    def __init__(self, *, policy_version: str = V1_POLICY_VERSION) -> None:
        self.policy_version = _require_text(policy_version, "policy_version")
        self._cases: dict[str, ResearchCase] = {}
        self._case_by_membership: dict[str, str] = {}
        self._claims: dict[str, DisclosureClaim] = {}
        self._decisions: dict[str, list[ReviewDecision]] = {}
        self._decision_ids: set[str] = set()

    def create_case(
        self,
        membership: MarketCapMembership,
        *,
        case_id: str,
        scope_version: str,
        owner: str,
        created_at: datetime | None = None,
        freshness_recheck_at: datetime | None = None,
    ) -> ResearchCase:
        _validate_reviewed_membership(membership)
        if membership.membership_id in self._case_by_membership:
            raise DuplicateResearchError(
                f"research case already exists for membership: {membership.membership_id}"
            )
        case = ResearchCase.from_membership(
            membership,
            case_id=case_id,
            scope_version=scope_version,
            policy_version=self.policy_version,
            owner=owner,
            created_at=created_at,
            freshness_recheck_at=freshness_recheck_at,
        )
        if case.case_id in self._cases:
            raise DuplicateResearchError(f"research case already exists: {case.case_id}")
        self._cases[case.case_id] = case
        self._case_by_membership[case.membership_id] = case.case_id
        return case

    def get_case(self, case_id: str) -> ResearchCase:
        try:
            return self._cases[case_id]
        except KeyError as exc:
            raise ResearchError(f"unknown research case: {case_id}") from exc

    def case_for_membership(self, membership_id: str) -> ResearchCase:
        try:
            return self._cases[self._case_by_membership[membership_id]]
        except KeyError as exc:
            raise ResearchError(f"unknown research membership: {membership_id}") from exc

    def cases(self, *, status: ResearchCaseStatus | None = None) -> tuple[ResearchCase, ...]:
        if status is not None:
            status = _coerce_enum(status, ResearchCaseStatus, "status")
        return tuple(case for case in self._cases.values() if status is None or case.status is status)

    def transition_case(
        self,
        case_id: str,
        status: ResearchCaseStatus,
        *,
        at: datetime,
        rationale: str | None = None,
        no_result_rationale: str | None = None,
    ) -> ResearchCase:
        case = self.get_case(case_id)
        updated = case.transition(
            status,
            at=at,
            rationale=rationale,
            no_result_rationale=no_result_rationale,
        )
        self._cases[case_id] = updated
        return updated

    def add_search_log(self, case_id: str, entry: SearchLogEntry) -> ResearchCase:
        case = self.get_case(case_id)
        if not isinstance(entry, SearchLogEntry):
            raise ResearchError("entry must be a SearchLogEntry")
        updated = replace(case, search_log=case.search_log + (entry,))
        self._cases[case_id] = updated
        return updated

    def add_claim(self, claim: DisclosureClaim) -> DisclosureClaim:
        if claim.claim_id in self._claims:
            raise DuplicateResearchError(f"claim already exists: {claim.claim_id}")
        case = self.get_case(claim.case_id)
        if claim.membership_id != case.membership_id or claim.company_id != case.company_id:
            raise ResearchError("claim must match its research case membership and company")
        if case.status is ResearchCaseStatus.NO_QUALIFYING_DISCLOSURE_FOUND:
            raise ResearchError("no-result cases cannot receive disclosure claims")
        if claim.policy_version != case.policy_version:
            raise ResearchError("claim policy_version must match its research case")
        self._claims[claim.claim_id] = claim
        return claim

    def claims_for_case(self, case_id: str) -> tuple[DisclosureClaim, ...]:
        self.get_case(case_id)
        return tuple(claim for claim in self._claims.values() if claim.case_id == case_id)

    def get_claim(self, claim_id: str) -> DisclosureClaim:
        try:
            return self._claims[claim_id]
        except KeyError as exc:
            raise ResearchError(f"unknown disclosure claim: {claim_id}") from exc

    def record_review_decision(
        self,
        decision: ReviewDecision,
        *,
        evidence_repository: EvidenceRepository | None = None,
    ) -> ReviewDecision:
        if decision.decision_id in self._decision_ids:
            raise DuplicateResearchError(f"review decision already exists: {decision.decision_id}")
        claim = self.get_claim(decision.claim_id)
        history = self._decisions.get(decision.claim_id, [])
        if history and decision.decided_at <= history[-1].decided_at:
            raise ReviewError("review decisions must be appended in chronological order")
        if decision.submitter is not None and decision.submitter != claim.submitted_by:
            raise ReviewError("review decision submitter does not match claim submitter")
        if decision.decision is ReviewAction.APPROVED:
            if decision.reviewer == claim.submitted_by:
                raise ReviewError("claim submitter cannot approve their own claim")
            if decision.policy_version != self.policy_version or claim.policy_version != self.policy_version:
                raise ReviewError("approval requires the current policy version")
            if evidence_repository is None:
                raise PublicationGateError("approval requires an evidence repository")
            self.assert_publication_eligible(
                claim.claim_id,
                at=decision.decided_at,
                evidence_repository=evidence_repository,
                require_approval=False,
            )
        history = self._decisions.setdefault(claim.claim_id, [])
        history.append(decision)
        self._decision_ids.add(decision.decision_id)
        if decision.decision is ReviewAction.APPROVED:
            case = self.get_case(claim.case_id)
            if case.status in {ResearchCaseStatus.CANDIDATE_FOUND, ResearchCaseStatus.NEEDS_REVIEW}:
                self._cases[case.case_id] = case.transition(
                    ResearchCaseStatus.COMPLETE,
                    at=decision.decided_at,
                    rationale="approved claim completed independent review",
                )
        return decision

    def review_history(self, claim_id: str) -> tuple[ReviewDecision, ...]:
        self.get_claim(claim_id)
        return tuple(self._decisions.get(claim_id, ()))

    def latest_review_decision(self, claim_id: str) -> ReviewDecision | None:
        history = self.review_history(claim_id)
        return history[-1] if history else None

    def assert_publication_eligible(
        self,
        claim_id: str,
        *,
        at: datetime,
        evidence_repository: EvidenceRepository,
        require_approval: bool = True,
    ) -> DisclosureClaim:
        claim = self.get_claim(claim_id)
        case = self.get_case(claim.case_id)
        if require_approval:
            latest = self.latest_review_decision(claim_id)
            if latest is None or latest.decision is not ReviewAction.APPROVED:
                raise PublicationGateError("claim requires an approved review decision")
        if case.status is ResearchCaseStatus.STALE:
            raise PublicationGateError("stale research cases require a fresh research and review pass")
        if claim.policy_version != self.policy_version or case.policy_version != self.policy_version:
            raise PublicationGateError("claim and case must use the current policy version")
        if claim.effect_category.public_eligible is False:
            raise PublicationGateError("claim category is not public eligible")
        if claim.assertion_strength.public_eligible is False:
            raise PublicationGateError("claim assertion strength is not public eligible")
        blocking_flags = {
            AmbiguityFlag.ENTITY_AMBIGUOUS,
            AmbiguityFlag.MECHANISM_AMBIGUOUS,
            AmbiguityFlag.TARIFF_CONNECTION_AMBIGUOUS,
            AmbiguityFlag.CONTRADICTORY_SOURCE,
            AmbiguityFlag.RIGHTS_UNRESOLVED,
        }
        if blocking_flags.intersection(claim.ambiguity_flags):
            raise PublicationGateError("claim has a publication-blocking ambiguity flag")
        if not claim.source_document_id or not claim.evidence_excerpt_id:
            raise PublicationGateError("approved claim requires a primary source and evidence excerpt")
        try:
            excerpt = evidence_repository.assert_public_projection_eligible(claim.evidence_excerpt_id, at)
            source = evidence_repository.sources.get(claim.source_document_id)
        except EvidenceError as exc:
            # Preserve the evidence subsystem's reason without allowing a
            # failed source/rights check to look like a valid review action.
            raise PublicationGateError(f"evidence publication gate failed: {exc}") from exc
        if excerpt.source_document_id != source.document_id:
            raise PublicationGateError("excerpt and claim source document do not match")
        if not source.internal_evidence_eligible or not source.source_class.is_primary_eligible:
            raise PublicationGateError("claim requires an eligible primary source")
        if not source.original_url or not source.title or not source.publisher:
            raise PublicationGateError("claim is missing source provenance")
        if source.published_at is None or source.retrieved_at is None or not source.content_fingerprint:
            raise PublicationGateError("claim is missing source provenance")
        if not excerpt.exact_quote or not excerpt.surrounding_context or excerpt.locator is None:
            raise PublicationGateError("claim is missing locatable evidence provenance")
        return claim


# Name used by some callers for the repository boundary.
ResearchCaseRepository = ResearchRepository


__all__ = [
    "AmbiguityFlag",
    "AssertionStrength",
    "ClaimAssertionStrength",
    "ClaimCategory",
    "DisclosureClaim",
    "DuplicateResearchError",
    "EffectCategory",
    "InvalidResearchTransitionError",
    "PublicationGateError",
    "ResearchCase",
    "ResearchCaseRepository",
    "ResearchCaseStatus",
    "ResearchError",
    "ResearchRepository",
    "ResearchStatus",
    "ReviewAction",
    "ReviewDecision",
    "ReviewDecisionType",
    "ReviewError",
    "SearchLogEntry",
    "V1_POLICY_VERSION",
]
