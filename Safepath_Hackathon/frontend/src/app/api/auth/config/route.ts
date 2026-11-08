import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Check the actual NextAuth runtime configuration in the FRONTEND container.
 * Never expose credentials or reuse a backend status check for this decision.
 */
export async function GET() {
  const id = process.env.AUTH_GOOGLE_ID || process.env.GOOGLE_CLIENT_ID || "";
  const googleSecret = process.env.AUTH_GOOGLE_SECRET || process.env.GOOGLE_CLIENT_SECRET || "";
  const sessionSecret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET || "";
  const missing = [
    ...(!id.trim() ? ["AUTH_GOOGLE_ID"] : []),
    ...(!googleSecret.trim() ? ["AUTH_GOOGLE_SECRET"] : []),
    ...(!sessionSecret.trim() ? ["AUTH_SECRET"] : []),
  ];
  const configured = missing.length === 0;
  return NextResponse.json(
    {
      status: configured ? "CONFIGURED" : "BLOCKED_CONFIGURATION",
      google_oauth_configured: configured,
      missing_variables: missing,
      callback_url: "/api/auth/callback/google",
    },
    { headers: { "Cache-Control": "private, no-store, max-age=0" } }
  );
}
