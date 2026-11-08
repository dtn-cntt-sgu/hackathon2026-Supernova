import { NextResponse } from "next/server";
import { signedIdentityHeaders, signedClientHeaders } from "@/lib/server-identity";
import { auth } from "@/auth";
import { isSameOriginMutation } from "@/lib/request-origin";
import { isIP } from "node:net";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

const FORWARD_HEADERS = [
  "accept", "content-type", "authorization", "x-user-token",
  "if-none-match", "if-modified-since", "range", "x-request-id",
];
const HOP_HEADERS = [
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailers", "transfer-encoding", "upgrade",
];

async function forward(request: Request, { params }: RouteContext): Promise<Response> {
  const { path } = await params;
  const backend = process.env.INTERNAL_BACKEND_URL || process.env.BACKEND_URL ||
    (process.env.NODE_ENV !== "production" ? "http://127.0.0.1:8000" : "");

  if (!backend) {
    return NextResponse.json(
      { detail: "INTERNAL_BACKEND_URL is not configured on the frontend server" },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  let target: URL;
  try {
    target = new URL(backend);
    if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) {
      throw new Error("Invalid backend origin");
    }
    const safePath = path.map((part) => encodeURIComponent(part)).join("/");
    target.pathname = `${target.pathname.replace(/\/$/, "")}/api/v1/${safePath}`;
    target.search = new URL(request.url).search;
  } catch {
    return NextResponse.json({ detail: "Invalid INTERNAL_BACKEND_URL configuration" }, { status: 503 });
  }

  const headers = new Headers();
  FORWARD_HEADERS.forEach((key) => {
    const value = request.headers.get(key);
    if (value !== null) headers.set(key, value);
  });

  // Production frontend has no published port; Caddy replaces untrusted forwarded headers.
  const address = request.headers.get("x-forwarded-for")?.split(",").at(-1)?.trim();
  if (address && isIP(address)) Object.entries(signedClientHeaders(address)).forEach(([key, value]) => headers.set(key, value));
  const joinedPath = path.join("/");
  if (joinedPath.startsWith("user/")) {
    const session = await auth();
    const hasBearerOrToken = Boolean(
      request.headers.get("authorization") || request.headers.get("x-user-token")
    );
    if (session?.user?.email) {
      if (!["GET", "HEAD", "OPTIONS"].includes(request.method) && !hasBearerOrToken &&
          !isSameOriginMutation(request.headers.get("origin"), process.env.NEXTAUTH_URL, request.url)) {
        return NextResponse.json({ detail: { code: "CSRF_ORIGIN_MISMATCH" } }, { status: 403 });
      }
      const email = session.user.email.toLowerCase().trim();
      const providerAccountId = String(
        (session.user as any).providerAccountId || (session.user as any).id || email
      );
      try {
        Object.entries(signedIdentityHeaders(email, providerAccountId)).forEach(([key, value]) => headers.set(key, value));
      } catch {
        return NextResponse.json({ detail: "Identity signing is unavailable" }, { status: 503 });
      }

      const clientUserId = request.headers.get("x-user-id");
      if (clientUserId) {
        headers.set("X-User-Id", clientUserId);
      }
    } else if (!hasBearerOrToken) {
      return NextResponse.json(
        {
          detail: {
            code: "UNAUTHORIZED",
            message: "Authenticated session required for /api/v1/user/* endpoints.",
          },
        },
        { status: 401, headers: { "Cache-Control": "no-store" } }
      );
    } else {
      const clientUserId = request.headers.get("x-user-id");
      if (clientUserId) {
        headers.set("X-User-Id", clientUserId);
      }
    }
  }

  let body: Uint8Array | undefined;
  if (request.method !== "GET" && request.method !== "HEAD" && request.body) {
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let length = 0;
    let timedOut = false;
    const bodyTimeout = setTimeout(() => { timedOut = true; void reader.cancel(); }, 10000);
    try {
      while (true) {
        const result = await reader.read();
        if (result.done) break;
        length += result.value.byteLength;
        if (length > 262144) {
          await reader.cancel();
          return NextResponse.json({ detail: "Request body too large" }, { status: 413 });
        }
        chunks.push(result.value);
      }
      if (timedOut) return NextResponse.json({ detail: "Request body timed out" }, { status: 408 });
      body = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    } finally { clearTimeout(bodyTimeout); reader.releaseLock(); }
  }
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: body as BodyInit | undefined,
      signal: AbortSignal.timeout(30000),
      redirect: "manual",
      cache: "no-store",
    });
    const responseHeaders = new Headers(upstream.headers);
    HOP_HEADERS.forEach((key) => responseHeaders.delete(key));
    // The browser must not receive a backend's internal redirect Location.
    const location = responseHeaders.get("location");
    if (location && location.startsWith(backend)) {
      responseHeaders.set("location", location.replace(backend, ""));
    }
    return new Response(
      upstream.status === 204 || upstream.status === 304 || request.method === "HEAD"
        ? null : upstream.body,
      { status: upstream.status, headers: responseHeaders }
    );
  } catch (error) {
    console.error("[api/v1 proxy] Backend request failed:", error instanceof Error ? error.message : "unknown");
    return NextResponse.json(
      { detail: "Backend temporarily unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const HEAD = forward;
