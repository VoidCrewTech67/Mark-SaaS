"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();
  return (
    <nav className="navbar">
      <div className="nav-logo">
        <div className="nav-logo-icon">M</div>
        <span className="nav-logo-name">MarkItDown</span>
      </div>
      <div className="nav-sep" />
      <Link href="/" className={`nav-link${pathname === "/" ? " active" : ""}`}>
        ⚡ Upload &amp; Convert
      </Link>
      <Link href="/docs" className={`nav-link${pathname === "/docs" ? " active" : ""}`}>
        📖 Documentation
      </Link>
      <div className="nav-spacer" />
      <a href="https://github.com/microsoft/markitdown" target="_blank" rel="noopener noreferrer" className="nav-link">
        ⬡ Source
      </a>
      <div className="nav-sep" />
      <span className="nav-link disabled">
        🔐 Login<span className="nav-badge">SOON</span>
      </span>
    </nav>
  );
}
