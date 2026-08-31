import type { components } from "@/generated/api-types";

type Api = components["schemas"];

export type ConnectionState =
  | { readonly status: "connected"; readonly lastSequence: number }
  | { readonly status: "reconnecting"; readonly lastSequence: number }
  | { readonly status: "disconnected"; readonly lastSequence: number };

export interface IncidentListOptions {
  readonly startedAtOrAfter?: string;
  readonly startedBefore?: string;
  readonly severity?: readonly Api["IncidentSeverity"][];
  readonly processingRegion?: readonly string[];
  readonly paymentMethod?: readonly string[];
  readonly sortBy?: "started_at" | "severity" | "lifecycle";
  readonly sortDirection?: "asc" | "desc";
  readonly cursor?: string;
}

export interface MetricHistoryOptions {
  readonly metricKey: Api["MetricKey"];
  readonly startAt: string;
  readonly endAt: string;
  readonly incidentId?: string;
}

export interface InvestigatorRepository {
  getOverview(): Promise<Api["SystemOverviewResponse"]>;
  getMetricHistory(options: MetricHistoryOptions): Promise<Api["MetricHistoryResponse"]>;
  listIncidents(options?: IncidentListOptions): Promise<Api["CursorPage_IncidentSummary_"]>;
  getIncident(incidentId: string): Promise<Api["IncidentWorkspaceResponse"]>;
  getEvidence(
    incidentId: string,
    packageId?: string,
    packageVersion?: number,
  ): Promise<Api["EvidenceProjectionResponse"]>;
  getEvidenceItem(
    incidentId: string,
    evidenceId: string,
  ): Promise<Api["EvidenceDetailResponse"]>;
  getCopilotThread(
    incidentId: string,
  ): Promise<Api["CopilotThreadResponse"]>;
  getCopilotMessages(
    incidentId: string,
    cursor?: string,
  ): Promise<Api["CanonicalCopilotMessagePage"]>;
  requestInitialCopilotReport(
    incidentId: string,
  ): Promise<Api["CopilotInteractionView"]>;
  submitCopilotMessage(
    incidentId: string,
    request: Api["SubmitCopilotMessageRequest"],
  ): Promise<Api["SubmitCopilotMessageResponse"]>;
  getCopilotInteraction(
    incidentId: string,
    interactionId: string,
  ): Promise<Api["CopilotInteractionView"]>;
  retryCopilotInteraction(
    incidentId: string,
    interactionId: string,
  ): Promise<Api["CopilotInteractionView"]>;
  submitCopilotFeedback(
    incidentId: string,
    messageId: string,
    request: Api["CopilotFeedbackRequest"],
  ): Promise<Api["ResourceVersion"]>;
  updateHumanReview(
    incidentId: string,
    request: Api["HumanReviewRequest"],
  ): Promise<Api["HumanReviewView"]>;
  getSimulationStatus(): Promise<Api["SimulationStatus"]>;
  runSimulationCommand(
    action: Api["SimulationAction"],
    clientRequestId: string,
  ): Promise<Api["SimulationStatus"]>;
}
