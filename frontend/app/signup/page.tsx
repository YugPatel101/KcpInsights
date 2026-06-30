import Link from "next/link";
import AuthLayout from "@/components/auth/AuthLayout";
import KcpButton from "@/components/common/KcpButton";

export default function SignupPage() {
  return (
    <AuthLayout
      title="Create Account"
      subtitle="Start your IPO research journey with AI-powered insights."
    >
      <form className="space-y-5">

        <div>
          <label className="mb-2 block text-sm font-medium text-slate-300">
            Full Name
          </label>

          <input
            type="text"
            placeholder="John Doe"
            className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-white outline-none transition focus:border-white/30"
          />
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-slate-300">
            Email
          </label>

          <input
            type="email"
            placeholder="you@example.com"
            className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-white outline-none transition focus:border-white/30"
          />
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium text-slate-300">
            Password
          </label>

          <input
            type="password"
            placeholder="••••••••"
            className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-white outline-none transition focus:border-white/30"
          />
        </div>

        <KcpButton className="w-full">
          Create Account
        </KcpButton>

        <p className="text-center text-sm text-slate-400">
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-semibold text-white hover:underline"
          >
            Sign In
          </Link>
        </p>

      </form>
    </AuthLayout>
  );
}