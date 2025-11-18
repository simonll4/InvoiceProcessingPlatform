import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import type { SqliteClient, SchemaSummary } from "../db/sqliteClient.js";

/**
 * Renders the schema in a model-friendly text format.
 */
function renderSchemaText(schema: SchemaSummary): string {
  if (schema.tables.length === 0) {
    return "The database does not contain user tables.";
  }

  const lines: string[] = ["Database schema:"];

  for (const table of schema.tables) {
    lines.push(`\nTable: ${table.name}`);
    for (const col of table.columns) {
      const flags = [];
      if (col.pk) flags.push("PK");
      if (col.notNull) flags.push("NOT NULL");
      const flagsText = flags.length > 0 ? ` (${flags.join(", ")})` : "";
      lines.push(`  - ${col.name}: ${col.type || "UNKNOWN"}${flagsText}`);
    }
  }

  return lines.join("\n");
}

/**
 * Naive validation that only allows SELECT statements.
 */
function validateSelectQuery(query: string): { ok: boolean; reason?: string } {
  const trimmed = query.trim();
  if (!trimmed) {
    return { ok: false, reason: "The query is empty." };
  }

  const upper = trimmed.toUpperCase();

  if (!upper.startsWith("SELECT")) {
    return { ok: false, reason: "Only SELECT statements are allowed." };
  }

  // Dangerous keywords
  const forbiddenKeywords = [
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "PRAGMA",
    "ATTACH",
    "DETACH",
    "REINDEX",
    "REPLACE",
    "VACUUM",
    "CREATE",
  ];

  for (const keyword of forbiddenKeywords) {
    if (upper.includes(` ${keyword} `) || upper.includes(`\n${keyword} `)) {
      return {
        ok: false,
        reason: `The query contains the forbidden word '${keyword}'.`,
      };
    }
  }

  // Prevent multiple statements separated by ';'
  if (upper.split(";").length > 2) {
    return {
      ok: false,
      reason: "Multiple SQL statements in a single query are not allowed.",
    };
  }

  return { ok: true };
}

/**
 * Creates and configures the McpServer with the SQLite tools.
 */
export function createMcpServer(db: SqliteClient, maxRows: number): McpServer {
  const server = new McpServer({
    name: "sqlite-mcp-server",
    version: "1.0.0",
  });

  /**
   * Tool: sqlite_get_schema
   * - No input parameters.
   * - Returns the database schema.
   */
  server.registerTool(
    "sqlite_get_schema",
    {
      title: "SQLite Get Schema",
      description:
        "Retrieves the schema of the SQLite database (tables and columns).",
      inputSchema: z.object({}),
      outputSchema: z.object({
        tables: z.array(
          z.object({
            name: z.string(),
            columns: z.array(
              z.object({
                name: z.string(),
                type: z.string(),
                notNull: z.boolean(),
                pk: z.boolean(),
              })
            ),
          })
        ),
      }),
    },
    async () => {
      const schema = db.getSchema();
      const text = renderSchemaText(schema);

      return {
        content: [
          {
            type: "text",
            text,
          },
        ],
        structuredContent: {
          tables: schema.tables,
        },
      };
    }
  );

  /**
   * Tool: sqlite_run_select
   * - Executes a SELECT with a row limit.
   */
  server.registerTool(
    "sqlite_run_select",
    {
      title: "SQLite Run SELECT",
      description:
        "Executes a safe SELECT query on the SQLite database. " +
        "Only SELECT statements are allowed; the result is limited to a maximum number of rows.",
      inputSchema: z.object({
        query: z.string().min(1, "query cannot be empty"),
      }),
      outputSchema: z.object({
        rows: z.array(z.record(z.any())),
        rowCount: z.number(),
      }),
    },
    async ({ query }: { query: string }) => {
      const validation = validateSelectQuery(query);

      if (!validation.ok) {
        // On validation errors, return textual content only (no structuredContent).
        return {
          content: [
            {
              type: "text",
              text: `Query error: ${validation.reason}`,
            },
          ],
        };
      }

      try {
        const result = db.runSelect(query, maxRows);

        const preview = JSON.stringify(result.rows.slice(0, 5), null, 2);

        const text =
          `Query executed successfully.\n` +
          `Rows returned (max ${maxRows}): ${result.rowCount}\n\n` +
          `First rows (up to 5):\n${preview}`;

        return {
          content: [
            {
              type: "text",
              text,
            },
          ],
          structuredContent: {
            rows: result.rows,
            rowCount: result.rowCount,
          },
        };
      } catch (err: any) {
        return {
          content: [
            {
              type: "text",
              text: `Error executing the query: ${err?.message ?? String(err)}`,
            },
          ],
        };
      }
    }
  );

  return server;
}
