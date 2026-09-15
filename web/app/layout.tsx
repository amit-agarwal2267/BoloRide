import type { Metadata } from "next";
import "./globals.css";
import "./demo.css";

export const metadata: Metadata = {
  title: "BoloRide — Book a ride by speaking",
  description: "Explore BoloRide's voice-first ride experience and interactive phone preview.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
