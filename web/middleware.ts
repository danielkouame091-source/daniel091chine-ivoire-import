/**
 * Middleware Next.js — protège les routes selon le rôle.
 * Lecture du JWT depuis cookie (si présent) ou header custom.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/mfa", "/", "/_next", "/favicon", "/api"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Chemins publics
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return NextResponse.next();
  }

  // Récupération du token (cookie posé par le client après login)
  const accessToken = request.cookies.get("mtech_access_token")?.value;

  if (!accessToken) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  // Décodage rapide pour vérifier l'expiration (pas de signature — vérif serveur)
  try {
    const [, payload] = accessToken.split(".");
    if (!payload) throw new Error("invalid");
    const decoded = JSON.parse(
      Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString()
    );
    const expired = decoded.exp * 1000 < Date.now();
    if (expired) {
      const url = request.nextUrl.clone();
      url.pathname = "/login";
      url.searchParams.set("next", pathname);
      const res = NextResponse.redirect(url);
      res.cookies.delete("mtech_access_token");
      res.cookies.delete("mtech_refresh_token");
      return res;
    }

    // Protection cockpit (fondateur uniquement)
    if (pathname.startsWith("/cockpit") && !decoded.is_founder) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    // Le fondateur n'a pas de tenant → rediriger vers cockpit
    if (decoded.is_founder && !pathname.startsWith("/cockpit") && pathname !== "/billing") {
      return NextResponse.redirect(new URL("/cockpit", request.url));
    }
  } catch {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
