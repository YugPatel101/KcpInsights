import Link from "next/link";
import AuroraBackground from "@/components/common/AuroraBackground";

interface AuthLayoutProps {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}

export default function AuthLayout({
  title,
  subtitle,
  children,
}: AuthLayoutProps) {
  return (
    <>
      <AuroraBackground />
      <main id="main" className="relative z-10 flex min-h-screen items-center justify-center px-6 py-12">
        <div className="w-full max-w-md rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl">

          {/* Logo */}
          <div className="mb-8 text-center">
            <Link href="/" className="text-3xl font-extrabold tracking-tight text-white">
              Kcp<span className="text-slate-400">Insights</span>
            </Link>

            <p className="mt-2 text-sm text-slate-400">
              Educational IPO research
            </p>
          </div>

          {/* Heading */}
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-white">
              {title}
            </h1>

            <p className="mt-2 text-slate-400">
              {subtitle}
            </p>
          </div>

          {/* Form */}
          {children}

        </div>
      </main>
    </>
  );
}
