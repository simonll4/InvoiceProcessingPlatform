"""
LangGraph definition for the Invoice Agent.

This graph orchestrates the flow from question to answer:
1. ReceiveQuestion - Load question and history
2. EnsureSchema - Get DB schema from MCP
3. GenerateSQL - Use LLM to create SQL query
4. ValidateSQL - Ensure query is safe
5. ExecuteSQLViaMCP - Run query through MCP
6. GenerateAnswer - Use LLM to create Spanish response
7. HandleError - Convert errors to Spanish messages

All nodes return InvoiceAgentState with updates.
"""

from functools import partial
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph
from loguru import logger

from ..core.memory import ConversationTurn, MemoryStore
from ..integrations.mcp_client import MCPClient
from .nodes import (
    ensure_schema,
    execute_sql_via_mcp,
    generate_answer,
    generate_sql,
    handle_error,
    receive_question,
    validate_sql,
)
from .state import InvoiceAgentState


def _should_handle_error(state: InvoiceAgentState) -> Literal["handle_error", "continue"]:
    """
    Routing function to check if we should handle an error.
    
    Args:
        state: Current agent state
        
    Returns:
        "handle_error" if error_code is set, "continue" otherwise
    """
    if state.get("error_code"):
        return "handle_error"
    return "continue"


def _after_generate_answer(state: InvoiceAgentState) -> Literal["handle_error", "end"]:
    """
    Routing after GenerateAnswer node.
    
    Args:
        state: Current agent state
        
    Returns:
        "handle_error" if error occurred, "end" otherwise
    """
    if state.get("error_code"):
        return "handle_error"
    return "end"


def build_graph(
    llm: BaseChatModel,
    mcp_client: MCPClient,
    memory_store: MemoryStore,
) -> StateGraph:
    """
    Build the complete LangGraph for invoice agent.
    
    Args:
        llm: Language model (ChatGroq) for SQL generation and answer generation
        mcp_client: MCP client for database access
        memory_store: Memory store for conversation history
        
    Returns:
        Compiled StateGraph ready to invoke
    """
    logger.info("[BuildGraph] Creating Invoice Agent graph")
    
    # Create the graph
    graph = StateGraph(InvoiceAgentState)
    
    # Bind dependencies to nodes using partial
    receive_question_node = partial(receive_question, memory_store=memory_store)
    ensure_schema_node = partial(ensure_schema, mcp_client=mcp_client)
    generate_sql_node = partial(generate_sql, llm=llm)
    validate_sql_node = validate_sql
    execute_sql_node = partial(execute_sql_via_mcp, mcp_client=mcp_client)
    generate_answer_node = partial(generate_answer, llm=llm)
    handle_error_node = handle_error
    
    # Add nodes
    graph.add_node("receive_question", receive_question_node)
    graph.add_node("ensure_schema", ensure_schema_node)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("execute_sql_via_mcp", execute_sql_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("handle_error", handle_error_node)
    
    # Set entry point
    graph.set_entry_point("receive_question")
    
    # Define edges
    # ReceiveQuestion -> EnsureSchema (always)
    graph.add_edge("receive_question", "ensure_schema")
    
    # EnsureSchema -> GenerateSQL or HandleError
    graph.add_conditional_edges(
        "ensure_schema",
        _should_handle_error,
        {
            "handle_error": "handle_error",
            "continue": "generate_sql",
        },
    )
    
    # GenerateSQL -> ValidateSQL or HandleError
    graph.add_conditional_edges(
        "generate_sql",
        _should_handle_error,
        {
            "handle_error": "handle_error",
            "continue": "validate_sql",
        },
    )
    
    # ValidateSQL -> ExecuteSQLViaMCP or HandleError
    graph.add_conditional_edges(
        "validate_sql",
        _should_handle_error,
        {
            "handle_error": "handle_error",
            "continue": "execute_sql_via_mcp",
        },
    )
    
    # ExecuteSQLViaMCP -> GenerateAnswer or HandleError
    graph.add_conditional_edges(
        "execute_sql_via_mcp",
        _should_handle_error,
        {
            "handle_error": "handle_error",
            "continue": "generate_answer",
        },
    )
    
    # GenerateAnswer -> END or HandleError
    graph.add_conditional_edges(
        "generate_answer",
        _after_generate_answer,
        {
            "handle_error": "handle_error",
            "end": END,
        },
    )
    
    # HandleError -> END (always)
    graph.add_edge("handle_error", END)
    
    # Compile the graph
    compiled_graph = graph.compile()
    
    logger.info("[BuildGraph] Graph compiled successfully")
    
    return compiled_graph


def save_to_memory(
    state: InvoiceAgentState,
    memory_store: MemoryStore,
) -> None:
    """
    Save the completed turn to memory after successful execution.
    
    This should be called after the graph execution is complete.
    
    Args:
        state: Final agent state with answer
        memory_store: Memory store to update
    """
    session_id = state.get("session_id")
    question = state.get("question")
    answer = state.get("answer")
    sql = state.get("sql")
    
    if not session_id or not question or not answer:
        logger.warning("[SaveToMemory] Missing required fields, not saving to memory")
        return
    
    # Create conversation turn
    turn = ConversationTurn(
        user_question=question,
        assistant_answer=answer,
        sql=sql,
    )
    
    # Append to memory
    memory_store.append_turn(session_id, turn)
    
    # Trim to keep only last N turns
    memory_store.trim_history(session_id)
    
    logger.info(f"[SaveToMemory] Saved turn to memory for session {session_id}")


