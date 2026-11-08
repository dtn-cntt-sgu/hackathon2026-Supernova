import crypto from "node:crypto";

/** Only call from trusted server code after OAuth session validation. */
export function signedIdentityHeaders(email: string, providerAccountId: string) {
  const secret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET;
  if (!secret) throw new Error("Server identity signing secret is not configured");
  const normalizedEmail = email.toLowerCase().trim();
  const timestamp = String(Math.floor(Date.now() / 1000));
  return {
    "X-Auth-User-Email": normalizedEmail,
    "X-Auth-Provider-Id": providerAccountId,
    "X-Auth-Timestamp": timestamp,
    "X-Auth-Signature": crypto.createHmac("sha256", secret)
      .update(`${normalizedEmail}:${providerAccountId}:${timestamp}`).digest("hex"),
  };
}

export function signedClientHeaders(address: string) {
  const secret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET;
  if (!secret) return {};
  const timestamp = String(Math.floor(Date.now() / 1000));
  return { "X-Proxy-Client-IP": address, "X-Proxy-Timestamp": timestamp,
    "X-Proxy-Signature": crypto.createHmac("sha256", secret).update(`client:${address}:${timestamp}`).digest("hex") };
}
