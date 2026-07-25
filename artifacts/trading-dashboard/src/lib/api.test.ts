import { describe, it, expect, vi, afterEach } from "vitest";
import { apiJson, ApiError, API_BASE } from "./api";

function mockFetch(body: string, init: { status?: number; contentType?: string } = {}) {
  const { status = 200, contentType = "application/json" } = init;
  const res = new Response(body, {
    status,
    headers: { "content-type": contentType },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API_BASE", () => {
  it("points at the root-mounted API, not the SPA base path", () => {
    expect(API_BASE).toBe("/api");
    expect(API_BASE.startsWith("/trading-dashboard")).toBe(false);
  });
});

describe("apiJson", () => {
  it("parses valid JSON responses", async () => {
    mockFetch(JSON.stringify({ ok: true, id: "abc123", status: "queued" }));
    const data = await apiJson("/experiments", { method: "POST" });
    expect(data.id).toBe("abc123");
    expect(data.status).toBe("queued");
  });

  it("throws a clear ApiError on empty body instead of 'Unexpected end of JSON input'", async () => {
    mockFetch("", { status: 500 });
    const err = await apiJson("/experiments").catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toContain("empty response");
    expect(err.message).toContain("HTTP 500");
    expect(err.message).not.toContain("Unexpected end of JSON input");
  });

  it("returns {} for an empty body on a successful response", async () => {
    mockFetch("", { status: 200 });
    await expect(apiJson("/experiments")).resolves.toEqual({});
  });

  it("detects HTML responses (SPA fallback) and reports misrouting", async () => {
    mockFetch("<!DOCTYPE html>\n<html><head></head><body></body></html>", {
      contentType: "text/html",
    });
    const err = await apiJson("/experiments/export/csv").catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toContain("HTML");
    expect(err.message).toContain("misrouted");
  });

  it("detects HTML even when content-type lies", async () => {
    mockFetch("  <html><body>error page</body></html>", {
      contentType: "application/json",
    });
    const err = await apiJson("/batches").catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toContain("HTML");
  });

  it("throws with a body snippet on invalid JSON", async () => {
    mockFetch("this is not json at all");
    const err = await apiJson("/experiments").catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toContain("Invalid JSON");
    expect(err.message).toContain("this is not json");
  });

  it("surfaces backend error messages with status context", async () => {
    mockFetch(JSON.stringify({ error: "Duplicate experiment config" }), { status: 409 });
    const err = await apiJson("/experiments", { method: "POST" }).catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("Duplicate experiment config");
    expect(err.status).toBe(409);
  });

  it("surfaces backend error field even on HTTP 200", async () => {
    mockFetch(JSON.stringify({ error: "name required" }), { status: 200 });
    const err = await apiJson("/experiments", { method: "POST" }).catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("name required");
  });

  it("wraps network failures in ApiError with endpoint context", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await apiJson("/experiments").catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.endpoint).toBe("/api/experiments");
  });

  it("prefixes paths with API_BASE and attaches an AbortController signal", async () => {
    mockFetch(JSON.stringify({ ok: true }));
    await apiJson("/experiments/leaderboard");
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    // The second argument now always contains a signal (AbortController timeout).
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/experiments/leaderboard",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
});
