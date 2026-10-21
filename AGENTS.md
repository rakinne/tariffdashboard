# Tariff Dashboard Agent Map

This file is the repository-level map. Keep it short and orient agents to the right source of truth; do not duplicate detailed role instructions here.

## Project

The Tariff Dashboard is an evidence-first research product for public tariff disclosures and tariff-related benefits. The current v1 scope is a dated, versioned cohort of the top 100 U.S.-listed public companies by market capitalization.

The repository is at an early foundation stage. Prefer small, tested vertical slices and clearly labeled synthetic fixtures until validated production data sources exist.

## Agent routing

- Planning, sequencing, scope, and delivery coordination: `config/agents/project_manager/AGENT.md`
- Architecture and implementation: `config/agents/senior_staff_engineer/AGENT.md`
- Evidence, taxonomy, source rights, retention, and review policy: `config/agents/research_governance/AGENT.md`

Implementation work should follow the Senior Staff Engineer role and consult Research & Governance before introducing domain claims or evidence fields. Project coordination should follow the Project Manager role.

## Agent directory map

- `config/agents/project_manager/`: sequencing, acceptance criteria, coordination, and delivery status.
- `config/agents/senior_staff_engineer/`: architecture, implementation, validation, and technical handoffs.
- `config/agents/tenx_engineer/`: high-leverage implementation support when the Senior Staff Engineer task is unavailable.
- `config/agents/research_governance/`: evidence policy, taxonomy, rights, retention, and review boundaries.
- `config/agents/financial_specialist/`: financial interpretation, market-data methodology, and claim/comparability review.

## Product sources of truth

- Linear project: Tariff Refund Dashboard
- Initial implementation sequence: FOO-7, FOO-10, then FOO-8/FOO-9
- FOO-11 design baseline: `docs/design_decisions/FOO-11-evidence-atlas-design.md`
- Scope and architecture decisions live in the linked Linear documents and issues; do not silently broaden them.

## Repository rules

- Read the relevant role file and current ticket before acting.
- Preserve provenance, auditability, correction paths, and source-rights boundaries.
- Do not invent tariff data, causal claims, or product requirements.
- Keep changes focused, test domain logic, and report validation results.
- Surface assumptions, blockers, and unresolved policy questions explicitly.
