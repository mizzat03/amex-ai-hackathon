# Authoritative-source traceability

| Authoritative document | Implementation representation |
| --- | --- |
| `AMEX-Incident-Investigator-Planning-Context.md` | Architecture boundaries, deterministic pipeline, evidence/Copilot trust model, evaluation policy and responsible-AI docs. |
| `AMEX-Incident-Investigator-Decision-Register.md` | Locked taxonomy, lifecycle/RCA/evidence decisions, API semantics, human control, provider-neutral validation and no-runtime-routing policy. |
| `plan.md` | Ordered Stages 1–11, deterministic modules, persistence, UI, Copilot reliability controls, labelled evaluation set and end-to-end gates. |
| `AMEX-Incident-Investigator-Frontend-Plan.md` | Approved Variant B Overview, Variant A workspace, shared tokens, fixtures, themes, accessibility, responsive behavior and component manifest. |
| `frontend-backend-contract.md` | Pydantic/OpenAPI source of truth, generated TypeScript, repository adapters, error envelope, idempotency/version conflicts, simulator commands and compact WebSocket invalidations. |

Implementation-owned measured defaults and deviations are recorded in
`docs/implementation-decisions.md`; stage results and limitations are recorded in
`docs/stage-checkpoints.md`. No source authority is replaced by these implementation notes.
