import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Incident Investigator",
  description: "Evidence-first payment incident investigation workspace"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>): React.JSX.Element {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
