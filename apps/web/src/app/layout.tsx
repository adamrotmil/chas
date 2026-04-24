import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CharlesOps",
  description: "Production asset library and annotation workbench"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
