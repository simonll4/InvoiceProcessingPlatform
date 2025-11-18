"""
HandleError node - Convert errors into user-friendly Spanish messages.

Takes error_code and error_message (in English) and produces a Spanish answer.
"""

from loguru import logger

from ..state import InvoiceAgentState


# Error message templates in Spanish
ERROR_TEMPLATES = {
    "validation_error": "Lo siento, no puedo procesar esa consulta porque no cumple con las reglas de seguridad.",
    "mcp_error": "Lo siento, hubo un problema al acceder a la base de datos. Por favor, intenta de nuevo más tarde.",
    "agent_error": "Lo siento, no pude procesar tu pregunta en este momento. Por favor, intenta reformularla.",
}


def handle_error(state: InvoiceAgentState) -> InvoiceAgentState:
    """
    Handle errors by generating a user-friendly Spanish message.
    
    Args:
        state: Current agent state with error_code and error_message
        
    Returns:
        Updated state with answer in Spanish
    """
    error_code = state.get("error_code", "unknown_error")
    error_message = state.get("error_message", "Unknown error occurred")
    
    logger.warning(f"[HandleError] Handling error: {error_code} - {error_message}")
    
    # Get Spanish template for this error type
    spanish_message = ERROR_TEMPLATES.get(
        error_code,
        "Lo siento, ocurrió un error inesperado. Por favor, intenta de nuevo.",
    )
    
    # If we want to provide more context, we could call LLM here to generate
    # a more specific Spanish error message. For now, keep it simple.
    
    logger.info(f"[HandleError] Error message in Spanish: {spanish_message}")
    
    return {
        **state,
        "answer": spanish_message,
        # Keep error_code and error_message for API response
    }
