"""
Invoice Agent State definition for LangGraph.

Minimal state that flows through all nodes in the graph.
Supports conversation memory and Spanish responses with English error codes.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ConversationTurn(TypedDict):
    """A single turn in the conversation history."""

    user_question: str
    assistant_answer: str
    sql: Optional[str]


class InvoiceAgentState(TypedDict, total=False):
    """
    State shared between all nodes in the LangGraph workflow.
    
    Fields:
        session_id: Unique identifier for the conversation session
        question: Current user question (can be in Spanish)
        history: Previous conversation turns for context
        schema: Database schema description in English
        sql: Generated SQL SELECT query
        query_result: Rows returned from database (list of dicts)
        truncated: Whether results were truncated due to row limit
        answer: Final answer to user in Spanish
        error_code: Error code in English (e.g., 'validation_error', 'mcp_error')
        error_message: Technical error message in English
    """

    session_id: str
    question: str
    history: List[ConversationTurn]
    schema: Optional[str]
    sql: Optional[str]
    query_result: Optional[List[Dict[str, Any]]]
    truncated: Optional[bool]
    answer: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]


