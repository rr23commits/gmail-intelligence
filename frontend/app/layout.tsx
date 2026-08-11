import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./styles.css";
import "./layout-overrides.css";
import { Shell } from "./shell";

export const metadata: Metadata = {
  title: "Gmail Intelligence",
  description: "Personal Gmail intelligence system",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
