import type { Metadata } from "next";
import "./globals.css";
import AppHeader from "@/components/AppHeader";

export const metadata: Metadata = {
  title: "SAGE",
  description: "SE Adaptive Growth Engine",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col"><AppHeader />{children}</body>
    </html>
  );
}
