/**
 * The headers every page of the web application is served with (`next.config.ts`).
 *
 * The content security policy bounds what a script that found its way into a page could do. It
 * could reach no address but the site's own and the API's (`connect-src`), and load no image,
 * font or object from elsewhere. That keeps the refresh token kept in the page's storage
 * (ADR-0027) from being sent anywhere else. Scripts may be inline, as the pages Next.js renders
 * start with inline scripts of their own; a nonce on each would make every page dynamic.
 * Development adds `'unsafe-eval'`, which its refreshing needs. A PDF being read is shown in an
 * `<object>` from a `blob:` address, and a picture from one too. No other site may frame a page
 * (`frame-ancestors`, `X-Frame-Options` for older browsers), so none can be laid under a page
 * that has a person press a button unawares: the consent an MCP client asks for least of all
 * (RFC 9700 §4.16). No page sends its address on, which may hold an invitation's code or an
 * authorization's parameters (`Referrer-Policy`). No page uses a camera, a microphone, a
 * position or a payment (`Permissions-Policy`).
 */
export function securityHeaders(
  api: string,
  development: boolean,
): { key: string; value: string }[] {
  const policy = [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${development ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self' ${new URL(api).origin}`,
    "object-src blob:",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
  return [
    { key: "Content-Security-Policy", value: policy },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "no-referrer" },
    {
      key: "Permissions-Policy",
      value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    },
  ];
}
