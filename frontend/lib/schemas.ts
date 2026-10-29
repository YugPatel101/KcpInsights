import { z } from "zod";

// Mirrors backend password rules (app/core/security.py); the server re-validates.
export const loginSchema = z.object({
  email: z.string().trim().email("Enter a valid e-mail"),
  password: z.string().min(1, "Enter your password").max(256),
});
export type LoginInput = z.infer<typeof loginSchema>;

export const registerSchema = z
  .object({
    display_name: z.string().trim().min(1, "Enter your name").max(120),
    email: z.string().trim().email("Enter a valid e-mail"),
    password: z
      .string()
      .min(10, "At least 10 characters")
      .max(256)
      .regex(/[A-Za-z]/, "Include a letter")
      .regex(/[0-9]/, "Include a digit"),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });
export type RegisterInput = z.infer<typeof registerSchema>;

const optNum = (min: number, max: number) =>
  z.preprocess(
    (v) => (v === "" || v === null || v === undefined ? undefined : Number(v)),
    z.number({ message: "Must be a number" }).min(min).max(max).optional(),
  );

export const scenarioOverrideSchema = z.object({
  revenue_growth_pct: optNum(-90, 300),
  ebitda_margin_pct: optNum(-100, 100),
  multiple: optNum(0.01, 500),
  market_adjustment_pct: optNum(-90, 200),
});
export const scenarioFormSchema = z.object({
  bear: scenarioOverrideSchema,
  base: scenarioOverrideSchema,
  bull: scenarioOverrideSchema,
});
export type ScenarioForm = z.input<typeof scenarioFormSchema>;

export const documentUploadSchema = z.object({
  title: z.string().trim().min(3, "At least 3 characters").max(300),
  doc_type: z.enum(["drhp", "rhp", "prospectus", "annual_report", "disclosure", "other"]),
  source_url: z
    .string()
    .trim()
    .max(1000)
    .refine((v) => v === "" || /^https?:\/\//.test(v), "Must start with http:// or https://"),
});
export type DocumentUpload = z.infer<typeof documentUploadSchema>;

/** Strip empty overrides before sending to the API. */
export function compactOverrides(form: z.output<typeof scenarioFormSchema>) {
  const out: Record<string, Record<string, number>> = {};
  for (const [name, o] of Object.entries(form)) {
    const kept = Object.fromEntries(Object.entries(o).filter(([, v]) => typeof v === "number")) as Record<string, number>;
    if (Object.keys(kept).length) out[name] = kept;
  }
  return out;
}
