import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter, Inter_Tight } from "next/font/google";
import { MotionPrefsProvider } from "@/lib/motion";
import "./globals.css";

/* PolySans carries the display type on the site this system was measured from
   and is proprietary; we have no licence. Inter Tight at weight 400 is the
   substitute, because it holds the tight-tracked, light-weight look that is
   the strongest single idea in the palette. Inter carries everything else.
   Only the weights actually used are requested. */
const display = Inter_Tight({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-inter-tight",
  display: "swap",
});

const sans = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-inter",
  display: "swap",
});

/* Kept for one job: an AD number, a paragraph id and a millisecond reading are
   scanned in columns, and proportional digits break the column. */
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
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
    <html
      lang="en"
      data-theme="light"
      data-reduced-motion="false"
      className={`${display.variable} ${sans.variable} ${mono.variable}`}
    >
      <body className="h-full antialiased">
        <MotionPrefsProvider>{children}</MotionPrefsProvider>
      </body>
    </html>
  );
}
