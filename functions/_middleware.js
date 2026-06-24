const ADMIN_USER = "admin";
const ADMIN_PASSWORD = "Www54589";

function needsAuth(pathname, method) {
  if (pathname === "/admin" || pathname.startsWith("/admin/")) return true;
  if (pathname === "/api/save") return true;
  if (pathname === "/api/update-clock") return true;
  if (pathname === "/api/patch-mygadget") return true;
  if (pathname === "/api/refresh-row-price") return true;
  if (pathname === "/api/download-xlsx" && method !== "GET") return true;
  return false;
}

function unauthorized() {
  return new Response("Authentication required", {
    status: 401,
    headers: {
      "www-authenticate": 'Basic realm="Price Compare Admin", charset="UTF-8"',
      "cache-control": "no-store",
    },
  });
}

function decodeBasicAuth(header) {
  if (!header || !header.startsWith("Basic ")) return null;
  try {
    const decoded = atob(header.slice(6));
    const separator = decoded.indexOf(":");
    if (separator === -1) return null;
    return {
      user: decoded.slice(0, separator),
      password: decoded.slice(separator + 1),
    };
  } catch {
    return null;
  }
}

export async function onRequest(context) {
  const url = new URL(context.request.url);
  if (!needsAuth(url.pathname, context.request.method)) return context.next();

  const credentials = decodeBasicAuth(context.request.headers.get("authorization"));
  if (credentials?.user !== ADMIN_USER || credentials?.password !== ADMIN_PASSWORD) {
    return unauthorized();
  }

  return context.next();
}
