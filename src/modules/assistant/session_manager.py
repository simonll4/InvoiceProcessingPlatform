"""Session manager - manejo de conversaciones con historial."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from .config import MAX_HISTORY_MESSAGES, SESSION_TIMEOUT_SECONDS


@dataclass
class ChatSession:
    """Representa una sesión de chat con historial."""

    session_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        """Agrega un mensaje al historial."""
        self.messages.append({"role": role, "content": content})
        self.last_activity = time.time()

        # Keep only last N messages
        if len(self.messages) > MAX_HISTORY_MESSAGES * 2:  # user + assistant pairs
            self.messages = self.messages[-MAX_HISTORY_MESSAGES * 2 :]

    def is_expired(self) -> bool:
        """Verifica si la sesión expiró por inactividad."""
        return (time.time() - self.last_activity) > SESSION_TIMEOUT_SECONDS

    def get_history(self) -> list[dict[str, Any]]:
        """Retorna el historial de mensajes."""
        return self.messages.copy()


class SessionManager:
    """
    Maneja sesiones de chat en memoria.

    Nota: Para producción con múltiples instancias, esto debería
    moverse a Redis u otro storage distribuido.
    """

    def __init__(self):
        self.sessions: dict[str, ChatSession] = {}
        logger.info("SessionManager initialized (in-memory)")

    def create_session(self) -> str:
        """Crea una nueva sesión y retorna su ID."""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = ChatSession(session_id=session_id)
        logger.info(f"Session created: {session_id}")
        return session_id

    def get_session(self, session_id: str) -> ChatSession | None:
        """Get a session by ID, or None if it doesn't exist/expired."""
        session = self.sessions.get(session_id)

        if session is None:
            return None

        if session.is_expired():
            logger.info(f"Session expired: {session_id}")
            del self.sessions[session_id]
            return None

        return session

    def add_message_to_session(self, session_id: str, role: str, content: str) -> bool:
        """
        Add a message to a session.

        Returns:
            True if added successfully, False if session doesn't exist.
        """
        session = self.get_session(session_id)
        if session is None:
            return False

        session.add_message(role, content)
        return True

    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.

        Returns:
            Number of deleted sessions.
        """
        expired = [
            sid for sid, session in self.sessions.items() if session.is_expired()
        ]

        for sid in expired:
            del self.sessions[sid]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")

        return len(expired)

    def get_stats(self) -> dict[str, Any]:
        """Retorna estadísticas de las sesiones."""
        return {
            "total_sessions": len(self.sessions),
            "session_ids": list(self.sessions.keys()),
        }
