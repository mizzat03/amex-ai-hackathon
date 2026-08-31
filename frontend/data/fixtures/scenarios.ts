import type { components } from "@/generated/api-types";
import type { ConnectionState } from "@/data/repositories/investigator-repository";

export type Api = components["schemas"];

const currentPeriod = {
  start_at: "2026-08-27T11:48:00Z",
  end_at: "2026-08-27T11:53:00Z"
} satisfies Api["Period"];

const baselinePeriod = {
  start_at: "2026-08-27T11:18:00Z",
  end_at: "2026-08-27T11:48:00Z"
} satisfies Api["Period"];

function comparison(
  baselineValue: number,
  absoluteChange: number,
  interpretation: Api["MetricComparison"]["interpretation"] = "DEGRADED"
): Api["MetricComparison"] {
  return {
    baseline_value: baselineValue,
    absolute_change: absoluteChange,
    relative_change: baselineValue === 0 ? null : absoluteChange / baselineValue,
    direction: absoluteChange > 0 ? "UP" : absoluteChange < 0 ? "DOWN" : "UNCHANGED",
    interpretation
  };
}

function metric(
  value: number | null,
  unit: Api["MetricValue"]["unit"],
  baseline?: number,
  interpretation?: Api["MetricComparison"]["interpretation"]
): Api["MetricValue"] {
  const result: Api["MetricValue"] = { value, unit, display_precision: unit === "RATE" ? 4 : 0 };
  if (value !== null && baseline !== undefined) {
    result.comparison = comparison(baseline, value - baseline, interpretation);
  }
  return result;
}

export const incidentSummary = {
  incident_id: "INC-2026-0827-017",
  title: "Elevated technical errors after authorization deployment",
  severity: "HIGH",
  lifecycle: "OPEN",
  started_at: "2026-08-27T11:44:00Z",
  updated_at: "2026-08-27T11:53:00Z",
  affected_scope: {
    processing_region: "SG",
    payment_method: "MOBILE_WALLET",
    service: "authorization-api",
    service_version: "v2.4.1"
  },
  dominant_error_signature: "UPSTREAM_TIMEOUT",
  leading_hypothesis: {
    hypothesis_id: "HYP-DEPLOY-241",
    summary: "authorization-api v2.4.1 deployment is temporally and dimensionally aligned",
    evidence_tier: "STRONG_EVIDENCE"
  },
  evidence_completeness: "COMPLETE",
  human_review_status: "UNREVIEWED"
} satisfies Api["IncidentSummary"];

export const overviewFixture = {
  generated_at: "2026-08-27T11:53:00Z",
  latest_sample_at: "2026-08-27T11:53:00Z",
  telemetry_stale_after_seconds: 30,
  telemetry_state: "HEALTHY",
  baseline: {
    ready: true,
    current_samples: 17940,
    required_samples: 6000,
    progress: 1,
    unavailable_reason: null
  },
  metrics: {
    technical_error_rate: metric(0.0837, "RATE", 0.0061),
    approval_rate: metric(0.7912, "RATE", 0.8814),
    business_decline_rate: metric(0.1251, "RATE", 0.1125, "HEALTHY_RANGE"),
    throughput: metric(988, "ATTEMPTS_PER_SECOND", 1004, "HEALTHY_RANGE"),
    average_authorization_latency: metric(714, "MILLISECONDS", 238),
    p95_authorization_latency: metric(1842, "MILLISECONDS", 612)
  },
  punchline_metric: {
    label: "Technical error rate",
    metric_key: "technical_error_rate",
    metric: metric(0.0837, "RATE", 0.0061),
    supporting_count: metric(3831, "COUNT", 279)
  },
  detector_summary: {
    global_technical_error_state: "OPEN",
    latency_state: "OPEN"
  },
  active_incident_count: 1,
  active_incidents: [incidentSummary]
} satisfies Api["SystemOverviewResponse"];

const historyValues = [
  0.0058, 0.0062, 0.0059, 0.0064, 0.0061, 0.006, 0.0063, 0.0062,
  0.0065, 0.0071, 0.0138, 0.0287, 0.0512, 0.0764, 0.0861, 0.0892,
  0.0851, 0.0837
];

export const metricHistoryFixture = {
  metric_key: "technical_error_rate",
  unit: "RATE",
  period: { start_at: "2026-08-27T11:36:00Z", end_at: "2026-08-27T11:53:00Z" },
  resolution_seconds: 60,
  points: historyValues.map((value, index) => ({
    at: new Date(Date.parse("2026-08-27T11:36:00Z") + index * 60_000).toISOString(),
    value
  })),
  events: [
    {
      timeline_item_id: "TL-001",
      event_type: "OPERATIONAL_CHANGE",
      occurred_at: "2026-08-27T11:43:00Z",
      operational_event_id: "DEPLOY-241",
      title: "Deployment completed",
      summary: "authorization-api v2.4.1 reached 100% of SG traffic"
    },
    {
      timeline_item_id: "TL-002",
      event_type: "INCIDENT_LIFECYCLE",
      occurred_at: "2026-08-27T11:46:00Z",
      lifecycle: "OPEN",
      title: "Incident opened",
      summary: "Technical error persistence threshold crossed"
    }
  ]
} satisfies Api["MetricHistoryResponse"];

const hypothesisRelations = [
  { evidence_id: "EV-SCOPE-001", relation: "SUPPORTING" },
  { evidence_id: "EV-TIME-001", relation: "SUPPORTING" },
  { evidence_id: "EV-ERROR-001", relation: "SUPPORTING" }
] satisfies Api["HypothesisRelationView"][];

export const leadingHypothesis = {
  hypothesis_id: "HYP-DEPLOY-241",
  candidate_type: "DEPLOYMENT",
  operational_event_id: "DEPLOY-241",
  summary: "authorization-api v2.4.1 deployment is temporally and dimensionally aligned",
  evidence_tier: "STRONG_EVIDENCE",
  rank: 1,
  is_leading: true,
  relations: hypothesisRelations
} satisfies Api["HypothesisView"];

const alternativeHypothesis = {
  hypothesis_id: "HYP-CONFIG-552",
  candidate_type: "CONFIG_CHANGE",
  operational_event_id: "CONFIG-552",
  summary: "Gateway timeout threshold change preceded the incident but affects all regions",
  evidence_tier: "WEAK_EVIDENCE",
  rank: 2,
  is_leading: false,
  relations: [
    { evidence_id: "EV-TIME-001", relation: "SUPPORTING" },
    { evidence_id: "EV-SCOPE-001", relation: "CONTRADICTORY" }
  ]
} satisfies Api["HypothesisView"];

const evidenceItems = [
  {
    evidence_id: "EV-SCOPE-001",
    stable_logical_key: "affected-scope-sg-wallet-v241",
    category: "DERIVED_FINDING",
    statement: "SG mobile-wallet traffic on v2.4.1 carries 91.8% of excess technical errors.",
    structured_value: { traffic_share: 0.184, excess_error_share: 0.918 },
    unit: "RATE",
    period: currentPeriod,
    scope: incidentSummary.affected_scope,
    temporal_scope: "INCIDENT_SNAPSHOT",
    source_module: "dimensional-analysis",
    source_version: "1.0.0",
    provenance_label: "Deterministic scope comparison"
  },
  {
    evidence_id: "EV-TIME-001",
    stable_logical_key: "deploy-precedes-error-rise",
    category: "OBSERVED_FACT",
    statement: "Deployment completed 63 seconds before the sustained technical-error rise.",
    structured_value: { elapsed_seconds: 63 },
    unit: "SECONDS",
    period: currentPeriod,
    scope: incidentSummary.affected_scope,
    temporal_scope: "INCIDENT_SNAPSHOT",
    source_module: "operational-events",
    source_version: "1.0.0",
    provenance_label: "Operational-event correlation"
  },
  {
    evidence_id: "EV-ERROR-001",
    stable_logical_key: "upstream-timeout-dominant",
    category: "DERIVED_FINDING",
    statement: "UPSTREAM_TIMEOUT represents 78.4% of current technical errors.",
    structured_value: { share: 0.784, count: 3492 },
    unit: "RATE",
    period: currentPeriod,
    scope: incidentSummary.affected_scope,
    temporal_scope: "INCIDENT_SNAPSHOT",
    source_module: "error-signatures",
    source_version: "1.0.0",
    provenance_label: "Normalized error signature"
  },
  {
    evidence_id: "EV-LIMIT-001",
    stable_logical_key: "downstream-trace-gap",
    category: "LIMITATION",
    statement: "Downstream issuer traces are not available in this synthetic environment.",
    temporal_scope: "INCIDENT_SNAPSHOT",
    source_module: "evidence-builder",
    source_version: "1.0.0",
    provenance_label: "Evidence availability check"
  }
] satisfies Api["EvidenceItemView"][];

export const workspaceFixture = {
  generated_at: "2026-08-27T11:53:00Z",
  incident_id: incidentSummary.incident_id,
  incident: {
    ...incidentSummary,
    impact_summary: "An estimated 3,831 excess technical errors affected SG mobile-wallet authorizations; business declines remained within baseline range.",
    incident_period: { start_at: "2026-08-27T11:44:00Z", end_at: "2026-08-27T11:53:00Z" },
    current_period: currentPeriod,
    baseline_period: baselinePeriod,
    resolved_at: null,
    closure_mode: null,
    manual_closure_reason: null
  },
  affected_scope: {
    label: "SG · Mobile wallet · authorization-api v2.4.1",
    scope: incidentSummary.affected_scope,
    technical_error_rate: metric(0.312, "RATE", 0.0057),
    complement_technical_error_rate: metric(0.0112, "RATE", 0.0062),
    traffic_share: metric(0.184, "RATE"),
    excess_technical_errors: metric(3517, "COUNT"),
    caveats: ["Scope ranking compares bounded dimensions and up to three-way combinations."]
  },
  error_signature: {
    label: "Upstream timeout",
    normalized_error_code: "UPSTREAM_TIMEOUT",
    current_count: metric(3492, "COUNT"),
    excess_count: metric(3246, "COUNT"),
    share_of_technical_errors: metric(0.784, "RATE"),
    attempt_rate: metric(0.0656, "RATE", 0.0009)
  },
  rca_summary: {
    result_version: 3,
    overall_tier: "STRONG_EVIDENCE",
    leading_hypothesis: leadingHypothesis,
    alternatives: [alternativeHypothesis],
    insufficient_evidence_reason: null
  },
  timeline: metricHistoryFixture.events,
  evidence_package_id: "EP-INC-017",
  evidence_package_version: 3,
  evidence_status: {
    completeness: "COMPLETE",
    limitations: [evidenceItems[3]!],
    validation_message: "Package validated against evidence schema v1."
  },
  copilot_summary: {
    thread_available: true,
    initial_analysis_status: "VALIDATED",
    latest_interaction_id: "COP-INT-017",
    latest_validated_message_id: "COP-MSG-017"
  },
  human_review: {
    status: "UNREVIEWED",
    hypothesis_id: null,
    note: null,
    reviewed_by: null,
    updated_at: "2026-08-27T11:53:00Z",
    version: 1
  }
} satisfies Api["IncidentWorkspaceResponse"];

export const evidenceFixture = {
  evidence_package_id: "EP-INC-017",
  evidence_package_version: 3,
  incident_id: incidentSummary.incident_id,
  generated_at: "2026-08-27T11:53:00Z",
  completeness: "COMPLETE",
  items: evidenceItems,
  hypotheses: [leadingHypothesis, alternativeHypothesis],
  citation_allowlist: evidenceItems.slice(0, 3).map((item) => ({
    citation_type: "EVIDENCE" as const,
    evidence_id: item.evidence_id,
    evidence_package_id: "EP-INC-017",
    evidence_package_version: 3
  })),
  package_limitations: ["Downstream issuer traces are unavailable in the synthetic demo."]
} satisfies Api["EvidenceProjectionResponse"];

const copilotThreadId = "thr-incident-017";
const primaryCitation: Api["CopilotEvidenceCitation"] = {
  citation_type: "EVIDENCE",
  citation_number: 1,
  statement: evidenceItems[0]!.statement,
  structured_value: { traffic_share: 0.184, excess_error_share: 0.918 },
  unit: "RATE",
  scope: incidentSummary.affected_scope,
  period: currentPeriod,
  temporal_scope: "INCIDENT_SNAPSHOT",
  provenance_label: evidenceItems[0]!.provenance_label,
  evidence_package_id: "EP-INC-017",
  evidence_package_version: 3,
  technical_details: {
    evidence_id: evidenceItems[0]!.evidence_id,
    source_module: evidenceItems[0]!.source_module,
    source_version: evidenceItems[0]!.source_version,
    calculation_method: "Deterministic bounded comparison",
    calculation_lineage: ["bucket rollups", "scope comparison"],
    source_references: [evidenceItems[0]!.stable_logical_key]
  }
};

export const copilotMessageFixture = {
  message_id: "COP-MSG-017",
  thread_id: copilotThreadId,
  interaction_id: "COP-INT-017",
  incident_id: incidentSummary.incident_id,
  sequence: 1,
  evidence_package_id: "EP-INC-017",
  evidence_package_version: 3,
  role: "ASSISTANT",
  content_type: "COPILOT_ANSWER",
  created_at: "2026-08-27T11:53:30Z",
  content: {
    type: "COPILOT_ANSWER",
    schema_version: "copilot-answer.v2",
    answer_kind: "initial_report",
    headline: "Deployment-aligned authorization failures",
    direct_answer: "The v2.4.1 deployment is the strongest available explanation, with temporal, scope, and error-signature agreement.",
    confidence: "HIGH",
    supporting_points: [
      { text: "The affected scope carries 91.8% of excess technical errors.", citation_numbers: [1] }
    ],
    contradictory_points: [
      { text: "A broad gateway configuration change remains a weaker alternative.", citation_numbers: [] }
    ],
    unknown_points: [
      { text: "Downstream issuer traces are unavailable, so causality is not proven.", citation_numbers: [] }
    ],
    recommended_checks: [
      {
        title: "Compare v2.4.0 and v2.4.1 timeout paths",
        rationale: "The error signature and version scope align tightly.",
        expected_signal: "Timeouts fall back toward baseline on the previous version.",
        risk: "LOW",
        requires_human_approval: true,
        citation_numbers: [1]
      }
    ],
    citations: [primaryCitation],
    suggested_questions: ["What evidence weakens this hypothesis?", "What should I verify before rollback?"],
    validation_status: "VALIDATED"
  }
} as const satisfies Api["CopilotMessage"];

export const copilotUserMessageFixture = {
  message_id: "COP-MSG-018",
  thread_id: copilotThreadId,
  incident_id: incidentSummary.incident_id,
  sequence: 2,
  role: "USER",
  content_type: "USER_QUESTION",
  content: {
    type: "USER_QUESTION",
    question: "What evidence weakens this hypothesis?",
    referenced_message_ids: [copilotMessageFixture.message_id]
  },
  client_request_id: "fixture-follow-up",
  created_at: "2026-08-27T11:54:00Z"
} as const satisfies Api["CopilotMessage"];

export const copilotFollowUpFixture = {
  ...copilotMessageFixture,
  message_id: "COP-MSG-019",
  interaction_id: "COP-INT-019",
  sequence: 3,
  response_to_message_id: copilotUserMessageFixture.message_id,
  created_at: "2026-08-27T11:54:08Z",
  content: {
    ...copilotMessageFixture.content,
    answer_kind: "follow_up",
    headline: "The timing evidence is strongest; causality remains open",
    direct_answer: "The hypothesis would weaken if version-scoped errors remained elevated after rollback or if another region showed the same signature.",
    supporting_points: [
      { text: "The current package still concentrates excess errors in SG mobile-wallet traffic.", citation_numbers: [1] }
    ],
    contradictory_points: [],
    unknown_points: [
      { text: "Post-rollback comparison data is not yet present in this snapshot.", citation_numbers: [] }
    ],
    recommended_checks: [],
    suggested_questions: []
  }
} as const satisfies Api["CopilotMessage"];

export const copilotTransitionFixture = {
  message_id: "COP-MSG-NOTICE-020",
  thread_id: copilotThreadId,
  incident_id: incidentSummary.incident_id,
  sequence: 4,
  role: "SYSTEM",
  content_type: "EVIDENCE_VERSION_NOTICE",
  content: {
    type: "EVIDENCE_VERSION_NOTICE",
    previous_evidence_package_id: "EP-INC-017",
    previous_evidence_package_version: 3,
    evidence_package_id: "EP-INC-017",
    evidence_package_version: 4,
    summary: "Newer incident evidence is available. Earlier answers keep their original evidence."
  },
  created_at: "2026-08-27T11:55:00Z"
} as const satisfies Api["CopilotMessage"];

export const copilotFallbackFixture = {
  message_id: "COP-MSG-021",
  thread_id: copilotThreadId,
  interaction_id: "COP-INT-021",
  incident_id: incidentSummary.incident_id,
  sequence: 5,
  evidence_package_id: "EP-INC-017",
  evidence_package_version: 4,
  role: "ASSISTANT",
  content_type: "DETERMINISTIC_FALLBACK",
  content: {
    type: "DETERMINISTIC_FALLBACK",
    label: "Deterministic fallback",
    summary: "The AI provider is unavailable; deterministic incident findings remain available.",
    reason_code: "provider_http_failure",
    retry_eligible: true
  },
  created_at: "2026-08-27T11:55:10Z"
} as const satisfies Api["CopilotMessage"];

export const copilotThreadFixture = {
  thread: {
    thread_id: copilotThreadId,
    incident_id: incidentSummary.incident_id,
    created_at: "2026-08-27T11:53:20Z",
    updated_at: "2026-08-27T11:53:30Z",
    latest_evidence_package_id: "EP-INC-017",
    latest_evidence_package_version: 3
  },
  messages: { items: [copilotMessageFixture], next_cursor: null }
} as const satisfies Api["CopilotThreadResponse"];

export const copilotTranscriptFixtures = {
  initial: [copilotMessageFixture],
  followUp: [copilotMessageFixture, copilotUserMessageFixture, copilotFollowUpFixture],
  transition: [copilotMessageFixture, copilotUserMessageFixture, copilotFollowUpFixture, copilotTransitionFixture],
  fallback: [copilotMessageFixture, copilotTransitionFixture, copilotFallbackFixture],
  restored: [copilotMessageFixture, copilotUserMessageFixture, copilotFollowUpFixture],
  progress: { status: "IN_PROGRESS", stage: "VALIDATING_CITATIONS" },
  feedback: ["HELPFUL", "PARTIALLY_HELPFUL", "NOT_HELPFUL"]
} as const;

export const simulationFixture = {
  state: "INCIDENT_ACTIVE",
  active_scenario_id: "deployment-regression-sg-wallet",
  started_at: "2026-08-27T11:15:00Z",
  baseline_ready: true,
  available_actions: ["TRIGGER_ROLLBACK_RECOVERY", "STOP", "RESET"],
  message: "Synthetic incident is active; rollback recovery is available."
} satisfies Api["SimulationStatus"];

export const incidentListFixture = {
  items: [
    incidentSummary,
    {
      ...incidentSummary,
      incident_id: "INC-2026-0826-004",
      title: "Issuer latency elevated in AU card-present traffic",
      severity: "MEDIUM",
      lifecycle: "RECOVERY_CANDIDATE",
      started_at: "2026-08-26T08:15:00Z",
      updated_at: "2026-08-26T08:42:00Z",
      affected_scope: { processing_region: "AU", payment_method: "CARD_PRESENT", service: "authorization-api", service_version: "v2.4.0" },
      dominant_error_signature: "ISSUER_TIMEOUT",
      evidence_completeness: "PARTIAL",
      human_review_status: "INCONCLUSIVE"
    },
    {
      ...incidentSummary,
      incident_id: "INC-2026-0825-011",
      title: "Gateway configuration caused transient routing failures",
      severity: "LOW",
      lifecycle: "RESOLVED",
      started_at: "2026-08-25T03:10:00Z",
      updated_at: "2026-08-25T03:31:00Z",
      affected_scope: { processing_region: "US", payment_method: "ECOMMERCE", service: "payment-gateway", service_version: "v7.8.2" },
      dominant_error_signature: "ROUTE_UNAVAILABLE",
      evidence_completeness: "COMPLETE",
      human_review_status: "ACKNOWLEDGED"
    }
  ],
  next_cursor: null
} satisfies Api["CursorPage_IncidentSummary_"];

export const requiredStateFixtures = {
  telemetry: ["WARMING_UP", "STALE", "UNKNOWN"],
  lifecycle: ["SUSPECTED", "OPEN", "RECOVERY_CANDIDATE", "RESOLVED"],
  completeness: ["COMPLETE", "PARTIAL", "INVALID"],
  copilot: ["QUEUED", "IN_PROGRESS", "VALIDATED", "FAILED", "FALLBACK"],
  reconnect: [
    { status: "connected", lastSequence: 1042 },
    { status: "reconnecting", lastSequence: 1042 },
    { status: "disconnected", lastSequence: 1042 }
  ] satisfies ConnectionState[],
  review: ["UNREVIEWED", "ACKNOWLEDGED", "REJECTED", "INCONCLUSIVE"],
  feedback: ["HELPFUL", "PARTIALLY_HELPFUL", "NOT_HELPFUL"]
} as const satisfies {
  telemetry: readonly Api["TelemetryState"][];
  lifecycle: readonly Api["IncidentLifecycle"][];
  completeness: readonly Api["EvidenceCompleteness"][];
  copilot: readonly Api["CopilotInteractionView"]["status"][];
  reconnect: readonly ConnectionState[];
  review: readonly Api["HumanReviewStatus"][];
  feedback: readonly Api["CopilotFeedbackRequest"]["rating"][];
};

export const insufficientRcaFixture = {
  ...workspaceFixture,
  rca_summary: {
    result_version: 4,
    overall_tier: "INSUFFICIENT_EVIDENCE",
    leading_hypothesis: null,
    alternatives: [],
    insufficient_evidence_reason: "No operational event is both temporally close and scope-consistent."
  }
} satisfies Api["IncidentWorkspaceResponse"];
