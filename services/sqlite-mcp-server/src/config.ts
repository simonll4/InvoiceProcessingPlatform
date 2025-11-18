import "dotenv/config";

function getNumberEnv(name: string, defaultValue: number): number {
  const raw = process.env[name];
  if (!raw) return defaultValue;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : defaultValue;
}

function getStringEnv(name: string, defaultValue?: string): string {
  const value = process.env[name] ?? defaultValue;
  if (value === undefined || value === "") {
    throw new Error(`Environment variable ${name} is required`);
  }
  return value;
}

export const config = {
  APP_DB_PATH: getStringEnv("APP_DB_PATH", "/app/data/app.db"),
  PORT: getNumberEnv("PORT", 3000),
  MAX_ROWS: getNumberEnv("MAX_ROWS", 200),
};
