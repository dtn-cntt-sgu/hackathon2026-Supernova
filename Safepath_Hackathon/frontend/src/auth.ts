import { getServerSession, NextAuthOptions } from "next-auth";
import { signedIdentityHeaders } from "./lib/server-identity";
import GoogleProvider from "next-auth/providers/google";

const googleClientId = process.env.AUTH_GOOGLE_ID || process.env.GOOGLE_CLIENT_ID || "";
const googleClientSecret = process.env.AUTH_GOOGLE_SECRET || process.env.GOOGLE_CLIENT_SECRET || "";
const authSecret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET;

if (!authSecret && process.env.NODE_ENV === "production") {
  throw new Error("AUTH_SECRET or NEXTAUTH_SECRET environment variable is strictly required in production.");
}

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: googleClientId,
      clientSecret: googleClientSecret,
    }),
  ],
  secret: authSecret,
  session: {
    strategy: "jwt",
    maxAge: 30 * 24 * 60 * 60, // 30 days
  },
  callbacks: {
    async signIn({ user, account, profile }) {
      if (account?.provider === "google" && user.email && (profile as any)?.email_verified === true) {
        try {
          const backendUrl = process.env.INTERNAL_BACKEND_URL || "http://127.0.0.1:8000";
          const res = await fetch(`${backendUrl}/api/v1/user/sync`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...signedIdentityHeaders(user.email, account.providerAccountId) },
            signal: AbortSignal.timeout(10000),
            body: JSON.stringify({
              provider: "google",
              provider_account_id: account.providerAccountId,
              email: user.email,
              display_name: user.name || "Người dùng Google",
              avatar_url: user.image || null,
            }),
          });
          if (res.ok) {
            const synced = await res.json();
            if (!synced.is_active || !synced.id) return false;
            user.id = synced.id;
            return true;
          }
          console.warn("Google account sync rejected by backend", { status: res.status });
          return false;
        } catch (err) {
          console.warn("Backend user sync on Google sign in failed");
          return false;
        }
      }
      return false;
    },
    async jwt({ token, user, account }) {
      if (user?.id) {
        token.id = user.id;
      }
      if (account?.providerAccountId) {
        token.providerAccountId = account.providerAccountId;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as any).id = token.id || token.sub;
        (session.user as any).providerAccountId = token.providerAccountId;
      }
      return session;
    },
  },
};

export const auth = () => getServerSession(authOptions);


