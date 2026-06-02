import "./globals.css";

export const metadata = {
  title: "MarkItDown — Convert Documents to AI-Ready Markdown",
  description: "Convert any document into AI-ready Markdown with OCR, token optimization, and smart chunking.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head />
      <body>{children}</body>
    </html>
  );
}
