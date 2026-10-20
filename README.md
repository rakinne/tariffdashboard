## Tariff Dashboard

The repository contains the FOO-7 domain foundation for an auditable, dated
top-100 U.S.-listed operating-company cohort and the dependency-free FOO-8/
FOO-14 evidence boundary. It intentionally has no market-data provider
integration, network fetcher, or production fixture data.

`tariff_dashboard.cohort` provides:

- immutable `MarketCapSnapshot`, `Company`, and `MarketCapMembership` records;
- complete snapshot provenance, terms, source/method versions, and listing scope;
- alias/ticker/source-identifier resolution that preserves ambiguous mappings for review;
- exclusion handling for funds, ETFs, ETNs, closed-end funds, pre-combination SPACs,
  duplicate share classes, and non-operating/non-U.S.-listed candidates;
- an authenticated internal intake boundary with duplicate protections; and
- a validated transition to `research_ready` only after exactly 100 eligible,
  resolved, approved members are present.

Snapshots and their membership tuples are immutable. A changed market-data
universe must be imported under a new snapshot ID and version.

`tariff_dashboard.evidence` provides immutable source metadata/fingerprint
versions, locatable evidence excerpts, primary-source and transcript
authorization gates, reference-only default retention, rights/takedown history,
transient-artifact cleanup, and a safe fetch boundary. See
[`docs/evidence_capture_v1.md`](docs/evidence_capture_v1.md) for the contract.
