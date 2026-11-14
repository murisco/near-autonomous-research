import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MERIDIAN | NEAR Ecosystem Intelligence",
  description: "A public NEAR ecosystem intelligence dashboard for network fundamentals, developer activity, and a transparent evidence-based investment thesis.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
