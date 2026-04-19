"""Superset agent workflow with LangGraph.

Design: deterministic stages handle tool calls with explicit IDs kept in state.
LLM is only used for (1) INTENT_PARSE and (2) SCHEMA_PLAN — turning the parsed
intent plus real schema into a concrete SQL and viz-params plan. All other
stages execute tools with known arguments — no free-form LLM tool-picking."""

import logging
import json
import os
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI
from langgraph.graph import StateGraph, END

from mcp_agent.graph.graph_state import AgentState, create_initial_state
from mcp_agent.graph.state import StageType

logger = logging.getLogger(__name__)


class SupersetAgentWorkflow:
    """Workflow for Superset visualization — deterministic tool calls with a single LLM plan step."""

    def __init__(self, llm=None, agent=None, database_agent=None):
        self.llm = llm or OpenAI()
        self.agent = agent
        self.database_agent = database_agent

    # ---------- helpers ----------

    async def _call_tool(self, agent, tool_name: str, args: dict) -> str:
        if not agent:
            raise RuntimeError("No agent available")
        for _server_name, session in agent.sessions.items():
            try:
                result = await session.call_tool(tool_name, args)
                content = result.content
                if hasattr(content, "text"):
                    return str(content.text)
                if isinstance(content, list) and content:
                    first = content[0]
                    if hasattr(first, "text"):
                        return str(first.text)
                return str(content)
            except Exception as e:
                logger.warning(f"[Superset] Tool '{tool_name}' failed: {e}")
                continue
        raise RuntimeError(f"Tool '{tool_name}' not found in connected sessions")

    @staticmethod
    def _parse_json_tool_result(raw: str) -> Any:
        """Tools return JSON strings; parse safely."""
        try:
            return json.loads(raw)
        except Exception:
            return None

    @staticmethod
    def _has_error(state: AgentState) -> bool:
        return bool(state.get("error"))

    # ---------- graph wiring ----------

    def get_stage_handlers(self) -> Dict[str, Any]:
        return {
            StageType.INTENT_PARSE.value: self.intent_parse,
            StageType.DB_CONNECTION.value: self.db_connection,
            StageType.SCHEMA_DISCOVERY.value: self.schema_discovery,
            StageType.SCHEMA_PLAN.value: self.schema_plan,
            StageType.SQL_EXECUTION.value: self.sql_execution,
            StageType.CHART_CREATION.value: self.chart_creation,
            StageType.CHART_EMBED.value: self.chart_embed,
        }

    def _build_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        handlers = self.get_stage_handlers()

        stage_order = [
            StageType.INTENT_PARSE.value,
            StageType.DB_CONNECTION.value,
            StageType.SCHEMA_DISCOVERY.value,
            StageType.SCHEMA_PLAN.value,
            StageType.SQL_EXECUTION.value,
            StageType.CHART_CREATION.value,
            StageType.CHART_EMBED.value,
        ]

        for stage_name in stage_order:
            handler = handlers[stage_name]
            async def node_wrapper(state, _handler=handler):
                return await _handler(state, self.agent)
            workflow.add_node(stage_name, node_wrapper)

        async def start_handler(state):
            return {**state, "current_stage": stage_order[0]}
        workflow.add_node("START", start_handler)

        async def done_handler(state):
            return {**state, "current_stage": StageType.DONE.value}
        workflow.add_node(StageType.DONE.value, done_handler)

        workflow.set_entry_point("START")
        workflow.add_edge("START", stage_order[0])
        for i in range(len(stage_order) - 1):
            workflow.add_edge(stage_order[i], stage_order[i + 1])
        workflow.add_edge(stage_order[-1], StageType.DONE.value)
        workflow.add_edge(StageType.DONE.value, END)
        return workflow.compile()

    async def run(self, session_id: str, user_message: str) -> AgentState:
        state = create_initial_state(session_id, user_message, "superset")
        graph = self._build_graph()
        return await graph.ainvoke(state)

    # ---------- stages ----------

    async def intent_parse(self, state: AgentState, _agent) -> AgentState:
        user_message = state["user_message"]
        logger.info(f"[Superset] Intent parse: {user_message[:80]}...")

        response = self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Analyze a visualization request and extract:\n"
                        "- chart_type: one of bar, line, pie, table, area, scatter, heatmap\n"
                        "- metrics: what to measure/aggregate (free text)\n"
                        "- dimensions: how to group/categorize (free text)\n"
                        "- filters: any WHERE conditions mentioned (free text)\n"
                        "- detected_language: 'en' or 'vi'\n"
                        "Return strict JSON."
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        try:
            intent = json.loads(response.choices[0].message.content)
        except Exception:
            intent = {"chart_type": "bar", "metrics": "", "dimensions": "", "filters": "", "detected_language": "en"}

        return {
            **state,
            "intent": intent,
            "detected_language": intent.get("detected_language", "en"),
            "chart_type": intent.get("chart_type", "bar"),
        }

    async def db_connection(self, state: AgentState, agent) -> AgentState:
        """Register or locate the project's DB in Superset; save db_id + db_name into state."""
        logger.info("[Superset] Checking Superset database connection...")

        if not agent:
            return {**state, "error": "No Superset agent available"}

        # Step 1: get URI from database_agent. Superset runs in Docker — host paths
        # (from database_agent) are unreadable inside the container. docker-compose
        # mounts ./api-server/databases → /app/databases, so translate SQLite paths
        # by taking the filename and prepending the container mount prefix.
        db_uri = ""
        db_name = ""
        db_backend = ""  # "sqlite" | "postgresql" | ...
        sqlite_container_prefix = os.getenv(
            "SUPERSET_SQLITE_CONTAINER_PREFIX", "/app/databases"
        )
        if self.database_agent:
            try:
                db_info = await self._call_tool(self.database_agent, "get_connection_info", {})
                logger.info(f"[Superset] DB connection info: {db_info[:200]}")
                m_type = re.search(r"Type:\s*(\w+)", db_info, re.IGNORECASE)
                db_type = m_type.group(1).lower() if m_type else ""
                if "sqlite" in db_type:
                    db_backend = "sqlite"
                    m_path = re.search(r"File:\s*([^\n]+)", db_info)
                    if m_path:
                        host_path = m_path.group(1).strip()
                        filename = os.path.basename(host_path)
                        db_uri = f"sqlite:///{sqlite_container_prefix.rstrip('/')}/{filename}"
                elif "postgres" in db_type:
                    db_backend = "postgresql"
                    db_uri = os.getenv("PROJECT_DB_URI", "")
                m_proj = re.search(r"/([^/]+)\.db", db_info)
                if m_proj:
                    db_name = f"project_{m_proj.group(1).replace('.db', '')}"
            except Exception as e:
                logger.warning(f"[Superset] Failed to get DB connection info: {e}")

        if not db_name:
            return {**state, "error": "Could not derive Superset database name from project DB info"}

        # Step 2: already registered?
        db_id: Optional[int] = None
        try:
            dbs_raw = await self._call_tool(agent, "list_superset_databases", {})
            dbs = self._parse_json_tool_result(dbs_raw) or []
            seen_names = [db.get("database_name") for db in dbs if isinstance(db, dict)]
            logger.info(
                f"[Superset] list_superset_databases returned {len(seen_names)} DBs, "
                f"looking for '{db_name}'. Names: {seen_names}"
            )
            for db in dbs:
                if isinstance(db, dict) and db.get("database_name", "").lower() == db_name.lower():
                    db_id = int(db["id"])
                    logger.info(f"[Superset] Reusing existing DB '{db_name}' id={db_id}")
                    break
        except Exception as e:
            logger.warning(f"[Superset] Failed to list databases: {e}")

        # Step 3: register if missing
        if db_id is None:
            if not db_uri:
                return {**state, "error": "No database URI available. Please connect to a database first."}
            try:
                reg_raw = await self._call_tool(
                    agent,
                    "register_database",
                    {"name": db_name, "sqlalchemy_uri": db_uri},
                )
                reg = self._parse_json_tool_result(reg_raw) or {}
                logger.info(f"[Superset] register_database result: {str(reg)[:300]}")
                if isinstance(reg, dict) and reg.get("id"):
                    db_id = int(reg["id"])
                else:
                    return {
                        **state,
                        "error": f"register_database did not return an id: {reg_raw[:200]}",
                    }
            except Exception as e:
                return {**state, "error": f"Failed to register database: {e}"}

        return {
            **state,
            "superset_db_id": db_id,
            "superset_db_name": db_name,
            "superset_db_backend": db_backend,
            "output": {
                "type": "db_connection",
                "message": f"Superset database ready: {db_name} (id={db_id}, backend={db_backend})",
            },
        }

    async def schema_discovery(self, state: AgentState, agent) -> AgentState:
        """Deterministic: list tables + metadata for the registered DB."""
        if self._has_error(state):
            logger.info(f"[Superset] Schema discovery skipped (prior error: {state.get('error')})")
            return state
        logger.info("[Superset] Schema discovery...")

        db_id = state.get("superset_db_id")
        if not db_id:
            return {**state, "error": "No superset_db_id in state"}

        # Pick default schema by backend. Superset's tables endpoint requires a
        # schema_name; SQLite's default schema is "main", Postgres is "public".
        backend = (state.get("superset_db_backend") or "").lower()
        default_schema = {"sqlite": "main", "postgresql": "public"}.get(backend)

        # Tables
        try:
            args: Dict[str, Any] = {"database_id": db_id}
            if default_schema:
                args["schema"] = default_schema
            tables_raw = await self._call_tool(agent, "get_database_tables", args)
            tables_list = self._parse_json_tool_result(tables_raw) or []
        except Exception as e:
            return {**state, "error": f"get_database_tables failed: {e}"}

        table_names: List[str] = []
        for t in tables_list:
            if isinstance(t, dict):
                name = t.get("value") or t.get("name") or t.get("label")
                if name:
                    table_names.append(str(name))
            elif isinstance(t, str):
                table_names.append(t)

        # Columns per table (best-effort; skip on error)
        enriched: List[Dict[str, Any]] = []
        for name in table_names[:50]:  # cap to avoid hammering Superset
            cols: List[Dict[str, Any]] = []
            try:
                meta_args: Dict[str, Any] = {"database_id": db_id, "table_name": name}
                if default_schema:
                    meta_args["schema"] = default_schema
                meta_raw = await self._call_tool(agent, "get_table_metadata", meta_args)
                meta = self._parse_json_tool_result(meta_raw) or {}
                for col in (meta.get("columns") or []):
                    if isinstance(col, dict):
                        cols.append({"name": col.get("name"), "type": col.get("type")})
            except Exception as e:
                logger.warning(f"[Superset] get_table_metadata for {name} failed: {e}")
            enriched.append({"table": name, "columns": cols})

        return {
            **state,
            "superset_tables": enriched,
            "output": {
                "type": "schema_discovery",
                "message": f"Found {len(enriched)} tables in {state.get('superset_db_name')}",
                "tables": enriched,
            },
        }

    async def schema_plan(self, state: AgentState, _agent) -> AgentState:
        """Single LLM call: intent + schema → concrete SQL and viz params plan."""
        if self._has_error(state):
            logger.info(f"[Superset] Schema plan skipped (prior error: {state.get('error')})")
            return state
        logger.info("[Superset] Schema plan...")

        tables = state.get("superset_tables") or []
        if not tables:
            return {**state, "error": "No tables available to plan against"}

        intent = state.get("intent") or {}
        schema_brief = [
            {"table": t["table"], "columns": t.get("columns", [])}
            for t in tables
        ]
        logger.info(
            "[Superset] Planner input tables/columns: "
            + json.dumps(schema_brief, ensure_ascii=False)
        )

        system_prompt = (
            "You are a visualization planner. Given a user request, the parsed intent, "
            "and the available schema, produce a STRICT JSON plan that downstream code "
            "will execute verbatim. No prose, no markdown.\n\n"
            "Return this shape:\n"
            "{\n"
            '  "table": "<chosen table name from schema>",\n'
            '  "sql": "<a SELECT statement suitable for charting>",\n'
            '  "dataset_name": "<short snake_case base name>",\n'
            '  "slice_name": "<chart title in user\'s language>",\n'
            '  "viz_type": "<Superset viz_type — see list below>",\n'
            '  "viz_params": { ... Superset viz_params blob ... }\n'
            "}\n\n"
            "CRITICAL — schema fidelity:\n"
            "- You MUST use ONLY the tables and columns listed in the provided schema.\n"
            "- NEVER invent a column because the user's phrasing suggests it. If the user asks to "
            "group by a dimension that does not exist in the schema, pick the closest available "
            "column (usually a categorical string column) or group by 1 (single-bucket aggregate) "
            "rather than fabricate.\n"
            "- Before writing SQL, scan the chosen table's `columns` list and reference only those names.\n\n"
            "SQL rules:\n"
            "- Pick ONE table from the schema.\n"
            "- ALWAYS double-quote the original table/column names when they appear in FROM / WHERE / GROUP BY (names may contain spaces or non-ASCII, which SQLite/Postgres require quoted).\n"
            "- ALWAYS alias every projected column to a short snake_case ASCII identifier with `AS`. "
            "Example (when schema has column 'tên'): SELECT \"tên\" AS ten, COUNT(*) AS so_luong FROM \"học sinh\" GROUP BY \"tên\". "
            "This is MANDATORY because Superset uses the output column names as metric/dimension keys, "
            "and non-ASCII or quoted names break the chart's metric/groupby bindings.\n"
            "- Include a LIMIT if the result could be large.\n\n"
            "Valid viz_type values for THIS Superset instance (4.x with modern plugins only):\n"
            "- echarts_timeseries_bar: bar chart. Requires an x_axis (any column, incl. categorical). Use this for ANY bar chart the user asks for.\n"
            "- echarts_timeseries_line / echarts_area: over a DATE/TIME x_axis.\n"
            "- pie: share/proportion of a categorical column.\n"
            "- table: tabular view.\n"
            "- big_number_total: single KPI number.\n"
            "- histogram: numeric distribution.\n"
            "Do NOT use 'bar', 'dist_bar', 'line' — these legacy types are disabled.\n\n"
            "viz_params rules:\n"
            "- Reference the ASCII aliases from the SELECT, NOT the original Unicode/quoted names.\n"
            "- Include metrics (list) and for echarts_timeseries_*: `x_axis` (string, the dim alias) and `time_range: 'No filter'`. For pie: `groupby: [\"<dim_alias>\"]`.\n"
            "- metrics items: {\"expressionType\":\"SIMPLE\",\"column\":{\"column_name\":\"<ascii_alias>\"},\"aggregate\":\"SUM\",\"label\":\"...\"}. "
            "When the SQL already aggregates (SELECT ... COUNT(*) AS so_luong), the viz metric should SUM the ASCII alias so_luong (Superset re-aggregates the dataset).\n"
        )
        user_payload = {
            "user_message": state.get("user_message", ""),
            "intent": intent,
            "schema": schema_brief,
        }

        try:
            response = self.llm.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            plan = json.loads(response.choices[0].message.content)
        except Exception as e:
            return {**state, "error": f"SCHEMA_PLAN LLM call failed: {e}"}

        # Validate minimal shape
        required = ["table", "sql", "dataset_name", "slice_name", "viz_type", "viz_params"]
        missing = [k for k in required if not plan.get(k)]
        if missing:
            return {**state, "error": f"Plan missing fields: {missing}. Raw: {str(plan)[:300]}"}

        allowed_tables = {t["table"].lower() for t in tables}
        if plan["table"].lower() not in allowed_tables:
            return {
                **state,
                "error": f"Planner picked table '{plan['table']}' not in schema ({sorted(allowed_tables)})",
            }

        # Validate every double-quoted identifier in the SQL against the chosen
        # table's columns. This catches the LLM inventing columns from the user's
        # phrasing (e.g., asking for "by class" when no class column exists).
        picked = next(t for t in tables if t["table"].lower() == plan["table"].lower())
        known_cols = {
            (c.get("name") or "").lower()
            for c in picked.get("columns", [])
            if c.get("name")
        }
        known_cols.add(plan["table"].lower())  # allow the table name itself
        quoted_ids = set(re.findall(r'"([^"]+)"', plan["sql"]))
        invented = [q for q in quoted_ids if q.lower() not in known_cols]
        if invented:
            return {
                **state,
                "error": (
                    f"Planner referenced columns not in schema: {invented}. "
                    f"Known columns for '{plan['table']}': {sorted(known_cols)}. "
                    f"SQL: {plan['sql']}"
                ),
            }

        logger.info(f"[Superset] Plan: table={plan['table']} viz={plan['viz_type']} sql={plan['sql'][:120]}")
        return {
            **state,
            "superset_plan": plan,
            "sql": plan["sql"],
            "selected_table": plan["table"],
            "chart_type": plan["viz_type"],
            "output": {"type": "schema_plan", "message": "Plan ready", "plan": plan},
        }

    async def sql_execution(self, state: AgentState, agent) -> AgentState:
        """Deterministic: execute the planned SQL and create a virtual dataset."""
        if self._has_error(state):
            logger.info(f"[Superset] SQL execution skipped (prior error: {state.get('error')})")
            return state
        logger.info("[Superset] SQL execution + virtual dataset...")

        db_id = state.get("superset_db_id")
        plan = state.get("superset_plan") or {}
        if not db_id or not plan.get("sql"):
            return {**state, "error": "Missing db_id or plan.sql for SQL execution"}

        # Sanity check: run the SQL once to surface errors early
        try:
            exec_raw = await self._call_tool(
                agent,
                "execute_sql",
                {"database_id": db_id, "sql": plan["sql"]},
            )
            exec_res = self._parse_json_tool_result(exec_raw) or {}
            if isinstance(exec_res, dict) and exec_res.get("error"):
                return {
                    **state,
                    "error": f"SQL execution failed: {exec_res.get('message') or exec_res.get('error')}",
                }
        except Exception as e:
            return {**state, "error": f"execute_sql failed: {e}"}

        # Create virtual dataset
        try:
            ds_raw = await self._call_tool(
                agent,
                "create_virtual_dataset",
                {
                    "database_id": db_id,
                    "table_name": plan.get("dataset_name") or "mcp_dataset",
                    "sql": plan["sql"],
                },
            )
            ds = self._parse_json_tool_result(ds_raw) or {}
            dataset_id = ds.get("id") if isinstance(ds, dict) else None
            if not dataset_id:
                return {**state, "error": f"create_virtual_dataset did not return id: {ds_raw[:200]}"}
        except Exception as e:
            return {**state, "error": f"create_virtual_dataset failed: {e}"}

        return {
            **state,
            "superset_dataset_id": int(dataset_id),
            "query_result": exec_res,
            "output": {
                "type": "sql_execution",
                "message": f"Dataset ready (id={dataset_id})",
                "row_count": (exec_res or {}).get("row_count"),
            },
        }

    async def chart_creation(self, state: AgentState, agent) -> AgentState:
        """Deterministic: create chart with plan's viz_type and viz_params."""
        if self._has_error(state):
            logger.info(f"[Superset] Chart creation skipped (prior error: {state.get('error')})")
            return state
        logger.info("[Superset] Chart creation...")

        dataset_id = state.get("superset_dataset_id")
        plan = state.get("superset_plan") or {}
        if not dataset_id or not plan:
            return {**state, "error": "Missing dataset_id or plan for chart creation"}

        try:
            chart_raw = await self._call_tool(
                agent,
                "create_chart",
                {
                    "slice_name": plan.get("slice_name") or "MCP Chart",
                    "datasource_id": dataset_id,
                    "viz_type": plan.get("viz_type") or "bar",
                    "params": json.dumps(plan.get("viz_params") or {}),
                },
            )
            chart = self._parse_json_tool_result(chart_raw) or {}
            chart_id = chart.get("id") if isinstance(chart, dict) else None
            if not chart_id:
                return {**state, "error": f"create_chart did not return id: {chart_raw[:200]}"}
        except Exception as e:
            return {**state, "error": f"create_chart failed: {e}"}

        return {
            **state,
            "superset_chart_id": int(chart_id),
            "output": {
                "type": "chart_creation",
                "message": f"Chart created (id={chart_id})",
                "chart_id": chart_id,
                "explore_url": (chart or {}).get("explore_url"),
            },
        }

    async def chart_embed(self, state: AgentState, agent) -> AgentState:
        """Deterministic: resolve embed URL from chart_id."""
        if self._has_error(state):
            logger.info(f"[Superset] Chart embed skipped (prior error: {state.get('error')})")
            return state
        logger.info("[Superset] Chart embed URL...")

        chart_id = state.get("superset_chart_id")
        if not chart_id:
            return {**state, "error": "Missing chart_id for embed"}

        try:
            emb_raw = await self._call_tool(agent, "get_chart_embed_url", {"chart_id": chart_id})
            emb = self._parse_json_tool_result(emb_raw) or {}
            embed_url = emb.get("embed_url") or emb.get("fullscreen_url")
        except Exception as e:
            return {**state, "error": f"get_chart_embed_url failed: {e}"}

        if not embed_url:
            return {**state, "error": f"No embed_url returned: {emb_raw[:200]}"}

        marker = f"[CHART_EMBED_URL_START]{embed_url}[CHART_EMBED_URL_END]"
        plan = state.get("superset_plan") or {}
        message = (
            f"{plan.get('slice_name') or 'Chart'}\n\n"
            f"{marker}"
        )

        return {
            **state,
            "chart_data": {"embed_url": embed_url, "chart_id": chart_id},
            "output": {
                "type": "chart_embed",
                "message": message,
                "embed_url": embed_url,
                "chart_id": chart_id,
            },
        }
