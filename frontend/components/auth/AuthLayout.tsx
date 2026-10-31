import Link from "next/link";

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
      <main id="main" className="relative z-10 flex min-h-screen items-center justify-center bg-canvas px-4 py-12">
        <div className="w-full max-w-md rounded-xl border border-line bg-surface p-7">

          {/* Logo */}
          <div className="mb-8 text-center">
            <Link href="/" className="text-2xl font-semibold tracking-tight text-ink">
              Kcp<span className="text-brand-ink">Insights</span>
            </Link>

            <p className="mt-2 text-sm text-ink-2">
              Educational IPO research
            </p>
          </div>

          {/* Heading */}
          <div className="mb-8">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">
              {title}
            </h1>

            <p className="mt-2 text-ink-2">
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
