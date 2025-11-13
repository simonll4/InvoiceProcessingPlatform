"""MCP Server para exponer SQLite como herramienta controlada."""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from loguru import logger
from mcp.server.fastmcp import FastMCP

from .config import ALLOWED_SQL_KEYWORDS, DB_PATH, FORBIDDEN_SQL_KEYWORDS


class SQLiteMCPServer:
    """
    MCP Server que expone operaciones de lectura sobre SQLite.

    Implementa el patrón de herramientas seguras:
    - Validación estricta de queries (solo SELECT, PRAGMA, EXPLAIN)
    - Logging de todas las operaciones
    - Gestión de errores limpia
    """

    QUERY_CACHE_TTL_SECONDS = 60
    MAX_RESULT_ROWS = 500  # Increased to allow processing more data without artificial limits

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._schema_cache: dict[str, Any] | None = None
        self._query_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.fast_mcp = self._create_fastmcp()
        self._openai_tools = self._build_tool_definitions()
        self._register_fastmcp_tools()
        self._http_mount_path: str | None = None
        logger.info(f"MCP Server initialized with database: {db_path}")

    def _create_fastmcp(self) -> FastMCP:
        """Configure the official MCP server backing this implementation."""
        instructions = (
            "Proveedor MCP para la plataforma de facturas. "
            "Ofrece acceso de solo lectura a SQLite (tablas invoices e items). "
            "Todas las consultas deben ser seguras y nunca modificar datos."
        )
        return FastMCP(
            name="invoice-sqlite-mcp",
            instructions=instructions,
            json_response=True,
            stateless_http=True,
            streamable_http_path="/",
        )

    def mount_http_transport(self, app: FastAPI, base_path: str = "/mcp") -> None:
        """
        Expone el servidor MCP oficial como transport HTTP dentro de la API principal.

        Args:
            app: instancia FastAPI donde se montará el transport
            base_path: ruta raíz para el endpoint streamable HTTP
        """
        if self._http_mount_path == base_path:
            return
        self.fast_mcp.settings.mount_path = base_path
        self.fast_mcp.settings.streamable_http_path = "/"
        logger.info("Mounting MCP HTTP transport at %s", base_path)
        app.mount(base_path, self.fast_mcp.streamable_http_app())
        self._http_mount_path = base_path

    def _register_fastmcp_tools(self) -> None:
        """Registra las herramientas utilizando el SDK oficial."""

        @self.fast_mcp.tool(
            name="execute_sql_query",
            description="Execute a read-only SQL query (SELECT/PRAGMA/EXPLAIN) against the SQLite invoices database.",
        )
        async def _tool_execute_sql_query(sql: str) -> dict[str, Any]:
            return self.execute_query(sql)

        @self.fast_mcp.tool(
            name="get_invoice_by_id",
            description="Get a specific invoice by ID, including all its items.",
        )
        async def _tool_get_invoice_by_id(doc_id: int) -> dict[str, Any]:
            return self.get_invoice_by_id(doc_id)

        @self.fast_mcp.tool(
            name="search_invoices_by_vendor",
            description="Search invoices from a specific vendor (partial name matching).",
        )
        async def _tool_search_invoices_by_vendor(
            vendor_name: str, limit: int = 10
        ) -> dict[str, Any]:
            return self.search_invoices_by_vendor(vendor_name, limit)

        @self.fast_mcp.tool(
            name="get_top_vendors",
            description="Get vendors with highest total spending, sorted in descending order.",
        )
        async def _tool_get_top_vendors(limit: int = 10) -> dict[str, Any]:
            return self.get_top_vendors(limit)

        @self.fast_mcp.tool(
            name="search_by_text",
            description="Search invoices containing a specific term in their extracted raw text.",
        )
        async def _tool_search_by_text(
            search_term: str, limit: int = 20
        ) -> dict[str, Any]:
            return self.search_by_text(search_term, limit)

        @self.fast_mcp.tool(
            name="get_invoices_by_date_range",
            description="Get invoices within a date range (ISO format: YYYY-MM-DD).",
        )
        async def _tool_get_invoices_by_date_range(
            start_date: str, end_date: str, limit: int = 100
        ) -> dict[str, Any]:
            return self.get_invoices_by_date_range(start_date, end_date, limit)

        @self.fast_mcp.tool(
            name="get_database_schema",
            description="Obtains the complete database schema (tables, columns, types, relationships).",
        )
        async def _tool_get_database_schema() -> dict[str, Any]:
            return {"success": True, "schema": self.get_schema()}

        @self.fast_mcp.tool(
            name="get_most_expensive_item",
            description="Get the single most expensive line item across all invoices.",
        )
        async def _tool_get_most_expensive_item() -> dict[str, Any]:
            return self.get_most_expensive_item()

        @self.fast_mcp.tool(
            name="get_top_categories_by_spend",
            description="Get categories with highest total spending, sorted descending. Supports pagination.",
        )
        async def _tool_get_top_categories_by_spend(
            limit: int = 10, offset: int = 0
        ) -> dict[str, Any]:
            return self.get_top_categories_by_spend(limit, offset)

        @self.fast_mcp.tool(
            name="get_pricey_categories_by_unit",
            description="Get categories with highest average unit price. Supports pagination.",
        )
        async def _tool_get_pricey_categories_by_unit(
            limit: int = 10, offset: int = 0
        ) -> dict[str, Any]:
            return self.get_pricey_categories_by_unit(limit, offset)

        @self.fast_mcp.tool(
            name="get_recent_invoices",
            description="Get most recent invoices by date, sorted descending. Supports pagination.",
        )
        async def _tool_get_recent_invoices(
            limit: int = 10, offset: int = 0
        ) -> dict[str, Any]:
            return self.get_recent_invoices(limit, offset)

        @self.fast_mcp.tool(
            name="get_vendor_invoices",
            description="Get invoices from a specific vendor with pagination support.",
        )
        async def _tool_get_vendor_invoices(
            vendor_name: str, limit: int = 20, offset: int = 0
        ) -> dict[str, Any]:
            return self.get_vendor_invoices(vendor_name, limit, offset)

        @self.fast_mcp.tool(
            name="get_invoice_items_by_doc_id",
            description="Get all line items for a specific invoice/document ID.",
        )
        async def _tool_get_invoice_items_by_doc_id(doc_id: int) -> dict[str, Any]:
            return self.get_invoice_items_by_doc_id(doc_id)

        @self.fast_mcp.tool(
            name="get_total_invoices_summary",
            description="Get summary of all invoices: total count and total amounts grouped by currency.",
        )
        async def _tool_get_total_invoices_summary() -> dict[str, Any]:
            return self.get_total_invoices_summary()

        @self.fast_mcp.tool(
            name="get_max_invoice",
            description="Get the invoice with the highest total_cents across all currencies.",
        )
        async def _tool_get_max_invoice() -> dict[str, Any]:
            return self.get_max_invoice()

    def _build_tool_definitions(self) -> list[dict[str, Any]]:
        """Arma la descripción OpenAI-compatible reutilizada por el orquestador."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "execute_sql_query",
                    "description": (
                        "Execute a read-only SQL query (SELECT, PRAGMA, EXPLAIN) "
                        "against the SQLite invoices database. "
                        "Use this when you need to query data not covered "
                        "by specialized functions."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "SQL query to execute (only SELECT/PRAGMA/EXPLAIN)",
                            }
                        },
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_invoice_by_id",
                    "description": "Get a specific invoice by ID, including all its items.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "doc_id": {
                                "type": "integer",
                                "description": "Document/invoice ID",
                            }
                        },
                        "required": ["doc_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_invoices_by_vendor",
                    "description": "Search invoices from a specific vendor (partial name matching).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "vendor_name": {
                                "type": "string",
                                "description": "Vendor name or part of the vendor name",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results (default: 10)",
                                "default": 10,
                            },
                        },
                        "required": ["vendor_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_vendors",
                    "description": "Get vendors with highest total spending, sorted in descending order.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Number of vendors to return (default: 10)",
                                "default": 10,
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_by_text",
                    "description": "Search invoices containing a specific term in their extracted raw text.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "Term to search in the text",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results (default: 20)",
                                "default": 20,
                            },
                        },
                        "required": ["search_term"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_invoices_by_date_range",
                    "description": "Get invoices within a date range (ISO format: YYYY-MM-DD).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {
                                "type": "string",
                                "description": "Start date (YYYY-MM-DD)",
                            },
                            "end_date": {
                                "type": "string",
                                "description": "End date (YYYY-MM-DD)",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results (default: 100)",
                                "default": 100,
                            },
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_database_schema",
                    "description": "Obtains the complete database schema (tables, columns, types, relationships).",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_most_expensive_item",
                    "description": "Get the single most expensive line item across all invoices.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_categories_by_spend",
                    "description": "Get categories with highest total spending, sorted descending. Supports pagination for 'second category', etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Number of categories to return (default: 10)",
                                "default": 10,
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Number of categories to skip for pagination (default: 0)",
                                "default": 0,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_pricey_categories_by_unit",
                    "description": "Get categories with highest average unit price. Supports pagination.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Number of categories to return (default: 10)",
                                "default": 10,
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Number of categories to skip for pagination (default: 0)",
                                "default": 0,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_recent_invoices",
                    "description": "Get most recent invoices by date, sorted descending. Supports pagination.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Number of invoices to return (default: 10)",
                                "default": 10,
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Number of invoices to skip for pagination (default: 0)",
                                "default": 0,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_vendor_invoices",
                    "description": "Get invoices from a specific vendor with pagination support.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "vendor_name": {
                                "type": "string",
                                "description": "Vendor name or partial name",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Number of invoices to return (default: 20)",
                                "default": 20,
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Number of invoices to skip for pagination (default: 0)",
                                "default": 0,
                            },
                        },
                        "required": ["vendor_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_invoice_items_by_doc_id",
                    "description": "Get all line items for a specific invoice/document ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "doc_id": {
                                "type": "integer",
                                "description": "Document/invoice ID",
                            }
                        },
                        "required": ["doc_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_total_invoices_summary",
                    "description": "Get summary of all invoices: count and total amounts grouped by currency. Use this for questions about 'total de facturas', 'suma de todos los montos', etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_max_invoice",
                    "description": "Get the invoice with the highest total_cents amount. Use this for questions about 'factura más cara', 'factura con mayor monto', 'invoice with highest amount', etc.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]

    def _validate_query(self, sql: str) -> tuple[bool, str]:
        """
        Valida que la query sea segura (solo lectura).

        Returns:
            (is_valid, error_message)
        """
        # Strip leading/trailing whitespace and comments
        cleaned = sql.strip()
        
        # Remove leading SQL comments (-- and /* */ style)
        while cleaned:
            if cleaned.startswith('--'):
                # Skip until newline
                newline_idx = cleaned.find('\n')
                if newline_idx == -1:
                    cleaned = ''
                    break
                cleaned = cleaned[newline_idx+1:].lstrip()
            elif cleaned.startswith('/*'):
                # Skip until */
                end_idx = cleaned.find('*/')
                if end_idx == -1:
                    return False, "Malformed comment block"
                cleaned = cleaned[end_idx+2:].lstrip()
            else:
                break
        
        if not cleaned:
            return False, "Query is empty after removing comments"
        
        sql_upper = cleaned.upper()

        # Check forbidden keywords
        for keyword in FORBIDDEN_SQL_KEYWORDS:
            if keyword in sql_upper:
                return False, f"Operación no permitida: {keyword}"

        # Check allowed keywords - now on cleaned SQL
        starts_with_allowed = any(
            sql_upper.startswith(kw) for kw in ALLOWED_SQL_KEYWORDS
        )
        if not starts_with_allowed:
            return False, f"Query debe comenzar con: {', '.join(ALLOWED_SQL_KEYWORDS)}"

        return True, ""

    def get_schema(self) -> dict[str, Any]:
        """
        Obtiene el schema completo de la base de datos.
        Cachea el resultado para eficiencia.
        """
        if self._schema_cache:
            return self._schema_cache

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get all tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]

            schema = {"tables": {}}

            for table in tables:
                # Get columns info
                cursor.execute(f"PRAGMA table_info({table})")
                columns = []
                for col in cursor.fetchall():
                    columns.append(
                        {
                            "name": col[1],
                            "type": col[2],
                            "not_null": bool(col[3]),
                            "primary_key": bool(col[5]),
                        }
                    )

                # Get foreign keys
                cursor.execute(f"PRAGMA foreign_key_list({table})")
                foreign_keys = []
                for fk in cursor.fetchall():
                    foreign_keys.append(
                        {
                            "column": fk[3],
                            "references_table": fk[2],
                            "references_column": fk[4],
                        }
                    )

                # Get indexes
                cursor.execute(f"PRAGMA index_list({table})")
                indexes = [
                    {"name": row[1], "unique": bool(row[2])}
                    for row in cursor.fetchall()
                ]

                schema["tables"][table] = {
                    "columns": columns,
                    "foreign_keys": foreign_keys,
                    "indexes": indexes,
                }

            conn.close()
            self._schema_cache = schema
            logger.info(f"Schema loaded: {len(tables)} tables")

            # Add schema summary for easy LLM consumption
            schema["summary"] = {
                "total_tables": len(tables),
                "table_names": tables,
            }

            return schema

        except Exception as e:
            logger.error(f"Error loading schema: {e}")
            return {"tables": {}, "error": str(e)}

    def _normalize_sql(self, sql: str) -> str:
        return " ".join(sql.strip().split())

    def _cache_key(self, sql: str) -> str:
        normalized = self._normalize_sql(sql)
        return hashlib.md5(normalized.encode()).hexdigest()

    def _get_cached_query(self, sql: str) -> dict[str, Any] | None:
        key = self._cache_key(sql)
        cached = self._query_cache.get(key)
        if not cached:
            return None
        timestamp, payload = cached
        if time.time() - timestamp > self.QUERY_CACHE_TTL_SECONDS:
            del self._query_cache[key]
            return None
        return payload

    def _set_cached_query(self, sql: str, payload: dict[str, Any]) -> None:
        key = self._cache_key(sql)
        self._query_cache[key] = (time.time(), payload)

    def execute_query(self, sql: str) -> dict[str, Any]:
        """
        Ejecuta una query de lectura y retorna resultados.

        Returns:
            {
                "success": bool,
                "rows": list[dict],
                "row_count": int,
                "columns": list[str],
                "error": str | None,
                "query": str  # For audit
            }
        """
        # Validate
        is_valid, error_msg = self._validate_query(sql)
        if not is_valid:
            logger.warning(f"Query rejected: {error_msg} | SQL: {sql[:100]}")
            return {
                "success": False,
                "error": error_msg,
                "query": sql,
                "rows": [],
                "row_count": 0,
                "columns": [],
            }

        cached = self._get_cached_query(sql)
        if cached:
            logger.debug("SQL cache hit for query: %s", sql[:80])
            return cached

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Return rows as dicts
            cursor = conn.cursor()

            cursor.execute(sql)
            fetched_rows = cursor.fetchall()

            # Convert to list of dicts
            columns = (
                [desc[0] for desc in cursor.description] if cursor.description else []
            )
            total_rows = len(fetched_rows)
            truncated = False
            rows = fetched_rows
            if total_rows > self.MAX_RESULT_ROWS:
                truncated = True
                rows = rows[: self.MAX_RESULT_ROWS]

            result_rows = [dict(row) for row in rows]

            conn.close()

            logger.info(
                f"Query executed successfully: {len(result_rows)} rows | SQL: {sql[:100]}"
            )

            payload = {
                "success": True,
                "rows": result_rows,
                "row_count": total_rows,
                "returned_rows": len(result_rows),
                "columns": columns,
                "error": None,
                "query": sql,
                "truncated": truncated,
            }

            # Cache only successful, non-truncated queries
            if not truncated:
                self._set_cached_query(sql, payload)

            return payload

        except Exception as e:
            logger.error(f"Query execution error: {e} | SQL: {sql[:100]}")
            return {
                "success": False,
                "error": str(e),
                "query": sql,
                "rows": [],
                "row_count": 0,
                "columns": [],
            }

    # High-level safe wrappers
    def get_invoice_by_id(self, doc_id: int) -> dict[str, Any]:
        """Safe wrapper: get invoice by ID."""
        sql = f"""
            SELECT 
                d.*,
                GROUP_CONCAT(
                    json_object(
                        'idx', i.idx,
                        'description', i.description,
                        'qty', i.qty,
                        'unit_price_cents', i.unit_price_cents,
                        'line_total_cents', i.line_total_cents,
                        'category', i.category
                    )
                ) as items_json
            FROM invoices d
            LEFT JOIN items i ON d.id = i.document_id
            WHERE d.id = {doc_id}
            GROUP BY d.id
        """
        return self.execute_query(sql)

    def search_invoices_by_vendor(
        self, vendor_name: str, limit: int = 10
    ) -> dict[str, Any]:
        """Safe wrapper: search invoices by vendor."""
        # Escape single quotes
        vendor_escaped = vendor_name.replace("'", "''")
        sql = f"""
            SELECT 
                id, invoice_number, invoice_date, vendor_name,
                total_cents, currency_code, path
            FROM invoices
            WHERE vendor_name LIKE '%{vendor_escaped}%'
            ORDER BY invoice_date DESC
            LIMIT {limit}
        """
        return self.execute_query(sql)

    def get_top_vendors(self, limit: int = 10) -> dict[str, Any]:
        """
        Wrapper seguro: top vendors por monto total.
        CORREGIDO: Agrupa solo por vendor_name (no por currency) y lista todas las monedas.
        """
        sql = f"""
            SELECT 
                vendor_name,
                COUNT(*) as invoice_count,
                SUM(total_cents) as total_spent_cents,
                GROUP_CONCAT(DISTINCT currency_code) as currencies,
                MAX(invoice_date) as last_invoice_date
            FROM invoices
            GROUP BY vendor_name
            ORDER BY total_spent_cents DESC
            LIMIT {limit}
        """
        return self.execute_query(sql)

    def search_by_text(self, search_term: str, limit: int = 20) -> dict[str, Any]:
        """Wrapper seguro: buscar en texto bruto."""
        term_escaped = search_term.replace("'", "''")
        sql = f"""
            SELECT 
                id, invoice_number, vendor_name, invoice_date,
                total_cents, currency_code,
                substr(raw_text, 1, 200) as text_preview
            FROM invoices
            WHERE raw_text LIKE '%{term_escaped}%'
            ORDER BY invoice_date DESC
            LIMIT {limit}
        """
        return self.execute_query(sql)

    def get_invoices_by_date_range(
        self, start_date: str, end_date: str, limit: int = 100
    ) -> dict[str, Any]:
        """Safe wrapper: invoices in date range."""
        sql = f"""
            SELECT 
                id, invoice_number, vendor_name, invoice_date,
                total_cents, currency_code
            FROM invoices
            WHERE invoice_date BETWEEN '{start_date}' AND '{end_date}'
            ORDER BY invoice_date DESC
            LIMIT {limit}
        """
        return self.execute_query(sql)

    def get_most_expensive_item(self) -> dict[str, Any]:
        """Get the single most expensive line item across all invoices."""
        sql = """
            SELECT
                i.id,
                i.description,
                i.qty,
                i.unit_price_cents,
                i.line_total_cents,
                i.category,
                d.id as document_id,
                d.invoice_number,
                d.invoice_date,
                d.vendor_name,
                d.currency_code
            FROM items i
            JOIN invoices d ON d.id = i.document_id
            ORDER BY i.line_total_cents DESC, COALESCE(i.unit_price_cents, 0) DESC, i.id DESC
            LIMIT 1
        """
        return self.execute_query(sql)

    def get_top_categories_by_spend(
        self, limit: int = 10, offset: int = 0
    ) -> dict[str, Any]:
        """Get categories with highest total spending, with pagination."""
        sql = f"""
            SELECT
                COALESCE(i.category, 'Uncategorized') AS category,
                COUNT(*) AS items_count,
                SUM(i.line_total_cents) AS total_cents
            FROM items i
            GROUP BY category
            ORDER BY total_cents DESC
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute_query(sql)

    def get_pricey_categories_by_unit(
        self, limit: int = 10, offset: int = 0
    ) -> dict[str, Any]:
        """Get categories with highest average unit price, with pagination."""
        sql = f"""
            SELECT
                COALESCE(category, 'Uncategorized') AS category,
                AVG(COALESCE(unit_price_cents, 0)) AS avg_unit_price_cents,
                COUNT(*) AS n_items
            FROM items
            WHERE unit_price_cents IS NOT NULL AND unit_price_cents > 0
            GROUP BY category
            HAVING n_items >= 3
            ORDER BY avg_unit_price_cents DESC
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute_query(sql)

    def get_recent_invoices(
        self, limit: int = 10, offset: int = 0
    ) -> dict[str, Any]:
        """Get most recent invoices by date, with pagination."""
        sql = f"""
            SELECT
                id,
                invoice_number,
                vendor_name,
                invoice_date,
                total_cents,
                currency_code
            FROM invoices
            ORDER BY invoice_date DESC, id DESC
            LIMIT {limit} OFFSET {offset}
        """
        return self.execute_query(sql)

    def get_vendor_invoices(
        self, vendor_name: str, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """Get invoices from a specific vendor, with pagination and parameterized query."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            sql = """
                SELECT
                    id,
                    invoice_number,
                    vendor_name,
                    invoice_date,
                    total_cents,
                    currency_code
                FROM invoices
                WHERE vendor_name LIKE ?
                ORDER BY invoice_date DESC
                LIMIT ? OFFSET ?
            """
            
            cursor.execute(sql, (f"%{vendor_name}%", limit, offset))
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return {
                "success": True,
                "rows": rows,
                "row_count": len(rows),
                "columns": list(rows[0].keys()) if rows else [],
                "query": sql,
            }
        except Exception as e:
            logger.error(f"Error in get_vendor_invoices: {e}")
            return {"success": False, "error": str(e)}

    def get_invoice_items_by_doc_id(self, doc_id: int) -> dict[str, Any]:
        """Get all line items for a specific invoice/document ID, using parameterized query."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            sql = """
                SELECT
                    i.idx,
                    i.description,
                    i.qty,
                    i.unit_price_cents,
                    i.line_total_cents,
                    i.category
                FROM items i
                WHERE i.document_id = ?
                ORDER BY i.idx
            """
            
            cursor.execute(sql, (doc_id,))
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return {
                "success": True,
                "rows": rows,
                "row_count": len(rows),
                "columns": list(rows[0].keys()) if rows else [],
                "query": sql,
            }
        except Exception as e:
            logger.error(f"Error in get_invoice_items_by_doc_id: {e}")
            return {"success": False, "error": str(e)}

    def get_total_invoices_summary(self) -> dict[str, Any]:
        """
        Get summary of all invoices: total count and totals by currency.
        CRITICAL: Returns separate totals per currency to avoid mixing currencies.
        """
        sql = """
            SELECT
                COUNT(*) as total_invoices,
                currency_code,
                SUM(total_cents) as total_cents
            FROM invoices
            GROUP BY currency_code
            ORDER BY total_cents DESC
        """
        return self.execute_query(sql)

    def get_max_invoice(self) -> dict[str, Any]:
        """
        Get the invoice with the highest total_cents.
        CRITICAL: Correctly ordered by total_cents DESC.
        """
        sql = """
            SELECT
                id,
                invoice_number,
                invoice_date,
                vendor_name,
                total_cents,
                currency_code,
                path
            FROM invoices
            ORDER BY total_cents DESC, id DESC
            LIMIT 1
        """
        return self.execute_query(sql)

    def get_tools_description(self) -> list[dict[str, Any]]:
        """
    Retorna la descripción de las herramientas disponibles
    en formato compatible con el esquema OpenAI (p. ej., Groq).
        """
        return list(self._openai_tools)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Dispatcher central para llamadas a herramientas desde el LLM.
        """
        logger.info(f"Tool call: {tool_name} with args: {arguments}")

        try:
            if tool_name == "execute_sql_query":
                return self.execute_query(arguments["sql"])
            elif tool_name == "get_invoice_by_id":
                return self.get_invoice_by_id(arguments["doc_id"])
            elif tool_name == "search_invoices_by_vendor":
                return self.search_invoices_by_vendor(
                    arguments["vendor_name"], arguments.get("limit", 10)
                )
            elif tool_name == "get_top_vendors":
                return self.get_top_vendors(arguments.get("limit", 10))
            elif tool_name == "search_by_text":
                return self.search_by_text(
                    arguments["search_term"], arguments.get("limit", 20)
                )
            elif tool_name == "get_invoices_by_date_range":
                return self.get_invoices_by_date_range(
                    arguments["start_date"],
                    arguments["end_date"],
                    arguments.get("limit", 100),
                )
            elif tool_name == "get_database_schema":
                return {"success": True, "schema": self.get_schema()}
            elif tool_name == "get_most_expensive_item":
                return self.get_most_expensive_item()
            elif tool_name == "get_top_categories_by_spend":
                return self.get_top_categories_by_spend(
                    arguments.get("limit", 10), arguments.get("offset", 0)
                )
            elif tool_name == "get_pricey_categories_by_unit":
                return self.get_pricey_categories_by_unit(
                    arguments.get("limit", 10), arguments.get("offset", 0)
                )
            elif tool_name == "get_recent_invoices":
                return self.get_recent_invoices(
                    arguments.get("limit", 10), arguments.get("offset", 0)
                )
            elif tool_name == "get_total_invoices_summary":
                return self.get_total_invoices_summary()
            elif tool_name == "get_max_invoice":
                return self.get_max_invoice()
            elif tool_name == "get_vendor_invoices":
                return self.get_vendor_invoices(
                    arguments["vendor_name"],
                    arguments.get("limit", 20),
                    arguments.get("offset", 0),
                )
            elif tool_name == "get_invoice_items_by_doc_id":
                return self.get_invoice_items_by_doc_id(arguments["doc_id"])
            else:
                return {
                    "success": False,
                    "error": f"Herramienta desconocida: {tool_name}",
                }
        except Exception as e:
            logger.error(f"Error in tool call {tool_name}: {e}")
            return {"success": False, "error": str(e)}
