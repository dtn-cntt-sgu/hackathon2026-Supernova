import type { Metadata, Viewport } from "next";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};
import "./globals.css";
import "../styles/liquid-glass.css";
import { AuthProvider } from "../context/AuthContext";
import { OnboardingProvider } from "../components/onboarding/OnboardingProvider";
import { OnboardingTour } from "../components/onboarding/OnboardingTour";

export const metadata: Metadata = {
  title: "SafePathAI - Tuyến đường thông minh TP.HCM",
  description:
    "Lộ trình lái xe an toàn thời gian thực dựa trên dữ liệu giao thông, camera và thủy văn tại TP.HCM.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body className="min-h-screen bg-pearl-100 text-ink-900 antialiased selection:bg-indigo-600 selection:text-white">
        <AuthProvider>
          <OnboardingProvider>
            {children}
            <OnboardingTour />
          </OnboardingProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
