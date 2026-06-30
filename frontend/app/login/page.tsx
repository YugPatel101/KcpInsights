import Link from "next/link";
import AuthLayout from "@/components/auth/AuthLayout";
import KcpButton from "@/components/common/KcpButton";
import KcpInput from "@/components/common/KcpInput";

export default function LoginPage() {
  return (
    <AuthLayout
      title="Welcome Back"
      subtitle="Sign in to continue your IPO research journey."
    >
      <form className="space-y-5">
        <KcpInput
          label="Email"
          type="email"
          placeholder="you@example.com"
        />

        <KcpInput
          label="Password"
          type="password"
          placeholder="••••••••"
        />

        <div className="flex justify-end">
          <button
            type="button"
            className="text-sm text-slate-400 transition hover:text-white"
          >
            Forgot Password?
          </button>
        </div>

        <div className="pt-2">
          <KcpButton className="w-full">
            Sign In
          </KcpButton>
        </div>

        <p className="text-center text-sm text-slate-400">
          Don&apos;t have an account?{" "}
          <Link
            href="/signup"
            className="font-semibold text-white transition hover:underline"
          >
            Create one
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}