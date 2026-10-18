import { redirect, type RequestHandler } from "@sveltejs/kit";
import { consumeMagicLink } from "../../../lib/server/auth";

const sessionCookieName = "navigator_session";
const sessionLifetime = 30 * 24 * 60 * 60;

export const GET: RequestHandler = ({ cookies, url }) => {
  const token = url.searchParams.get("token");
  const result = token && token.length <= 128 ? consumeMagicLink(token) : null;

  if (!result) {
    redirect(303, "/?error=link");
  }

  cookies.set(sessionCookieName, result.sessionToken, {
    path: "/",
    httpOnly: true,
    secure: process.env.NODE_ENV !== "development",
    sameSite: "lax",
    maxAge: sessionLifetime
  });

  redirect(303, "/?verified=1");
};
