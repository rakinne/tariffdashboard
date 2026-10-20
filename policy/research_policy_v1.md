# Tariff Research Policy v1

**Policy ID:** `tariff-research-policy`
**Policy version:** `1.0.0`
**Status:** implementation baseline
**Effective date:** 2026-10-19
**Owner:** Research & Governance
**Implementation ticket:** FOO-10

This policy is the human-readable companion to [`taxonomy_v1.json`](taxonomy_v1.json) and [`synthetic_decision_examples_v1.json`](synthetic_decision_examples_v1.json). The JSON files are the version-referenceable contract for application code and tests; this document explains how reviewers apply it.

## 1. Product question and scope boundary

The product answers a narrow question: which companies in the dated top-100 U.S.-listed operating-company market-cap cohort made an explicit, tariff-related financial-benefit disclosure, what did the company say, and where can a reader verify it?

The market-cap snapshot selects the research queue. It is not evidence of a tariff benefit and cannot establish a benefit amount, motive, materiality, or causality. A changed cohort is a new snapshot version; it does not rewrite prior research.

This policy governs research classification and publication eligibility. It does not create a market-data provider contract, source-ingestion implementation, or public API schema.

## 2. Source eligibility and source/claim boundary

### Eligible primary evidence

The preferred evidence order is:

1. SEC filings and exhibits.
2. Issuer-hosted earnings releases, investor presentations, and investor-relations materials.
3. An issuer-authorized vendor-hosted webcast or transcript, only when the authorization chain, host terms, identity, and human verification requirements are satisfied.
4. Government records that directly identify the company and the disclosed effect.
5. Other official issuer material accepted by a reviewer.

An eligible source must be tied to the reviewed company and contain, or directly resolve through documented surrounding context, both parts of the claim: the tariff connection and the stated economic effect. A source may establish only what its text and locator support. It does not authorize an amount, causal explanation, period, entity, or mechanism that the source does not state.

Secondary reporting, analyst research, search snippets, blogs, copied or unauthorized transcripts, machine-only transcripts, and AI summaries are leads only. They may help find a primary source but cannot satisfy the public-claim evidence gate.

The default rights posture is `reference_only`: preserve URL, metadata, locator, retrieval time, fingerprint, terms/authorization links, and audit history; do not assume a right to retain or publish source bytes, full text, screenshots, transcript bodies, or verbatim excerpts. Public quotation requires a source-specific licensed or counsel-approved rights state. Rights status is a publication gate, not a substitute for evidence.

## 3. Explicit-claim threshold

A claim is explicit only when a primary source directly states:

1. a tariff, duty, customs, or tariff-program connection; and
2. a positive financial effect or a clearly named benefit mechanism.

The researcher may transcribe the source’s wording and structure it into one atomic claim. The researcher must not infer a benefit from an exclusion, avoided cost, price recovery, improved margin, policy eligibility, or general tariff discussion. The researcher must not calculate an amount, normalize an ambiguous period or currency, or assert causality, motive, materiality, or consumer impact that the source does not state.

`refund` has the strictest boundary: it requires an explicit repayment or return of duties or tariffs already paid. An application, expectation, avoided charge, drawback, exclusion, reimbursement, supplier credit, or price recovery is not a refund.

## 4. Effect category contract

Every candidate receives exactly one `effect_category` from the controlled values in `taxonomy_v1.json`:

| Value | Use when | Do not use when |
| --- | --- | --- |
| `refund` | The source explicitly says duties or tariffs already paid were repaid or returned. | The source describes an exclusion, waiver, drawback, reimbursement, offset, price recovery, avoided cost, application, or expectation. |
| `duty_drawback` | The source explicitly names a statutory or customs duty-drawback benefit. | The source merely says “refund” without a drawback mechanism, or describes a different reimbursement. |
| `exclusion_or_waiver` | An exclusion, exemption, waiver, or similar relief avoids a charge. | A repayment of duties already paid is stated. |
| `reimbursement_or_offset` | A government, customer, supplier, or other third party reimburses, credits, or offsets the tariff effect. | The source only says the company passed costs through or recovered costs in prices. |
| `other_explicit_benefit` | Another positive tariff-related economic effect is explicitly stated and its mechanism is retained verbatim. | The mechanism is inferred, unclear, or better represented by a named category. |
| `tariff_effect_not_benefit` | The source describes tariff cost, risk, exposure, neutral monitoring, or another non-benefit effect. | A positive benefit is explicitly stated. This category is never counted as a benefit. |
| `unclassified` | The candidate is awaiting review or the source/claim boundary is unresolved. | A reviewer has enough evidence to choose a category. It is never public. |

Categories are mutually exclusive per atomic claim. One disclosure may yield multiple claims only when each claim has its own source-supported mechanism and locator.

## 5. Assertion strength and ambiguity

Use one controlled `assertion_strength`:

- `explicit`: the source directly states the tariff connection and positive economic effect.
- `explicit_amount_link_ambiguous`: an amount is explicit, but its tariff linkage or benefit mechanism is not fully clear. Preserve the quoted amount, exclude it from all totals, and return it for clarification; do not publish it as a resolved benefit.
- `qualitative_explicit`: the benefit and tariff connection are explicit, but no amount is stated.
- `not_sufficient`: the evidence is retained as a rejected or unresolved candidate and does not meet the explicit-claim threshold.

Use zero or more `ambiguity_flags` from the controlled values. An ambiguity flag is a required explanation, not a license to guess. Entity, mechanism, tariff-connection, contradictory-source, or rights ambiguity blocks publication. Amount or period ambiguity requires source wording and excludes the claim from aggregation. A contradiction keeps both evidence paths and removes the claim from the public projection until resolved.

## 6. Research-case and review lifecycle

The case status describes research progress, not truth:

`not_started` → `in_progress` → `candidate_found` → `needs_review` → `complete`, with `no_qualifying_disclosure_found` as an explicit completed outcome and `stale` for a case requiring recheck.

`no_qualifying_disclosure_found` means that the documented search scope, sources, and date range found no qualifying disclosure. It must be displayed or reported with exactly that wording, or a clearly equivalent wording. It does not mean “the company received no benefit” or “no benefit exists.”

Review decisions are append-only controlled values: `approved`, `rejected`, `needs_clarification`, or `superseded`. The researcher cannot automatically approve their own public claim. A later correction creates a new decision and retains the prior history.

## 7. Minimum public-claim evidence package

A public claim requires all of the following:

1. A reviewed membership in the selected market-cap snapshot.
2. One approved primary `SourceDocument` and one approved `EvidenceExcerpt`.
3. A verbatim excerpt, stable page/section/line/timestamp locator, and enough surrounding context to identify the entity, period, tariff connection, and effect.
4. Source title, publisher/host, original and canonical URL when available, publication date, retrieval date, source fingerprint, and rights decision.
5. Exactly one effect category, assertion strength, and ambiguity flags where applicable.
6. An approved review decision under this policy version.
7. A source-language summary that does not add an amount, cause, motive, materiality, or conclusion absent from the source.

Claims with `unclassified`, `not_sufficient`, unresolved rights, unresolved contradiction, or missing primary evidence remain internal research records. No code path may publish them automatically.

The launch does not publish a single cross-claim “total benefit” number. If a later policy permits aggregation, it must enumerate claim IDs and restrict the calculation to compatible categories, entities, periods, currencies, and explicit monetary amounts.

## 8. Synthetic decision examples

[`synthetic_decision_examples_v1.json`](synthetic_decision_examples_v1.json) contains 14 labeled, non-production examples. Every example is marked `synthetic: true`; its invented excerpt is not a factual claim about a real company. Each example names what the source can establish, what it cannot establish, the expected category/strength/status/decision, and the publication disposition. The examples include positive cases, strict refund near-misses, ambiguous amounts, rights-gated evidence, secondary leads, market-cap inputs, and contradictory sources.

## 9. Open policy questions

These questions remain explicit and are not silently decided by this artifact:

- Which market-data provider and terms record will support the production cohort snapshot?
- Which issuer-authorized transcript hosts and verification sources will be allowlisted, and what evidence of authorization is sufficient for each host?
- Which source-specific licenses or counsel decisions will permit durable quotes or archived source artifacts?
- What correction and takedown service-level targets will apply after public display?
- If aggregation is proposed after launch, who approves comparability rules for period, currency, entity, gross/net basis, and amount precision?
- What exact public wording should accompany rights-limited source references when the evidence is sufficient internally but a quote cannot be displayed?

## 10. Change control

A change to a controlled value, category boundary, source eligibility rule, publication gate, or aggregation rule requires:

1. a dated decision recorded in the architecture or governance source of truth;
2. a policy version increment using semantic versioning;
3. a migration or backfill plan for affected claims and examples;
4. a review of public wording and existing displayed claims; and
5. updated machine-readable values, synthetic examples, and focused tests.

This v1 artifact is linked to the accepted [Architecture Baseline](https://linear.app/foote-technologies-llc/document/architecture-baseline-evidence-first-tariff-refund-research-a00478b55a09), the [top-100 market-cap scope amendment](https://linear.app/foote-technologies-llc/document/scope-amendment-v11-top-100-public-company-market-cap-cohort-be320c8e9290), and the [source-rights governance decision](https://linear.app/foote-technologies-llc/document/governance-decision-v1-fortune-transcript-and-source-retention-rights-86274bc02ef7).
