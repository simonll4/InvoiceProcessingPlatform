"""
MCP Client for interacting with the SQLite MCP server.

This client handles all database access through the MCP protocol.
Direct database access is not allowed - all queries must go through MCP.
"""

from typing import Any, Dict, Optional

import httpx
from loguru import logger

from .mcp_types import QueryResult, SchemaInfo


class MCPError(Exception):
    """Base exception for MCP-related errors."""

    pass


class MCPClient:
    """
    HTTP client for the SQLite MCP server.
    
    Provides two main operations:
    - get_schema(): Retrieve database schema
    - run_sql_select(): Execute a SELECT query
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
    ) -> None:
        """
        Initialize MCP client.
        
        Args:
            base_url: Base URL of the MCP server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_schema(self) -> SchemaInfo:
        """
        Retrieve database schema from MCP server.
        
        Returns:
            SchemaInfo with table information
            
        Raises:
            MCPError: If the request fails or returns an error
        """
        url = f"{self.base_url}/mcp"
        logger.debug(f"Calling MCP get_schema at {url}")

        # MCP JSON-RPC request
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "sqlite_get_schema",
                "arguments": {}
            }
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    }
                )
                resp.raise_for_status()
                data = resp.json()

                # Check for JSON-RPC error
                if "error" in data:
                    error_msg = data["error"].get("message", str(data["error"]))
                    raise MCPError(f"MCP get_schema error: {error_msg}")

                # Extract result from JSON-RPC response
                result = data.get("result", {})
                
                # Check for structured content first (preferred)
                if "structuredContent" in result:
                    structured = result["structuredContent"]
                    tables = structured.get("tables", [])
                    return SchemaInfo(tables=tables, raw_schema=structured)
                
                # Fallback: parse text content
                if isinstance(result, dict) and "content" in result:
                    content = result["content"]
                    if isinstance(content, list) and len(content) > 0:
                        schema_text = content[0].get("text", "")
                        # Parse the schema text to extract tables
                        tables = self._parse_schema_text(schema_text)
                        return SchemaInfo(tables=tables, raw_schema={"schema_text": schema_text})
                
                # Last resort: try to use result directly
                tables = result.get("tables", [])
                return SchemaInfo(tables=tables, raw_schema=result)

        except httpx.HTTPStatusError as exc:
            logger.error(f"HTTP error calling MCP get_schema: {exc}")
            raise MCPError(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.RequestError as exc:
            logger.error(f"Request error calling MCP get_schema: {exc}")
            raise MCPError(f"Connection error: {str(exc)}") from exc
        except Exception as exc:
            logger.error(f"Unexpected error calling MCP get_schema: {exc}")
            raise MCPError(f"Unexpected error: {str(exc)}") from exc
    
    def _parse_schema_text(self, schema_text: str) -> list:
        """Parse schema text to extract table information."""
        # Simple parser for schema text
        # Expected format: lines with "Table: table_name" and column info
        tables = []
        current_table = None
        
        for line in schema_text.split('\n'):
            line = line.strip()
            if line.startswith('Table:'):
                if current_table:
                    tables.append(current_table)
                table_name = line.split(':', 1)[1].strip()
                current_table = {"name": table_name, "columns": []}
            elif line and current_table and '-' in line:
                # Column line (e.g., "- id: INTEGER")
                current_table["columns"].append(line)
        
        if current_table:
            tables.append(current_table)
        
        return tables

    def get_schema_text(self) -> str:
        """
        Get a human-readable text representation of the schema in English.
        
        Returns:
            Schema as formatted text string
            
        Raises:
            MCPError: If the request fails
        """
        schema_info = self.get_schema()
        
        if not schema_info.tables:
            return "No tables found in database."

        lines = ["Database Schema:", ""]
        
        for table in schema_info.tables:
            table_name = table.get("name", "unknown")
            columns = table.get("columns", [])
            
            lines.append(f"Table: {table_name}")
            
            if columns:
                lines.append("Columns:")
                for col in columns:
                    col_name = col.get("name", "unknown")
                    col_type = col.get("type", "unknown")
                    # MCP server uses 'notNull' and 'pk'
                    not_null = " (NOT NULL)" if col.get("notNull", False) else ""
                    pk_flag = " [PRIMARY KEY]" if col.get("pk", False) else ""
                    lines.append(f"  - {col_name}: {col_type}{not_null}{pk_flag}")
            
            lines.append("")

        return "\n".join(lines)

    def run_sql_select(self, query: str) -> QueryResult:
        """
        Execute a SELECT query via MCP server.
        
        Args:
            query: SQL SELECT query to execute
            
        Returns:
            QueryResult with rows and truncated flag
            
        Raises:
            MCPError: If the request fails or query is invalid
        """
        url = f"{self.base_url}/mcp"
        logger.debug(f"Calling MCP run_sql_select at {url}")
        logger.debug(f"SQL query: {query}")

        # MCP JSON-RPC request
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "sqlite_run_select",
                "arguments": {
                    "query": query
                }
            }
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    }
                )
                resp.raise_for_status()
                data = resp.json()

                # Check for JSON-RPC error
                if "error" in data:
                    error_msg = data["error"].get("message", str(data["error"]))
                    raise MCPError(f"MCP query error: {error_msg}")

                # Extract result from JSON-RPC response
                result = data.get("result", {})
                
                # Check for structured content first (preferred)
                if "structuredContent" in result:
                    structured = result["structuredContent"]
                    rows = structured.get("rows", [])
                    row_count = structured.get("rowCount", len(rows))
                    truncated = row_count > len(rows) if row_count else False
                    return QueryResult(rows=rows, truncated=truncated)
                
                # Fallback: parse text content
                if isinstance(result, dict) and "content" in result:
                    content = result["content"]
                    if isinstance(content, list) and len(content) > 0:
                        # Parse the text response
                        result_text = content[0].get("text", "")
                        rows = self._parse_query_result(result_text)
                        return QueryResult(rows=rows, truncated=False)
                
                # Last resort: try to use result directly
                rows = result.get("rows", [])
                truncated = result.get("truncated", False)
                
                return QueryResult(rows=rows, truncated=truncated)

        except httpx.HTTPStatusError as exc:
            logger.error(f"HTTP error calling MCP run_sql_select: {exc}")
            raise MCPError(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.RequestError as exc:
            logger.error(f"Request error calling MCP run_sql_select: {exc}")
            raise MCPError(f"Connection error: {str(exc)}") from exc
        except Exception as exc:
            logger.error(f"Unexpected error calling MCP run_sql_select: {exc}")
            raise MCPError(f"Unexpected error: {str(exc)}") from exc
    
    def _parse_query_result(self, result_text: str) -> list:
        """Parse query result text into rows."""
        import json
        
        try:
            # Try to parse as JSON first
            parsed = json.loads(result_text)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict) and "rows" in parsed:
                return parsed["rows"]
        except json.JSONDecodeError:
            pass
        
        # If not JSON, return as single row with text
        return [{"result": result_text}]
