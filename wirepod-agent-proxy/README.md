# Wire-Pod External Agent Proxy Orchestrator

This is a standalone Python-based proxy server that acts as an OpenAI-compatible API gateway for Wire-Pod. It intercepts LLM requests from Wire-Pod, executes local robot SDK APIs and MCP tools, and returns the final answer.

## Key Features

1. **OpenAI-Compatible `/v1/chat/completions`:** Easy configuration inside Wire-Pod's Custom LLM panel.
2. **Local Robot Tools:** The LLM can dynamically call:
   - `get_battery()`: Reads current voltage and state.
   - `set_eye_color(color)`: Updates eye color preset.
   - `set_volume(level)`: Adjusts volume.
   - `play_intent(intent)`: Plays animations or greetings.
3. **MCP Tool Calling:** Support for stdio-based MCP servers.
4. **Multi-turn Agent Loop:** Resolves multiple tool dependencies before replying.
5. **No Clash Port:** Listens on port `8099` (safe from standard ports).

---

## Installation

1. Navigate to this directory:
   ```bash
   cd wirepod-agent-proxy
   ```

2. (Optional) Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Configuration

Open `config.json` and customize the fields:

```json
{
  "llm": {
    "base_url": "http://localhost:1234/v1",       // URL to your local LM Studio / Ollama / OpenAI
    "api_key": "lm-studio",                       // LLM API Key (put "lm-studio" or your OpenAI API Key)
    "model": "meta-llama-3-8b-instruct"            // The model ID to load
  },
  "wirepod": {
    "base_url": "http://localhost:8080",          // The base URL of your Wire-Pod SDK API (default: 8080)
    "default_esn": "00e00000"                     // Fallback robot serial if none is supplied
  },
  "mcp_servers": [                                // (Optional) Configure stdio-based MCP Servers here
    {
      "name": "everything",
      "command": "node",
      "args": ["/absolute/path/to/mcp-server/index.js"]
    }
  ]
}
```

---

## Running the Proxy

Start the proxy server using:
```bash
python main.py
```
Or use the convenience startup script:
```bash
./start.sh
```

---

## Configuring Wire-Pod Integration

1. Access your Wire-Pod setup console in your browser (default is `http://localhost:8080`).
2. Go to the **Knowledge Graph** section.
3. Select **custom** as the provider.
4. Fill in the parameters:
   * **Endpoint:** `http://localhost:8099/v1` (or the IP address of the machine running this proxy, if separate).
   * **Model:** (Any string; it will be overwritten by `config.json`'s model).
   * **API Key:** Set this to your robot's **Serial Number (ESN)** (e.g. `00e20120`). The proxy dynamically reads this API Key as the ESN to control the correct robot!
