/** Compare against the public origin because Next may normalize its internal request host. */
export function isSameOriginMutation(origin: string | null, publicUrl: string | undefined, requestUrl: string): boolean {
  if (!origin) return false;
  try {
    const expected = new URL(publicUrl || requestUrl);
    const supplied = new URL(origin);
    return ["http:", "https:"].includes(supplied.protocol) && supplied.origin === expected.origin;
  } catch { return false; }
}
