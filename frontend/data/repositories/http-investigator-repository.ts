import type { components } from "@/generated/api-types";
import type {
  IncidentListOptions,
  InvestigatorRepository,
  MetricHistoryOptions
} from "@/data/repositories/investigator-repository";

type Api = components["schemas"];

export class InvestigatorApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;

  constructor(status: number, payload: Api["ApiError"]) {
    super(payload.error.message);
    this.name = "InvestigatorApiError";
    this.status = status;
    this.code = payload.error.code;
    this.retryable = payload.error.retryable;
  }
}

function appendMany(search: URLSearchParams, key: string, values?: readonly string[]): void {
  values?.forEach((value) => search.append(key, value));
}

export class HttpInvestigatorRepository implements InvestigatorRepository {
  readonly baseUrl: string;

  constructor(baseUrl = process.env.NEXT_PUBLIC_AMEX_API_URL ?? "http://127.0.0.1:8100/api/v1") {
    const parsed = new URL(baseUrl);
    if (!(["http:", "https:"] as const).includes(parsed.protocol as "http:" | "https:")) {
      throw new Error("Investigator API URL must use HTTP or HTTPS");
    }
    this.baseUrl = parsed.toString().replace(/\/$/, "");
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...init?.headers }
    });
    const payload: unknown = await response.json();
    if (!response.ok) {
      throw new InvestigatorApiError(response.status, payload as Api["ApiError"]);
    }
    return payload as T;
  }

  getOverview(): Promise<Api["SystemOverviewResponse"]> {
    return this.request("/system/overview");
  }

  getMetricHistory(options: MetricHistoryOptions): Promise<Api["MetricHistoryResponse"]> {
    const search = new URLSearchParams({
      metric_key: options.metricKey,
      start_at: options.startAt,
      end_at: options.endAt
    });
    if (options.incidentId) search.set("incident_id", options.incidentId);
    return this.request(`/metrics/history?${search.toString()}`);
  }

  listIncidents(options: IncidentListOptions = {}): Promise<Api["CursorPage_IncidentSummary_"]> {
    const search = new URLSearchParams();
    if (options.startedAtOrAfter) search.set("started_at_or_after", options.startedAtOrAfter);
    if (options.startedBefore) search.set("started_before", options.startedBefore);
    appendMany(search, "severity", options.severity);
    appendMany(search, "processing_region", options.processingRegion);
    appendMany(search, "payment_method", options.paymentMethod);
    if (options.sortBy) search.set("sort_by", options.sortBy);
    if (options.sortDirection) search.set("sort_direction", options.sortDirection);
    if (options.cursor) search.set("cursor", options.cursor);
    const query = search.size ? `?${search.toString()}` : "";
    return this.request(`/incidents${query}`);
  }

  getIncident(incidentId: string): Promise<Api["IncidentWorkspaceResponse"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}`);
  }

  getEvidence(
    incidentId: string,
    packageId?: string,
    packageVersion?: number
  ): Promise<Api["EvidenceProjectionResponse"]> {
    const search = new URLSearchParams();
    if (packageId) search.set("evidence_package_id", packageId);
    if (packageVersion !== undefined) search.set("evidence_package_version", String(packageVersion));
    const query = search.size ? `?${search.toString()}` : "";
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/evidence${query}`);
  }

  getEvidenceItem(incidentId: string, evidenceId: string): Promise<Api["EvidenceDetailResponse"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/evidence/${encodeURIComponent(evidenceId)}`);
  }

  getCopilotThread(incidentId: string): Promise<Api["CopilotThreadResponse"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/copilot/thread`);
  }

  getCopilotMessages(incidentId: string, cursor?: string): Promise<Api["CanonicalCopilotMessagePage"]> {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/copilot/messages${query}`);
  }

  requestInitialCopilotReport(incidentId: string): Promise<Api["CopilotInteractionView"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/copilot/initial-report`, {
      method: "POST"
    });
  }

  submitCopilotMessage(
    incidentId: string,
    request: Api["SubmitCopilotMessageRequest"]
  ): Promise<Api["SubmitCopilotMessageResponse"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/copilot/messages`, {
      method: "POST",
      body: JSON.stringify(request)
    });
  }

  getCopilotInteraction(
    incidentId: string,
    interactionId: string
  ): Promise<Api["CopilotInteractionView"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/copilot/interactions/${encodeURIComponent(interactionId)}`);
  }

  retryCopilotInteraction(
    incidentId: string,
    interactionId: string
  ): Promise<Api["CopilotInteractionView"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/copilot/interactions/${encodeURIComponent(interactionId)}/retry`, {
      method: "POST",
      body: JSON.stringify({ client_request_id: crypto.randomUUID() })
    });
  }

  submitCopilotFeedback(
    incidentId: string,
    messageId: string,
    request: Api["CopilotFeedbackRequest"]
  ): Promise<Api["ResourceVersion"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/copilot/messages/${encodeURIComponent(messageId)}/feedback`, {
      method: "POST",
      body: JSON.stringify(request)
    });
  }

  updateHumanReview(
    incidentId: string,
    request: Api["HumanReviewRequest"]
  ): Promise<Api["HumanReviewView"]> {
    return this.request(`/incidents/${encodeURIComponent(incidentId)}/human-review`, {
      method: "PUT",
      body: JSON.stringify(request)
    });
  }

  getSimulationStatus(): Promise<Api["SimulationStatus"]> {
    return this.request("/simulation/status");
  }

  runSimulationCommand(
    action: Api["SimulationAction"],
    clientRequestId: string
  ): Promise<Api["SimulationStatus"]> {
    const path: Record<Api["SimulationAction"], string> = {
      START: "/simulation/start",
      INJECT_DEPLOYMENT_REGRESSION:
        "/simulation/scenarios/payment-gateway-v2.4.1-token-regression/inject",
      TRIGGER_ROLLBACK_RECOVERY: "/simulation/recovery",
      STOP: "/simulation/stop",
      RESET: "/simulation/reset"
    };
    return this.request(path[action], {
      method: "POST",
      body: JSON.stringify({
        client_request_id: clientRequestId,
        ...(action === "RESET" ? { confirmation: "RESET_SYNTHETIC_DEMO" } : {})
      })
    });
  }
}
