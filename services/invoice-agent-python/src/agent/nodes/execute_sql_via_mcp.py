"""
ExecuteSQLViaMCP node - Execute SQL query through MCP server.

Runs the validated query and captures results.
"""

from loguru import logger

from ...integrations.mcp_client import MCPClient, MCPError
from ..state import InvoiceAgentState


def execute_sql_via_mcp(
    state: InvoiceAgentState,
    mcp_client: MCPClient,
) -> InvoiceAgentState:
    """
    Execute SQL query via MCP server.
    
    Args:
        state: Current agent state with validated sql
        mcp_client: MCP client for database access
        
    Returns:
        Updated state with query_result and truncated flag, or error
    """
    logger.info("[ExecuteSQLViaMCP] Executing SQL query")
    
    sql = state.get("sql", "")
    
    if not sql:
        logger.error("[ExecuteSQLViaMCP] No SQL query to execute")
        return {
            **state,
            "error_code": "agent_error",
            "error_message": "No SQL query available for execution",
        }
    
    try:
        result = mcp_client.run_sql_select(sql)
        
        row_count = len(result.rows)
        logger.info(f"[ExecuteSQLViaMCP] Query returned {row_count} rows")
        
        if result.truncated:
            logger.warning("[ExecuteSQLViaMCP] Results were truncated")
        
        return {
            **state,
            "query_result": result.rows,
            "truncated": result.truncated,
        }
    
    except MCPError as exc:
        logger.error(f"[ExecuteSQLViaMCP] MCP error: {exc}")
        return {
            **state,
            "error_code": "mcp_error",
            "error_message": f"Failed to execute SQL query: {str(exc)}",
        }
    except Exception as exc:
        logger.error(f"[ExecuteSQLViaMCP] Unexpected error: {exc}")
        return {
            **state,
            "error_code": "mcp_error",
            "error_message": f"Unexpected error executing query: {str(exc)}",
        }
