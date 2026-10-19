import { createHash } from "node:crypto";
import configuredSources from "../../sources.json";
import { database } from "./database";

export interface WebsiteSource {
  id: string;
  name: string;
  url: string;
  institution: string;
  seedPaths: string[];
  sourceType: "core" | "custom";
}

interface WebsiteSourceRow {
  id: string;
  name: string;
  url: string;
  institution: string;
  seed_paths_json: string;
  source_type: "core" | "custom";
}

const seedCoreSources = database.prepare(
  `INSERT OR IGNORE INTO website_sources
   (id, name, url, institution, host, seed_paths_json, created_at, created_by, source_type, is_active)
   VALUES (?, ?, ?, ?, ?, ?, ?, 'system', 'core', 1)`
);

for (const source of configuredSources.sources) {
  seedCoreSources.run(
    source.id,
    source.name,
    source.url,
    source.institution,
    new URL(source.url).host.toLowerCase().replace(/^www\./, ""),
    JSON.stringify(source.seed_paths),
    Date.now()
  );
}

const listSourceRows = database.prepare(
  `SELECT id, name, url, institution, seed_paths_json, source_type
   FROM website_sources
   WHERE is_active = 1
   ORDER BY
     CASE source_type WHEN 'core' THEN 0 ELSE 1 END,
     CASE id WHEN 'unibe' THEN 0 WHEN 'artorg' THEN 1 WHEN 'dcberne' THEN 2 ELSE 3 END,
     name COLLATE NOCASE`
);

const findSourceByHost = database.prepare(
  "SELECT id, source_type, is_active FROM website_sources WHERE host = ?"
);
const findSourceById = database.prepare("SELECT id FROM website_sources WHERE id = ?");
const insertSource = database.prepare(
  `INSERT INTO website_sources
   (id, name, url, institution, host, seed_paths_json, created_at, created_by, source_type, is_active)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'custom', 1)`
);
const findOtherSourceByHost = database.prepare(
  "SELECT id FROM website_sources WHERE host = ? AND id != ?"
);
const updateSource = database.prepare(
  `UPDATE website_sources
   SET name = ?, url = ?, institution = ?, host = ?, seed_paths_json = ?
   WHERE id = ? AND is_active = 1`
);
const restoreCoreSource = database.prepare(
  `UPDATE website_sources
   SET name = ?, url = ?, institution = ?, seed_paths_json = ?, is_active = 1
   WHERE id = ? AND source_type = 'core'`
);
const findSourceType = database.prepare("SELECT source_type FROM website_sources WHERE id = ?");
const deactivateSource = database.prepare("UPDATE website_sources SET is_active = 0 WHERE id = ? AND is_active = 1");
const deleteCustomSource = database.prepare(
  "DELETE FROM website_sources WHERE id = ? AND source_type = 'custom' AND is_active = 1"
);

export function listWebsiteSources(): WebsiteSource[] {
  return (listSourceRows.all() as WebsiteSourceRow[]).map((source) => ({
    id: source.id,
    name: source.name,
    url: source.url,
    institution: source.institution,
    seedPaths: JSON.parse(source.seed_paths_json) as string[],
    sourceType: source.source_type
  }));
}

export function listSourceCatalog(): WebsiteSource[] {
  return listWebsiteSources();
}

export function addWebsiteSource(
  input: Omit<WebsiteSource, "id" | "sourceType">,
  createdBy: string
): "added" | "duplicate" {
  const host = new URL(input.url).host.toLowerCase().replace(/^www\./, "");
  const existing = findSourceByHost.get(host) as
    | { id: string; source_type: "core" | "custom"; is_active: number }
    | undefined;
  if (existing?.is_active) return "duplicate";
  if (existing?.source_type === "core") {
    restoreCoreSource.run(
      input.name,
      input.url,
      input.institution,
      JSON.stringify(input.seedPaths),
      existing.id
    );
    return "added";
  }

  const slug = host.replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "source";
  const suffix = createHash("sha256").update(host).digest("hex").slice(0, 10);
  let id = `${slug}-${suffix}`;
  while (findSourceById.get(id)) {
    id = `${slug}-${createHash("sha256").update(`${host}:${id}`).digest("hex").slice(0, 10)}`;
  }

  insertSource.run(
    id,
    input.name,
    input.url,
    input.institution,
    host,
    JSON.stringify(input.seedPaths),
    Date.now(),
    createdBy
  );

  return "added";
}

export function updateWebsiteSource(
  id: string,
  input: Omit<WebsiteSource, "id" | "sourceType">
): "updated" | "duplicate" | "not-found" {
  const host = new URL(input.url).host.toLowerCase().replace(/^www\./, "");
  if (findOtherSourceByHost.get(host, id)) return "duplicate";
  const result = updateSource.run(
    input.name,
    input.url,
    input.institution,
    host,
    JSON.stringify(input.seedPaths),
    id
  );

  return result.changes ? "updated" : "not-found";
}

export function removeWebsiteSource(id: string): boolean {
  const source = findSourceType.get(id) as { source_type: "core" | "custom" } | undefined;
  if (!source) return false;
  if (source.source_type === "core") {
    return deactivateSource.run(id).changes > 0;
  }
  return deleteCustomSource.run(id).changes > 0;
}
