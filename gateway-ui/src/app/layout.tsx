import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AIGateway-X",
  description: "Bramka AI: routing modeli, limity tokenów i koszty per agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl">
      <body className="min-h-screen font-sans antialiased">{children}</body>
    </html>
  );
}
