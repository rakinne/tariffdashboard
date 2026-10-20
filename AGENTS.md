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

## Product sources of truth

- Linear project: Tariff Refund Dashboard
- Initial implementation sequence: FOO-7, FOO-10, then FOO-8/FOO-9
- Scope and architecture decisions live in the linked Linear documents and issues; do not silently broaden them.

## Repository rules

- Read the relevant role file and current ticket before acting.
- Preserve provenance, auditability, correction paths, and source-rights boundaries.
- Do not invent tariff data, causal claims, or product requirements.
- Keep changes focused, test domain logic, and report validation results.
- Surface assumptions, blockers, and unresolved policy questions explicitly.
