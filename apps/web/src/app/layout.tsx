import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SEF Kopilot",
  description:
    "Deterministička validacija, objašnjenja i pregledne ispravke elektronskih faktura (SEF, EN 16931, Peppol).",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  // The UI language switch (sr-Latn / en) arrives with next-intl in M3;
  // until then the shell is Serbian (Latin) with an English subtitle.
  return (
    <html lang="sr-Latn" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
