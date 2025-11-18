"""
Memory management for conversation history per session.

Stores conversation turns in RAM to support contextual follow-up questions
like "and the invoice?" or "what about that product?".
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ConversationTurn:
    """Represents a single turn in the conversation."""

    user_question: str
    assistant_answer: str
    sql: Optional[str] = None


@dataclass
class MemoryStore:
    """
    In-memory storage for conversation history by session_id.
    
    This is sufficient for the TP scope. For production, consider
    using Redis or a database.
    """

    _sessions: Dict[str, List[ConversationTurn]] = field(default_factory=dict)
    max_turns: int = 5

    def get_history(self, session_id: str) -> List[ConversationTurn]:
        """
        Retrieve conversation history for a session.
        
        Args:
            session_id: Unique identifier for the session
            
        Returns:
            List of conversation turns (empty if session doesn't exist)
        """
        return self._sessions.get(session_id, [])

    def append_turn(
        self,
        session_id: str,
        turn: ConversationTurn,
    ) -> None:
        """
        Append a new turn to the session history.
        
        Args:
            session_id: Unique identifier for the session
            turn: The conversation turn to append
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        
        self._sessions[session_id].append(turn)

    def trim_history(
        self,
        session_id: str,
        max_turns: Optional[int] = None,
    ) -> None:
        """
        Trim the history to keep only the last N turns.
        
        Args:
            session_id: Unique identifier for the session
            max_turns: Maximum number of turns to keep (defaults to self.max_turns)
        """
        limit = max_turns if max_turns is not None else self.max_turns
        
        if session_id in self._sessions:
            self._sessions[session_id] = self._sessions[session_id][-limit:]

    def clear_session(self, session_id: str) -> None:
        """
        Clear all history for a session.
        
        Args:
            session_id: Unique identifier for the session
        """
        if session_id in self._sessions:
            del self._sessions[session_id]

    def clear_all(self) -> None:
        """Clear all sessions from memory."""
        self._sessions.clear()
