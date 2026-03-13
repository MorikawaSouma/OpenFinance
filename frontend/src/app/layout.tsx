import type { ReactNode } from "react";
import { IBM_Plex_Sans, Noto_Sans_SC, Source_Serif_4 } from "next/font/google";

import { AppShell } from "@/components/layout/app-shell";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { WorkbenchProvider } from "@/components/providers/workbench-provider";
import "./globals.css";

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
  display: "swap",
});

const notoSansSc = Noto_Sans_SC({
  subsets: ["latin"],
  variable: "--font-noto-sc",
  display: "swap",
});

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-display",
  display: "swap",
});

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" translate="no" className="notranslate" suppressHydrationWarning>
      <head>
        <meta name="google" content="notranslate" />
      </head>
      <body className={`${ibmPlexSans.variable} ${notoSansSc.variable} ${sourceSerif.variable}`}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <WorkbenchProvider>
            <AppShell>{children}</AppShell>
          </WorkbenchProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
