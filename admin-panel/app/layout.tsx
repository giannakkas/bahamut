import type { Metadata } from "next";
import { QueryProvider } from "@/providers/QueryProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bahamut TICC — Trading Intelligence Control Center",
  description: "AI-driven portfolio intelligence admin panel",
  icons: {
    icon: "/favicon.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        <QueryProvider>
          {children}
          <ToastProvider />
        </QueryProvider>
      </body>
    </html>
  );
}
