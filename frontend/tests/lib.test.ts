import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, setCsrfToken } from "@/lib/api";
import { MISSING, fmtCr, fmtMetric, fmtPct, fmtScore, priceBand, riskTone, scoreTone } from "@/lib/format";
import { registerSchema, documentUploadSchema } from "@/lib/schemas";

describe("format", () => {
  it("renders missing values explicitly, never as zero", () => {
    expect(fmtCr(null)).toBe(MISSING);
    expect(fmtPct(undefined)).toBe(MISSING);
    expect(fmtScore(Number.NaN)).toBe(MISSING);
    expect(fmtMetric(null, "%")).toBe(MISSING);
    expect(priceBand(null, null)).toBe(MISSING);
  });
  it("formats values", () => {
    expect(fmtPct(12.345, 1, true)).toBe("+12.3%");
    expect(fmtPct(-2, 1, true)).toBe("-2.0%");
    expect(fmtMetric(0.75, "share")).toBe("75%");
    expect(fmtMetric(1.5, "x")).toBe("1.50x");
    expect(fmtCr(1234.5, 1)).toBe("₹1,234.5 cr");
    expect(priceBand(95, 100)).toBe("₹95–100");
  });
  it("assigns tones", () => {
    expect(scoreTone(80)).toContain("pos");
    expect(scoreTone(30)).toContain("warn");
    expect(scoreTone(null)).toContain("ink-3");
    expect(riskTone("high")).toContain("neg");
    expect(riskTone("elevated")).toContain("neg");
    expect(riskTone("low")).toContain("pos");
    expect(riskTone(null)).toContain("ink-3");
  });
  it("formats ratio units without inventing values", () => {
    expect(fmtMetric(29.854, "%")).toBe("29.85%");
    expect(fmtMetric(2.7838, "x")).toBe("2.78x");
    expect(fmtMetric(-0.31, "pp")).toBe("-0.31 pp");
    expect(fmtMetric(undefined, "x")).toBe(MISSING);
  });
});

describe("schemas", () => {
  it("enforces password rules and confirmation", () => {
    const base = { display_name: "A", email: "a@example.com", password: "abcdefghij1", confirm: "abcdefghij1" };
    expect(registerSchema.safeParse(base).success).toBe(true);
    expect(registerSchema.safeParse({ ...base, password: "short1", confirm: "short1" }).success).toBe(false);
    expect(registerSchema.safeParse({ ...base, password: "onlyletterslong", confirm: "onlyletterslong" }).success).toBe(false);
    expect(registerSchema.safeParse({ ...base, confirm: "different1x" }).success).toBe(false);
  });
  it("validates document source URLs", () => {
    expect(documentUploadSchema.safeParse({ title: "RHP", doc_type: "rhp", source_url: "javascript:alert(1)" }).success).toBe(false);
    expect(documentUploadSchema.safeParse({ title: "RHP", doc_type: "rhp", source_url: "" }).success).toBe(true);
  });
});

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken(null);
  });

  it("sends the CSRF token on unsafe methods only", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("tok");
    await api("/api/x");
    await api("/api/y", { body: { a: 1 } });
    expect(fetchMock.mock.calls[0][1].headers["X-CSRF-Token"]).toBeUndefined();
    expect(fetchMock.mock.calls[1][1].headers["X-CSRF-Token"]).toBe("tok");
    expect(fetchMock.mock.calls[1][1].method).toBe("POST");
  });

  it("maps the error envelope to ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "not_found", message: "IPO not found" } }), { status: 404 })));
    await expect(api("/api/ipos/9")).rejects.toMatchObject({ status: 404, code: "not_found", message: "IPO not found" });
  });

  it("reports an unreachable backend clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const err = await api("/api/health").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(errorMessage(err)).toMatch(/backend/i);
  });

  it("handles 204 and proxy 5xx without a body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api("/api/x", { method: "DELETE" })).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Internal Server Error", { status: 500 })));
    await expect(api("/api/x")).rejects.toMatchObject({ code: "backend_unavailable" });
  });
});

describe("API timestamps", () => {
  it("reads a naive API timestamp as UTC (regression: shown 5.5 h off in IST)", async () => {
    const { parseApiTime } = await import("@/lib/format");
    expect(parseApiTime("2026-10-31T15:40:17").toISOString()).toBe("2026-10-31T15:40:17.000Z");
    expect(parseApiTime("2026-10-31T15:40:17.123456").getUTCHours()).toBe(15);
    expect(parseApiTime("2026-10-31T15:40:17+05:30").toISOString()).toBe("2026-10-31T10:10:17.000Z");
    expect(parseApiTime("2026-10-31T15:40:17Z").toISOString()).toBe("2026-10-31T15:40:17.000Z");
  });
});
