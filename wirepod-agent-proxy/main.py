import os
import json
import time
import asyncio
import httpx
import uvicorn
import shutil
import re
from fastapi import FastAPI, Request, Header
from fastapi.responses import StreamingResponse
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
import openai

# Helper to automatically wrap raw command patterns in double curly braces
def fix_commands(text: str) -> str:
    if not text:
        return text
    
    def repl(match):
        cmd = match.group(1) or match.group(3)
        param = match.group(2) or match.group(4)
        
        # Clean parameter: strip quotes, spaces, braces
        param = param.strip('"\'[]{}() ')
        
        # Validate parameter against allowed presets to prevent bad robot actions
        valid_anims = {"happy", "veryHappy", "sad", "verySad", "angry", "frustrated", "dartingEyes", "confused", "thinking", "celebrate", "love"}
        valid_getimage = {"front", "lookingUp"}
        valid_voicereq = {"now"}
        
        # Map parameters to valid fallbacks if invalid
        if cmd in ("playAnimationWI", "playAnimation"):
            if param not in valid_anims:
                if "hot" in param.lower():
                    param = "frustrated"
                elif "happy" in param.lower():
                    param = "happy"
                elif "sad" in param.lower():
                    param = "sad"
                else:
                    param = "thinking" # default fallback
        elif cmd == "getImage":
            if param not in valid_getimage:
                param = "front"
        elif cmd == "newVoiceRequest":
            if param not in valid_voicereq:
                param = "now"
                
        return f"{{{{{cmd}||{param}}}}}"

    # Match raw commands or commands with quotes/brackets safely
    pattern = re.compile(
        r'\{\{\s*(playAnimationWI|playAnimation|getImage|newVoiceRequest)\s*(?:\|\||\||\s+)\s*([^\}]+?)\s*\}\}'
        r'|'
        r'\b(playAnimationWI|playAnimation|getImage|newVoiceRequest)\s*(?:\|\||\||\s+)\s*["\'\[\(]?([a-zA-Z0-9_-]+)["\'\]\)]?'
    )
    return pattern.sub(repl, text)

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

# Helper to locate commands on macOS/Linux
def resolve_command_path(command: str) -> str:
    # Resolve relative paths (e.g. starting with ./ or ../) to absolute
    if command.startswith("./") or command.startswith("../"):
        abs_path = os.path.abspath(command)
        if os.path.exists(abs_path) and os.access(abs_path, os.X_OK):
            return abs_path

    if os.path.isabs(command):
        return command
    
    path = shutil.which(command)
    if path:
        return path
        
    # Search common macOS binary directories if not in default path
    common_paths = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    for base in common_paths:
        full_path = os.path.join(base, command)
        if os.path.exists(full_path) and os.access(full_path, os.X_OK):
            return full_path
            
    return command

# Stdio MCP Client implementation
class MCPServerClient:
    def __init__(self, name: str, command: str, args: List[str]):
        self.name = name
        self.command = resolve_command_path(command)
        self.args = args
        self.process = None
        self.msg_id = 0
        self.pending_responses: Dict[int, asyncio.Future] = {}
        self.tools: List[Dict[str, Any]] = []
        self.reader_task: Optional[asyncio.Task] = None

    async def start(self):
        try:
            print(f"Starting MCP server '{self.name}': {self.command} {' '.join(self.args)}")
            self.process = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.reader_task = asyncio.create_task(self._read_loop())
            
            # Send initialize handshake
            init_res = await self.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "wirepod-agent-proxy", "version": "1.0.0"}
            })
            
            # Send initialized notification
            await self.send_notification("notifications/initialized", {})
            
            # Fetch tools
            tools_res = await self.send_request("tools/list", {})
            self.tools = tools_res.get("tools", [])
            print(f"✓ MCP Server '{self.name}' initialized successfully with {len(self.tools)} tools.")
        except Exception as e:
            print(f"✗ Failed to start/initialize MCP server '{self.name}': {e}")

    async def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self.msg_id += 1
        req_id = self.msg_id
        req = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id
        }
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_responses[req_id] = future
        
        req_str = json.dumps(req) + "\n"
        self.process.stdin.write(req_str.encode())
        await self.process.stdin.drain()
        
        try:
            response = await asyncio.wait_for(future, timeout=15.0)
            return response.get("result", {})
        except asyncio.TimeoutError:
            if req_id in self.pending_responses:
                del self.pending_responses[req_id]
            raise Exception(f"Request '{method}' (id={req_id}) timed out")

    async def send_notification(self, method: str, params: Dict[str, Any]):
        req = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        req_str = json.dumps(req) + "\n"
        self.process.stdin.write(req_str.encode())
        await self.process.stdin.drain()

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return await self.send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })

    async def _read_loop(self):
        while True:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break
                
                data = json.loads(line.decode().strip())
                req_id = data.get("id")
                if req_id is not None and req_id in self.pending_responses:
                    future = self.pending_responses.pop(req_id)
                    if not future.done():
                        future.set_result(data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in MCP client '{self.name}' read loop: {e}")

    async def stop(self):
        if self.reader_task:
            self.reader_task.cancel()
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                pass


mcp_clients: List[MCPServerClient] = []

# Modern FastAPI Lifespan Handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    servers = config.get("mcp_servers", [])
    for s in servers:
        client = MCPServerClient(s["name"], s["command"], s.get("args", []))
        await client.start()
        mcp_clients.append(client)
        print(f"Registered tools for client '{client.name}': {[t['name'] for t in client.tools]}")
    yield
    # Shutdown actions
    for client in mcp_clients:
        await client.stop()

app = FastAPI(title="Wire-Pod External Agent Proxy", lifespan=lifespan)

# Local Robot Tools Definition
LOCAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_battery",
            "description": "Get Vector's current battery state/level.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_eye_color",
            "description": "Change Vector's eye color presets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "color": {
                        "type": "string",
                        "description": "Preset eye color. Choices: 0 (Teal), 1 (Orange), 2 (Yellow), 3 (Lime Green), 4 (Sapphire Blue), 5 (Purple).",
                        "enum": ["0", "1", "2", "3", "4", "5"]
                    }
                },
                "required": ["color"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Change Vector's speaker volume level.",
            "parameters": {
                "type": "object",
                "properties": {
                    "volume": {
                        "type": "string",
                        "description": "Volume level parameter string. Recommended values: 0 (Mute), 1 (Low), 2 (Medium Low), 3 (Medium), 4 (Medium High), 5 (High).",
                        "enum": ["0", "1", "2", "3", "4", "5"]
                    }
                },
                "required": ["volume"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_intent",
            "description": "Instruct Vector to play a specific behavior or animation intent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "Intent identifier. E.g., 'intent_greeting_hello', 'intent_imperative_dance', 'intent_seasonal_happy_new_year', 'intent_clock_saytime'.",
                        "enum": ["intent_greeting_hello", "intent_imperative_dance", "intent_seasonal_happy_new_year", "intent_clock_saytime"]
                    }
                },
                "required": ["intent"]
            }
        }
    }
]

# Wire-Pod SDK API wrappers
async def execute_get_battery(esn: str) -> str:
    url = f"{config['wirepod']['base_url']}/api-sdk/get_battery?serial={esn}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        return resp.text

async def execute_set_eye_color(esn: str, color: str) -> str:
    url = f"{config['wirepod']['base_url']}/api-sdk/eye_color?serial={esn}&color={color}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        return resp.text

async def execute_set_volume(esn: str, volume: str) -> str:
    url = f"{config['wirepod']['base_url']}/api-sdk/volume?serial={esn}&volume={volume}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        return resp.text

async def execute_play_intent(esn: str, intent: str) -> str:
    url = f"{config['wirepod']['base_url']}/api-sdk/cloud_intent?serial={esn}&intent={intent}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        return resp.text

@app.post("/v1/chat/completions")
async def chat_completions(req: Dict[str, Any], authorization: Optional[str] = Header(None)):
    # 1. Resolve robot serial number (ESN)
    esn = config["wirepod"]["default_esn"]
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        if len(token) >= 8:
            esn = token

    incoming_messages = req.get("messages", [])
    print(f"Incoming Messages: {incoming_messages}")
    
    # 2. Build Tools Catalog
    tools_catalog = []
    tools_catalog.extend(LOCAL_TOOLS)

    # Merge MCP Tools
    for client in mcp_clients:
        for tool in client.tools:
            # Hide fetch_content from the LLM catalog since the proxy runs it automatically
            if tool["name"] == "fetch_content":
                continue
            # Replace hyphens with underscores for local LLM tokenizers
            tool_name = f"mcp_{client.name}_{tool['name']}".replace("-", "_")
            tools_catalog.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}})
                }
            })

    # 3. Create OpenAI Client to speak to local LLM (e.g. LM Studio / Ollama)
    openai_client = openai.AsyncOpenAI(
        base_url=config["llm"]["base_url"],
        api_key=config["llm"]["api_key"]
    )

    # Build plain text instructions describing the tools catalog
    tools_instruction = "\n\nAvailable tools:\n"
    for tool in tools_catalog:
        tools_instruction += f"- Tool Name: {tool['function']['name']}\n"
        tools_instruction += f"  Description: {tool['function']['description']}\n"
        tools_instruction += f"  Parameters (JSON Schema): {json.dumps(tool['function']['parameters'])}\n\n"
        
    tools_instruction += (
        "To execute a tool call, you MUST output the call exactly using this format in your response: \n"
        "<function=TOOL_NAME>{\"parameter_name\": \"value\"}</function>\n"
        "Do not output anything else in the message when you want to call a tool."
    )

    current_messages = []
    if len(incoming_messages) > 0:
        # Keep the system message at index 0
        current_messages.append(dict(incoming_messages[0]))
        
        # Group the rest of the history into complete user-led turns
        turns = []
        current_turn = []
        for msg in incoming_messages[1:]:
            if msg.get("role") == "user":
                if current_turn:
                    turns.append(current_turn)
                current_turn = [dict(msg)]
            else:
                current_turn.append(dict(msg))
        if current_turn:
            turns.append(current_turn)
            
        # Keep only the last 1 turn to ensure context is clean, fast, and template-compatible
        turns_limit = 1
        if len(turns) > turns_limit:
            turns = turns[-turns_limit:]
            
        for turn in turns:
            current_messages.extend(turn)

    print(f"Truncated Current Messages: {current_messages}")

    if len(current_messages) > 0 and current_messages[0]["role"] == "system":
        system_content = current_messages[0].get("content", "") or ""
        instruction = (
            "\n\nCRITICAL TOOL USE & STYLE INSTRUCTIONS:\n"
            "- You have access to tools for web search and robot control. Do NOT try to write them as {{command||parameter}} text commands.\n"
            "- If the user asks about any real-time info (like weather, news, current events, search), you MUST immediately trigger the search tool call on your first turn. Do not write conversational filler saying you will check; call the tool!\n"
            "- If the user asks you to change color, volume, play an animation, or check battery, you MUST call the corresponding native tool immediately.\n"
            "- Summarize search or weather details clearly and informatively. Keep it concise (2-3 sentences), direct, and conversational. Do NOT speak URLs or citations, but do include key highlights (like temperatures, conditions, news details) so the user gets a high-quality answer.\n"
            "- Do NOT use the getImage command unless the user explicitly requests you to take a photo, look at something, or ask what you see.\n\n"
        )
        instruction += tools_instruction
        if "CRITICAL TOOL USE & STYLE INSTRUCTIONS" not in system_content:
            current_messages[0]["content"] = system_content + instruction

    # 4. Agent Tool Calling Loop (Limit to 5 steps to avoid infinite loops)
    for step in range(5):


        # Call the LLM non-streaming first to handle potential tool calls.
        # We completely omit the "tools" and "tool_choice" parameters to prevent Groq API server validation errors.
        response = await openai_client.chat.completions.create(
            model=config["llm"]["model"],
            messages=current_messages
        )

        message = response.choices[0].message
        print(f"DEBUG: message content: {repr(message.content)}")
        print(f"DEBUG: message tool_calls: {repr(message.tool_calls)}")
        print(f"DEBUG: '<function=' in content? {'<function=' in (message.content or '')}")

        # Text-based function call fallback (e.g. Llama 3.1 or local LLMs outputting tags/braces in text)
        if not message.tool_calls and message.content:
            mock_tc = None
            intro_text = message.content
            
            # Form 1: Tag-based <function=tool_name>JSON</function>
            if "<function=" in message.content:
                match = re.search(r'<function=(\w+)>(.*?)(?:</function>|<function>|$)', message.content, re.DOTALL)
                if match:
                    tool_name = match.group(1)
                    tool_args_str = match.group(2).strip()
                    intro_text = message.content[:match.start()].strip()
                    
                    # Parse JSON arguments robustly
                    args_dict = {}
                    try:
                        args_dict = json.loads(tool_args_str)
                    except json.JSONDecodeError:
                        try:
                            import ast
                            args_dict = ast.literal_eval(tool_args_str)
                        except Exception:
                            try:
                                args_dict = json.loads(tool_args_str.replace("'", '"'))
                            except Exception:
                                pass
                    
                    if "max_results" in args_dict:
                        try:
                            args_dict["max_results"] = int(args_dict["max_results"])
                        except Exception:
                            pass
                    
                    class MockFunction:
                        def __init__(self, name, arguments):
                            self.name = name
                            self.arguments = arguments
                    class MockToolCall:
                        def __init__(self, id, function):
                            self.id = id
                            self.type = "function"
                            self.function = function
                    
                    mock_tc = MockToolCall(
                        id=f"call_{int(time.time())}",
                        function=MockFunction(name=tool_name, arguments=json.dumps(args_dict))
                    )
                    print(f"Parsed tag-based fallback tool call: {tool_name} with args: {args_dict}")

            # Form 2: Brace-based {{tool_name|param1=val1|param2=val2}}
            if not mock_tc and ("mcp_" in message.content or any(t["function"]["name"] in message.content for t in LOCAL_TOOLS)):
                tool_pattern = r'\{\{((?:mcp_\w+|get_battery|set_volume|set_eye_color|play_intent))\|(.*?)\}\}'
                match = re.search(tool_pattern, message.content)
                if match:
                    import urllib.parse
                    tool_name = match.group(1)
                    args_str = match.group(2)
                    intro_text = message.content[:match.start()].strip()
                    
                    # Parse params separated by pipe '|'
                    args_dict = {}
                    for part in args_str.split("|"):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            v_decoded = urllib.parse.unquote_plus(v)
                            if v_decoded.isdigit():
                                args_dict[k] = int(v_decoded)
                            else:
                                args_dict[k] = v_decoded
                                
                    class MockFunction:
                        def __init__(self, name, arguments):
                            self.name = name
                            self.arguments = arguments
                    class MockToolCall:
                        def __init__(self, id, function):
                            self.id = id
                            self.type = "function"
                            self.function = function
                            
                    mock_tc = MockToolCall(
                        id=f"call_{int(time.time())}",
                        function=MockFunction(name=tool_name, arguments=json.dumps(args_dict))
                    )
                    print(f"Parsed brace-based fallback tool call: {tool_name} with args: {args_dict}")

            # Form 3: plain text name + JSON (e.g. name{"query": ...})
            if not mock_tc:
                tool_names_regex = r'(mcp_\w+|get_battery|set_volume|set_eye_color|play_intent)'
                # Double curly braces compile to literal braces in f-string
                match_plain = re.search(rf'\b{tool_names_regex}\s*({{.*?}})', message.content, re.DOTALL)
                if match_plain:
                    tool_name = match_plain.group(1)
                    tool_args_str = match_plain.group(2).strip()
                    intro_text = message.content[:match_plain.start()].strip()
                    
                    # Parse JSON arguments robustly
                    args_dict = {}
                    try:
                        args_dict = json.loads(tool_args_str)
                    except json.JSONDecodeError:
                        try:
                            import ast
                            args_dict = ast.literal_eval(tool_args_str)
                        except Exception:
                            try:
                                args_dict = json.loads(tool_args_str.replace("'", '"'))
                            except Exception:
                                pass
                    
                    if "max_results" in args_dict:
                        try:
                            args_dict["max_results"] = int(args_dict["max_results"])
                        except Exception:
                            pass
                            
                    class MockFunction:
                        def __init__(self, name, arguments):
                            self.name = name
                            self.arguments = arguments
                    class MockToolCall:
                        def __init__(self, id, function):
                            self.id = id
                            self.type = "function"
                            self.function = function
                    mock_tc = MockToolCall(
                        id=f"call_{int(time.time())}",
                        function=MockFunction(name=tool_name, arguments=json.dumps(args_dict))
                    )
                    print(f"Parsed plain text fallback tool call: {tool_name} with args: {args_dict}")

            if mock_tc:
                message.content = intro_text
                message.tool_calls = [mock_tc]

        # Case A: LLM returns final text (no tool calls)
        if not message.tool_calls:
            # Fix any missing double-braces in commands
            final_text = fix_commands(message.content or "")
            print(f"Final response: {final_text}")

            if req.get("stream", False):
                async def generate():
                    chunk_id = f"chatcmpl-{int(time.time())}"
                    # Stream actual text content
                    yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': req.get('model', 'model'), 'choices': [{'index': 0, 'delta': {'content': final_text}, 'finish_reason': None}]})}\n\n"
                    # Stream finished state
                    yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': req.get('model', 'model'), 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(generate(), media_type="text/event-stream")
            else:
                return {
                    "id": response.id,
                    "object": "chat.completion",
                    "created": response.created,
                    "model": response.model,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": final_text
                        },
                        "finish_reason": "stop"
                    }]
                }

        # Case B: LLM requests tool call(s)
        tool_calls_history = []
        for tc in message.tool_calls:
            tool_calls_history.append({
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })

        # Standardize robot commands in the conversational history (clear content to prevent repeating in Turn 2)
        current_messages.append({
            "role": "assistant",
            "content": f"Checking the web for: {', '.join([tc.function.name for tc in message.tool_calls])}...",
            "tool_calls": tool_calls_history
        })

        for tc in message.tool_calls:
            tool_name = tc.function.name
            tool_args = json.loads(tc.function.arguments)
            tool_id = tc.id

            print(f"Executing Tool: {tool_name} with arguments: {tool_args}")
            tool_result = ""

            try:
                if tool_name == "get_battery":
                    tool_result = await execute_get_battery(esn)
                elif tool_name == "set_eye_color":
                    tool_result = await execute_set_eye_color(esn, tool_args.get("color"))
                elif tool_name == "set_volume":
                    tool_result = await execute_set_volume(esn, tool_args.get("volume"))
                elif tool_name == "play_intent":
                    tool_result = await execute_play_intent(esn, tool_args.get("intent"))
                elif tool_name.startswith("mcp_"):
                    # Format: mcp_{mcp_server_name}_{actual_tool_name}
                    remainder = tool_name[4:] # strip "mcp_"
                    
                    matched_client = None
                    matched_tool_name = None
                    
                    # Sort clients by length descending to match most specific name first
                    sorted_clients = sorted(mcp_clients, key=lambda c: len(c.name), reverse=True)
                    for client in sorted_clients:
                        clean_client_name = client.name.replace("-", "_")
                        prefix_to_check = clean_client_name + "_"
                        if remainder.startswith(prefix_to_check):
                            matched_client = client
                            clean_tool_name = remainder[len(prefix_to_check):]
                            
                            # Match the actual tool name
                            for tool in client.tools:
                                if tool["name"].replace("-", "_") == clean_tool_name:
                                    matched_tool_name = tool["name"]
                                    break
                            break

                    if matched_client and matched_tool_name:
                        res = await matched_client.call_tool(matched_tool_name, tool_args)
                        # Extract plain text content from the MCP response for better LLM readability
                        content_items = res.get("content", [])
                        text_parts = []
                        for item in content_items:
                            if item.get("type") == "text":
                                text_parts.append(item.get("text", ""))
                        tool_result = "\n".join(text_parts) if text_parts else json.dumps(content_items)

                        # AUTO-FETCH SCRAPING OPTIMIZATION:
                        # If this is a search query, automatically scrape the first 2 URLs returned 
                        # and append their text content directly to the tool results. This gives the local LLM
                        # actual page data on Turn 2 without requiring a multi-turn LLM reasoning chain.
                        if matched_tool_name == "search" and tool_result:
                            urls = re.findall(r'URL:\s*(https?://\S+)', tool_result)
                            urls = [u.strip() for u in urls if u.strip()][:2]
                            if urls:
                                print(f"Auto-fetching webpage contents for: {urls}")
                                for url in urls:
                                    try:
                                        fetch_res = await matched_client.call_tool("fetch_content", {"url": url, "max_length": 2500})
                                        fetch_items = fetch_res.get("content", [])
                                        fetch_text = ""
                                        for f_item in fetch_items:
                                            if f_item.get("type") == "text":
                                                fetch_text += f_item.get("text", "")
                                        if fetch_text:
                                            tool_result += f"\n\n--- WEBPAGE TEXT CONTENT FROM {url} ---\n{fetch_text[:2000]}"
                                    except Exception as fetch_err:
                                        print(f"Failed to auto-fetch URL {url}: {fetch_err}")
                    else:
                        tool_result = f"Error: MCP client matching '{remainder}' not found."
                else:
                    tool_result = f"Error: Tool '{tool_name}' is not recognized."
            except Exception as e:
                tool_result = f"Error executing tool: {e}"

            print(f"Tool Result: {tool_result}")

            # 1. Append standard 'tool' message to satisfy OpenAI API schema validation
            current_messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "name": tool_name,
                "content": str(tool_result)
            })

            # 2. Append standard 'user' message with the results to ensure LM Studio templates don't drop it
            current_messages.append({
                "role": "user",
                "content": f"[SYSTEM: The tool '{tool_name}' returned the following results:\n{tool_result}\n\nPlease consume this information and generate your final direct response to the user's query.]"
            })

    # Fallback response if loop limit reached
    return {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "I finished running tools but hit my iteration limit."
            },
            "finish_reason": "stop"
        }]
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8099)
