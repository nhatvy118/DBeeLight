"""
Flask API Server để kết nối Frontend với MCP Agent
"""
import asyncio
import json
import os
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import sys
import threading

# Thêm mcp-client vào path - cần đi lên 2 cấp từ api_server/__init__.py
# api_server/__init__.py -> api-server/ -> mcp-server/ -> mcp-client/
_project_root = Path(__file__).parent.parent.parent
_mcp_client_path = _project_root / "mcp-client"
if str(_mcp_client_path) not in sys.path:
    sys.path.insert(0, str(_mcp_client_path))

from agent import DatabaseAgent, SessionManager

load_dotenv()

app = Flask(__name__)
CORS(app)  # Cho phép frontend gọi API

# Enable logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global agent instance và event loop
agent: DatabaseAgent = None
agent_loop = None
loop_thread = None

# Default MCP servers (relative to project root)
DEFAULT_SERVERS = [
    "database/database.py",
    "excel-summary/excel_summary.py"
]


def run_async(coro):
    """Chạy async function trong event loop riêng"""
    global agent_loop, loop_thread
    
    if agent_loop is None or agent_loop.is_closed():
        agent_loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=agent_loop.run_forever, daemon=True)
        loop_thread.start()
    
    future = asyncio.run_coroutine_threadsafe(coro, agent_loop)
    return future.result(timeout=60)  # 60 seconds timeout


async def init_agent():
    """Khởi tạo agent và kết nối đến MCP servers"""
    global agent
    
    if agent is not None and agent.sessions:
        return agent
    
    logger.info("Initializing DatabaseAgent...")
    session_manager = SessionManager()
    agent = DatabaseAgent(model="gpt-4o-mini", session_manager=session_manager)
    
    # Kết nối đến các servers
    server_paths = DEFAULT_SERVERS
    base_path = _project_root  # Sử dụng project root thay vì api-server/
    
    logger.info(f"Project root: {base_path}")
    logger.info(f"Looking for servers: {server_paths}")
    
    connected_count = 0
    for server_path in server_paths:
        full_path = base_path / server_path
        logger.info(f"Checking server: {full_path} (exists: {full_path.exists()})")
        if full_path.exists():
            server_name = full_path.stem
            try:
                logger.info(f"Attempting to connect to {server_name} at {full_path}")
                await agent.connect_to_server(server_name, str(full_path))
                logger.info(f"✅ Connected to {server_name}")
                connected_count += 1
            except Exception as e:
                logger.error(f"❌ Failed to connect to {server_name}: {e}")
                import traceback
                traceback.print_exc()
        else:
            logger.warning(f"⚠️  Server not found: {full_path}")
    
    if connected_count == 0:
        raise RuntimeError(f"No MCP servers connected. Checked paths: {[base_path / sp for sp in server_paths]}")
    
    # Tạo session mới
    session_manager.create_session()
    
    logger.info(f"✅ Agent initialized with {connected_count} server(s) connected")
    logger.info(f"Agent sessions: {list(agent.sessions.keys())}")
    return agent


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "agent_initialized": agent is not None
    })


@app.route('/api/chat', methods=['POST'])
def chat():
    """Xử lý chat message từ frontend"""
    try:
        data = request.json
        query = data.get('message', '').strip()
        session_id = data.get('session_id')
        
        if not query:
            return jsonify({"error": "Message is required"}), 400
        
        # Khởi tạo agent nếu chưa có
        if agent is None or not agent.sessions:
            try:
                run_async(init_agent())
            except Exception as e:
                error_msg = f"Failed to initialize agent: {str(e)}"
                print(error_msg)
                return jsonify({
                    "success": False,
                    "error": error_msg
                }), 500
        
        # Kiểm tra lại sau khi init
        if agent is None or not agent.sessions:
            return jsonify({
                "success": False,
                "error": "Agent initialized but no MCP servers connected. Please check server logs for connection errors."
            }), 500
        
        # Load session nếu có session_id
        if session_id and agent.session_manager:
            agent.session_manager.load_session(session_id)
        
        # Xử lý query
        response = run_async(agent.process_query(query, verbose=False))
        
        # Lấy session info
        session_info = agent.session_manager.get_session_info() if agent.session_manager else None
        
        return jsonify({
            "success": True,
            "response": response,
            "session_id": session_info.get("session_id") if session_info else None
        })
            
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """Lấy danh sách sessions"""
    try:
        if agent is None:
            run_async(init_agent())
        
        sessions = agent.session_manager.list_sessions() if agent.session_manager else []
        
        return jsonify({
            "success": True,
            "sessions": sessions
        })
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/sessions/new', methods=['POST'])
def create_session():
    """Tạo session mới"""
    try:
        data = request.json or {}
        session_name = data.get('name')
        
        if agent is None:
            run_async(init_agent())
        
        session_id = agent.session_manager.create_session(session_name) if agent.session_manager else None
        session_info = agent.session_manager.get_session_info() if agent.session_manager else None
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "session_info": session_info
        })
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    """Lấy thông tin session"""
    try:
        if agent is None:
            run_async(init_agent())
        
        if agent.session_manager:
            if agent.session_manager.load_session(session_id):
                session_info = agent.session_manager.get_session_info()
                messages = agent.session_manager.get_current_messages()
                
                return jsonify({
                    "success": True,
                    "session_info": session_info,
                    "messages": messages
                })
        
        return jsonify({
            "success": False,
            "error": "Session not found"
        }), 404
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def main():
    """Entry point for running the server"""
    # Chạy Flask server
    port = int(os.getenv('PORT', 5001))  # Default port 5001 để tránh conflict với AirPlay
    print("Starting API server...")
    print(f"Server will run on port {port}")
    print("Agent will be initialized on first request.")
    app.run(host='0.0.0.0', port=port, debug=True)


if __name__ == '__main__':
    main()

