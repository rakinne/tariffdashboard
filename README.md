## Tariff Dashboard

The repository currently contains the FOO-7 domain foundation for an auditable,
dated top-100 U.S.-listed operating-company cohort. It intentionally has no
market-data provider integration or production fixture data.

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
