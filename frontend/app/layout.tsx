import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible_Next, Newsreader } from "next/font/google";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { ApplicationSessionProvider } from "@/components/providers/application-session-provider";
import { WorkspaceRoot } from "@/components/workspace/workspace-root";
import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

// Reading face: answers, passages, titles. Variable with optical sizing so 28 px titles and 17 px prose both read well.
const newsreader = Newsreader({ subsets: ["latin"], variable: "--font-newsreader", axes: ["opsz"], style: ["normal", "italic"], display: "swap" });
// Interface face: distinct letterforms (I l 1, 0 O) matter for file names.
const atkinson = Atkinson_Hyperlegible_Next({ subsets: ["latin"], variable: "--font-atkinson", display: "swap",
  // next/font has no fallback metrics for this family; say so instead of logging a build error.
  adjustFontFallback: false });

export const metadata: Metadata = {
  title: { default: "DriveMind", template: "%s · DriveMind" },
  description: "Ask questions about the Google Drive documents you choose, with every answer tied to its source.",
};
export const viewport: Viewport = {
  width: "device-width", initialScale: 1, viewportFit: "cover",
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#f3f5f2" }, { media: "(prefers-color-scheme: dark)", color: "#11171e" }],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${newsreader.variable} ${atkinson.variable}`}>
      <body className="h-dvh overflow-hidden">
        <ThemeProvider>
          <ToastProvider>
            <TooltipProvider>
              <ApplicationSessionProvider>
                <WorkspaceRoot>{children}</WorkspaceRoot>
              </ApplicationSessionProvider>
            </TooltipProvider>
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
