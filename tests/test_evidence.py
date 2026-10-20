from datetime import datetime, timedelta, timezone

import pytest

from tariff_dashboard.evidence import (
    AccessibilityStatus,
    EvidenceError,
    EvidenceExcerpt,
    EvidenceLocator,
    EvidenceRepository,
    ExtractionMethod,
    FailureCode,
    FetchBoundary,
    FetchBoundaryError,
    FetchPolicy,
    RightsBasis,
    RightsChangeEvent,
    RightsDecision,
    RightsError,
    RightsRecord,
    RetentionClass,
    SourceClass,
    SourceDocument,
    SourceEligibilityError,
    SourceRepository,
    TermsReviewStatus,
    TranscriptAuthorization,
    TransientArtifactStore,
    VerificationState,
    fingerprint_bytes,
    sanitize_rendered_text,
    validate_fetch_url,
)


NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def reference_rights() -> RightsRecord:
    return RightsRecord()


def quote_rights(*, expires_at: datetime | None = None) -> RightsRecord:
    return RightsRecord(
        basis=RightsBasis.COUNSEL_APPROVAL,
        decision=RightsDecision.ALLOWED,
        retention_class=RetentionClass.COUNSEL_APPROVED_QUOTE,
        public_quote_permission=True,
        usage_scope=("public quoted evidence excerpt",),
        expires_at=expires_at,
        permission_reference="https://rights.example.test/decision/quote-1",
        reviewer="governance-reviewer",
        decided_at=NOW,
    )


def make_source(
    *,
    source_class: SourceClass = SourceClass.ISSUER_HOSTED_IR_MATERIAL,
    rights: RightsRecord | None = None,
    source_id: str = "doc-v1",
    source_key: str = "issuer:synthetic-release",
    version: int = 1,
    fingerprint: str | None = None,
    accessibility: AccessibilityStatus = AccessibilityStatus.ACCESSIBLE,
    transcript_authorization: TranscriptAuthorization | None = None,
) -> SourceDocument:
    return SourceDocument(
        document_id=source_id,
        source_key=source_key,
        version=version,
        source_class=source_class,
        publisher="Synthetic Issuer",
        original_url="https://issuer.example.test/releases/1",
        canonical_url="https://issuer.example.test/releases/1",
        title="Synthetic issuer release",
        published_at=NOW - timedelta(days=1),
        retrieved_at=NOW,
        content_fingerprint=fingerprint or fingerprint_bytes(b"synthetic source v1"),
        accessibility=accessibility,
        extraction_method=ExtractionMethod.HTML_TEXT,
        content_type="text/html",
        content_length=128,
        rights=rights or reference_rights(),
        transcript_authorization=transcript_authorization,
    )


def make_excerpt(source_id: str = "doc-v1") -> EvidenceExcerpt:
    return EvidenceExcerpt(
        excerpt_id="excerpt-1",
        source_document_id=source_id,
        exact_quote="Synthetic quote retained only for a permitted fixture.",
        locator=EvidenceLocator(page=2, section="Outlook", line_start=10, line_end=12),
        surrounding_context="Synthetic surrounding context.",
        captured_at=NOW,
        extraction_method=ExtractionMethod.HTML_TEXT,
    )


def test_reference_only_source_preserves_metadata_but_blocks_durable_excerpt() -> None:
    repository = EvidenceRepository()
    repository.capture_source(make_source())

    with pytest.raises(RightsError, match="public-quote permission"):
        repository.capture_excerpt(make_excerpt())


def test_successful_capture_requires_primary_source_rights_and_review() -> None:
    repository = EvidenceRepository()
    repository.capture_source(make_source(rights=quote_rights()))
    captured = repository.capture_excerpt(make_excerpt())

    assert captured.verification_state is VerificationState.UNVERIFIED
    with pytest.raises(SourceEligibilityError, match="reviewer-verified"):
        repository.assert_public_projection_eligible(captured.excerpt_id, NOW)

    verified = repository.verify_excerpt(captured.excerpt_id, "independent-reviewer", NOW)
    assert verified.verification_state is VerificationState.REVIEWER_VERIFIED
    assert repository.assert_public_projection_eligible(captured.excerpt_id, NOW) == verified


def test_secondary_source_can_be_captured_as_metadata_but_not_evidence() -> None:
    repository = EvidenceRepository()
    repository.capture_source(make_source(source_class=SourceClass.SEARCH_SNIPPET, rights=quote_rights()))

    with pytest.raises(SourceEligibilityError, match="primary evidence"):
        repository.capture_excerpt(make_excerpt())


def test_missing_locator_is_rejected() -> None:
    with pytest.raises(EvidenceError, match="stable locator"):
        EvidenceLocator()


def test_changed_refetch_is_a_new_immutable_source_version() -> None:
    sources = SourceRepository()
    first = sources.add(make_source())
    changed = first.next_version(
        document_id="doc-v2",
        retrieved_at=NOW + timedelta(hours=1),
        content_fingerprint=fingerprint_bytes(b"synthetic source v2"),
        accessibility=AccessibilityStatus.CHANGED,
    )
    sources.add(changed)

    assert sources.latest(first.source_key).document_id == "doc-v2"
    assert sources.get("doc-v1").content_fingerprint != sources.get("doc-v2").content_fingerprint
    assert sources.get("doc-v1").version == 1
    assert sources.get("doc-v2").version == 2
    assert sources.get("doc-v2").supersedes_document_id == "doc-v1"
    assert sources.get("doc-v2").accessibility is AccessibilityStatus.CHANGED


def test_vendor_transcript_needs_authorization_terms_and_independent_verification() -> None:
    incomplete = make_source(source_class=SourceClass.ISSUER_AUTHORIZED_VENDOR_TRANSCRIPT)
    assert incomplete.internal_evidence_eligible is False

    authorization = TranscriptAuthorization(
        authorization_url="https://issuer.example.test/ir/event-1",
        authorized_relationship="issuer IR page links to exact vendor transcript",
        captured_at=NOW,
        reviewer="governance-reviewer",
        terms_url="https://vendor.example.test/terms",
        terms_reviewed_at=NOW,
        terms_status=TermsReviewStatus.VERIFIED_ALLOWED,
        verification_source_url="https://issuer.example.test/ir/event-1-webcast",
        verification_locator="00:12:40",
        verified_by="independent-reviewer",
        verified_at=NOW,
    )
    complete = make_source(
        source_class=SourceClass.ISSUER_AUTHORIZED_VENDOR_TRANSCRIPT,
        rights=quote_rights(),
        transcript_authorization=authorization,
    )
    assert complete.internal_evidence_eligible is True


def test_expired_quote_right_blocks_public_projection() -> None:
    repository = EvidenceRepository()
    repository.capture_source(make_source(rights=quote_rights(expires_at=NOW - timedelta(seconds=1))))
    with pytest.raises(RightsError, match="durable excerpt"):
        repository.capture_excerpt(make_excerpt(), at=NOW)


def test_rights_takedown_is_append_only_and_immediately_blocks_projection() -> None:
    repository = EvidenceRepository()
    source = make_source(rights=quote_rights())
    repository.capture_source(source)
    repository.capture_excerpt(make_excerpt())
    repository.verify_excerpt("excerpt-1", "independent-reviewer", NOW)

    takedown = RightsChangeEvent(
        event_id="rights-event-1",
        source_document_id=source.document_id,
        rights=RightsRecord(
            decision=RightsDecision.TAKEDOWN,
            retention_class=RetentionClass.REFERENCE_ONLY,
        ),
        changed_at=NOW + timedelta(minutes=1),
        actor="governance-reviewer",
        reason="rights holder requested removal",
    )
    repository.record_rights_change(takedown)

    with pytest.raises(RightsError, match="current public-quote right"):
        repository.assert_public_projection_eligible("excerpt-1", NOW + timedelta(minutes=2))
    assert source.rights.public_quote_permission is True
    assert repository.rights_history(source.document_id) == (takedown,)


def test_market_cap_scope_fields_require_a_verified_license() -> None:
    source = make_source(source_class=SourceClass.MARKET_CAP_SNAPSHOT)
    with pytest.raises(RightsError, match="current license"):
        source.assert_scope_fields_allowed(("rank", "published_name"), NOW)

    licensed = RightsRecord(
        basis=RightsBasis.SOURCE_LICENSE,
        decision=RightsDecision.ALLOWED,
        retention_class=RetentionClass.LICENSED_ARCHIVE,
        usage_scope=("internal licensed cohort research",),
        permitted_fields=("rank", "published_name"),
        permission_reference="https://rights.example.test/license/cohort",
        reviewer="governance-reviewer",
        decided_at=NOW,
    )
    licensed_source = make_source(source_class=SourceClass.MARKET_CAP_SNAPSHOT, rights=licensed)
    licensed_source.assert_scope_fields_allowed(("rank", "published_name"), NOW)


def test_fetch_boundary_blocks_ssrf_limits_content_and_records_safe_failures() -> None:
    with pytest.raises(FetchBoundaryError):
        validate_fetch_url("https://127.0.0.1/private")
    with pytest.raises(FetchBoundaryError):
        validate_fetch_url("https://public.example.test", resolved_ips=("169.254.169.254",))

    boundary = FetchBoundary(FetchPolicy(max_bytes=100, minimum_domain_interval=timedelta(seconds=5)))
    url = "https://issuer.example.test/release"
    boundary.check_request(url, NOW)
    boundary.record_request(url, NOW)
    with pytest.raises(FetchBoundaryError, match="rate limit"):
        boundary.check_request(url, NOW + timedelta(seconds=1))
    with pytest.raises(FetchBoundaryError, match="content type"):
        boundary.validate_response("application/octet-stream", 10, NOW, url)
    with pytest.raises(FetchBoundaryError, match="content length"):
        boundary.validate_response("text/html", 101, NOW, url)

    assert boundary.failure_log
    assert all(event[1] in {FailureCode.THROTTLED, FailureCode.CONTENT_TYPE_BLOCKED, FailureCode.SIZE_LIMIT_EXCEEDED} for event in boundary.failure_log)
    assert all("Synthetic secret body" not in repr(event) for event in boundary.failure_log)


def test_rendered_text_is_escaped_and_control_bytes_are_removed() -> None:
    assert sanitize_rendered_text("<script>alert('x')</script>\x00") == "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"


def test_transient_artifacts_are_cleaned_within_24_hours() -> None:
    store = TransientArtifactStore()
    store.put("buffer-1", b"source bytes are transient", NOW)
    assert store.contains("buffer-1", NOW + timedelta(hours=23, minutes=59))
    assert store.cleanup(NOW + timedelta(hours=24)) == ("buffer-1",)
    assert store.contains("buffer-1", NOW + timedelta(hours=24)) is False

    with pytest.raises(EvidenceError, match="at most 24 hours"):
        TransientArtifactStore(timedelta(hours=24, seconds=1))
