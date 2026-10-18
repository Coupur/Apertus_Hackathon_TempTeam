import Database from "better-sqlite3";
import { createHash, randomBytes } from "node:crypto";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const databaseDirectory = resolve(process.cwd(), ".data");
mkdirSync(databaseDirectory, { recursive: true });

const database = new Database(resolve(databaseDirectory, "auth.sqlite"));
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
`);

const magicLinkLifetime = 15 * 60 * 1000;
const sessionLifetime = 30 * 24 * 60 * 60 * 1000;
const requestWindow = 60 * 60 * 1000;
const requestCooldown = 60 * 1000;
const maxRequestsPerHour = 5;

function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export const createMagicLink = database.transaction((email: string): string | null => {
  const now = Date.now();
  const recentRequests = database
    .prepare(
      `SELECT COUNT(*) AS count, MAX(created_at) AS latest
       FROM magic_link_requests
       WHERE email = ? AND created_at > ?`
    )
    .get(email, now - requestWindow) as { count: number; latest: number | null };

  if (
    recentRequests.count >= maxRequestsPerHour ||
    (recentRequests.latest !== null && now - recentRequests.latest < requestCooldown)
  ) {
    return null;
  }

  database.prepare("DELETE FROM magic_link_requests WHERE created_at < ?").run(now - 24 * requestWindow);
  database.prepare("DELETE FROM magic_links WHERE email = ?").run(email);

  const token = randomBytes(32).toString("base64url");
  database
    .prepare("INSERT INTO magic_links (token_hash, email, expires_at, created_at) VALUES (?, ?, ?, ?)")
    .run(hashToken(token), email, now + magicLinkLifetime, now);
  database.prepare("INSERT INTO magic_link_requests (email, created_at) VALUES (?, ?)").run(email, now);

  return token;
});

interface MagicLinkRow {
  email: string;
  expires_at: number;
}

interface SessionRow {
  email: string;
  expires_at: number;
}

export const consumeMagicLink = database.transaction((token: string) => {
  const tokenHash = hashToken(token);
  const link = database
    .prepare("SELECT email, expires_at FROM magic_links WHERE token_hash = ?")
    .get(tokenHash) as MagicLinkRow | undefined;

  if (!link || link.expires_at <= Date.now()) {
    database.prepare("DELETE FROM magic_links WHERE token_hash = ?").run(tokenHash);
    return null;
  }

  const now = Date.now();
  const sessionToken = randomBytes(32).toString("base64url");
  database
    .prepare("INSERT INTO users (email, created_at) VALUES (?, ?) ON CONFLICT(email) DO NOTHING")
    .run(link.email, now);
  database
    .prepare("INSERT INTO sessions (token_hash, email, expires_at, created_at) VALUES (?, ?, ?, ?)")
    .run(hashToken(sessionToken), link.email, now + sessionLifetime, now);
  database.prepare("DELETE FROM magic_links WHERE email = ?").run(link.email);

  return { email: link.email, sessionToken };
});

export function getSessionUser(sessionToken: string | undefined): string | null {
  if (!sessionToken) return null;

  const tokenHash = hashToken(sessionToken);
  const session = database
    .prepare("SELECT email, expires_at FROM sessions WHERE token_hash = ?")
    .get(tokenHash) as SessionRow | undefined;

  if (!session || session.expires_at <= Date.now()) {
    database.prepare("DELETE FROM sessions WHERE token_hash = ?").run(tokenHash);
    return null;
  }

  return session.email;
}

export function deleteSession(sessionToken: string | undefined): void {
  if (sessionToken) {
    database.prepare("DELETE FROM sessions WHERE token_hash = ?").run(hashToken(sessionToken));
  }
}
