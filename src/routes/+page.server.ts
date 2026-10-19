import { ORIGIN, RESEND_API_KEY, RESEND_FROM_EMAIL } from "$app/env/private";
import { fail, type Actions } from "@sveltejs/kit";
import { redirect } from "@sveltejs/kit";
import { Resend } from "resend";
import type { PageServerLoad } from "./$types";
import { createMagicLink, deleteSession, getSessionUser } from "../lib/server/auth";
import { getDashboardMetrics } from "../lib/server/metrics";
import { listWebsiteSources } from "../lib/server/sources";

const sessionCookieName = "navigator_session";

export const load: PageServerLoad = async ({ cookies, url }) => {
  const email = getSessionUser(cookies.get(sessionCookieName));
  return {
    email,
    metrics: email ? await getDashboardMetrics() : null,
    sources: listWebsiteSources(),
    notice:
      url.searchParams.get("verified") === "1"
        ? "Your email is verified. You are signed in."
        : url.searchParams.get("error") === "link"
          ? "That sign-in link is invalid or has expired. Request a new one."
          : null
  };
};

export const actions: Actions = {
  requestLink: async ({ request, url }) => {
    const formData = await request.formData();
    const submittedEmail = formData.get("email");

    if (typeof submittedEmail !== "string") {
      return fail(400, { error: "Enter a valid email address.", message: undefined });
    }

    const email = submittedEmail.trim().toLowerCase();
    if (
      email.length > 254 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
    ) {
      return fail(400, { error: "Enter a valid email address.", message: undefined });
    }

    const apiKey = RESEND_API_KEY;
    if (!apiKey) {
      console.error("Magic-link delivery is unavailable: RESEND_API_KEY is not configured.");
      return fail(503, {
        error: "Email sign-in is temporarily unavailable. Please try again later.",
        message: undefined
      });
    }

    const configuredOrigin = ORIGIN;
    if (!configuredOrigin && process.env.NODE_ENV === "production") {
      console.error("Magic-link delivery is unavailable: ORIGIN is not configured.");
      return fail(503, {
        error: "Email sign-in is temporarily unavailable. Please try again later.",
        message: undefined
      });
    }

    let appOrigin: URL;
    try {
      appOrigin = new URL(configuredOrigin ?? url.origin);
      if (
        appOrigin.username ||
        appOrigin.password ||
        appOrigin.pathname !== "/" ||
        appOrigin.search ||
        appOrigin.hash ||
        (appOrigin.protocol !== "https:" &&
          !(process.env.NODE_ENV !== "production" && appOrigin.hostname === "localhost"))
      ) {
        throw new Error("ORIGIN must be an HTTPS origin.");
      }
    } catch {
      console.error("Magic-link delivery is unavailable: ORIGIN is invalid.");
      return fail(503, {
        error: "Email sign-in is temporarily unavailable. Please try again later.",
        message: undefined
      });
    }

    const token = createMagicLink(email);
    if (!token) {
      return fail(429, {
        error: "Please wait a moment before requesting another sign-in link.",
        message: undefined
      });
    }

    const link = new URL("/auth/verify", appOrigin);
    link.searchParams.set("token", token);
    const resend = new Resend(apiKey);
    const from = RESEND_FROM_EMAIL;

    try {
      const { error } = await resend.emails.send({
        from,
        to: email,
        subject: "Your sign-in link",
        text: `Use this one-time link to sign in. It expires in 15 minutes:\n\n${link.href}`,
        html: `<p>Use this one-time link to sign in. It expires in 15 minutes:</p><p><a href="${link.href}">Sign in</a></p>`
      });

      if (error) {
        console.error("Resend could not send a magic-link email.");
        return fail(502, {
          error: "We couldn't send your sign-in link. Please try again later.",
          message: undefined
        });
      }
    } catch (error) {
      console.error("Resend magic-link request failed.", error);
      return fail(502, {
        error: "We couldn't send your sign-in link. Please try again later.",
        message: undefined
      });
    }

    return {
      error: undefined,
      message: "Your sign-in link is on its way. Check your inbox."
    };
  },

  logout: async ({ cookies }) => {
    const sessionToken = cookies.get(sessionCookieName);
    deleteSession(sessionToken);
    cookies.delete(sessionCookieName, { path: "/" });
    redirect(303, "/");
  }
};
