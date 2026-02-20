import type { ReactNode } from "react";
import { Inter, Noto_Sans_SC } from "next/font/google";

import { AppShell } from "@/components/layout/app-shell";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { WorkbenchProvider } from "@/components/providers/workbench-provider";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const notoSansSc = Noto_Sans_SC({
  subsets: ["latin"],
  variable: "--font-noto-sc",
  display: "swap",
});

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${notoSansSc.variable}`}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <WorkbenchProvider>
            <AppShell>{children}</AppShell>
          </WorkbenchProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
