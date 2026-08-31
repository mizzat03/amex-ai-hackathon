import type { components } from "@/generated/api-types";

type Api = components["schemas"];

export type CopilotContent = Api["CopilotMessage"]["content"];

export function isCopilotAnswer(content: CopilotContent): content is Api["CopilotAnswerContent"] {
  return content.type === "COPILOT_ANSWER";
}

export function isUserQuestion(content: CopilotContent): content is Api["UserQuestionContent"] {
  return content.type === "USER_QUESTION";
}

export function isFallback(content: CopilotContent): content is Api["DeterministicFallbackContent"] {
  return content.type === "DETERMINISTIC_FALLBACK";
}

export function isEvidenceNotice(content: CopilotContent): content is Api["EvidenceVersionNoticeContent"] {
  return content.type === "EVIDENCE_VERSION_NOTICE";
}

export function isLifecycleNotice(content: CopilotContent): content is Api["LifecycleNoticeContent"] {
  return content.type === "LIFECYCLE_NOTICE";
}

export function confidenceLabel(confidence: Api["CopilotAnswerContent"]["confidence"]): string {
  return {
    LOW: "Low confidence",
    MODERATE: "Moderate confidence",
    HIGH: "High confidence",
  }[confidence];
}

export function progressLabel(stage: Api["CopilotInteractionView"]["progress_stage"]): string {
  if (!stage || stage === "QUEUED") return "Request accepted";
  return {
    ANALYSING_EVIDENCE: "Analysing evidence",
    COMPARING_HYPOTHESES: "Comparing hypotheses",
    CHECKING_RUNBOOKS: "Checking approved guidance",
    VALIDATING_CITATIONS: "Validating citations",
    PREPARING_RESPONSE: "Preparing response",
  }[stage];
}
