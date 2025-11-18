"""
EnsureSchema node - Retrieve database schema from MCP.

Gets the schema and converts it to a human-readable English description.
"""

from loguru import logger

from ...integrations.mcp_client import MCPClient, MCPError
from ..state import InvoiceAgentState


def ensure_schema(
    state: InvoiceAgentState,
    mcp_client: MCPClient,
) -> InvoiceAgentState:
    """
    Retrieve database schema from MCP server.
    
    Args:
        state: Current agent state
        mcp_client: MCP client for database access
        
    Returns:
        Updated state with schema or error
    """
    logger.info("[EnsureSchema] Retrieving database schema from MCP")
    
    try:
        schema_text = mcp_client.get_schema_text()
        logger.debug(f"[EnsureSchema] Schema retrieved successfully")
        
        return {
            **state,
            "schema": schema_text,
        }
    
    except MCPError as exc:
        logger.error(f"[EnsureSchema] MCP error: {exc}")
        return {
            **state,
            "error_code": "mcp_error",
            "error_message": f"Failed to retrieve database schema: {str(exc)}",
        }
    except Exception as exc:
        logger.error(f"[EnsureSchema] Unexpected error: {exc}")
        return {
            **state,
            "error_code": "mcp_error",
            "error_message": f"Unexpected error retrieving schema: {str(exc)}",
        }
