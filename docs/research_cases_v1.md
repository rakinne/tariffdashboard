# Research cases and review gates v1

`tariff_dashboard.research` is the dependency-free internal workflow contract
for FOO-9. It does not fetch sources or expose a public API.

## Cases

`ResearchRepository.create_case` accepts only an eligible, resolved, approved
`MarketCapMembership`. The repository enforces one case per membership. Each
case records its scope and policy versions, owner, search log, status rationale,
no-result rationale, and freshness/recheck date.

The lifecycle is explicit:

`not_started` → `in_progress` → `candidate_found` → `needs_review` →
`complete`

`no_qualifying_disclosure_found` is a separate completed outcome and must carry
the documented wording that the result is limited to the search scope and does
not mean no benefit exists. `stale` requires a rationale and can be re-opened
for a new pass.

## Claims and decisions

`DisclosureClaim` is one atomic effect with exactly one v1 `EffectCategory` and
one `AssertionStrength`. Amount, period, tariff-program, jurisdiction, and
ambiguity fields remain source-language metadata; the model does not calculate
or infer them.

`ReviewDecision` records are append-only. A submitter cannot approve their own
claim. Rejections, returns for clarification, supersessions, and later
corrections remain in the decision history.

Approval runs all publication gates:

1. reviewed membership and matching case/company identifiers;
2. current policy version;
3. a reviewer-verified excerpt tied to an eligible primary source;
4. current public-quote rights and complete source/excerpt provenance; and
5. a public-eligible category/assertion with no blocking ambiguity.

Amount and period ambiguity are retained for research display but remain
ineligible for aggregation. Entity, mechanism, tariff-connection,
contradictory-source, and unresolved-rights flags block approval.

Tests use a Target-named synthetic membership only to exercise the queue and
no-result workflow. No Target source, quote, or tariff fact is fetched or
invented.
