"""
GenerateAnswer node - Generate final answer in Spanish using LLM.

Uses query results and conversation context to produce user-facing response.
"""

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from ..state import InvoiceAgentState


SYSTEM_PROMPT = """You are a helpful assistant that explains database query results to Spanish-speaking users.

Your task is to:
1. Read the user's original question (which may be in Spanish)
2. Review the conversation history for context
3. Examine the SQL query that was executed
4. Analyze the query results (as JSON)
5. Produce a clear, concise answer IN SPANISH

CRITICAL RULES:
- Always respond in SPANISH (even if the question was in English)
- Be concise and direct
- If results were truncated, mention that only partial data is shown
- Do NOT explain the SQL query unless asked
- Do NOT add technical details unless relevant to the user
- If no results were found, say so clearly in Spanish
- Format numbers, dates, and currency appropriately for Spanish users

Your answer should directly address the user's question based on the data.
"""


def _format_history(history: list) -> str:
    """Format conversation history for the prompt."""
    if not history:
        return "No previous conversation."
    
    lines = []
    for i, turn in enumerate(history, 1):
        lines.append(f"{i}) User: \"{turn['user_question']}\"")
        lines.append(f"   Assistant: \"{turn['assistant_answer']}\"")
    
    return "\n".join(lines)


def generate_answer(
    state: InvoiceAgentState,
    llm: BaseChatModel,
) -> InvoiceAgentState:
    """
    Generate final answer in Spanish using LLM.
    
    Args:
        state: Current agent state with question, history, sql, query_result
        llm: Language model (ChatGroq)
        
    Returns:
        Updated state with answer or error
    """
    logger.info("[GenerateAnswer] Generating final answer in Spanish")
    
    question = state["question"]
    history = state.get("history", [])
    sql = state.get("sql", "")
    query_result = state.get("query_result", [])
    truncated = state.get("truncated", False)
    
    # Build the prompt
    history_text = _format_history(history)
    
    # Convert query results to JSON string for LLM
    if query_result:
        # Limit the data sent to LLM to avoid token overflow
        result_preview = query_result[:100] if len(query_result) > 100 else query_result
        result_json = json.dumps(result_preview, indent=2, ensure_ascii=False)
        
        if len(query_result) > 100:
            result_json += f"\n... ({len(query_result) - 100} more rows not shown in prompt)"
    else:
        result_json = "[]"
    
    user_prompt = f"""Conversation history:
{history_text}

Current user question:
"{question}"

SQL query executed:
{sql}

Query results (as JSON):
{result_json}

Results truncated due to row limit: {truncated}

Please provide a clear answer in SPANISH that addresses the user's question."""
    
    try:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        
        logger.debug(f"[GenerateAnswer] Calling LLM with {len(query_result)} result rows")
        response = llm.invoke(messages)
        
        answer = response.content.strip()
        
        if not answer:
            logger.warning("[GenerateAnswer] LLM returned empty answer")
            return {
                **state,
                "error_code": "agent_error",
                "error_message": "The model failed to generate a final answer",
            }
        
        logger.info(f"[GenerateAnswer] Answer generated successfully")
        logger.debug(f"[GenerateAnswer] Answer: {answer[:100]}...")
        
        return {
            **state,
            "answer": answer,
        }
    
    except Exception as exc:
        logger.error(f"[GenerateAnswer] Error calling LLM: {exc}")
        return {
            **state,
            "error_code": "agent_error",
            "error_message": f"Failed to generate final answer: {str(exc)}",
        }
