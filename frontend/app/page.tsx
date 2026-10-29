import Hero from "@/components/home/Hero";
import DashboardPreview from "@/components/home/DashboardPreview";
import Navbar from "@/components/layout/Navbar";
import AuroraBackground from "@/components/common/AuroraBackground";

export default function Home() {
  return (
    <>
      <AuroraBackground />
      <div className="relative z-10">
        <Navbar />
        <main id="main">
          <Hero />
          <DashboardPreview />
        </main>
      </div>
    </>
  );
}
