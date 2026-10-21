# Evidence Atlas preview

This is a buildless, local-only UI slice for the Tariff Dashboard. It intentionally uses one synthetic Target evidence card to exercise the visual review state without changing the backend projection contract.

Run it from the repository root:

```sh
python3 -m http.server 4173 --directory preview
```

Then open <http://localhost:4173>.

The Q2 2026 filing period, `$994m` recognized refund, accounting treatment, source locator, fingerprint, rights state, and review gaps are presented as captured metadata pending review. They are not approved public data, a cohort ranking, or a cohort total.
