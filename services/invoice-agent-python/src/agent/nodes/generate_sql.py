"""
GenerateSQL node - Use LLM to generate SQL query.

Uses conversation history and schema to generate a SELECT query.
All prompts are in English, but handles Spanish user questions.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from ..state import InvoiceAgentState


SYSTEM_PROMPT = """You are an expert SQLite query generator for an invoice database system.

Your task is to:
1. Understand the user's question (which may be in Spanish or English)
2. Use the conversation history for context (to understand references like "la factura" or "ese producto")
3. Generate a single, safe SQLite SELECT query that answers the current question

CRITICAL RULES:
- Output ONLY the SQL query, nothing else
- Use only SELECT statements
- NEVER use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE or any DDL/DML
- The query must be valid SQLite syntax
- Use the provided schema to ensure correct table and column names
- Consider the conversation history to resolve ambiguous references

SQL BEST PRACTICES:
- When using aggregate functions (COUNT, SUM, AVG, MAX, MIN), ALWAYS include GROUP BY
- DISTINCT and aggregate functions cannot be used together in most cases
- For "top N" or "principales" queries, use: SELECT column, COUNT(*) as total FROM table GROUP BY column ORDER BY total DESC LIMIT N
- For date ranges, use strftime() or BETWEEN with proper date format
- Always alias aggregate columns for clarity (e.g., COUNT(*) as total_invoices)

COMMON QUERY PATTERNS:
- Top vendors: SELECT vendor_name, COUNT(*) as total FROM invoices GROUP BY vendor_name ORDER BY total DESC LIMIT 10
- Total amount: SELECT SUM(total_cents)/100.0 as total FROM invoices
- Count invoices: SELECT COUNT(*) as total FROM invoices
- Recent invoices: SELECT * FROM invoices ORDER BY invoice_date DESC LIMIT N

If you cannot generate a valid query, output exactly: "CANNOT_GENERATE_QUERY"
"""


def _format_history(history: list) -> str:
    """Format conversation history for the prompt."""
    if not history:
        return "No previous conversation."

    lines = []
    for i, turn in enumerate(history, 1):
        lines.append(f"{i}) User: \"{turn['user_question']}\"")
        lines.append(f"   Assistant: \"{turn['assistant_answer']}\"")
        if turn.get("sql"):
            lines.append(f"   SQL: {turn['sql']}")

    return "\n".join(lines)


def generate_sql(
    state: InvoiceAgentState,
    llm: BaseChatModel,
) -> InvoiceAgentState:
    """
    Generate SQL query using LLM with conversation context.

    Args:
        state: Current agent state with question, history, schema
        llm: Language model (ChatGroq)

    Returns:
        Updated state with sql or error
    """
    logger.info("[GenerateSQL] Generating SQL query with LLM")

    question = state["question"]
    history = state.get("history", [])
    schema = state.get("schema", "")

    if not schema:
        logger.error("[GenerateSQL] No schema available")
        return {
            **state,
            "error_code": "agent_error",
            "error_message": "Database schema not available for query generation",
        }

    # Build the prompt
    history_text = _format_history(history)

    user_prompt = f"""Conversation history:
{history_text}

Current question:
"{question}"

Database schema:
{schema}

Generate the SQL SELECT query to answer the current question."""

    try:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        logger.debug(f"[GenerateSQL] Calling LLM with {len(history)} turns of history")
        response = llm.invoke(messages)

        sql = response.content.strip()

        if not sql or sql == "CANNOT_GENERATE_QUERY":
            logger.warning("[GenerateSQL] LLM could not generate a valid query")
            return {
                **state,
                "error_code": "agent_error",
                "error_message": "The model could not generate a SQL query for this question",
            }

        logger.info(f"[GenerateSQL] Generated SQL: {sql}")

        return {
            **state,
            "sql": sql,
        }

    except Exception as exc:
        logger.error(f"[GenerateSQL] Error calling LLM: {exc}")
        return {
            **state,
            "error_code": "agent_error",
            "error_message": f"Failed to generate SQL query: {str(exc)}",
        }
