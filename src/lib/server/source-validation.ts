import { isIP } from "node:net";

export interface WebsiteSourceInput {
  name: string;
  institution: string;
  url: string;
  seedPaths: string[];
}

export function parseWebsiteSource(
  formData: FormData
): { input: WebsiteSourceInput; error?: never } | { input?: never; error: string } {
  const name = formData.get("name");
  const institution = formData.get("institution");
  const submittedUrl = formData.get("url");
  const submittedSeedPaths = formData.get("seedPaths");

  if (
    typeof name !== "string" ||
    typeof institution !== "string" ||
    typeof submittedUrl !== "string" ||
    typeof submittedSeedPaths !== "string"
  ) {
    return { error: "Complete each required field." };
  }

  const cleanName = name.trim();
  const cleanInstitution = institution.trim();
  if (!cleanName || cleanName.length > 120 || !cleanInstitution || cleanInstitution.length > 120) {
    return {
      error: "Enter a source name and institution, each no longer than 120 characters."
    };
  }

  let url: URL;
  try {
    url = new URL(submittedUrl.trim());
  } catch {
    return { error: "Enter a valid website URL." };
  }

  const host = url.hostname.toLowerCase();
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    !host ||
    isIP(host) ||
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host.endsWith(".local") ||
    (url.port && !["80", "443"].includes(url.port)) ||
    url.search ||
    url.hash
  ) {
    return {
      error: "Use a public HTTP or HTTPS website URL without credentials, query strings, or fragments."
    };
  }

  const seedPaths = submittedSeedPaths
    .split(/\r?\n/)
    .map((path) => path.trim())
    .filter(Boolean);
  if (seedPaths.some((path) => !path.startsWith("/") || path.startsWith("//") || path.length > 300)) {
    return { error: "Seed paths must be site-local paths beginning with a single slash." };
  }

  return {
    input: {
      name: cleanName,
      institution: cleanInstitution,
      url: url.href,
      seedPaths: [...new Set(seedPaths)]
    }
  };
}
