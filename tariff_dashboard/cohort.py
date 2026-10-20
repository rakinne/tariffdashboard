"""Versioned market-cap cohort and company-resolution domain model.

This module intentionally contains no provider integration or production market
data.  It defines the validated intake boundary that a future authenticated API
or import job can use.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import re
from typing import Iterable
from urllib.parse import urlparse


class CohortError(ValueError):
    """Base error for invalid cohort data or workflow transitions."""


class AuthenticationError(PermissionError):
    """Raised when a caller is not authorized for internal cohort intake."""


class DuplicateImportError(CohortError):
    """Raised when an import would create an ambiguous or duplicate cohort."""


class SnapshotNotFoundError(KeyError):
    """Raised when a requested snapshot does not exist."""


class SnapshotStatus(StrEnum):
    DRAFT = "draft"
    RESEARCH_READY = "research_ready"


class ReviewState(StrEnum):
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Eligibility(StrEnum):
    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"


class ExclusionReason(StrEnum):
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"
    ETN = "etn"
    CLOSED_END_FUND = "closed_end_fund"
    PRE_COMBINATION_SPAC = "pre_combination_spac"
    DUPLICATE_SHARE_CLASS = "duplicate_share_class"
    NON_US_LISTED = "non_us_listed"
    NON_OPERATING_COMPANY = "non_operating_company"


class MappingMethod(StrEnum):
    EXACT_SOURCE_IDENTIFIER = "exact_source_identifier"
    TICKER_EXCHANGE = "ticker_exchange"
    ALIAS = "alias"
    MANUAL_REVIEW = "manual_review"
    UNRESOLVED = "unresolved"


class MappingConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CohortError(f"{field_name} is required")
    return value.strip()


def _normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CohortError(f"{field_name} must be timezone-aware")


def _require_https_url(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise CohortError(f"{field_name} must be an HTTPS URL")


@dataclass(frozen=True, slots=True)
class IssuerListing:
    """A ticker/exchange pair used for company resolution."""

    ticker: str
    exchange: str

    def __post_init__(self) -> None:
        _require_text(self.ticker, "ticker")
        _require_text(self.exchange, "exchange")

    @property
    def key(self) -> tuple[str, str]:
        return (self.ticker.casefold(), self.exchange.casefold())


@dataclass(frozen=True, slots=True)
class Company:
    """Canonical operating company identity, separate from a snapshot."""

    company_id: str
    legal_name: str
    display_name: str
    aliases: tuple[str, ...] = ()
    listings: tuple[IssuerListing, ...] = ()
    source_identifiers: tuple[str, ...] = ()
    canonical_domain: str | None = None
    active: bool = True

    def __post_init__(self) -> None:
        _require_text(self.company_id, "company_id")
        _require_text(self.legal_name, "legal_name")
        _require_text(self.display_name, "display_name")
        if not self.listings and not self.source_identifiers:
            raise CohortError("company must have at least one listing or source identifier")
        if self.canonical_domain is not None:
            _require_text(self.canonical_domain, "canonical_domain")

        aliases = [_normalise_name(name) for name in self.aliases]
        if any(not alias for alias in aliases):
            raise CohortError("company aliases cannot be empty")
        if len(aliases) != len(set(aliases)):
            raise CohortError("company aliases must be unique")

        source_ids = [identifier.casefold() for identifier in self.source_identifiers]
        if any(not identifier.strip() for identifier in source_ids):
            raise CohortError("source identifiers cannot be empty")
        if len(source_ids) != len(set(source_ids)):
            raise CohortError("company source identifiers must be unique")

    @property
    def names(self) -> tuple[str, ...]:
        return (self.legal_name, self.display_name, *self.aliases)


@dataclass(frozen=True, slots=True)
class Resolution:
    company_id: str | None
    method: MappingMethod
    confidence: MappingConfidence
    reason: str | None = None


class CompanyRegistry:
    """Resolve provider identities without guessing through ambiguous aliases."""

    def __init__(self, companies: Iterable[Company] = ()) -> None:
        self._companies: dict[str, Company] = {}
        self._source_ids: dict[str, str] = {}
        self._listings: dict[tuple[str, str], str] = {}
        self._names: dict[str, list[str]] = {}
        for company in companies:
            self.register(company)

    def register(self, company: Company) -> None:
        if company.company_id in self._companies:
            raise DuplicateImportError(f"company already registered: {company.company_id}")
        for source_id in company.source_identifiers:
            key = source_id.casefold()
            if key in self._source_ids:
                raise DuplicateImportError(f"source identifier already mapped: {source_id}")
        for listing in company.listings:
            if listing.key in self._listings:
                raise DuplicateImportError(
                    f"ticker/exchange already mapped: {listing.ticker}/{listing.exchange}"
                )

        self._companies[company.company_id] = company
        for source_id in company.source_identifiers:
            self._source_ids[source_id.casefold()] = company.company_id
        for listing in company.listings:
            self._listings[listing.key] = company.company_id
        for name in company.names:
            name_key = _normalise_name(name)
            name_matches = self._names.setdefault(name_key, [])
            if company.company_id not in name_matches:
                name_matches.append(company.company_id)

    def get(self, company_id: str) -> Company:
        try:
            return self._companies[company_id]
        except KeyError as exc:
            raise CohortError(f"unknown company: {company_id}") from exc

    def resolve(
        self,
        *,
        published_name: str,
        ticker: str,
        exchange: str,
        source_identifier: str,
    ) -> Resolution:
        source_match = self._source_ids.get(source_identifier.casefold())
        if source_match is not None:
            return Resolution(source_match, MappingMethod.EXACT_SOURCE_IDENTIFIER, MappingConfidence.HIGH)

        listing_match = self._listings.get((ticker.casefold(), exchange.casefold()))
        if listing_match is not None:
            return Resolution(listing_match, MappingMethod.TICKER_EXCHANGE, MappingConfidence.HIGH)

        name_matches = self._names.get(_normalise_name(published_name), [])
        if len(name_matches) == 1:
            return Resolution(name_matches[0], MappingMethod.ALIAS, MappingConfidence.MEDIUM)
        if len(name_matches) > 1:
            return Resolution(
                None,
                MappingMethod.UNRESOLVED,
                MappingConfidence.NONE,
                "published name matches multiple companies",
            )
        return Resolution(None, MappingMethod.UNRESOLVED, MappingConfidence.NONE, "no company match")


@dataclass(frozen=True, slots=True)
class MarketCapSnapshot:
    """Immutable provenance and method record for one market-cap snapshot."""

    snapshot_id: str
    version: str
    as_of_market_close: datetime
    as_of_timezone: str
    provider: str
    source_url: str
    retrieved_at: datetime
    source_version: str
    method_version: str
    terms_record: str
    currency: str
    listing_scope: str
    corporate_action_treatment: str
    ranking_metric: str
    status: SnapshotStatus = SnapshotStatus.DRAFT

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.snapshot_id, "snapshot_id"),
            (self.version, "version"),
            (self.as_of_timezone, "as_of_timezone"),
            (self.provider, "provider"),
            (self.source_version, "source_version"),
            (self.method_version, "method_version"),
            (self.terms_record, "terms_record"),
            (self.listing_scope, "listing_scope"),
            (self.corporate_action_treatment, "corporate_action_treatment"),
            (self.ranking_metric, "ranking_metric"),
        ):
            _require_text(value, field_name)
        _require_aware_datetime(self.as_of_market_close, "as_of_market_close")
        _require_aware_datetime(self.retrieved_at, "retrieved_at")
        _require_https_url(self.source_url, "source_url")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise CohortError("currency must be a three-letter uppercase code")
        if self.listing_scope != "us_listed_operating_companies":
            raise CohortError("listing_scope must be us_listed_operating_companies")


@dataclass(frozen=True, slots=True)
class MarketCapMembership:
    """A ranked provider row, including unresolved/excluded candidates."""

    membership_id: str
    snapshot_id: str
    rank: int
    published_name: str
    ticker: str
    exchange: str
    source_identifier: str
    company_id: str | None
    mapping_method: MappingMethod
    mapping_confidence: MappingConfidence
    review_state: ReviewState
    eligibility: Eligibility = Eligibility.ELIGIBLE
    exclusion_reason: ExclusionReason | None = None
    share_class_key: str | None = None

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.membership_id, "membership_id"),
            (self.snapshot_id, "snapshot_id"),
            (self.published_name, "published_name"),
            (self.ticker, "ticker"),
            (self.exchange, "exchange"),
            (self.source_identifier, "source_identifier"),
        ):
            _require_text(value, field_name)
        if not isinstance(self.rank, int) or isinstance(self.rank, bool) or self.rank < 1:
            raise CohortError("rank must be a positive integer")
        if self.company_id is None:
            if self.mapping_method is not MappingMethod.UNRESOLVED:
                raise CohortError("unresolved membership must use mapping_method=unresolved")
            if self.mapping_confidence is not MappingConfidence.NONE:
                raise CohortError("unresolved membership must use mapping_confidence=none")
            if self.review_state is ReviewState.APPROVED:
                raise CohortError("unresolved membership cannot be approved")
        else:
            _require_text(self.company_id, "company_id")
            if self.mapping_method is MappingMethod.UNRESOLVED:
                raise CohortError("resolved membership cannot use mapping_method=unresolved")
            if self.mapping_confidence is MappingConfidence.NONE:
                raise CohortError("resolved membership must have mapping confidence")
        if self.eligibility is Eligibility.EXCLUDED:
            if self.exclusion_reason is None:
                raise CohortError("excluded membership requires an exclusion_reason")
        elif self.exclusion_reason is not None:
            raise CohortError("eligible membership cannot have an exclusion_reason")
        if self.share_class_key is not None:
            _require_text(self.share_class_key, "share_class_key")

    @property
    def resolved(self) -> bool:
        return self.company_id is not None


@dataclass(frozen=True, slots=True)
class SnapshotCohort:
    """Frozen snapshot plus all retained candidate rows from its intake."""

    snapshot: MarketCapSnapshot
    memberships: tuple[MarketCapMembership, ...]

    def __post_init__(self) -> None:
        if not self.memberships:
            raise CohortError("snapshot must retain at least one membership candidate")
        ids = [membership.membership_id for membership in self.memberships]
        if len(ids) != len(set(ids)):
            raise DuplicateImportError("membership IDs must be unique within a snapshot")
        if any(membership.snapshot_id != self.snapshot.snapshot_id for membership in self.memberships):
            raise CohortError("membership snapshot_id must match the snapshot")

    @property
    def cohort_memberships(self) -> tuple[MarketCapMembership, ...]:
        """The first 100 eligible and resolved rows, in source rank order."""

        selected = [
            membership
            for membership in self.memberships
            if membership.eligibility is Eligibility.ELIGIBLE and membership.resolved
        ]
        return tuple(sorted(selected, key=lambda membership: membership.rank)[:100])


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    """Identity supplied by the host authentication layer for internal intake."""

    subject: str
    roles: frozenset[str]

    def __post_init__(self) -> None:
        _require_text(self.subject, "subject")
        if "cohort_admin" not in self.roles:
            raise AuthenticationError("cohort_admin role is required for market-cap intake")


class CohortRepository:
    """Small in-memory repository with immutable record replacement semantics."""

    def __init__(self) -> None:
        self._records: dict[str, SnapshotCohort] = {}
        self._versions: set[str] = set()

    def add(self, record: SnapshotCohort) -> None:
        if record.snapshot.snapshot_id in self._records:
            raise DuplicateImportError(f"snapshot already imported: {record.snapshot.snapshot_id}")
        if record.snapshot.version in self._versions:
            raise DuplicateImportError(f"snapshot version already imported: {record.snapshot.version}")
        self._records[record.snapshot.snapshot_id] = record
        self._versions.add(record.snapshot.version)

    def replace(self, record: SnapshotCohort) -> None:
        if record.snapshot.snapshot_id not in self._records:
            raise SnapshotNotFoundError(record.snapshot.snapshot_id)
        existing = self._records[record.snapshot.snapshot_id]
        if existing.memberships != record.memberships:
            raise CohortError("snapshot memberships are frozen and cannot be replaced")
        self._records[record.snapshot.snapshot_id] = record

    def get(self, snapshot_id: str) -> SnapshotCohort:
        try:
            return self._records[snapshot_id]
        except KeyError as exc:
            raise SnapshotNotFoundError(snapshot_id) from exc

    def has_snapshot(self, snapshot_id: str) -> bool:
        return snapshot_id in self._records

    def has_version(self, version: str) -> bool:
        return version in self._versions


class CohortIntake:
    """Authenticated create/resolve/ready workflow for market-cap snapshots."""

    def __init__(self, actor: AuthenticatedActor, registry: CompanyRegistry, repository: CohortRepository) -> None:
        self.actor = actor
        self.registry = registry
        self.repository = repository

    def create_snapshot(
        self,
        snapshot: MarketCapSnapshot,
        memberships: Iterable[MarketCapMembership],
    ) -> SnapshotCohort:
        if snapshot.status is not SnapshotStatus.DRAFT:
            raise CohortError("new snapshots must start in draft status")
        candidates = tuple(memberships)
        if not candidates:
            raise CohortError("snapshot import requires at least one membership candidate")

        resolved_candidates = tuple(self._resolve_membership(membership) for membership in candidates)
        self._validate_import(snapshot, resolved_candidates)
        record = SnapshotCohort(snapshot=snapshot, memberships=resolved_candidates)
        self.repository.add(record)
        return record

    def mark_research_ready(self, snapshot_id: str) -> SnapshotCohort:
        record = self.repository.get(snapshot_id)
        selected = record.cohort_memberships
        if len(selected) != 100:
            raise CohortError(
                f"snapshot requires exactly 100 eligible, resolved members; found {len(selected)}"
            )
        selected_ranks = {membership.rank for membership in selected}
        if selected_ranks != set(range(1, 101)):
            raise CohortError("snapshot requires eligible, resolved source ranks 1 through 100")
        if any(
            membership.review_state is not ReviewState.APPROVED
            or membership.company_id is None
            or membership.mapping_method is MappingMethod.UNRESOLVED
            for membership in selected
        ):
            raise CohortError("all selected members must have reviewed, resolved mappings")
        ready_snapshot = replace(record.snapshot, status=SnapshotStatus.RESEARCH_READY)
        ready_record = SnapshotCohort(snapshot=ready_snapshot, memberships=record.memberships)
        self.repository.replace(ready_record)
        return ready_record

    def _resolve_membership(self, membership: MarketCapMembership) -> MarketCapMembership:
        if membership.company_id is not None:
            self.registry.get(membership.company_id)
            return membership
        resolution = self.registry.resolve(
            published_name=membership.published_name,
            ticker=membership.ticker,
            exchange=membership.exchange,
            source_identifier=membership.source_identifier,
        )
        if resolution.company_id is None:
            return membership
        return MarketCapMembership(
            **{
                field_name: getattr(membership, field_name)
                for field_name in MarketCapMembership.__dataclass_fields__
                if field_name not in {"company_id", "mapping_method", "mapping_confidence"}
            },
            company_id=resolution.company_id,
            mapping_method=resolution.method,
            mapping_confidence=resolution.confidence,
        )

    def _validate_import(
        self,
        snapshot: MarketCapSnapshot,
        memberships: tuple[MarketCapMembership, ...],
    ) -> None:
        if self.repository.has_snapshot(snapshot.snapshot_id):
            raise DuplicateImportError(f"snapshot already imported: {snapshot.snapshot_id}")
        if self.repository.has_version(snapshot.version):
            raise DuplicateImportError(f"snapshot version already imported: {snapshot.version}")
        ranks: set[int] = set()
        source_ids: set[str] = set()
        listings: set[tuple[str, str]] = set()
        company_ids: set[str] = set()
        share_classes: set[str] = set()
        for membership in memberships:
            if membership.snapshot_id != snapshot.snapshot_id:
                raise CohortError("membership snapshot_id must match the imported snapshot")
            if membership.rank in ranks:
                raise DuplicateImportError(f"duplicate source rank: {membership.rank}")
            ranks.add(membership.rank)
            source_key = membership.source_identifier.casefold()
            if source_key in source_ids:
                raise DuplicateImportError(f"duplicate source identifier: {membership.source_identifier}")
            source_ids.add(source_key)
            listing_key = (membership.ticker.casefold(), membership.exchange.casefold())
            if listing_key in listings:
                raise DuplicateImportError(
                    f"duplicate ticker/exchange: {membership.ticker}/{membership.exchange}"
                )
            listings.add(listing_key)
            if membership.eligibility is Eligibility.ELIGIBLE and membership.company_id is not None:
                if membership.company_id in company_ids:
                    raise DuplicateImportError(
                        f"company appears more than once in snapshot: {membership.company_id}"
                    )
                company_ids.add(membership.company_id)
            if membership.share_class_key is not None:
                share_class_key = membership.share_class_key.casefold()
                if share_class_key in share_classes and membership.eligibility is Eligibility.ELIGIBLE:
                    raise DuplicateImportError(f"duplicate share class: {membership.share_class_key}")
                if membership.eligibility is Eligibility.ELIGIBLE:
                    share_classes.add(share_class_key)
