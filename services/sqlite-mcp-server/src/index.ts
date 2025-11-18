import { createApp } from "./http/app.js";
import { config } from "./config.js";

const app = createApp();

app
  .listen(config.PORT, () => {
    console.log(
      `SQLite MCP Server listening at http://localhost:${config.PORT}/mcp  (DB: ${config.APP_DB_PATH})`
    );
  })
  .on("error", (error) => {
    console.error("Error starting the HTTP server:", error);
    process.exit(1);
  });
