"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { label: "Upload & Convert", href: "/",    icon: "⚡" },
  { label: "Documentation",    href: "/docs", icon: "📖" },
  { label: "Login",            href: "#",     icon: "🔐", disabled: true },
];

const STEPS = [
  { icon: "📁", name: "Upload",   desc: "Drop any file type" },
  { icon: "⚙️", name: "Convert",  desc: "Extract Markdown" },
  { icon: "🔍", name: "OCR",      desc: "Text extraction" },
  { icon: "✨", name: "Optimize", desc: "Reduce tokens" },
  { icon: "⬇️", name: "Download", desc: "Get your files" },
];

export default function Sidebar({ health }) {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <div className="sb-section">
        <div className="sb-logo">
          <div className="sb-logo-icon">M</div>
          <span className="sb-logo-name">MarkItDown</span>
        </div>
        <div className="sb-tagline">Convert documents into AI-ready Markdown</div>
        <div className="sb-status">
          <div className="sb-status-item">✓ OCR Ready</div>
          <div className="sb-status-item">✓ Optimization Ready</div>
          <div className="sb-status-item">✓ Smart Chunking Ready</div>
        </div>
      </div>

      <div className="sb-section">
        <div className="sb-label">Navigation</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          {NAV.map(({ label, href, icon, disabled }) =>
            disabled ? (
              <div key={label} className="nav-link disabled" style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 8px", fontSize: 11.5 }}>
                <span>{icon}</span><span>{label}</span>
                <span className="nav-badge" style={{ marginLeft: "auto" }}>SOON</span>
              </div>
            ) : (
              <Link key={label} href={href}
                className={`nav-link${pathname === href ? " active" : ""}`}
                style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 8px", fontSize: 11.5 }}>
                <span>{icon}</span><span>{label}</span>
              </Link>
            )
          )}
        </div>
      </div>

      <div className="sb-section" style={{ flex: 1 }}>
        <div className="sb-label">How It Works</div>
        <div className="sb-steps">
          {STEPS.map(s => (
            <div key={s.name} className="sb-step">
              <span className="sb-step-icon">{s.icon}</span>
              <div>
                <div className="sb-step-name">{s.name}</div>
                <div className="sb-step-desc">{s.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="sb-section">
        <a href="https://github.com/microsoft/markitdown" target="_blank" rel="noopener noreferrer"
          style={{ fontSize: 10.5, color: "var(--text-3)", textDecoration: "none", display: "flex", alignItems: "center", gap: 4 }}>
          ⬡ Powered by Microsoft MarkItDown
        </a>
      </div>
    </aside>
  );
}
