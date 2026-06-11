import Database from "better-sqlite3";
import path from "path";
import type { Adapter, AdapterUser, AdapterAccount, VerificationToken } from "next-auth/adapters";

const DB_PATH =
  process.env.NEXTAUTH_DB_PATH ?? path.join(process.cwd(), "nextauth.db");

const db = new Database(DB_PATH);

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT UNIQUE NOT NULL,
    email_verified TEXT,
    image TEXT
  );

  CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_account_id TEXT NOT NULL,
    refresh_token TEXT,
    access_token TEXT,
    expires_at INTEGER,
    token_type TEXT,
    scope TEXT,
    id_token TEXT,
    session_state TEXT,
    UNIQUE (provider, provider_account_id)
  );

  CREATE TABLE IF NOT EXISTS verification_tokens (
    identifier TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    expires TEXT NOT NULL,
    PRIMARY KEY (identifier, token)
  );
`);

function rowToUser(row: Record<string, unknown>): AdapterUser {
  return {
    id: row.id as string,
    name: (row.name as string | null) ?? null,
    email: row.email as string,
    emailVerified: row.email_verified ? new Date(row.email_verified as string) : null,
    image: (row.image as string | null) ?? null,
  };
}

export function SQLiteAdapter(): Adapter {
  return {
    createUser(user: Omit<AdapterUser, "id">): AdapterUser {
      const id = crypto.randomUUID();
      db.prepare(
        "INSERT INTO users (id, name, email, email_verified, image) VALUES (?, ?, ?, ?, ?)"
      ).run(
        id,
        user.name ?? null,
        user.email,
        user.emailVerified?.toISOString() ?? null,
        user.image ?? null
      );
      return { id, ...user };
    },

    getUser(id: string): AdapterUser | null {
      const row = db.prepare("SELECT * FROM users WHERE id = ?").get(id) as Record<string, unknown> | undefined;
      return row ? rowToUser(row) : null;
    },

    getUserByEmail(email: string): AdapterUser | null {
      const row = db.prepare("SELECT * FROM users WHERE email = ?").get(email) as Record<string, unknown> | undefined;
      return row ? rowToUser(row) : null;
    },

    getUserByAccount({ provider, providerAccountId }: Pick<AdapterAccount, "provider" | "providerAccountId">): AdapterUser | null {
      const row = db
        .prepare(
          "SELECT u.* FROM users u JOIN accounts a ON u.id = a.user_id WHERE a.provider = ? AND a.provider_account_id = ?"
        )
        .get(provider, providerAccountId) as Record<string, unknown> | undefined;
      return row ? rowToUser(row) : null;
    },

    updateUser(user: Partial<AdapterUser> & Pick<AdapterUser, "id">): AdapterUser {
      const existing = db.prepare("SELECT * FROM users WHERE id = ?").get(user.id) as Record<string, unknown>;
      const merged = {
        ...existing,
        ...user,
        email_verified:
          user.emailVerified !== undefined
            ? user.emailVerified?.toISOString() ?? null
            : existing.email_verified,
      };
      db.prepare(
        "UPDATE users SET name = ?, email = ?, email_verified = ?, image = ? WHERE id = ?"
      ).run(
        merged.name ?? null,
        merged.email,
        merged.email_verified ?? null,
        merged.image ?? null,
        user.id
      );
      return rowToUser(merged);
    },

    linkAccount(account: AdapterAccount): AdapterAccount {
      const id = crypto.randomUUID();
      db.prepare(
        `INSERT INTO accounts (id, user_id, type, provider, provider_account_id,
          refresh_token, access_token, expires_at, token_type, scope, id_token, session_state)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      ).run(
        id,
        account.userId,
        account.type,
        account.provider,
        account.providerAccountId,
        account.refresh_token ?? null,
        account.access_token ?? null,
        account.expires_at ?? null,
        account.token_type ?? null,
        account.scope ?? null,
        account.id_token ?? null,
        account.session_state ?? null
      );
      return account;
    },

    createVerificationToken(token: VerificationToken): VerificationToken {
      db.prepare(
        "INSERT INTO verification_tokens (identifier, token, expires) VALUES (?, ?, ?)"
      ).run(token.identifier, token.token, token.expires.toISOString());
      return token;
    },

    useVerificationToken({ identifier, token }: { identifier: string; token: string }): VerificationToken | null {
      const row = db
        .prepare("SELECT * FROM verification_tokens WHERE identifier = ? AND token = ?")
        .get(identifier, token) as Record<string, unknown> | undefined;
      if (!row) return null;
      db.prepare(
        "DELETE FROM verification_tokens WHERE identifier = ? AND token = ?"
      ).run(identifier, token);
      return {
        identifier: row.identifier as string,
        token: row.token as string,
        expires: new Date(row.expires as string),
      };
    },
  };
}
