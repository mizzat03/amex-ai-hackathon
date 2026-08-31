import type { ConnectionState } from "@/data/repositories/investigator-repository";

export type LiveResource = "overview" | "incidents" | "evidence" | "copilot" | "review" | "simulation" | "all";

export interface LiveInvalidation {
  readonly resource: LiveResource;
  readonly payload: Readonly<Record<string, unknown>>;
}

export interface LiveSubscription {
  close(): void;
}

interface WsEnvelope {
  readonly event_type: string;
  readonly sequence: number;
  readonly payload: Record<string, unknown>;
}

const resourceByEvent: Readonly<Record<string, LiveResource>> = {
  "system.overview.updated": "overview",
  "baseline.readiness.updated": "overview",
  "incident.lifecycle.changed": "incidents",
  "incident.updated": "incidents",
  "evidence.package.created": "evidence",
  "copilot.progress.updated": "copilot",
  "copilot.message.validated": "copilot",
  "copilot.fallback.ready": "copilot",
  "human_review.updated": "review",
  "simulation.status.changed": "simulation"
};

export function createLiveSubscription(options: {
  readonly apiBaseUrl: string;
  readonly onInvalidate: (event: LiveInvalidation) => void;
  readonly onState: (state: ConnectionState) => void;
  readonly socketFactory?: (url: string) => WebSocket;
}): LiveSubscription {
  const socketFactory = options.socketFactory ?? ((url: string) => new WebSocket(url));
  const parsed = new URL(options.apiBaseUrl);
  parsed.protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
  parsed.pathname = `${parsed.pathname.replace(/\/$/, "")}/ws/updates`;
  let socket: WebSocket | null = null;
  let closed = false;
  let lastSequence = 0;
  let reconnectAttempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function connect(): void {
    if (closed) return;
    options.onState({ status: reconnectAttempt ? "reconnecting" : "disconnected", lastSequence });
    socket = socketFactory(parsed.toString());
    socket.addEventListener("open", () => {
      reconnectAttempt = 0;
      options.onState({ status: "connected", lastSequence });
      if (lastSequence > 0) options.onInvalidate({ resource: "all", payload: {} });
    });
    socket.addEventListener("message", (message) => {
      let envelope: WsEnvelope;
      try {
        envelope = JSON.parse(String(message.data)) as WsEnvelope;
      } catch {
        options.onInvalidate({ resource: "all", payload: {} });
        return;
      }
      if (lastSequence > 0 && envelope.sequence !== lastSequence + 1) {
        options.onInvalidate({ resource: "all", payload: envelope.payload });
      }
      lastSequence = envelope.sequence;
      options.onState({ status: "connected", lastSequence });
      options.onInvalidate({
        resource: resourceByEvent[envelope.event_type] ?? "all",
        payload: envelope.payload
      });
    });
    socket.addEventListener("close", () => {
      if (closed) return;
      reconnectAttempt += 1;
      options.onState({ status: "reconnecting", lastSequence });
      reconnectTimer = setTimeout(connect, Math.min(1000 * 2 ** reconnectAttempt, 10_000));
    });
    socket.addEventListener("error", () => socket?.close());
  }

  connect();
  return {
    close(): void {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    }
  };
}
