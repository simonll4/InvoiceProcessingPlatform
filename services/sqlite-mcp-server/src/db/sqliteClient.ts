import Database from "better-sqlite3";

export interface ColumnInfo {
  name: string;
  type: string;
  notNull: boolean;
  pk: boolean;
}

export interface TableInfo {
  name: string;
  columns: ColumnInfo[];
}

export interface SchemaSummary {
  tables: TableInfo[];
}

/**
 * Encapsulates SQLite access in read-only mode.
 */
export class SqliteClient {
  private db: Database.Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath, { readonly: true });

  // Optional: reasonable pragmas compatible with read-only access
  this.db.pragma("foreign_keys = ON");
  }

  /**
   * Returns a schema summary (tables and columns).
   */
  getSchema(): SchemaSummary {
    const tablesRows = this.db
      .prepare(
        `
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        `
      )
      .all() as { name: string }[];

    const tables: TableInfo[] = tablesRows.map((row: { name: string }) => {
      const columnsRaw = this.db
        .prepare(`PRAGMA table_info(${row.name})`)
        .all() as any[];

      const columns: ColumnInfo[] = columnsRaw.map((c) => ({
        name: c.name,
        type: c.type,
        notNull: Boolean(c.notnull),
        pk: Boolean(c.pk),
      }));

      return {
        name: row.name,
        columns,
      };
    });

    return { tables };
  }

  /**
   * Executes a SELECT with a row limit.
   * Safety validation happens in the MCP layer.
   */
  runSelect(query: string, maxRows: number): { rows: any[]; rowCount: number } {
    const stmt = this.db.prepare(query);

    const rows: any[] = [];
    let count = 0;

    for (const row of stmt.iterate()) {
      rows.push(row);
      count += 1;
      if (count >= maxRows) break;
    }

    return {
      rows,
      rowCount: rows.length,
    };
  }

  close(): void {
    this.db.close();
  }
}

/**
 * Simple factory to create the client.
 */
export function createSqliteClient(dbPath: string): SqliteClient {
  return new SqliteClient(dbPath);
}
