"""
ReceiveQuestion node - Entry point for the agent graph.

Loads the current question and retrieves conversation history from memory.
"""

from loguru import logger

from ...core.memory import ConversationTurn, MemoryStore
from ..state import InvoiceAgentState


def receive_question(
    state: InvoiceAgentState,
    memory_store: MemoryStore,
) -> InvoiceAgentState:
    """
    Load question and retrieve conversation history.
    
    Args:
        state: Current agent state with session_id and question
        memory_store: Memory store to retrieve history
        
    Returns:
        Updated state with history populated
    """
    session_id = state["session_id"]
    question = state["question"]
    
    logger.info(f"[ReceiveQuestion] session_id={session_id}, question={question}")
    
    # Retrieve conversation history
    history_turns = memory_store.get_history(session_id)
    
    # Convert to state format
    history = [
        {
            "user_question": turn.user_question,
            "assistant_answer": turn.assistant_answer,
            "sql": turn.sql,
        }
        for turn in history_turns
    ]
    
    logger.debug(f"[ReceiveQuestion] Retrieved {len(history)} previous turns")
    
    return {
        **state,
        "history": history,
    }
