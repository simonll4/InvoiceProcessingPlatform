"""
MCP Client types and data structures.
"""

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class QueryResult:
    """Result from executing a SQL query via MCP."""

    rows: List[Dict[str, Any]]
    truncated: bool = False


@dataclass
class SchemaInfo:
    """Database schema information from MCP."""

    tables: List[Dict[str, Any]]
    raw_schema: Dict[str, Any]
