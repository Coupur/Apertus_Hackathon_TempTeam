import { fail, redirect, type Actions } from "@sveltejs/kit";
import { getSessionUser } from "../../lib/server/auth";
import {
  addWebsiteSource,
  listSourceCatalog,
  removeWebsiteSource,
  updateWebsiteSource
} from "../../lib/server/sources";
import { parseWebsiteSource } from "../../lib/server/source-validation";
import type { PageServerLoad } from "./$types";

const sessionCookieName = "navigator_session";

export const load: PageServerLoad = ({ cookies }) => {
  const email = getSessionUser(cookies.get(sessionCookieName));
  if (!email) redirect(303, "/");

  return {
    email,
    sources: listSourceCatalog()
  };
};

export const actions: Actions = {
  addSource: async ({ cookies, request }) => {
    const email = getSessionUser(cookies.get(sessionCookieName));
    if (!email) {
      return fail(401, { error: "Sign in to manage data sources.", success: undefined });
    }

    const formData = await request.formData();
    const parsed = parseWebsiteSource(formData);
    if (!parsed.input) {
      return fail(400, {
        error: parsed.error,
        success: undefined
      });
    }

    const result = addWebsiteSource(parsed.input, email);

    if (result === "duplicate") {
      return fail(409, {
        error: "A source for this website is already in the registry.",
        success: undefined
      });
    }

    return {
      error: undefined,
      success: `${parsed.input.name} was added to your source registry. Run the crawler to begin collecting pages.`
    };
  },

  editSource: async ({ cookies, request }) => {
    const email = getSessionUser(cookies.get(sessionCookieName));
    if (!email) {
      return fail(401, { error: "Sign in to manage data sources.", success: undefined });
    }

    const formData = await request.formData();
    const id = formData.get("id");
    if (typeof id !== "string" || !id) {
      return fail(400, { error: "Choose a source to edit.", success: undefined });
    }

    const parsed = parseWebsiteSource(formData);
    if (!parsed.input) {
      return fail(400, { error: parsed.error, success: undefined });
    }

    const result = updateWebsiteSource(id, parsed.input);
    if (result === "duplicate") {
      return fail(409, { error: "Another source already uses this website.", success: undefined });
    }
    if (result === "not-found") {
      return fail(404, { error: "That source could not be found.", success: undefined });
    }

    return { error: undefined, success: `${parsed.input.name} was updated.` };
  },

  removeSource: async ({ cookies, request }) => {
    const email = getSessionUser(cookies.get(sessionCookieName));
    if (!email) {
      return fail(401, { error: "Sign in to manage data sources.", success: undefined });
    }

    const formData = await request.formData();
    const id = formData.get("id");
    if (typeof id !== "string" || !id) {
      return fail(400, { error: "Choose a source to remove.", success: undefined });
    }

    if (!removeWebsiteSource(id)) {
      return fail(404, { error: "That managed source could not be found.", success: undefined });
    }

    return { error: undefined, success: "The website source was removed from the registry." };
  }
};
