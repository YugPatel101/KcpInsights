import type { Metadata } from "next";
// Self-hosted font files (no network fetch at build or dev time — the app works offline).
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: { default: "KcpInsights", template: "%s · KcpInsights" },
  description: "Educational IPO research platform: automated IPO data, prospectus financials and transparent quantitative scoring.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`dark ${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="relative min-h-screen overflow-x-hidden bg-canvas text-ink">
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-brand focus:px-3 focus:py-2 focus:text-ink">
          Skip to content
        </a>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
