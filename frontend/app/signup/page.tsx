"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import AuthLayout from "@/components/auth/AuthLayout";
import KcpButton from "@/components/common/KcpButton";
import KcpInput from "@/components/common/KcpInput";
import { ErrorState } from "@/components/kcp/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { registerSchema, type RegisterInput } from "@/lib/schemas";

export default function SignupPage() {
  const { register: signUp } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<RegisterInput>({ resolver: zodResolver(registerSchema) });
  const e = formState.errors;

  return (
    <AuthLayout title="Create Account" subtitle="Accounts are stored locally in your KcpInsights database.">
      <form
        className="space-y-5"
        noValidate
        onSubmit={handleSubmit(async (v) => {
          setError(null);
          try {
            await signUp(v.display_name, v.email, v.password);
            router.push("/dashboard");
          } catch (err) {
            setError(errorMessage(err));
          }
        })}
      >
        {error && <ErrorState message={error} />}
        <KcpInput label="Full Name" autoComplete="name" placeholder="Your name" error={e.display_name?.message} {...register("display_name")} />
        <KcpInput label="Email" type="email" autoComplete="email" placeholder="you@example.com" error={e.email?.message} {...register("email")} />
        <KcpInput label="Password" type="password" autoComplete="new-password" placeholder="At least 10 characters" error={e.password?.message} {...register("password")} />
        <KcpInput label="Confirm password" type="password" autoComplete="new-password" placeholder="Repeat password" error={e.confirm?.message} {...register("confirm")} />

        <KcpButton className="w-full" type="submit" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? "Creating…" : "Create Account"}
        </KcpButton>

        <p className="text-center text-sm text-slate-400">
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-white hover:underline">
            Sign In
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}
