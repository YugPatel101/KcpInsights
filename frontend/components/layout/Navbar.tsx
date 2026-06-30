import KcpButton from "@/components/common/KcpButton";

const navLinks = [
  { name: "Features", href: "#" },
  { name: "IPOs", href: "#" },
  { name: "Dashboard", href: "#" },
  { name: "About", href: "#" },
];

export default function Navbar() {
  return (
    <nav className="sticky top-0 z-50 border-b border-white/10 bg-black/80 backdrop-blur-xl">
      <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-10">

        {/* Logo */}
        <div className="cursor-pointer">
          <h1 className="text-4xl font-extrabold tracking-tight text-white">
            Kcp<span className="text-slate-400">Insights</span>
          </h1>
        </div>

        {/* Navigation */}
        <div className="hidden items-center gap-14 lg:flex">
          {navLinks.map((link) => (
            <a
              key={link.name}
              href={link.href}
              className="group relative text-[16px] font-semibold tracking-wide text-slate-300 transition-all duration-300 hover:text-white"
            >
              {link.name}

              <span className="absolute -bottom-2 left-0 h-[2px] w-0 bg-white transition-all duration-300 group-hover:w-full"></span>
            </a>
          ))}
        </div>

        {/* CTA */}
        <KcpButton>
          Sign In
        </KcpButton>

      </div>
    </nav>
  );
}