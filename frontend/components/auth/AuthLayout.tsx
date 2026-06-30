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
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-md rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-xl">

        {/* Logo */}
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-extrabold tracking-tight text-white">
            Kcp<span className="text-slate-400">Insights</span>
          </h1>

          <p className="mt-2 text-sm text-slate-400">
            AI-Powered IPO Intelligence
          </p>
        </div>

        {/* Heading */}
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-white">
            {title}
          </h2>

          <p className="mt-2 text-slate-400">
            {subtitle}
          </p>
        </div>

        {/* Form */}
        {children}

      </div>
    </main>
  );
}