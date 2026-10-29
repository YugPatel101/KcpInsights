"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import AuthLayout from "@/components/auth/AuthLayout";
import KcpButton from "@/components/common/KcpButton";
import KcpInput from "@/components/common/KcpInput";
import { ErrorState } from "@/components/kcp/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { loginSchema, type LoginInput } from "@/lib/schemas";

function safeNext(n: string | null): string {
  // only allow same-site relative paths (prevents open redirects)
  return n && n.startsWith("/") && !n.startsWith("//") ? n : "/dashboard";
}

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<LoginInput>({ resolver: zodResolver(loginSchema) });

  return (
    <form
      className="space-y-5"
      noValidate
      onSubmit={handleSubmit(async (v) => {
        setError(null);
        try {
          await login(v.email, v.password);
          router.push(safeNext(params.get("next")));
        } catch (e) {
          setError(errorMessage(e));
        }
      })}
    >
      {error && <ErrorState message={error} />}
      <KcpInput label="Email" type="email" autoComplete="email" placeholder="you@example.com" error={formState.errors.email?.message} {...register("email")} />
      <KcpInput label="Password" type="password" autoComplete="current-password" placeholder="••••••••" error={formState.errors.password?.message} {...register("password")} />

      <p className="text-xs text-slate-500">
        Forgot your password? Self-hosted installs have no e-mail service; an administrator can reset it with the CLI (see README).
      </p>

      <div className="pt-2">
        <KcpButton className="w-full" type="submit" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? "Signing in…" : "Sign In"}
        </KcpButton>
      </div>

      <p className="text-center text-sm text-slate-400">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="font-semibold text-white transition hover:underline">
          Create one
        </Link>
      </p>
      <p className="text-center text-xs text-slate-500">
        <Link href="/ipos" className="hover:text-slate-300">Continue without an account</Link> — browsing and scores work signed out.
      </p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <AuthLayout title="Welcome Back" subtitle="Sign in to keep your watchlist, reports and research conversations.">
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthLayout>
  );
}
