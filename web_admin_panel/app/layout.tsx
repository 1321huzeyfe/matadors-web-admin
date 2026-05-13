import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MatadorsApp Yönetici Paneli",
  description: "MatadorsApp read-only Supabase yönetici paneli"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}
