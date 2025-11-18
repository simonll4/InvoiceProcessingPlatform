"""
Dependency injection for Invoice Agent service.

Initializes and wires together:
- ChatGroq (LLM)
- MCPClient (database access)
- MemoryStore (conversation history)
- LangGraph (compiled graph)
"""

from functools import lru_cache

from langchain_groq import ChatGroq
from loguru import logger

from .agent.graph import build_graph
from .config import settings
from .core.memory import MemoryStore
from .integrations.mcp_client import MCPClient


@lru_cache(maxsize=1)
def get_llm() -> ChatGroq:
    """
    Get or create the ChatGroq LLM instance.
    
    Returns:
        Configured ChatGroq instance
    """
    logger.info("[DI] Initializing ChatGroq LLM")
    
    llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=settings.groq_temperature,
        max_retries=settings.groq_max_retries,
    )
    
    logger.info(f"[DI] ChatGroq initialized with model: {settings.groq_model}")
    return llm


@lru_cache(maxsize=1)
def get_mcp_client() -> MCPClient:
    """
    Get or create the MCP client instance.
    
    Returns:
        Configured MCPClient instance
    """
    logger.info("[DI] Initializing MCP client")
    
    client = MCPClient(
        base_url=settings.mcp_endpoint,
        timeout=settings.mcp_timeout,
    )
    
    logger.info(f"[DI] MCP client initialized: {settings.mcp_endpoint}")
    return client


@lru_cache(maxsize=1)
def get_memory_store() -> MemoryStore:
    """
    Get or create the memory store instance.
    
    Returns:
        Configured MemoryStore instance
    """
    logger.info("[DI] Initializing MemoryStore")
    
    store = MemoryStore(max_turns=settings.max_history_turns)
    
    logger.info(f"[DI] MemoryStore initialized with max_turns: {settings.max_history_turns}")
    return store


@lru_cache(maxsize=1)
def get_graph():
    """
    Get or create the compiled LangGraph.
    
    Returns:
        Compiled StateGraph ready to invoke
    """
    logger.info("[DI] Building and compiling LangGraph")
    
    llm = get_llm()
    mcp_client = get_mcp_client()
    memory_store = get_memory_store()
    
    graph = build_graph(
        llm=llm,
        mcp_client=mcp_client,
        memory_store=memory_store,
    )
    
    logger.info("[DI] LangGraph compiled successfully")
    return graph
