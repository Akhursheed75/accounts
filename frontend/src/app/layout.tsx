import type { Metadata, Viewport } from "next";

import { ConditionalShell } from "@/components/conditional-shell";
import { ToastProvider } from "@/components/ui";
import { AuthProvider } from "@/lib/auth";
import { THEME_BOOTSTRAP_SCRIPT, ThemeProvider } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "Reconcilia — shop accounting and bank reconciliation",
  description:
    "Daily shop accounting, bank statement processing and automatic payment reconciliation.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#090d19" },
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The bootstrap script below sets data-theme before React hydrates, which
    // is a deliberate mismatch with the server-rendered markup.
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <AuthProvider>
            <ToastProvider>
              <ConditionalShell>{children}</ConditionalShell>
            </ToastProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
