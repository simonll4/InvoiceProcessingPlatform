import express, { type Request, type Response } from "express";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createMcpServer } from "../mcp/server.js";
import { createSqliteClient } from "../db/sqliteClient.js";
import { config } from "../config.js";

export function createApp() {
  const app = express();

  // Parse JSON bodies
  app.use(express.json({ limit: "1mb" }));

  // Shared instances
  const db = createSqliteClient(config.APP_DB_PATH);
  const mcpServer = createMcpServer(db, config.MAX_ROWS);

  /**
   * MCP endpoint consumed by the MCP client (agent).
   */
  app.post("/mcp", async (req: Request, res: Response) => {
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: true,
    });

    res.on("close", () => {
      transport.close();
    });

    try {
      await mcpServer.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (err) {
      console.error("Error handling MCP request:", err);
      if (!res.headersSent) {
        res.status(500).json({ error: "Internal MCP server error" });
      }
    }
  });

  /**
   * Simple healthcheck for debugging/monitoring.
   */
  app.get("/health", (_req: Request, res: Response) => {
    res.json({ status: "ok" });
  });

  return app;
}
