import { HttpInvestigatorRepository, InvestigatorApiError } from "@/data/repositories/http-investigator-repository";
import { createLiveSubscription } from "@/data/repositories/live-updates";

class FakeSocket {
  readonly listeners = new Map<string, Array<(event: { data?: string }) => void>>();
  closed = false;

  addEventListener(type: string, listener: (event: { data?: string }) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  emit(type: string, data?: string): void {
    const event = data === undefined ? {} : { data };
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }

  close(): void {
    this.closed = true;
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("defaults browser requests to the dedicated local API port", () => {
  expect(new HttpInvestigatorRepository().baseUrl).toBe("http://127.0.0.1:8100/api/v1");
});

it("builds encoded no-store requests and preserves the safe API error envelope", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "VERSION_CONFLICT", message: "Refresh first", retryable: false, details: [] } }), { status: 409 }));
  const repository = new HttpInvestigatorRepository("http://127.0.0.1:8000/api/v1/");

  await expect(repository.listIncidents({ severity: ["HIGH"], processingRegion: ["SG"] })).resolves.toEqual({ items: [], next_cursor: null });
  expect(String(fetchMock.mock.calls[0]?.[0])).toContain("severity=HIGH&processing_region=SG");
  expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ cache: "no-store" });

  await expect(repository.updateHumanReview("INC / 1", { hypothesis_id: "HYP-1", status: "ACKNOWLEDGED", note: null, expected_version: 1 }))
    .rejects.toMatchObject({ status: 409, code: "VERSION_CONFLICT", retryable: false } satisfies Partial<InvestigatorApiError>);
  expect(String(fetchMock.mock.calls[1]?.[0])).toContain("INC%20%2F%201/human-review");
});

it("maps live events, detects sequence gaps, and closes only its own socket", () => {
  const socket = new FakeSocket();
  const invalidations: string[] = [];
  const states: string[] = [];
  const subscription = createLiveSubscription({
    apiBaseUrl: "https://investigator.test/api/v1",
    onInvalidate: (event) => invalidations.push(event.resource),
    onState: (state) => states.push(state.status),
    socketFactory: (url) => {
      expect(url).toBe("wss://investigator.test/api/v1/ws/updates");
      return socket as unknown as WebSocket;
    }
  });

  socket.emit("open");
  socket.emit("message", JSON.stringify({ event_type: "evidence.package.created", sequence: 4, payload: {} }));
  socket.emit("message", JSON.stringify({ event_type: "human_review.updated", sequence: 6, payload: {} }));

  expect(states).toContain("connected");
  expect(invalidations).toEqual(["evidence", "all", "review"]);
  subscription.close();
  expect(socket.closed).toBe(true);
});
