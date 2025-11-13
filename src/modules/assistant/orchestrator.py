"""Groq-backed two-pass orchestrator for SQL planning and summarization."""

from __future__ import annotations

import json
import math
import re
import textwrap
from itertools import islice
from typing import Any, Iterable

import requests
from loguru import logger

from .cache import ResponseCache
from .config import (
    DISABLE_FALLBACK,
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_MODEL_SQL,
    LLM_MODEL_SUMMARY,
    LLM_REQUEST_TIMEOUT,
    MAX_HISTORY_MESSAGES,
)
from .mcp_server import SQLiteMCPServer
from ..pipeline.llm.rate_limiter import get_rate_limiter


class PlanParseError(RuntimeError):
    """Raised when the planner returns an unexpected payload."""


class LLMOrchestrator:
    """Execute Groq two-pass workflow: plan SQL, execute tools, summarize."""

    MAX_TOOL_ROWS = 50  # Increased to process more results without artificial limits
    MAX_CELL_LENGTH = 180  # Increased for longer descriptions
    MAX_PLAN_ATTEMPTS = 4  # Increased for better retry with feedback
    AGGREGATION_THRESHOLD = 20  # For aggregations (COUNT, SUM, etc), show more rows

    def __init__(self, mcp_server: SQLiteMCPServer, cache_ttl: int = 300):
        self.mcp_server = mcp_server
        self.cache = ResponseCache(ttl_seconds=cache_ttl)
        self.plan_model = LLM_MODEL_SQL or LLM_MODEL
        self.summary_model = LLM_MODEL_SUMMARY or LLM_MODEL
        self.api_base = (LLM_API_BASE or "https://api.groq.com/openai/v1").rstrip("/")
        self.headers = self._build_headers()
        self.schema_summary = self._build_schema_summary()
        self.tool_manifest = self.mcp_server.get_tools_description()
        self.tool_lookup = {
            entry.get("function", {}).get("name"): entry for entry in self.tool_manifest
        }
        self.plan_system_prompt = self._build_plan_system_prompt()
        self.summary_system_prompt = self._build_summary_system_prompt()
        logger.info(
            "Groq two-pass orchestrator ready | plan_model=%s summary_model=%s",
            self.plan_model,
            self.summary_model,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process_question(
        self,
        question: str,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        trimmed_history = self._trim_history(history)
        short_reply = self._try_local_response(question)
        if short_reply:
            return short_reply

        cached = self.cache.get(question)
        if cached:
            logger.info("✓ Cache hit for question: %s", question[:60])
            return {
                "success": True,
                "answer": cached.get("answer", ""),
                "tool_calls": cached.get("metadata", {}).get("tool_calls", []),
                "cached": True,
            }

        history_text = self._format_history(trimmed_history)

        plan_result = self._plan_with_feedback(question, history_text)
        plan = plan_result["plan"]
        tool_runs = plan_result["tool_runs"]
        plan_responses = plan_result["plan_responses"]
        plan_response = plan_responses[-1] if plan_responses else {}

        # Si el modelo decidió que no necesita datos (ej: fuera de dominio)
        if not plan.get("needs_data") and not tool_runs:
            notes = plan.get("notes", "")
            if notes:
                answer = notes
            else:
                answer = "Lo siento, solo puedo responder preguntas relacionadas con los datos de facturas en mi base de datos."
            return {
                "success": True,
                "answer": answer,
                "plan": plan,
                "tool_calls": [],
                "cached": False,
            }

        summary_messages = self._build_summary_messages(
            question=question,
            history=history_text,
            plan=plan,
            tool_runs=tool_runs,
        )
        summary_response = self._call_groq(
            model=self.summary_model,
            messages=summary_messages,
            max_tokens=280,  # Increased for 3-6 sentences with disclaimers
            temperature=0.2,
            tag="assistant_summary",
        )
        answer = self._extract_message_content(summary_response).strip()

        fingerprint = self._fingerprint(plan, tool_runs)
        metadata = {
            "plan": plan,
            "tool_calls": tool_runs,
            "fingerprint": fingerprint,
            "plan_attempts": plan_responses,
            "plan_feedback": plan_result.get("feedback_history", []),
        }
        self.cache.set(question, answer, metadata)

        return {
            "success": True,
            "answer": answer,
            "plan": plan,
            "tool_calls": tool_runs,
            "raw_plan_response": plan_response,
            "raw_summary_response": summary_response,
            "cached": False,
        }

    # ------------------------------------------------------------------
    # Planner helpers
    # ------------------------------------------------------------------
    def _build_plan_system_prompt(self) -> str:
        tools_text = self._describe_tools()
        return textwrap.dedent(
            f"""
            You are an expert SQL analyst for an invoices database. Design a tool-based plan
            that answers the question using only the available SQLite database.

            ═══════════════════════════════════════════════════════════════════════════════
            RULE 0 — DOMAIN & SCHEMA:
            ═══════════════════════════════════════════════════════════════════════════════
            1. You ONLY answer questions about data in this invoices database. If the question
               is about something unrelated (weather, sports, general knowledge, etc.), set
               "needs_data" to false and explain that you only work with invoice data.

            2. ALWAYS call `get_database_schema` as your FIRST step when needs_data=true.
               This is MANDATORY. NEVER invent or guess table/column names.

            3. After consulting the schema, propose a read-only SQL query using
               `execute_sql_query` or use a specialized tool. Every SQL MUST begin with 
               SELECT, PRAGMA, or EXPLAIN.

            4. Let the schema be your source of truth: if you cannot find relevant tables or
               columns for the question, set "needs_data" to false and explain the limitation.
            ═══════════════════════════════════════════════════════════════════════════════

            ALWAYS return valid JSON with the following structure:
            {{
              "needs_data": true | false,
              "steps": [
                {{
                  "id": "step1",
                  "tool": "get_database_schema",
                  "description": "Inspect schema to confirm table/column names",
                  "arguments": {{}}
                }},
                {{
                  "id": "step2",
                  "tool": "execute_sql_query",
                  "description": "Query the relevant data",
                  "arguments": {{"sql": "SELECT ..."}}
                }}
              ],
              "notes": "optional comments"
            }}

            Additional rules:
            - Use only the available tool names listed below.
            - Keep a maximum of three concise, relevant steps.
            - If you can answer directly without data (e.g., greetings), set "needs_data" to false.
            - Describe calculated fields to help the second pass summarization.
            - If the question is outside the invoices domain, politely decline.

            Available tools:
            {tools_text}
            """
        ).strip()

    def _build_summary_system_prompt(self) -> str:
        return textwrap.dedent(
            """
            You are an assistant that writes concise conclusions in Spanish based solely on the
            structured digest provided. Reply in 3–6 sentences, cite key values with their units
            or currency, and warn if information is missing.
            
            CRITICAL RULES FOR ACCURACY:
            - If row_count=0, clearly state "No se encontraron datos para esa consulta."
            - If complete_result=true in the digest, present ALL data without mentioning truncation.
            - If complete_result=false and omitted_rows > 0, mention how many total results exist.
            
            CURRENCY HANDLING (MANDATORY):
            - ALWAYS mention the currency for monetary amounts (USD, EUR, ARS, etc.).
            - If data contains multiple currencies, present them separately (e.g., "3,738,565 centavos USD, 400,241 centavos EUR, 3,714,524 centavos ARS").
            - NEVER sum amounts in different currencies without explicitly converting them first.
            - When showing total_cents or line_total_cents, always specify the currency.
            
            DATA ACCURACY:
            - Use ONLY the exact values from the digest. Do NOT invent, approximate, or guess.
            - If a value is missing or null in the digest, acknowledge it clearly.
            - Present numeric values exactly as they appear (do not round unless asked).
            - If the digest is empty or minimal, acknowledge the limitation clearly.
            
            PRESENTATION:
            - Present the data naturally without mentioning technical limitations unless necessary.
            - Use clear, professional Spanish with proper formatting for numbers and lists.
            """
        ).strip()

    def _build_plan_messages(
        self,
        question: str,
        history: str,
        feedback: str | None = None,
    ) -> list[dict[str, str]]:
        sections = [
            textwrap.dedent(
                f"""
                ### User question
                {question}

                ### Conversation history
                {history or 'No prior history.'}

                ### Known schema summary
                {self.schema_summary}
                """
            ).strip()
        ]

        if feedback:
            sections.append(
                textwrap.dedent(
                    f"""
                    ### Feedback from previous attempt
                    {feedback.strip()}
                    """
                ).strip()
            )

        user_content = "\n\n".join(sections)
        return [
            {"role": "system", "content": self.plan_system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _plan_with_feedback(
        self,
        question: str,
        history_text: str,
    ) -> dict[str, Any]:
        feedback_history: list[str] = []
        feedback: str | None = None
        plan_responses: list[dict[str, Any]] = []
        plan: dict[str, Any] = {"needs_data": False, "steps": [], "notes": None}
        tool_runs: list[dict[str, Any]] = []
        plan_content: str = ""
        last_issue: dict[str, Any] | None = None
        fallback_plan: dict[str, Any] | None = None
        used_fallback = False

        for attempt in range(1, self.MAX_PLAN_ATTEMPTS + 1):
            plan_messages = self._build_plan_messages(question, history_text, feedback)
            plan_response = self._call_groq(
                model=self.plan_model,
                messages=plan_messages,
                max_tokens=256,  # Compact JSON plan (64-96 sufficient for simple plans)
                temperature=0.0,
                tag=f"assistant_plan_attempt_{attempt}",
            )
            plan_responses.append(plan_response)
            plan_content = self._extract_message_content(plan_response)

            try:
                plan = self._parse_plan(plan_content)
            except PlanParseError as exc:
                logger.error("Planner parse error: %s", exc)
                plan = {
                    "needs_data": False,
                    "steps": [],
                    "notes": "Unable to interpret the plan produced by the model.",
                    "error": str(exc),
                }

            logger.debug("Planner output attempt %s: %s", attempt, plan)

            if fallback_plan is None and not DISABLE_FALLBACK:
                fallback_plan = self._build_fallback_plan(question)

            if ((not plan.get("steps")) or not plan.get("needs_data")) and fallback_plan and not DISABLE_FALLBACK:
                logger.info("Applying fallback plan for question: %s", question[:80])
                plan = fallback_plan
                used_fallback = True

            tool_runs = self._execute_plan(plan)
            last_issue = self._analyze_tool_runs(plan, tool_runs)
            if not last_issue:
                break

            if used_fallback:
                logger.warning(
                    "Fallback plan did not resolve the issue for question: %s",
                    question[:80],
                )
                break

            feedback = self._build_retry_feedback(last_issue)
            feedback_history.append(feedback)

        if last_issue and not used_fallback and fallback_plan and not DISABLE_FALLBACK:
            logger.info(
                "Planner attempts failed; retrying with fallback plan for question: %s",
                question[:80],
            )
            plan = fallback_plan
            tool_runs = self._execute_plan(plan)
            last_issue = self._analyze_tool_runs(plan, tool_runs)
            used_fallback = True

        return {
            "plan": plan,
            "tool_runs": tool_runs,
            "plan_responses": plan_responses,
            "plan_content": plan_content,
            "feedback_history": feedback_history,
        }

    def _analyze_tool_runs(
        self,
        plan: dict[str, Any],
        tool_runs: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not plan.get("needs_data"):
            return None

        has_sql = False
        for run in tool_runs:
            if run.get("tool") != "execute_sql_query":
                continue
            has_sql = True
            summary = run.get("summary", {})
            success = summary.get("success", True)
            error_msg = summary.get("error") or run.get("error")
            if not success or error_msg:
                sql = run.get("arguments", {}).get("sql", "")
                tables = self._extract_table_names(sql)
                return {
                    "error": error_msg or "The query was rejected by the validator.",
                    "sql": sql,
                    "tables": tables,
                }
            row_count = summary.get("row_count")
            if row_count == 0:
                sql = run.get("arguments", {}).get("sql", "")
                tables = self._extract_table_names(sql)
                return {
                    "error": "The query returned zero rows.",
                    "sql": sql,
                    "tables": tables,
                    "zero_rows": True,
                }

        if plan.get("needs_data") and not has_sql:
            return {
                "error": "The plan did not execute any SQL query.",
                "sql": "",
                "tables": set(),
            }

        return None

    def _build_retry_feedback(self, issue: dict[str, Any]) -> str:
        error_msg = issue.get("error") or "An unknown error occurred."
        sql = issue.get("sql") or "(no SQL was executed)"
        tables = issue.get("tables") or set()
        schema_snippet = self._schema_snippet(tables)
        parts = [
            "The previous attempt failed while executing the proposed SQL query.",
            f"MCP error message: {error_msg}",
            "SQL that was sent:",
            f"```sql\n{sql}\n```",
            "Relevant schema snippet:",
            schema_snippet,
        ]
        if issue.get("zero_rows"):
            parts.append(
                "The query returned zero rows. Double-check table names, joins, and filters before proposing the next SQL statement."
            )
        parts.append(
            "Produce a new plan that uses the required tools (including get_database_schema when unsure) and a valid SQL query that follows all rules."
        )
        return "\n".join(parts)

    @staticmethod
    def _extract_table_names(sql: str) -> set[str]:
        if not isinstance(sql, str):
            return set()
        pattern = r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w]*)"
        return {
            match.lower() for match in re.findall(pattern, sql, flags=re.IGNORECASE)
        }

    def _schema_snippet(self, table_names: set[str]) -> str:
        schema = self.mcp_server.get_schema()
        tables = schema.get("tables", {})
        lines: list[str] = []
        for name in sorted(table_names):
            info = (
                tables.get(name) or tables.get(name.lower()) or tables.get(name.upper())
            )
            if not info:
                continue
            columns = info.get("columns", [])
            col_names = ", ".join(col.get("name") for col in columns[:8])
            if len(columns) > 8:
                col_names += ", …"
            lines.append(f"- {name}: {col_names}")

        if not lines:
            table_list = schema.get("summary", {}).get("table_names", [])
            if table_list:
                preview = ", ".join(table_list[:8])
                suffix = "…" if len(table_list) > 8 else ""
                return f"Schema tables detected: {preview}{suffix}"
            return "Schema information was not available in cache."

        return "\n".join(lines)

    def _parse_plan(self, content: str) -> dict[str, Any]:
        cleaned = self._strip_markdown_block(content)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:  # noqa: TRY003
            raise PlanParseError("Planner returned invalid JSON") from exc

        steps_raw = payload.get("steps", [])
        if not isinstance(steps_raw, list):
            raise PlanParseError("Plan steps must be a list")

        steps: list[dict[str, Any]] = []
        for idx, step in enumerate(steps_raw, start=1):
            if not isinstance(step, dict):
                continue
            tool = step.get("tool")
            if not tool or tool not in self.tool_lookup:
                continue
            arguments = step.get("arguments")
            if arguments is None and "sql" in step:
                arguments = {"sql": step["sql"]}
            if not isinstance(arguments, dict):
                arguments = {}
            if tool == "execute_sql_query":
                sql = arguments.get("sql")
                if not isinstance(sql, str):
                    continue
            steps.append(
                {
                    "id": step.get("id") or f"step{idx}",
                    "tool": tool,
                    "description": step.get("description", ""),
                    "arguments": arguments,
                }
            )

        needs_data_flag = payload.get("needs_data")
        if needs_data_flag is None:
            needs_data = bool(steps)
        else:
            needs_data = bool(needs_data_flag) or bool(steps)
        return {
            "needs_data": needs_data,
            "steps": steps,
            "notes": payload.get("notes") or payload.get("comment"),
        }

    def _execute_plan(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        if not plan.get("needs_data"):
            return runs

        for step in plan.get("steps", []):
            tool = step["tool"]
            arguments = step.get("arguments", {})
            logger.info("Executing tool %s with args %s", tool, arguments)
            try:
                raw_result = self.mcp_server.call_tool(tool, arguments)
                summary = self._summarize_tool_result(tool, raw_result)
                runs.append(
                    {
                        "step_id": step.get("id"),
                        "tool": tool,
                        "arguments": arguments,
                        "summary": summary,
                        "raw": raw_result,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Tool execution failed: %s", exc)
                runs.append(
                    {
                        "step_id": step.get("id"),
                        "tool": tool,
                        "arguments": arguments,
                        "summary": {"tool": tool, "success": False, "error": str(exc)},
                        "error": str(exc),
                    }
                )
        return runs

    # ------------------------------------------------------------------
    # Summarizer helpers
    # ------------------------------------------------------------------
    def _build_summary_messages(
        self,
        question: str,
        history: str,
        plan: dict[str, Any],
        tool_runs: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        plan_lines = []
        for step in plan.get("steps", []):
            sql_preview = step.get("arguments", {}).get("sql")
            if sql_preview:
                sql_preview = sql_preview.replace("\n", " ")
            plan_lines.append(
                f"- {step.get('id')}: {step.get('description') or 'no description'} | {step['tool']} | {sql_preview or ''}"
            )
        plan_text = "\n".join(plan_lines) or "(no steps executed)"

        result_lines = []
        for run in tool_runs:
            summary = run.get("summary", {})
            if run.get("tool") == "get_database_schema":
                tables = summary.get("schema_tables") or []
                table_text = ", ".join(tables)
                result_lines.append(
                    f"- {run.get('step_id')}: schema_tables=[{table_text}] total_tables={summary.get('schema_total_tables')}"
                )
                continue
            rows = summary.get("sample_rows") or []
            row_preview = (
                json.dumps(rows[: self.MAX_TOOL_ROWS], ensure_ascii=False)
                if rows
                else ""
            )
            result_lines.append(
                f"- {run.get('step_id')}: success={summary.get('success', True)} rows={summary.get('row_count')} truncated={summary.get('truncated', False)} preview={row_preview}"
            )
        result_text = "\n".join(result_lines) or "(no tools were executed)"

        notes = plan.get("notes") or "No additional planner notes."

        user_content = textwrap.dedent(
            f"""
            ### User question
            {question}

            ### Conversation history
            {history or 'No prior history.'}

            ### Plan executed
            {plan_text}

            ### Tool results digest
            {result_text}

            ### Planner notes
            {notes}

            Draft the final answer in Spanish using only the information above. If the data is
            insufficient, explain that clearly and suggest the next actionable step.
            """
        ).strip()

        return [
            {"role": "system", "content": self.summary_system_prompt},
            {"role": "user", "content": user_content},
        ]

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------
    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if not LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY is required for Groq requests")
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
        return headers

    def _call_groq(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        tag: str,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        rate_limiter = get_rate_limiter()
        estimated_tokens = self._estimate_payload_tokens(messages, max_tokens)
        rate_info = rate_limiter.check_and_wait(estimated_tokens, tag=tag)
        entry_id = rate_info.get("entry_id")

        try:
            response = requests.post(
                f"{self.api_base}/chat/completions",
                headers=self.headers,
                json=payload,
                timeout=LLM_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except Exception:
            if entry_id is not None:
                rate_limiter.cancel_request(entry_id)
            raise

        result = response.json()
        usage = result.get("usage") or {}
        if entry_id is not None:
            prompt_tokens = usage.get("prompt_tokens") or max(
                0, estimated_tokens - max_tokens
            )
            completion_tokens = usage.get("completion_tokens", 0)
            rate_limiter.record_actual_tokens(
                entry_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        return result

    @staticmethod
    def _estimate_payload_tokens(
        messages: Iterable[dict[str, Any]], max_tokens: int
    ) -> int:
        prompt_text = json.dumps(list(messages), ensure_ascii=False)
        return math.ceil(len(prompt_text) / 4) + max_tokens

    @staticmethod
    def _extract_message_content(response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return response.get("message", {}).get("content", "")

    def _summarize_tool_result(
        self, tool_name: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {"tool": tool_name}
        for key in ("success", "row_count", "columns", "error", "query"):
            if key in result:
                summary[key] = result[key]

        if "schema" in result:
            schema = result.get("schema", {})
            summary["schema_tables"] = (schema.get("summary", {}) or {}).get(
                "table_names", []
            )[:8]
            summary["schema_total_tables"] = (schema.get("summary", {}) or {}).get(
                "total_tables"
            )

        rows = result.get("rows")
        if isinstance(rows, list) and rows:
            # Intelligent truncation based on query type
            row_count = len(rows)
            columns = result.get("columns", [])
            is_aggregation = self._is_aggregation_result(columns, rows)
            
            # For aggregations (summary data), show more rows
            # For detailed listings, be more conservative
            max_rows = self.AGGREGATION_THRESHOLD if is_aggregation else self.MAX_TOOL_ROWS
            
            # If result is small enough, include everything
            if row_count <= max_rows:
                preview = []
                for row in rows:
                    compact = {}
                    for key, value in row.items():
                        if value is None:
                            compact[key] = None
                        elif isinstance(value, (int, float, bool)):
                            compact[key] = value
                        else:
                            text = str(value)
                            compact[key] = text[: self.MAX_CELL_LENGTH] + (
                                "…" if len(text) > self.MAX_CELL_LENGTH else ""
                            )
                    preview.append(compact)
                summary["sample_rows"] = preview
                summary["complete_result"] = True
            else:
                # For large results, include top N
                preview = []
                for row in islice(rows, max_rows):
                    compact = {}
                    for key, value in row.items():
                        if value is None:
                            compact[key] = None
                        elif isinstance(value, (int, float, bool)):
                            compact[key] = value
                        else:
                            text = str(value)
                            compact[key] = text[: self.MAX_CELL_LENGTH] + (
                                "…" if len(text) > self.MAX_CELL_LENGTH else ""
                            )
                    preview.append(compact)
                summary["sample_rows"] = preview
                summary["omitted_rows"] = row_count - len(preview)
                summary["complete_result"] = False

        summary["truncated"] = bool(result.get("truncated", False))
        return summary

    @staticmethod
    def _is_aggregation_result(columns: list[str], rows: list[dict]) -> bool:
        """
        Detect if result is an aggregation (summary) vs detailed listing.
        Aggregations typically have: COUNT, SUM, AVG, MAX, MIN in column names,
        or few columns with numeric values.
        """
        if not columns or not rows:
            return False
        
        # Check column names for aggregation functions
        agg_keywords = {'count', 'sum', 'avg', 'max', 'min', 'total', 'average'}
        col_lower = [str(c).lower() for c in columns]
        has_agg_col = any(
            any(kw in col for kw in agg_keywords) 
            for col in col_lower
        )
        
        # If few columns (<=5) and mostly numeric, likely aggregation
        is_compact = len(columns) <= 5
        
        # Check if most values are numeric (aggregations)
        if rows and is_compact:
            first_row = rows[0]
            numeric_count = sum(
                1 for v in first_row.values() 
                if isinstance(v, (int, float))
            )
            is_mostly_numeric = numeric_count >= len(first_row) * 0.5
            
            return has_agg_col or is_mostly_numeric
        
        return has_agg_col

    @staticmethod
    def _fingerprint(plan: dict[str, Any], tool_runs: list[dict[str, Any]]) -> str:
        payload = {
            "plan": plan.get("steps", []),
            "results": [
                {
                    "tool": run.get("tool"),
                    "query": run.get("summary", {}).get("query"),
                    "row_count": run.get("summary", {}).get("row_count"),
                }
                for run in tool_runs
            ],
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def _build_fallback_plan(self, question: str) -> dict[str, Any] | None:
        normalized = question.lower()
        plan_steps: list[dict[str, Any]] = []

        def add_sql_step(sql: str, description: str) -> None:
            plan_steps.append(
                {
                    "id": f"fallback_step{len(plan_steps) + 1}",
                    "tool": "execute_sql_query",
                    "description": description,
                    "arguments": {"sql": sql},
                }
            )

        def add_tool_step(
            tool: str, description: str, arguments: dict[str, Any] | None = None
        ) -> None:
            plan_steps.append(
                {
                    "id": f"fallback_step{len(plan_steps) + 1}",
                    "tool": tool,
                    "description": description,
                    "arguments": arguments or {},
                }
            )

        if any(
            phrase in normalized
            for phrase in [
                "cuántas facturas",
                "cuantas facturas",
                "número de facturas",
                "numero de facturas",
                "cantidad de facturas",
                "how many invoices",
            ]
        ):
            add_sql_step(
                "SELECT COUNT(*) AS total_invoices FROM invoices;",
                "Count how many invoices are stored",
            )

        if any(
            phrase in normalized
            for phrase in [
                "facturas más recientes",
                "facturas mas recientes",
                "facturas recientes",
                "últimas facturas",
                "ultimas facturas",
                "latest invoices",
                "recent invoices",
                "última factura",
                "ultima factura",
                "factura más nueva",
                "factura mas nueva",
            ]
        ):
            add_tool_step(
                "get_recent_invoices",
                "Get the most recent invoices",
                {"limit": 5, "offset": 0},
            )

        if any(
            phrase in normalized
            for phrase in [
                "primera factura",
                "primer factura",
                "primer comprobante",
                "first invoice",
                "earliest invoice",
                "factura más antigua",
                "factura mas antigua",
            ]
        ):
            add_sql_step(
                textwrap.dedent(
                    """
                    SELECT
                        id,
                        invoice_number,
                        invoice_date,
                        vendor_name,
                        total_cents,
                        currency_code
                    FROM invoices
                    ORDER BY invoice_date ASC, id ASC
                    LIMIT 1;
                    """
                ).strip(),
                "Retrieve the earliest invoice in the database",
            )

        # Detect specific invoice ID queries (e.g., "factura 5", "id 5", "documento 5")
        import re
        id_match = re.search(r'\b(?:factura|invoice|documento|document|id)\s+(\d+)\b', normalized)
        if id_match:
            doc_id = int(id_match.group(1))
            add_tool_step(
                "get_invoice_by_id",
                f"Retrieve invoice with ID {doc_id}",
                {"doc_id": doc_id},
            )

        if any(
            phrase in normalized
            for phrase in [
                "principales proveedores",
                "proveedores principales",
                "top proveedores",
                "top vendors",
                "mejores proveedores",
                "proveedores destacados",
                "mayor gasto por proveedor",
                "gasto por proveedor más alto",
                "gasto por proveedor mas alto",
                "main vendors",
                "todos los proveedores",
                "all vendors",
            ]
        ):
            # Detect if asking for ALL vendors or top N
            limit = 100  # Default to show all
            if any(top in normalized for top in ["top 5", "top 3", "principales 5"]):
                limit = 5
            elif any(top in normalized for top in ["top 10", "principales 10"]):
                limit = 10
            
            add_tool_step(
                "get_top_vendors",
                f"Retrieve the top {limit} vendors by total spending",
                {"limit": limit},
            )

        if any(
            phrase in normalized
            for phrase in [
                "factura donde se gastó más",
                "factura donde se gasto mas",
                "factura de mayor monto",
                "factura más cara",
                "factura mas cara",
                "factura con mayor total",
                "factura máxima",
                "factura maxima",
                "highest invoice",
                "largest invoice",
                "invoice with the highest amount",
            ]
        ):
            add_tool_step(
                "get_max_invoice",
                "Retrieve the invoice with the highest total amount",
            )

        if any(
            phrase in normalized
            for phrase in [
                "item más caro",
                "item mas caro",
                "producto más caro",
                "producto mas caro",
                "concepto más caro",
                "concepto mas caro",
                "línea más cara",
                "linea mas cara",
                "most expensive item",
                "expensive line item",
            ]
        ):
            add_tool_step(
                "get_most_expensive_item",
                "Get the single most expensive line item",
            )

        if any(
            phrase in normalized
            for phrase in [
                "categoría con más gasto",
                "categoria con mas gasto",
                "categoría con mayor gasto",
                "categoria con mayor gasto",
                "categorías por gasto",
                "categorias por gasto",
                "top categorías",
                "top categorias",
                "segunda categoría",
                "segunda categoria",
                "tercera categoría",
                "tercera categoria",
            ]
        ):
            # Detect if asking for second, third, etc.
            offset = 0
            if "segunda" in normalized or "second" in normalized:
                offset = 1
            elif "tercera" in normalized or "third" in normalized:
                offset = 2
            elif "cuarta" in normalized or "fourth" in normalized:
                offset = 3
            
            add_tool_step(
                "get_top_categories_by_spend",
                f"Get top categories by spending (offset={offset})",
                {"limit": 10, "offset": offset},
            )

        if any(
            phrase in normalized
            for phrase in [
                "total de facturas",
                "suma de facturas",
                "suma total",
                "total general",
                "sumar todas las facturas",
                "cuánto se gastó en total",
                "cuanto se gasto en total",
                "gasto total",
                "total amount",
                "sum of all invoices",
            ]
        ):
            add_tool_step(
                "get_total_invoices_summary",
                "Get total count and amounts by currency for all invoices",
            )

        # Keep old SQL fallback for backward compatibility
        if any(
            phrase in normalized
            for phrase in [
                "línea más cara legacy",  # Won't match, just keeping structure
            ]
        ):
            add_sql_step(
                textwrap.dedent(
                    """
                    SELECT
                        i.id,
                        i.description,
                        i.qty,
                        i.unit_price_cents,
                        i.line_total_cents,
                        d.invoice_number,
                        d.invoice_date,
                        d.vendor_name,
                        d.currency_code
                    FROM items i
                    JOIN invoices d ON d.id = i.document_id
                    ORDER BY i.line_total_cents DESC, COALESCE(i.unit_price_cents, 0) DESC, i.id DESC
                    LIMIT 1;
                    """
                ).strip(),
                "Retrieve the line item with the highest total amount",
            )

        if not plan_steps:
            return None

        plan_steps.insert(
            0,
            {
                "id": "fallback_step0",
                "tool": "get_database_schema",
                "description": "Inspect the SQLite schema before generating SQL",
                "arguments": {},
            },
        )

        return {
            "needs_data": True,
            "steps": plan_steps,
            "notes": "Plan produced by heuristic fallback.",
        }

    def _trim_history(
        self, history: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        if not history or MAX_HISTORY_MESSAGES <= 0:
            return []
        if len(history) <= MAX_HISTORY_MESSAGES:
            return list(history)
        return history[-MAX_HISTORY_MESSAGES:]

    def _format_history(self, history: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for entry in history:
            role = entry.get("role", "user").capitalize()
            content = str(entry.get("content", "")).strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _try_local_response(self, question: str) -> dict[str, Any] | None:
        normalized = question.strip().lower()
        if not normalized:
            return {
                "success": True,
                "answer": "Necesito una pregunta para ayudarte.",
                "tool_calls": [],
                "cached": False,
            }
        # Solo respuestas mínimas para saludos/gracias
        greetings = {"hola", "buenas", "buenas tardes", "buen día", "hello"}
        thanks = {"gracias", "muchas gracias"}
        if normalized in greetings:
            return {
                "success": True,
                "answer": "¡Hola! ¿En qué puedo ayudarte con las facturas?",
                "tool_calls": [],
                "cached": False,
            }
        if normalized in thanks:
            return {
                "success": True,
                "answer": "¡De nada! Si necesitas algo más, aquí estoy.",
                "tool_calls": [],
                "cached": False,
            }
        return None

    def _build_schema_summary(self) -> str:
        schema = self.mcp_server.get_schema()
        lines: list[str] = []
        for table_name, info in schema.get("tables", {}).items():
            columns = info.get("columns", [])
            column_names = ", ".join(col.get("name") for col in columns[:4])
            if len(columns) > 4:
                column_names += ", …"
            lines.append(f"- {table_name}: {column_names}")
        return "\n".join(lines) or "(schema unavailable)"

    def _describe_tools(self) -> str:
        lines: list[str] = []
        for entry in self.tool_manifest:
            fn = entry.get("function", {})
            name = fn.get("name")
            desc = fn.get("description", "").strip()
            lines.append(f"• {name}: {desc}")
        return "\n".join(lines) or "(no tools registered)"

    @staticmethod
    def _strip_markdown_block(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").strip()
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()
        return stripped
