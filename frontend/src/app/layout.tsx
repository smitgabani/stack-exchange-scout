import type { Metadata } from "next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import { Archivo, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthGate } from "./auth-gate";
import { Providers } from "./providers";

// Archivo is what all nine design mockups specify as the stand-in for
// design.md's Haas Grotesk; weights limited to the 400/500/600 they use.
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Stack Exchange Scout",
  description: "Stack Overflow questions, turned into coding challenges.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${archivo.variable} ${geistMono.variable}`}>
      <body>
        <Providers>
          <AuthGate>{children}</AuthGate>
        </Providers>
        <SpeedInsights />
      </body>
    </html>
  );
}
