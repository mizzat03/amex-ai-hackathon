/** Convenience aliases only; the OpenAPI-generated file remains authoritative. */
import type { components } from "@/generated/api-types";

export type ApiSchemas = components["schemas"];
export type SystemOverview = ApiSchemas["SystemOverviewResponse"];
export type IncidentWorkspace = ApiSchemas["IncidentWorkspaceResponse"];
export type EvidenceProjection = ApiSchemas["EvidenceProjectionResponse"];
export type ValidatedCopilotMessage = ApiSchemas["ValidatedCopilotMessage"];
