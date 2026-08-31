# Stage 8 Component Manifest

Status: `APPROVED_AND_CONSOLIDATED`

The approved frontend combines Variant B's Overview with Variant A's investigation workspace.
Both compositions use the same semantic colour, typography, spacing, radius, elevation and focus
tokens in `frontend/app/globals.css`; no runtime design-variant switch remains.

## Foundations

| Component | Source / pattern | Local implementation | Used by |
| --- | --- | --- | --- |
| Button | shadcn composition + CVA | `frontend/components/ui/button.tsx` | Approved product and fixture harness |
| Card | shadcn composition | `frontend/components/ui/card.tsx` | Approved product and fixture harness |
| Badge | shadcn-style semantic variant | `frontend/components/ui/badge.tsx` | Approved product and fixture harness |
| Tabs | Radix Tabs, shadcn composition | `frontend/components/ui/tabs.tsx` | Overview charts and incident workspace |
| Accordion | Radix Accordion, shadcn composition | `frontend/components/ui/accordion.tsx` | Evidence and citations |
| Dialog | Radix Dialog, shadcn composition | `frontend/components/ui/dialog.tsx` | Destructive reset confirmation |
| Tooltip | Radix Tooltip | `frontend/components/ui/tooltip.tsx` | Theme controls |
| Metric chart | Recharts AreaChart | `frontend/components/charts/metric-chart.tsx` | Overview and incident timeline |

No Magic UI component was included. Its use is optional in the master prompt, and neither concept
needed decorative motion. Essential behavior relies only on the shared accessible foundation.

## Product compositions

| Composition | Local implementation | Approved composition | Product route |
| --- | --- | --- | --- |
| Application shell | `frontend/components/investigator/app-shell.tsx` | Shared tokens with ledger and focused-investigation modes | All routes |
| Overview | `frontend/components/investigator/overview-page.tsx` | Variant B editorial split and rule-led hierarchy | `/` |
| Incident archive | `frontend/components/investigator/incidents-page.tsx` | Shared ledger top rail and data table | `/incidents` |
| Incident workspace | `frontend/components/investigator/incident-workspace.tsx` | Variant A command row and persistent investigation deck | `/incidents/[incidentId]` |
| Canonical Copilot thread | `frontend/components/investigator/copilot-thread.tsx` | Full-width ordered transcript, controlled progress and sticky composer | Incident `Copilot` tab |
| Copilot message | `frontend/components/investigator/copilot-message.tsx` | Grouped initial briefings, conversational follow-ups, notices, fallback and feedback | Canonical transcript |
| Copilot citation | `frontend/components/investigator/copilot-citation.tsx` | Per-answer numbered inline expansion with nested technical details | Validated assistant answers |
| Fixture state gallery | `frontend/components/review/state-gallery.tsx` | Isolated regression harness, not product navigation | `/fixture-states` |

## Review-code isolation and approved baselines

- All temporary `/review/variant-*` routes and component-level design switches were removed.
- `/fixture-states` remains intentionally isolated as an automated contract-state regression harness;
  query-scoped Copilot transcript fixtures exist only there for approved-state screenshots.
- Approved screenshots are `approved-overview-desktop-light.png`,
  `approved-overview-laptop-dark.png`, `approved-incident-desktop-light.png` and
  `approved-incident-laptop-dark.png` under `docs/screenshots/`.
- Copilot baselines are `approved-copilot-initial-desktop-light.png`,
  `approved-copilot-follow-up-desktop-light.png`, `approved-copilot-citation-desktop-light.png`,
  `approved-copilot-transition-laptop-dark.png`, `approved-copilot-fallback-laptop-dark.png` and
  `approved-copilot-restored-desktop-light.png`.
- Obsolete variant-review screenshots were removed after the approved baselines were generated and
  visually inspected.

## Fixture and behavior boundary

- Generated OpenAPI types: `frontend/generated/api-types.ts`.
- Compile-time checked fixtures: `frontend/data/fixtures/scenarios.ts`.
- Fixture repository boundary: `frontend/data/repositories/fixture-repository.ts`.
- Live REST repository: `frontend/data/repositories/http-investigator-repository.ts`.
- Compact WebSocket reconciliation: `frontend/data/repositories/live-updates.ts`; unknown events,
  reconnects and sequence gaps refetch authoritative REST state.
- `frontend/data/repositories/runtime-repository.ts` defaults product routes to live HTTP data;
  `NEXT_PUBLIC_AMEX_DATA_MODE=fixture` is an explicit test/review opt-in. There is no silent
  fixture fallback after a live request fails.
- Required states include telemetry warming/stale/unknown; suspected/open/recovery/resolved
  lifecycles; complete/partial/invalid evidence; insufficient RCA; Copilot queued/progress/
  validated/failure/fallback; reconnect/disconnect; review; and feedback.
- The technical-error-rate punchline and its excess-error supporting count remain visible while
  the large comparison chart changes tabs.
- Reset requires a modal confirmation. Human review validates explanatory notes, preserves input
  on failure, and returns a successful save to the preserved incident-list URL and scroll context.
- Incident navigation is `Summary | Timeline | Evidence | Copilot | Review`; deterministic RCA is
  prominent in Summary and `Open Copilot` selects/focuses the Copilot tab. Summary translates
  machine identifiers into readable labels, presents the leading cause as a compact evidence-led
  hierarchy, and retains the exact deterministic hypothesis behind an expandable technical detail.
  Product paths contain no drawer, resizer, width storage, close/return or conversation
  reset/selection controls.
- Copilot restores the complete canonical transcript, numbers citations within each answer, hides
  raw IDs/reason codes by default, exposes structured feedback, and keeps its sticky composer usable
  after a persisted deterministic fallback. Controlled progress never contains provider prose and
  keeps reconciling terminal status with bounded backoff until the transcript is ready or the view
  is closed.

## Accessibility and theme checks

- WCAG-AA light and dark semantic tokens, visible focus rings, labelled controls, keyboard-closing
  reset dialog, keyboard-operable incident tabs/citations, reduced-motion CSS, non-color status text,
  chart captions, and an accessible data table.
- Desktop viewport verified at 1440 x 1000; laptop viewport verified at 1280 x 800.
- Automated axe coverage runs on Overview, investigation and fixture states in both themes.
- Browser coverage and screenshot generation live in `frontend/tests/e2e/approved-frontend.spec.ts`.
