import { afterEach, describe, expect, it, vi } from "vitest";
import { timeAgo } from "@/lib/time";
import { fetchShared } from "@/lib/useApi";

describe("timeAgo", () => {
  const now = Date.parse("2026-10-29T12:00:00Z");
  it("treats API timestamps as UTC and formats relative time", () => {
    expect(timeAgo("2026-10-29T11:55:00", now)).toBe("5 min ago");
    expect(timeAgo("2026-10-29T09:00:00", now)).toBe("3 h ago");
    expect(timeAgo("2026-10-27T12:00:00", now)).toBe("2 d ago");
    expect(timeAgo(null, now)).toBe("never");
    expect(timeAgo("garbage", now)).toBe("unknown");
  });
});

describe("polling fetches", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shares one in-flight request between concurrent pollers of the same URL", async () => {
    let resolve: (r: Response) => void = () => {};
    const fetchMock = vi.fn().mockImplementation(() => new Promise<Response>((r) => (resolve = r)));
    vi.stubGlobal("fetch", fetchMock);
    const a = fetchShared<{ n: number }>("/api/market/overview");
    const b = fetchShared<{ n: number }>("/api/market/overview");
    resolve(new Response(JSON.stringify({ n: 1 }), { status: 200 }));
    expect(await a).toEqual({ n: 1 });
    expect(await b).toEqual({ n: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("revalidates GETs with ETags instead of bypassing the cache", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await fetchShared("/api/data/freshness");
    expect(fetchMock.mock.calls[0][1].cache).toBe("no-cache");
  });
});
