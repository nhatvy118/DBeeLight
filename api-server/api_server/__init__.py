"""
FastAPI Server để kết nối Frontend với MCP Agent
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import logging
import asyncio

# Thêm mcp-client vào path - api_server/__init__.py -> api-server/ -> mcp-server/ -> mcp-client/
_project_root = Path(__file__).parent.parent.parent
_mcp_client_path = _project_root / "mcp-client"
if str(_mcp_client_path) not in sys.path:
    sys.path.insert(0, str(_mcp_client_path))

from agent import DatabaseAgent, SessionManager  # noqa: E402

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_server")

# Default MCP servers (relative to project root)
DEFAULT_SERVERS = ["database/database.py", "excel-summary/excel_summary.py"]


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class NewSessionRequest(BaseModel):
    name: Optional[str] = None


class ChatOk(BaseModel):
    success: bool = True
    response: str
    session_id: Optional[str] = None


class ErrorResp(BaseModel):
    success: bool = False
    error: str


app = FastAPI(title="MCP API Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent
agent: Optional[DatabaseAgent] = None
agent_lock = asyncio.Lock()


async def init_agent() -> DatabaseAgent:
    """Khởi tạo agent và kết nối đến MCP servers (chạy trong event loop của FastAPI)."""
    global agent
    if agent is not None and agent.sessions:
        return agent

    async with agent_lock:
        if agent is not None and agent.sessions:
            return agent

        logger.info("Initializing DatabaseAgent...")
        session_manager = SessionManager()
        agent = DatabaseAgent(model="gpt-4o-mini", session_manager=session_manager)

        connected_count = 0
        base_path = _project_root
        logger.info(f"Project root: {base_path}")
        logger.info(f"Looking for servers: {DEFAULT_SERVERS}")

        for rel in DEFAULT_SERVERS:
            full_path = base_path / rel
            logger.info(f"Checking server: {full_path} (exists: {full_path.exists()})")
            if not full_path.exists():
                logger.warning(f"⚠️  Server not found: {full_path}")
                continue
            server_name = full_path.stem
            try:
                logger.info(f"Attempting to connect to {server_name} at {full_path}")
                await agent.connect_to_server(server_name, str(full_path))
                connected_count += 1
                logger.info(f"✅ Connected to {server_name}")
            except Exception as e:
                logger.exception(f"❌ Failed to connect to {server_name}: {e}")

        if connected_count == 0:
            raise RuntimeError(
                f"No MCP servers connected. Checked paths: {[base_path / sp for sp in DEFAULT_SERVERS]}"
            )

        session_manager.create_session()
        logger.info(f"✅ Agent initialized with {connected_count} server(s) connected")
        logger.info(f"Agent sessions: {list(agent.sessions.keys())}")
        return agent


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "agent_initialized": agent is not None and bool(agent.sessions if agent else False)}


@app.post("/api/chat", response_model=ChatOk)
async def chat(req: ChatRequest) -> ChatOk:
    query = (req.message or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Message is required")

    try:
        ag = await init_agent()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize agent: {str(e)}") from e

    if not ag.sessions:
        raise HTTPException(
            status_code=500,
            detail="Agent initialized but no MCP servers connected. Please check server logs for connection errors.",
        )

    if req.session_id and ag.session_manager:
        ag.session_manager.load_session(req.session_id)

    # Process query (async)
    response_text = await ag.process_query(query, verbose=False)
    session_info = ag.session_manager.get_session_info() if ag.session_manager else None
    return ChatOk(response=response_text, session_id=(session_info.get("session_id") if session_info else None))


@app.get("/api/sessions")
async def list_sessions() -> Dict[str, Any]:
    ag = await init_agent()
    sessions = ag.session_manager.list_sessions() if ag.session_manager else []
    return {"success": True, "sessions": sessions}


@app.post("/api/sessions/new")
async def create_session(req: NewSessionRequest) -> Dict[str, Any]:
    ag = await init_agent()
    session_id = ag.session_manager.create_session(req.name) if ag.session_manager else None
    session_info = ag.session_manager.get_session_info() if ag.session_manager else None
    return {"success": True, "session_id": session_id, "session_info": session_info}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    ag = await init_agent()
    if ag.session_manager and ag.session_manager.load_session(session_id):
        session_info = ag.session_manager.get_session_info()
        messages = ag.session_manager.get_current_messages()
        return {"success": True, "session_info": session_info, "messages": messages}
    raise HTTPException(status_code=404, detail="Session not found")


def main():
    """Entry point for running the server."""
    port = int(os.getenv("PORT", "5001"))
    logger.info(f"Starting FastAPI server on port {port}")
    uvicorn.run("api_server:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    main()

