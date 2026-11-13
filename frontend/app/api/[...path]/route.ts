import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL;

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!BACKEND_URL) {
    return Response.json(
      { detail: "Backend is not connected yet. Set BACKEND_URL on the dashboard service." },
      { status: 503 }
    );
  }

  const params = await context.params;
  const target =
    BACKEND_URL.replace(/\/$/, "") +
    "/api/" +
    params.path.map((part) => encodeURIComponent(part)).join("/") +
    request.nextUrl.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  const browserRequest = request.headers.get("x-meridian-requested");
  if (browserRequest) headers.set("x-meridian-requested", browserRequest);

  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.text();

  try {
    const upstream = await fetch(target, {
      method,
      headers,
      body,
      cache: "no-store",
    });
    const responseHeaders = new Headers();
    const upstreamType = upstream.headers.get("content-type");
    if (upstreamType) responseHeaders.set("content-type", upstreamType);
    const setCookie = upstream.headers.get("set-cookie");
    if (setCookie) responseHeaders.set("set-cookie", setCookie);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json({ detail: "Could not reach the research business API." }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
