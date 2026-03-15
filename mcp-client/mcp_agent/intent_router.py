"""Intent Router - classifies user queries to determine handling approach.

This is the recommended approach:
1. Parse user intent first
2. Route to appropriate handler (simple vs complex)
3. Simple queries → LLM-driven (fast)
4. Complex queries → LangGraph workflow (sequential stages)
"""

import logging
import json
from typing import Dict, Any, List, Optional, Literal
from enum import Enum
from openai import OpenAI

logger = logging.getLogger(__name__)


class QueryComplexity(str, Enum):
    """Query complexity classification."""
    SIMPLE = "simple"           # Single tool call, no approval needed
    COMPLEX = "complex"         # Multi-step, needs approval or sequential stages
    CONVERSATIONAL = "conversational"  # Follow-up questions


class QueryIntent(str, Enum):
    """Query intent types."""
    # Database intents
    LIST_TABLES = "list_tables"
    DESCRIBE_TABLE = "describe_table"
    SELECT_QUERY = "select_query"
    INSERT_DATA = "insert_data"
    UPDATE_DATA = "update_data"
    DELETE_DATA = "delete_data"
    EXPORT_DATA = "export_data"
    SCHEMA_QUERY = "schema_query"

    # Excel intents
    IMPORT_EXCEL = "import_excel"
    EXPORT_EXCEL = "export_excel"
    ANALYZE_DATA = "analyze_data"
    CREATE_CHART = "create_chart"
    TRANSFORM_DATA = "transform_data"

    # General intents
    HELP = "help"
    UNKNOWN = "unknown"


class IntentRouter:
    """Routes user queries to appropriate handling approach.

    Flow:
    1. Parse intent (what does user want?)
    2. Classify complexity (simple or complex?)
    3. Route to handler (LLM-driven or LangGraph)
    """

    def __init__(
        self,
        llm: OpenAI = None,
        model: str = "gpt-4o-mini",
    ):
        self.llm = llm or OpenAI()
        self.model = model

    async def classify(
        self,
        prompt: str,
        agent_type: str = None,
    ) -> Dict[str, Any]:
        """Classify user query.

        Args:
            prompt: User's input message
            agent_type: Optional agent type hint ("database", "excel")

        Returns:
            {
                "intent": QueryIntent,
                "complexity": QueryComplexity,
                "requires_approval": bool,
                "requires_workflow": bool,
                "suggested_tools": List[str],
                "reasoning": str
            }
        """
        logger.info(f"[IntentRouter] Classifying: {prompt[:50]}...")

        # Build context about agent types
        agent_context = ""
        if agent_type:
            agent_context = f"The agent type is: {agent_type}"

        response = self.llm.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": f"""You are an intent classifier. Analyze the user query and classify:

1. INTENT: What does the user want to do?
   - list_tables: Show available tables
   - describe_table: Show table structure/schema
   - select_query: Read data from database
   - insert_data: Add new data
   - update_data: Modify existing data
   - delete_data: Remove data
   - export_data: Export to file (Excel, CSV)
   - import_excel: Import from Excel file
   - analyze_data: Analyze data (stats, distribution)
   - create_chart: Create visualization
   - transform_data: Transform/clean data
   - help: General help
   - unknown: Cannot determine

2. COMPLEXITY: How should this be handled?
   - "simple": Single tool call, direct execution, no approval needed
   - "complex": Multi-step, needs approval, sequential stages, or complex workflow
   - "conversational": Follow-up question or clarification

3. REQUIRES_APPROVAL: Does this need user approval before execution?
   - true for: INSERT, UPDATE, DELETE, CREATE, DROP, EXPORT
   - false for: SELECT (read-only), LIST, DESCRIBE

4. REQUIRES_WORKFLOW: Does this need a structured workflow?
   - true for: complex multi-step operations, operations needing approval gates
   - false for: simple read operations

5. SUGGESTED_TOOLS: Which MCP tools would be useful?

{agent_context}

Return JSON with: intent, complexity, requires_approval, requires_workflow, suggested_tools, reasoning"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        try:
            result = json.loads(response.choices[0].message.content)
        except:
            result = {
                "intent": "unknown",
                "complexity": "simple",
                "requires_approval": False,
                "requires_workflow": False,
                "suggested_tools": [],
                "reasoning": "Failed to parse, defaulting to simple"
            }

        # Validate and normalize
        result["complexity"] = result.get("complexity", "simple")
        result["requires_approval"] = result.get("requires_approval", False)
        result["requires_workflow"] = result.get("requires_workflow", False)

        logger.info(f"[IntentRouter] Result: intent={result.get('intent')}, complexity={result.get('complexity')}")

        return result

    async def route(
        self,
        prompt: str,
        agent_type: str = None,
    ) -> Literal["llm_driven", "workflow", "conversational"]:
        """Route to appropriate handler.

        Returns:
            - "llm_driven": Use BaseAgent (LLM handles tools directly)
            - "workflow": Use LangGraph workflow (sequential stages)
            - "conversational": Handle as follow-up question
        """
        classification = await self.classify(prompt, agent_type)

        complexity = classification.get("complexity", "simple")

        if complexity == "conversational":
            return "conversational"
        elif complexity == "complex" or classification.get("requires_workflow"):
            return "workflow"
        else:
            return "llm_driven"


# Default router instance
_default_router: Optional[IntentRouter] = None


def get_intent_router(model: str = "gpt-4o-mini") -> IntentRouter:
    """Get or create default IntentRouter instance."""
    global _default_router
    if _default_router is None:
        _default_router = IntentRouter(model=model)
    return _default_router
