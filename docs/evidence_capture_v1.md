# Evidence capture and rights gates

This repository implements the FOO-8/FOO-14 foundation in
`tariff_dashboard.evidence`. It is metadata-first and does not fetch, proxy, or
archive Target material. Target may be used as a future research queue seed,
but this slice contains no Target claim or source content.

## Source versions

`SourceDocument` is immutable metadata for one retrieval: source class,
publisher, URLs, dates, accessibility state, extraction method, content type and
length, and a lowercase SHA-256 fingerprint. A changed retrieval is stored as
the next version with a new document ID and `supersedes_document_id`; a prior
record is never overwritten. Failed, blocked, and changed states remain
observable in the record and fetch failure log.

Secondary reporting, search snippets, copied or unauthorized transcripts, and
other lead-only classes can be retained as metadata, but cannot produce an
`EvidenceExcerpt`.

## Excerpts and publication

An excerpt must have an exact quote, surrounding context, and a stable locator
(page, section, line, timestamp, or anchor). It must refer to an accessible,
eligible primary source. Reviewer verification is a separate immutable
replacement value and requires a reviewer and timestamp.

The default rights state is `reference_only`: URL, metadata, locator,
fingerprint, and audit information are allowed; durable source bytes, full text,
media, screenshots, and verbatim excerpts are not. Durable excerpts require a
current `counsel_approved_quote` or other explicitly permitted quote decision.
The public projection checks both reviewer verification and the current rights
decision, so expiry or takedown blocks publication immediately.
Rights changes are recorded as chronological append-only events; the original
source and excerpt records remain available for audit while the current event
controls the public gate.

Issuer-authorized vendor transcripts remain leads until the record contains an
issuer authorization URL, reviewed host terms, and independent verification
against an issuer source with a locator. Authorization to host a transcript is
not itself a quote license.

## Fetch boundary

`FetchBoundary` is the dependency-free contract for a future isolated worker.
It requires HTTPS, rejects credentials and private/metadata-network targets,
accepts only configured content types and sizes, throttles by domain, and logs
only a URL, timestamp, and controlled failure code. Rendered text must pass
`sanitize_rendered_text`; source content must not enter logs, fixtures, prompts,
analytics, error reports, or backups. A production worker must delete transient
buffers within 24 hours. `TransientArtifactStore` provides the tested
process-local buffer and cleanup boundary for this slice; it is not a durable
archive.

Market-cap or other scope inputs have a separate gate: rank/name/membership
fields require a current source license with those fields explicitly permitted.
The default reference-only record cannot persist or publish those fields.
