"""Immutable source capture, evidence excerpts, and rights gates.

The module deliberately stores provenance metadata and fingerprints rather than
fetching or archiving source content.  A durable quote is accepted only when a
source-specific rights decision permits it.  This keeps the domain contract
usable with synthetic fixtures while avoiding an accidental source archive.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from html import escape
import hashlib
import ipaddress
import re
from typing import Iterable
from urllib.parse import urlsplit


class EvidenceError(ValueError):
    """Base error for invalid evidence or rights data."""


class FetchBoundaryError(EvidenceError):
    """Raised when a fetch request or response violates the safety boundary."""


class RightsError(EvidenceError):
    """Raised when a retention or publication right is absent or expired."""


class SourceEligibilityError(EvidenceError):
    """Raised when a non-primary or unverified source is used as evidence."""


class DuplicateSourceError(EvidenceError):
    """Raised when an immutable source/version would be duplicated."""


class SourceVersionError(EvidenceError):
    """Raised when a changed source is not captured as the next version."""


class SourceClass(StrEnum):
    SEC_FILING_OR_EXHIBIT = "sec_filing_or_exhibit"
    ISSUER_HOSTED_IR_MATERIAL = "issuer_hosted_ir_material"
    ISSUER_AUTHORIZED_VENDOR_TRANSCRIPT = "issuer_authorized_vendor_transcript"
    GOVERNMENT_RECORD_DIRECTLY_IDENTIFYING_COMPANY_EFFECT = (
        "government_record_directly_identifying_company_effect"
    )
    OTHER_OFFICIAL_ISSUER_MATERIAL_ACCEPTED_BY_REVIEW = (
        "other_official_issuer_material_accepted_by_review"
    )
    SECONDARY_REPORTING = "secondary_reporting"
    ANALYST_RESEARCH = "analyst_research"
    SEARCH_SNIPPET = "search_snippet"
    BLOG_OR_COMMENTARY = "blog_or_commentary"
    UNAUTHORIZED_TRANSCRIPT = "unauthorized_transcript"
    MACHINE_ONLY_TRANSCRIPT = "machine_only_transcript"
    AI_SUMMARY = "ai_summary"
    MARKET_CAP_SNAPSHOT = "market_cap_snapshot"

    @property
    def is_primary_eligible(self) -> bool:
        return self in {
            SourceClass.SEC_FILING_OR_EXHIBIT,
            SourceClass.ISSUER_HOSTED_IR_MATERIAL,
            SourceClass.ISSUER_AUTHORIZED_VENDOR_TRANSCRIPT,
            SourceClass.GOVERNMENT_RECORD_DIRECTLY_IDENTIFYING_COMPANY_EFFECT,
            SourceClass.OTHER_OFFICIAL_ISSUER_MATERIAL_ACCEPTED_BY_REVIEW,
        }

    @property
    def is_lead_only(self) -> bool:
        return not self.is_primary_eligible and self is not SourceClass.MARKET_CAP_SNAPSHOT


class AccessibilityStatus(StrEnum):
    ACCESSIBLE = "accessible"
    BLOCKED = "blocked"
    FAILED = "failed"
    CHANGED = "changed"
    UNKNOWN = "unknown"


class ExtractionMethod(StrEnum):
    NONE = "none"
    DIRECT_TEXT = "direct_text"
    HTML_TEXT = "html_text"
    PDF_TEXT = "pdf_text"
    OCR = "ocr"
    TRANSCRIPT = "transcript"


class RightsBasis(StrEnum):
    UNKNOWN = "unknown"
    SOURCE_LICENSE = "source_license"
    ISSUER_PERMISSION = "issuer_permission"
    COUNSEL_APPROVAL = "counsel_approval"
    HOST_TERMS = "host_terms"


class RightsDecision(StrEnum):
    UNREVIEWED = "unreviewed"
    ALLOWED = "allowed"
    NEEDS_REVIEW = "needs_review"
    DENIED = "denied"
    EXPIRED = "expired"
    TAKEDOWN = "takedown"


class RetentionClass(StrEnum):
    REFERENCE_ONLY = "reference_only"
    LICENSED_ARCHIVE = "licensed_archive"
    COUNSEL_APPROVED_QUOTE = "counsel_approved_quote"


class TermsReviewStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    VERIFIED_ALLOWED = "verified_allowed"
    VERIFIED_PROHIBITED = "verified_prohibited"
    NEEDS_REVIEW = "needs_review"


class VerificationState(StrEnum):
    UNVERIFIED = "unverified"
    REVIEWER_VERIFIED = "reviewer_verified"
    REJECTED = "rejected"


class FailureCode(StrEnum):
    SSRF_BLOCKED = "ssrf_blocked"
    CONTENT_TYPE_BLOCKED = "content_type_blocked"
    SIZE_LIMIT_EXCEEDED = "size_limit_exceeded"
    THROTTLED = "throttled"
    NETWORK_FAILURE = "network_failure"
    SOURCE_CHANGED = "source_changed"


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{field} is required")
    return value.strip()


def _require_aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceError(f"{field} must be timezone-aware")


def _require_https_url(value: str, field: str) -> None:
    _require_text(value, field)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise EvidenceError(f"{field} must be an HTTPS URL")
    if parsed.username or parsed.password:
        raise EvidenceError(f"{field} cannot contain credentials")


def validate_fetch_url(url: str, *, resolved_ips: Iterable[str] = ()) -> None:
    """Reject non-HTTPS and obvious/private-network SSRF targets.

    A production fetcher must resolve the hostname immediately before the
    request and pass the resolved addresses here to mitigate DNS rebinding.
    """

    try:
        _require_https_url(url, "url")
    except EvidenceError as exc:
        raise FetchBoundaryError(str(exc)) from exc
    hostname = urlsplit(url).hostname
    assert hostname is not None
    lowered = hostname.casefold().rstrip(".")
    blocked_names = {"localhost", "metadata.google.internal", "instance-data.ec2.internal"}
    if lowered in blocked_names or lowered.endswith((".localhost", ".local", ".internal")):
        raise FetchBoundaryError("fetch host is not public")
    addresses = list(resolved_ips)
    if _is_ip_literal(lowered):
        addresses.append(lowered)
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise FetchBoundaryError("resolved address is invalid") from exc
        if (
            parsed_address.is_private
            or parsed_address.is_loopback
            or parsed_address.is_link_local
            or parsed_address.is_multicast
            or parsed_address.is_reserved
            or parsed_address.is_unspecified
        ):
            raise FetchBoundaryError("fetch address is not public")


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def fingerprint_bytes(content: bytes) -> str:
    if not isinstance(content, bytes):
        raise EvidenceError("content must be bytes")
    return hashlib.sha256(content).hexdigest()


def sanitize_rendered_text(text: str) -> str:
    """Return text safe for HTML rendering without preserving control bytes."""

    _require_text(text, "text")
    cleaned = "".join(char for char in text if char in "\n\r\t" or ord(char) >= 0x20)
    return escape(cleaned, quote=True)


@dataclass(frozen=True, slots=True)
class RightsRecord:
    """Source-specific rights and retention decision; reference-only by default."""

    basis: RightsBasis = RightsBasis.UNKNOWN
    decision: RightsDecision = RightsDecision.UNREVIEWED
    retention_class: RetentionClass = RetentionClass.REFERENCE_ONLY
    public_quote_permission: bool = False
    raw_artifact_permission: bool = False
    usage_scope: tuple[str, ...] = ()
    permitted_fields: tuple[str, ...] = ()
    expires_at: datetime | None = None
    terms_url: str | None = None
    permission_reference: str | None = None
    reviewer: str | None = None
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        if self.decided_at is not None:
            _require_aware(self.decided_at, "decided_at")
        if self.terms_url is not None:
            _require_https_url(self.terms_url, "terms_url")
        if self.permission_reference is not None:
            _require_https_url(self.permission_reference, "permission_reference")
        if self.public_quote_permission and self.retention_class is RetentionClass.REFERENCE_ONLY:
            raise RightsError("reference_only cannot permit durable public quotes")
        if self.raw_artifact_permission and self.retention_class is not RetentionClass.LICENSED_ARCHIVE:
            raise RightsError("raw artifacts require licensed_archive retention")
        if self.public_quote_permission and self.decision is not RightsDecision.ALLOWED:
            raise RightsError("public quote permission requires an allowed rights decision")
        if (self.public_quote_permission or self.raw_artifact_permission) and self.basis is RightsBasis.UNKNOWN:
            raise RightsError("permitted use requires a recorded rights basis")
        if (self.public_quote_permission or self.raw_artifact_permission) and not self.usage_scope:
            raise RightsError("permitted use requires a usage scope")
        for field in (*self.usage_scope, *self.permitted_fields):
            _require_text(field, "rights field")

    def is_current(self, at: datetime) -> bool:
        _require_aware(at, "at")
        return self.decision is RightsDecision.ALLOWED and (
            self.expires_at is None or at < self.expires_at
        )

    def can_store_quote(self, at: datetime) -> bool:
        return self.is_current(at) and self.public_quote_permission

    def can_store_raw_artifact(self, at: datetime) -> bool:
        return self.is_current(at) and self.raw_artifact_permission

    def can_use_fields(self, fields: Iterable[str], at: datetime) -> bool:
        requested = { _require_text(field, "field") for field in fields }
        return self.is_current(at) and requested.issubset(self.permitted_fields)


@dataclass(frozen=True, slots=True)
class RightsChangeEvent:
    """Append-only rights change; the source and excerpt records remain intact."""

    event_id: str
    source_document_id: str
    rights: RightsRecord
    changed_at: datetime
    actor: str
    reason: str

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _require_text(self.source_document_id, "source_document_id")
        _require_aware(self.changed_at, "changed_at")
        _require_text(self.actor, "actor")
        _require_text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class TranscriptAuthorization:
    """Evidence needed before an issuer-authorized vendor transcript is primary."""

    authorization_url: str
    authorized_relationship: str
    captured_at: datetime
    reviewer: str
    terms_url: str
    terms_reviewed_at: datetime
    terms_status: TermsReviewStatus
    verification_source_url: str | None = None
    verification_locator: str | None = None
    verified_by: str | None = None
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_https_url(self.authorization_url, "authorization_url")
        _require_text(self.authorized_relationship, "authorized_relationship")
        _require_aware(self.captured_at, "captured_at")
        _require_text(self.reviewer, "reviewer")
        _require_https_url(self.terms_url, "terms_url")
        _require_aware(self.terms_reviewed_at, "terms_reviewed_at")
        if self.verification_source_url is not None:
            _require_https_url(self.verification_source_url, "verification_source_url")
        if self.verification_locator is not None:
            _require_text(self.verification_locator, "verification_locator")
        if self.verified_at is not None:
            _require_aware(self.verified_at, "verified_at")

    @property
    def complete_for_primary_evidence(self) -> bool:
        return (
            self.terms_status is TermsReviewStatus.VERIFIED_ALLOWED
            and self.verification_source_url is not None
            and self.verification_locator is not None
            and self.verified_by is not None
            and self.verified_at is not None
        )


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One immutable metadata/fingerprint version of a source."""

    document_id: str
    source_key: str
    version: int
    source_class: SourceClass
    publisher: str
    original_url: str
    canonical_url: str | None
    title: str
    published_at: datetime | None
    retrieved_at: datetime
    content_fingerprint: str
    accessibility: AccessibilityStatus
    extraction_method: ExtractionMethod
    content_type: str | None = None
    content_length: int | None = None
    rights: RightsRecord = RightsRecord()
    transcript_authorization: TranscriptAuthorization | None = None
    supersedes_document_id: str | None = None
    artifact_reference: str | None = None
    scope_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, field in (
            (self.document_id, "document_id"),
            (self.source_key, "source_key"),
            (self.publisher, "publisher"),
            (self.title, "title"),
        ):
            _require_text(value, field)
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise EvidenceError("version must be a positive integer")
        _require_https_url(self.original_url, "original_url")
        if self.canonical_url is not None:
            _require_https_url(self.canonical_url, "canonical_url")
        if self.published_at is not None:
            _require_aware(self.published_at, "published_at")
        _require_aware(self.retrieved_at, "retrieved_at")
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_fingerprint):
            raise EvidenceError("content_fingerprint must be a lowercase SHA-256 hex digest")
        if self.content_length is not None and (not isinstance(self.content_length, int) or self.content_length < 0):
            raise EvidenceError("content_length must be a non-negative integer")
        if self.artifact_reference is not None:
            _require_text(self.artifact_reference, "artifact_reference")
        if self.supersedes_document_id is not None:
            _require_text(self.supersedes_document_id, "supersedes_document_id")
        for field in self.scope_fields:
            _require_text(field, "scope field")
        if self.transcript_authorization is not None and self.source_class is not SourceClass.ISSUER_AUTHORIZED_VENDOR_TRANSCRIPT:
            raise EvidenceError("transcript authorization is only valid for vendor transcripts")

    @property
    def internal_evidence_eligible(self) -> bool:
        if not self.source_class.is_primary_eligible or self.accessibility is not AccessibilityStatus.ACCESSIBLE:
            return False
        if self.source_class is SourceClass.ISSUER_AUTHORIZED_VENDOR_TRANSCRIPT:
            return bool(self.transcript_authorization and self.transcript_authorization.complete_for_primary_evidence)
        return True

    def public_quote_eligible(self, at: datetime) -> bool:
        return self.internal_evidence_eligible and self.rights.can_store_quote(at)

    def public_scope_eligible(self, fields: Iterable[str], at: datetime) -> bool:
        return (
            self.source_class is SourceClass.MARKET_CAP_SNAPSHOT
            and self.rights.basis is RightsBasis.SOURCE_LICENSE
            and self.rights.can_use_fields(fields, at)
        )

    def assert_scope_fields_allowed(self, fields: Iterable[str], at: datetime) -> None:
        if not self.public_scope_eligible(fields, at):
            raise RightsError("scope fields require a current license with permitted fields")

    def next_version(
        self,
        *,
        document_id: str,
        retrieved_at: datetime,
        content_fingerprint: str,
        accessibility: AccessibilityStatus = AccessibilityStatus.ACCESSIBLE,
    ) -> "SourceDocument":
        """Create a new immutable version after a re-fetch; never mutate this record."""

        return replace(
            self,
            document_id=document_id,
            version=self.version + 1,
            retrieved_at=retrieved_at,
            content_fingerprint=content_fingerprint,
            accessibility=accessibility,
            supersedes_document_id=self.document_id,
        )


@dataclass(frozen=True, slots=True)
class EvidenceLocator:
    """Stable source position; at least one locator component is mandatory."""

    page: int | None = None
    section: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    timestamp_seconds: int | None = None
    anchor: str | None = None

    def __post_init__(self) -> None:
        if self.page is not None and (not isinstance(self.page, int) or self.page < 1):
            raise EvidenceError("page must be positive")
        if self.line_start is not None and (not isinstance(self.line_start, int) or self.line_start < 1):
            raise EvidenceError("line_start must be positive")
        if self.line_end is not None and (not isinstance(self.line_end, int) or self.line_end < 1):
            raise EvidenceError("line_end must be positive")
        if self.line_start is not None and self.line_end is not None and self.line_end < self.line_start:
            raise EvidenceError("line_end cannot precede line_start")
        if self.timestamp_seconds is not None and (not isinstance(self.timestamp_seconds, int) or self.timestamp_seconds < 0):
            raise EvidenceError("timestamp_seconds must be non-negative")
        if self.section is not None:
            _require_text(self.section, "section")
        if self.anchor is not None:
            _require_text(self.anchor, "anchor")
        if not any(value is not None for value in (self.page, self.section, self.line_start, self.timestamp_seconds, self.anchor)):
            raise EvidenceError("a stable locator is required")


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    """A reviewer-verifiable excerpt tied to exactly one source version."""

    excerpt_id: str
    source_document_id: str
    exact_quote: str
    locator: EvidenceLocator
    surrounding_context: str
    captured_at: datetime
    extraction_method: ExtractionMethod
    verification_state: VerificationState = VerificationState.UNVERIFIED
    reviewer: str | None = None
    verified_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text(self.excerpt_id, "excerpt_id")
        _require_text(self.source_document_id, "source_document_id")
        _require_text(self.exact_quote, "exact_quote")
        _require_text(self.surrounding_context, "surrounding_context")
        _require_aware(self.captured_at, "captured_at")
        if self.verification_state is VerificationState.REVIEWER_VERIFIED:
            if self.reviewer is None or self.verified_at is None:
                raise EvidenceError("verified excerpt requires reviewer and verified_at")
        if self.reviewer is not None:
            _require_text(self.reviewer, "reviewer")
        if self.verified_at is not None:
            _require_aware(self.verified_at, "verified_at")

    def verify(self, reviewer: str, verified_at: datetime) -> "EvidenceExcerpt":
        _require_text(reviewer, "reviewer")
        _require_aware(verified_at, "verified_at")
        return replace(
            self,
            verification_state=VerificationState.REVIEWER_VERIFIED,
            reviewer=reviewer,
            verified_at=verified_at,
        )


class SourceRepository:
    """In-memory append-only source versions for the first dependency-free slice."""

    def __init__(self) -> None:
        self._documents: dict[str, SourceDocument] = {}
        self._by_key: dict[str, list[str]] = {}

    def add(self, document: SourceDocument) -> SourceDocument:
        if document.document_id in self._documents:
            raise DuplicateSourceError(f"document already captured: {document.document_id}")
        versions = self._by_key.get(document.source_key, [])
        if not versions:
            if document.version != 1 or document.supersedes_document_id is not None:
                raise SourceVersionError("first source capture must be version 1 without a predecessor")
        else:
            previous = self._documents[versions[-1]]
            if document.content_fingerprint == previous.content_fingerprint:
                raise DuplicateSourceError("source fingerprint already captured")
            if document.version != previous.version + 1 or document.supersedes_document_id != previous.document_id:
                raise SourceVersionError("changed source must be the next version and name its predecessor")
        self._documents[document.document_id] = document
        self._by_key.setdefault(document.source_key, []).append(document.document_id)
        return document

    def get(self, document_id: str) -> SourceDocument:
        try:
            return self._documents[document_id]
        except KeyError as exc:
            raise EvidenceError(f"unknown source document: {document_id}") from exc

    def latest(self, source_key: str) -> SourceDocument:
        try:
            return self._documents[self._by_key[source_key][-1]]
        except (KeyError, IndexError) as exc:
            raise EvidenceError(f"unknown source key: {source_key}") from exc


class EvidenceRepository:
    """Capture and verify excerpts without bypassing primary-source or rights gates."""

    def __init__(self, sources: SourceRepository | None = None) -> None:
        self.sources = sources or SourceRepository()
        self._excerpts: dict[str, EvidenceExcerpt] = {}
        self._rights_events: dict[str, list[RightsChangeEvent]] = {}

    def capture_source(self, document: SourceDocument) -> SourceDocument:
        return self.sources.add(document)

    def capture_excerpt(self, excerpt: EvidenceExcerpt, *, at: datetime | None = None) -> EvidenceExcerpt:
        if excerpt.excerpt_id in self._excerpts:
            raise DuplicateSourceError(f"excerpt already captured: {excerpt.excerpt_id}")
        source = self.sources.get(excerpt.source_document_id)
        decision_time = at or excerpt.captured_at
        if not source.internal_evidence_eligible:
            raise SourceEligibilityError("source is not verified primary evidence")
        if not self.current_rights(source.document_id).can_store_quote(decision_time):
            raise RightsError("durable excerpt requires current public-quote permission")
        self._excerpts[excerpt.excerpt_id] = excerpt
        return excerpt

    def verify_excerpt(self, excerpt_id: str, reviewer: str, verified_at: datetime) -> EvidenceExcerpt:
        try:
            excerpt = self._excerpts[excerpt_id]
        except KeyError as exc:
            raise EvidenceError(f"unknown excerpt: {excerpt_id}") from exc
        source = self.sources.get(excerpt.source_document_id)
        if not source.internal_evidence_eligible or not self.current_rights(source.document_id).can_store_quote(verified_at):
            raise RightsError("excerpt no longer has an eligible source or current quote right")
        verified = excerpt.verify(reviewer, verified_at)
        self._excerpts[excerpt_id] = verified
        return verified

    def assert_public_projection_eligible(self, excerpt_id: str, at: datetime) -> EvidenceExcerpt:
        try:
            excerpt = self._excerpts[excerpt_id]
        except KeyError as exc:
            raise EvidenceError(f"unknown excerpt: {excerpt_id}") from exc
        source = self.sources.get(excerpt.source_document_id)
        if excerpt.verification_state is not VerificationState.REVIEWER_VERIFIED:
            raise SourceEligibilityError("excerpt must be reviewer-verified")
        if not source.internal_evidence_eligible or not self.current_rights(source.document_id).can_store_quote(at):
            raise RightsError("source does not have a current public-quote right")
        return excerpt

    def current_rights(self, source_document_id: str) -> RightsRecord:
        source = self.sources.get(source_document_id)
        events = self._rights_events.get(source_document_id)
        return events[-1].rights if events else source.rights

    def record_rights_change(self, event: RightsChangeEvent) -> RightsChangeEvent:
        self.sources.get(event.source_document_id)
        history = self._rights_events.get(event.source_document_id, [])
        if any(existing.event_id == event.event_id for existing in history):
            raise DuplicateSourceError(f"rights event already recorded: {event.event_id}")
        if history and event.changed_at <= history[-1].changed_at:
            raise EvidenceError("rights changes must be appended in chronological order")
        history.append(event)
        self._rights_events[event.source_document_id] = history
        return event

    def rights_history(self, source_document_id: str) -> tuple[RightsChangeEvent, ...]:
        self.sources.get(source_document_id)
        return tuple(self._rights_events.get(source_document_id, ()))


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    max_bytes: int = 10 * 1024 * 1024
    allowed_content_types: frozenset[str] = frozenset(
        {"text/html", "text/plain", "application/pdf", "application/json"}
    )
    minimum_domain_interval: timedelta = timedelta(seconds=1)

    def __post_init__(self) -> None:
        if self.max_bytes < 1:
            raise FetchBoundaryError("max_bytes must be positive")
        if self.minimum_domain_interval < timedelta(0):
            raise FetchBoundaryError("minimum_domain_interval cannot be negative")


class FetchBoundary:
    """Request/response checks and metadata-only failure observability."""

    def __init__(self, policy: FetchPolicy | None = None) -> None:
        self.policy = policy or FetchPolicy()
        self._last_request: dict[str, datetime] = {}
        self.failure_log: list[tuple[str, FailureCode, datetime]] = []

    def check_request(self, url: str, at: datetime, *, resolved_ips: Iterable[str] = ()) -> None:
        _require_aware(at, "at")
        try:
            validate_fetch_url(url, resolved_ips=resolved_ips)
        except FetchBoundaryError:
            self.record_failure(url, FailureCode.SSRF_BLOCKED, at)
            raise
        host = urlsplit(url).hostname
        assert host is not None
        previous = self._last_request.get(host.casefold())
        if previous is not None and at - previous < self.policy.minimum_domain_interval:
            self.record_failure(url, FailureCode.THROTTLED, at)
            raise FetchBoundaryError("domain request rate limit exceeded")

    def record_request(self, url: str, at: datetime) -> None:
        _require_aware(at, "at")
        host = urlsplit(url).hostname
        if host is None:
            raise FetchBoundaryError("url hostname is required")
        self._last_request[host.casefold()] = at

    def validate_response(self, content_type: str, content_length: int, at: datetime, url: str) -> None:
        _require_aware(at, "at")
        normalized = _require_text(content_type, "content_type").split(";", 1)[0].casefold()
        if normalized not in self.policy.allowed_content_types:
            self.record_failure(url, FailureCode.CONTENT_TYPE_BLOCKED, at)
            raise FetchBoundaryError("content type is not allowed")
        if content_length < 0 or content_length > self.policy.max_bytes:
            self.record_failure(url, FailureCode.SIZE_LIMIT_EXCEEDED, at)
            raise FetchBoundaryError("content length exceeds policy")

    def record_failure(self, url: str, code: FailureCode, at: datetime) -> None:
        _require_text(url, "url")
        _require_aware(at, "at")
        self.failure_log.append((url, code, at))


@dataclass(frozen=True, slots=True)
class _TransientArtifact:
    content: bytes
    expires_at: datetime


class TransientArtifactStore:
    """Process-local fetch/extraction buffer with mandatory bounded cleanup."""

    def __init__(self, ttl: timedelta = timedelta(hours=24)) -> None:
        if ttl <= timedelta(0) or ttl > timedelta(hours=24):
            raise EvidenceError("transient artifact ttl must be greater than zero and at most 24 hours")
        self.ttl = ttl
        self._artifacts: dict[str, _TransientArtifact] = {}

    def put(self, artifact_id: str, content: bytes, created_at: datetime) -> None:
        _require_text(artifact_id, "artifact_id")
        if not isinstance(content, bytes):
            raise EvidenceError("transient content must be bytes")
        _require_aware(created_at, "created_at")
        self.cleanup(created_at)
        self._artifacts[artifact_id] = _TransientArtifact(content, created_at + self.ttl)

    def get(self, artifact_id: str, at: datetime) -> bytes:
        _require_aware(at, "at")
        self.cleanup(at)
        try:
            return self._artifacts[artifact_id].content
        except KeyError as exc:
            raise EvidenceError(f"unknown or expired transient artifact: {artifact_id}") from exc

    def cleanup(self, at: datetime) -> tuple[str, ...]:
        _require_aware(at, "at")
        expired = tuple(
            artifact_id
            for artifact_id, artifact in self._artifacts.items()
            if artifact.expires_at <= at
        )
        for artifact_id in expired:
            del self._artifacts[artifact_id]
        return expired

    def contains(self, artifact_id: str, at: datetime) -> bool:
        try:
            self.get(artifact_id, at)
        except EvidenceError:
            return False
        return True
