import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { MotionPrefsProvider } from "@/lib/motion";
import "./globals.css";

const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AUTSG - AD answer engine",
  description:
    "Traceable answers to FAA airworthiness directive applicability questions: every sentence cited, every decision made by a rules engine.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" data-reduced-motion="false" className={`${sans.variable} ${mono.variable}`}>
      <body className="h-full antialiased">
        <MotionPrefsProvider>{children}</MotionPrefsProvider>
      </body>
    </html>
  );
}
