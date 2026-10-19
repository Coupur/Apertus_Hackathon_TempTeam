import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const dataDirectory = resolve(process.cwd(), ".data");
mkdirSync(dataDirectory, { recursive: true });

export const database = new Database(resolve(dataDirectory, "auth.sqlite"));
database.pragma("journal_mode = WAL");
database.pragma("foreign_keys = ON");
database.exec(`
  CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS magic_links (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS magic_link_requests (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    created_at INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
  );

  CREATE INDEX IF NOT EXISTS magic_link_requests_email_created
    ON magic_link_requests(email, created_at);

  CREATE TABLE IF NOT EXISTS website_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    institution TEXT NOT NULL,
    host TEXT NOT NULL UNIQUE,
    seed_paths_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL,
    created_by TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'custom',
    is_active INTEGER NOT NULL DEFAULT 1
  );
`);

const websiteSourceColumns = (
  database.pragma("table_info(website_sources)") as { name: string }[]
).map((column) => column.name);

if (!websiteSourceColumns.includes("source_type")) {
  database.exec("ALTER TABLE website_sources ADD COLUMN source_type TEXT NOT NULL DEFAULT 'custom'");
}

if (!websiteSourceColumns.includes("is_active")) {
  database.exec("ALTER TABLE website_sources ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1");
}

database
  .prepare("UPDATE website_sources SET source_type = 'core' WHERE id IN ('unibe', 'artorg', 'dcberne')")
  .run();
