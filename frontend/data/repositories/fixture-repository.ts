import type { components } from "@/generated/api-types";
import type {
  IncidentListOptions,
  InvestigatorRepository,
  MetricHistoryOptions
} from "@/data/repositories/investigator-repository";
import {
  copilotMessageFixture,
  copilotThreadFixture,
  evidenceFixture,
  incidentListFixture,
  metricHistoryFixture,
  overviewFixture,
  simulationFixture,
  workspaceFixture
} from "@/data/fixtures/scenarios";

type Api = components["schemas"];

export class FixtureInvestigatorRepository implements InvestigatorRepository {
  private readonly copilotThread = structuredClone(copilotThreadFixture) as Api["CopilotThreadResponse"];

  async getOverview(): Promise<Api["SystemOverviewResponse"]> {
    return structuredClone(overviewFixture);
  }

  async getMetricHistory(_options: MetricHistoryOptions): Promise<Api["MetricHistoryResponse"]> {
    return structuredClone(metricHistoryFixture);
  }

  async listIncidents(options?: IncidentListOptions): Promise<Api["CursorPage_IncidentSummary_"]> {
    let items: Api["IncidentSummary"][] = [...incidentListFixture.items];
    if (options?.severity?.length) items = items.filter((item) => options.severity?.includes(item.severity));
    if (options?.processingRegion?.length) items = items.filter((item) => item.affected_scope?.processing_region && options.processingRegion?.includes(item.affected_scope.processing_region));
    const direction = options?.sortDirection === "asc" ? 1 : -1;
    items.sort((left, right) => direction * left.started_at.localeCompare(right.started_at));
    return { items, next_cursor: null };
  }

  async getIncident(_incidentId: string): Promise<Api["IncidentWorkspaceResponse"]> {
    return structuredClone(workspaceFixture);
  }

  async getEvidence(_incidentId: string, _packageId?: string, _packageVersion?: number): Promise<Api["EvidenceProjectionResponse"]> {
    return structuredClone(evidenceFixture);
  }

  async getEvidenceItem(_incidentId: string, evidenceId: string): Promise<Api["EvidenceDetailResponse"]> {
    const item = evidenceFixture.items.find((candidate) => candidate.evidence_id === evidenceId);
    if (!item) throw new Error(`Unknown evidence item: ${evidenceId}`);
    return {
      incident_id: workspaceFixture.incident_id,
      evidence_package_id: evidenceFixture.evidence_package_id,
      evidence_package_version: evidenceFixture.evidence_package_version,
      item,
      source_references: [item.stable_logical_key],
      calculation_method: item.category === "DERIVED_FINDING" ? "Deterministic bounded comparison" : null,
      calculation_lineage: [item.source_module, item.source_version]
    };
  }

  async getCopilotThread(_incidentId: string): Promise<Api["CopilotThreadResponse"]> {
    return structuredClone(this.copilotThread);
  }

  async getCopilotMessages(_incidentId: string, _cursor?: string): Promise<Api["CanonicalCopilotMessagePage"]> {
    return structuredClone(this.copilotThread.messages);
  }

  async requestInitialCopilotReport(_incidentId: string): Promise<Api["CopilotInteractionView"]> {
    return {
      interaction_id: copilotMessageFixture.interaction_id,
      status: "VALIDATED",
      progress_stage: null,
      progress_updated_at: copilotMessageFixture.created_at,
      validated_message_id: copilotMessageFixture.message_id,
      deterministic_fallback: null,
      retry: { eligible: false, retry_after: null, unavailable_reason: null }
    };
  }

  async submitCopilotMessage(_incidentId: string, request: Api["SubmitCopilotMessageRequest"]): Promise<Api["SubmitCopilotMessageResponse"]> {
    const messageId = `fixture-user-${request.client_request_id}`;
    if (!this.copilotThread.messages.items.some((item) => item.message_id === messageId)) {
      this.copilotThread.messages.items.push({
        message_id: messageId,
        thread_id: this.copilotThread.thread.thread_id,
        incident_id: this.copilotThread.thread.incident_id,
        sequence: this.copilotThread.messages.items.length + 1,
        role: "USER",
        content_type: "USER_QUESTION",
        content: {
          type: "USER_QUESTION",
          question: request.question,
          referenced_message_ids: request.referenced_message_ids ?? []
        },
        client_request_id: request.client_request_id,
        created_at: "2026-08-27T11:54:00Z"
      });
    }
    return {
      interaction_id: `fixture-${request.client_request_id}`,
      thread_id: this.copilotThread.thread.thread_id,
      user_message_id: messageId,
      evidence_package_id: this.copilotThread.thread.latest_evidence_package_id ?? evidenceFixture.evidence_package_id,
      evidence_package_version: this.copilotThread.thread.latest_evidence_package_version ?? evidenceFixture.evidence_package_version,
      accepted_at: "2026-08-27T11:54:00Z",
      status: "QUEUED"
    };
  }

  async getCopilotInteraction(_incidentId: string, interactionId: string): Promise<Api["CopilotInteractionView"]> {
    return {
      interaction_id: interactionId,
      status: "VALIDATED",
      progress_stage: null,
      progress_updated_at: "2026-08-27T11:54:02Z",
      validated_message_id: copilotMessageFixture.message_id,
      deterministic_fallback: null,
      retry: { eligible: false, retry_after: null, unavailable_reason: null }
    };
  }

  async retryCopilotInteraction(incidentId: string, interactionId: string): Promise<Api["CopilotInteractionView"]> {
    return this.getCopilotInteraction(incidentId, interactionId);
  }

  async submitCopilotFeedback(_incidentId: string, _messageId: string, request: Api["CopilotFeedbackRequest"]): Promise<Api["ResourceVersion"]> {
    void request;
    return { version: 1, updated_at: "2026-08-27T11:55:00Z" };
  }

  async updateHumanReview(_incidentId: string, request: Api["HumanReviewRequest"]): Promise<Api["HumanReviewView"]> {
    return {
      hypothesis_id: request.hypothesis_id,
      status: request.status,
      note: request.note ?? null,
      reviewed_by: "demo-operator",
      updated_at: "2026-08-27T11:55:00Z",
      version: request.expected_version + 1
    };
  }

  async getSimulationStatus(): Promise<Api["SimulationStatus"]> {
    return structuredClone(simulationFixture);
  }

  async runSimulationCommand(action: Api["SimulationAction"], _clientRequestId: string): Promise<Api["SimulationStatus"]> {
    return { ...structuredClone(simulationFixture), message: `${action.replaceAll("_", " ")} accepted in fixture mode.` };
  }
}

export const fixtureRepository = new FixtureInvestigatorRepository();
