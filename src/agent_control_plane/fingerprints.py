"""Shadow AI/SaaS fingerprint database.

Detection signatures for identifying AI tools, LLM endpoints, coding agents,
and SaaS applications running in an organization's environment.
"""

from __future__ import annotations

from agent_control_plane.models import ShadowCategory, ShadowRisk

# Each fingerprint: {name, category, paths, body_patterns, header_patterns, port_hints, risk}
# paths: URL paths to probe (first match wins)
# body_patterns: strings to match in response body (any match = hit)
# header_patterns: {header_name: expected_value_substring}
# port_hints: common ports to check

FINGERPRINT_DB: list[dict] = [
    # ── AI APIs ──────────────────────────────────────────────────────────
    {
        "name": "OpenAI API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models", "/v1/chat/completions"],
        "body_patterns": ["gpt-4", "gpt-3.5", "data.openai.com", 'object": "list"'],
        "header_patterns": {"server": "openai", "openai-organization": ""},
        "port_hints": [443, 80],
        "risk": ShadowRisk.MEDIUM,
        "description": "OpenAI API endpoint for LLM inference",
    },
    {
        "name": "Anthropic API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/messages", "/v1/complete"],
        "body_patterns": ["claude", "anthropic"],
        "header_patterns": {"x-request-id": "", "anthropic-version": ""},
        "port_hints": [443, 80],
        "risk": ShadowRisk.MEDIUM,
        "description": "Anthropic Claude API endpoint",
    },
    {
        "name": "Google Gemini API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models", "/v1beta/models"],
        "body_patterns": ["gemini", "googleapis.com"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.MEDIUM,
        "description": "Google Gemini API endpoint",
    },
    {
        "name": "Mistral AI API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models", "/v1/chat/completions"],
        "body_patterns": ["mistral", "mistralai"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.MEDIUM,
        "description": "Mistral AI API endpoint",
    },
    {
        "name": "Groq API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models", "/openai/v1/models"],
        "body_patterns": ["groq", "mixtral", "llama-3"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.MEDIUM,
        "description": "Groq LPU inference API",
    },
    {
        "name": "Together AI API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models", "/api/models"],
        "body_patterns": ["together", "togethercomputer"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.MEDIUM,
        "description": "Together AI API endpoint",
    },
    {
        "name": "Fireworks AI API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models"],
        "body_patterns": ["fireworks", "fireworks.ai"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.MEDIUM,
        "description": "Fireworks AI inference API",
    },
    {
        "name": "DeepSeek API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models", "/v1/chat/completions"],
        "body_patterns": ["deepseek"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.MEDIUM,
        "description": "DeepSeek API endpoint",
    },
    {
        "name": "OpenRouter API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models", "/api/v1/models"],
        "body_patterns": ["openrouter"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.MEDIUM,
        "description": "OpenRouter multi-model API",
    },
    # ── Self-hosted LLMs ────────────────────────────────────────────────
    {
        "name": "Ollama",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/api/tags", "/api/version"],
        "body_patterns": ["models", "llama", "mistral", "model_name"],
        "header_patterns": {},
        "port_hints": [11434],
        "risk": ShadowRisk.CRITICAL,
        "description": "Ollama LLM server — no auth by default, common attack vector",
    },
    {
        "name": "LM Studio",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/v1/models", "/health"],
        "body_patterns": ["lm-studio", "lm_studio"],
        "header_patterns": {"server": "lm-studio"},
        "port_hints": [1234],
        "risk": ShadowRisk.CRITICAL,
        "description": "LM Studio local LLM server — local-only access",
    },
    {
        "name": "vLLM Server",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/v1/models", "/health"],
        "body_patterns": ["vllm", "vLLM"],
        "header_patterns": {"server": "vllm"},
        "port_hints": [8000],
        "risk": ShadowRisk.HIGH,
        "description": "vLLM inference server",
    },
    {
        "name": "Text Generation WebUI (oobabooga)",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/api/v1/model", "/v1/chat/completions"],
        "body_patterns": ["oobabooga", "text-generation-webui"],
        "header_patterns": {},
        "port_hints": [7860, 5000],
        "risk": ShadowRisk.HIGH,
        "description": "Text Generation WebUI LLM interface",
    },
    {
        "name": "LocalAI",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/v1/models", "/version"],
        "body_patterns": ["localai"],
        "header_patterns": {},
        "port_hints": [8080],
        "risk": ShadowRisk.HIGH,
        "description": "LocalAI self-hosted LLM server",
    },
    {
        "name": "llama.cpp Server",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/v1/models", "/infill"],
        "body_patterns": ["llama.cpp"],
        "header_patterns": {},
        "port_hints": [8080, 8081],
        "risk": ShadowRisk.HIGH,
        "description": "llama.cpp HTTP server for local inference",
    },
    {
        "name": "TabbyAPI",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/v1/models", "/v1/tokenize"],
        "body_patterns": ["tabbyapi", "exllama"],
        "header_patterns": {},
        "port_hints": [5000],
        "risk": ShadowRisk.HIGH,
        "description": "TabbyAPI ExLlama inference server",
    },
    {
        "name": "KoboldCPP",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/api/v1/model", "/api/extra/tags"],
        "body_patterns": ["koboldcpp", "kobold"],
        "header_patterns": {},
        "port_hints": [5001],
        "risk": ShadowRisk.HIGH,
        "description": "KoboldCPP LLM inference server",
    },
    # ── Coding Agents ────────────────────────────────────────────────────
    {
        "name": "Claude Code CLI",
        "category": ShadowCategory.CODING_AGENT,
        "paths": ["/health", "/api/status"],
        "body_patterns": ["claude-code", "anthropic"],
        "header_patterns": {},
        "port_hints": [8082],
        "risk": ShadowRisk.MEDIUM,
        "description": "Claude Code coding agent bridge",
    },
    {
        "name": "OpenCode Go",
        "category": ShadowCategory.CODING_AGENT,
        "paths": ["/health", "/v1/health"],
        "body_patterns": ["opencode"],
        "header_patterns": {},
        "port_hints": [8336],
        "risk": ShadowRisk.MEDIUM,
        "description": "OpenCode Go endpoint",
    },
    {
        "name": "Cursor IDE",
        "category": ShadowCategory.CODING_AGENT,
        "paths": ["/api/status"],
        "body_patterns": ["cursor"],
        "header_patterns": {},
        "port_hints": [15550],
        "risk": ShadowRisk.LOW,
        "description": "Cursor AI code editor",
    },
    {
        "name": "Continue.dev",
        "category": ShadowCategory.CODING_AGENT,
        "paths": ["/health", "/api/config"],
        "body_patterns": ["continue"],
        "header_patterns": {},
        "port_hints": [65432],
        "risk": ShadowRisk.MEDIUM,
        "description": "Continue.dev open-source coding agent",
    },
    {
        "name": "Codex CLI",
        "category": ShadowCategory.CODING_AGENT,
        "paths": ["/health", "/api/v1/models"],
        "body_patterns": ["codex"],
        "header_patterns": {},
        "port_hints": [8080],
        "risk": ShadowRisk.MEDIUM,
        "description": "OpenAI Codex CLI agent",
    },
    # ── MCP Servers ──────────────────────────────────────────────────────
    {
        "name": "MCP Server (FastMCP)",
        "category": ShadowCategory.MCP_SERVER,
        "paths": ["/mcp", "/health", "/sse"],
        "body_patterns": ["server", "tools", "FastMCP"],
        "header_patterns": {},
        "port_hints": [8000, 3000, 5000],
        "risk": ShadowRisk.HIGH,
        "description": "FastMCP server (unauthenticated MCP endpoint)",
    },
    {
        "name": "MCP Server (Generic)",
        "category": ShadowCategory.MCP_SERVER,
        "paths": ["/mcp", "/mcp/v1", "/.well-known/mcp"],
        "body_patterns": ["jsonrpc", "tools", "resources"],
        "header_patterns": {},
        "port_hints": [8000, 8080, 3000],
        "risk": ShadowRisk.HIGH,
        "description": "MCP protocol server",
    },
    {
        "name": "Agent Gateway (Bifrost)",
        "category": ShadowCategory.MCP_SERVER,
        "paths": ["/health", "/api/status"],
        "body_patterns": ["bifrost", "gateway"],
        "header_patterns": {},
        "port_hints": [8337, 8080],
        "risk": ShadowRisk.HIGH,
        "description": "Bifrost MCP+LLM gateway",
    },
    # ── AI Browsers / Automation ─────────────────────────────────────────
    {
        "name": "Browser Use",
        "category": ShadowCategory.AI_BROWSER,
        "paths": ["/health", "/api/status"],
        "body_patterns": ["browser-use", "browser_use"],
        "header_patterns": {},
        "port_hints": [3000, 5000],
        "risk": ShadowRisk.HIGH,
        "description": "Browser Use AI browser automation agent",
    },
    {
        "name": "Playwright Server",
        "category": ShadowCategory.AI_BROWSER,
        "paths": ["/health", "/status"],
        "body_patterns": ["playwright", "chromium"],
        "header_patterns": {},
        "port_hints": [3000, 9222],
        "risk": ShadowRisk.MEDIUM,
        "description": "Playwright browser automation server",
    },
    {
        "name": "Puppeteer Chrome DevTools",
        "category": ShadowCategory.AI_BROWSER,
        "paths": ["/json/version", "/json"],
        "body_patterns": ["Chrome", "chromium", "webSocketDebuggerUrl"],
        "header_patterns": {},
        "port_hints": [9222, 9229],
        "risk": ShadowRisk.HIGH,
        "description": "Chrome DevTools protocol (remote browser control)",
    },
    # ── Vector Databases ────────────────────────────────────────────────
    {
        "name": "ChromaDB",
        "category": ShadowCategory.VECTOR_DB,
        "paths": ["/api/v1/health", "/health"],
        "body_patterns": ["chroma", "chromadb"],
        "header_patterns": {},
        "port_hints": [8000],
        "risk": ShadowRisk.HIGH,
        "description": "ChromaDB vector database",
    },
    {
        "name": "Qdrant",
        "category": ShadowCategory.VECTOR_DB,
        "paths": ["/health", "/"],
        "body_patterns": ["qdrant"],
        "header_patterns": {},
        "port_hints": [6333],
        "risk": ShadowRisk.HIGH,
        "description": "Qdrant vector search engine",
    },
    {
        "name": "Weaviate",
        "category": ShadowCategory.VECTOR_DB,
        "paths": ["/v1/meta", "/health"],
        "body_patterns": ["weaviate"],
        "header_patterns": {},
        "port_hints": [8080],
        "risk": ShadowRisk.HIGH,
        "description": "Weaviate vector database",
    },
    {
        "name": "Milvus",
        "category": ShadowCategory.VECTOR_DB,
        "paths": ["/health", "/api/v1/health"],
        "body_patterns": ["milvus"],
        "header_patterns": {},
        "port_hints": [19530, 9091],
        "risk": ShadowRisk.HIGH,
        "description": "Milvus vector database",
    },
    {
        "name": "Pinecone",
        "category": ShadowCategory.VECTOR_DB,
        "paths": ["/health"],
        "body_patterns": ["pinecone"],
        "header_patterns": {"server": "pinecone"},
        "port_hints": [443],
        "risk": ShadowRisk.MEDIUM,
        "description": "Pinecone vector database (cloud)",
    },
    {
        "name": "Supabase Vector",
        "category": ShadowCategory.VECTOR_DB,
        "paths": ["/rest/v1/", "/health"],
        "body_patterns": ["supabase", "postgrest"],
        "header_patterns": {},
        "port_hints": [5432, 8000],
        "risk": ShadowRisk.MEDIUM,
        "description": "Supabase with pgvector",
    },
    # ── AI Dev Tools / Observability ────────────────────────────────────
    {
        "name": "Langfuse",
        "category": ShadowCategory.AI_DEV_TOOL,
        "paths": ["/api/public/health", "/health"],
        "body_patterns": ["langfuse"],
        "header_patterns": {},
        "port_hints": [3000],
        "risk": ShadowRisk.LOW,
        "description": "Langfuse LLM observability platform",
    },
    {
        "name": "LangSmith",
        "category": ShadowCategory.AI_DEV_TOOL,
        "paths": ["/api/v1/health", "/health"],
        "body_patterns": ["langsmith"],
        "header_patterns": {},
        "port_hints": [1984, 443],
        "risk": ShadowRisk.LOW,
        "description": "LangSmith LLM tracing",
    },
    {
        "name": "Arize AI",
        "category": ShadowCategory.AI_DEV_TOOL,
        "paths": ["/health", "/v1/health"],
        "body_patterns": ["arize"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.LOW,
        "description": "Arize AI LLM observability",
    },
    {
        "name": "Helicone",
        "category": ShadowCategory.AI_DEV_TOOL,
        "paths": ["/health", "/api/health"],
        "body_patterns": ["helicone"],
        "header_patterns": {},
        "port_hints": [443],
        "risk": ShadowRisk.LOW,
        "description": "Helicone LLM proxy and observability",
    },
    {
        "name": "Agenta",
        "category": ShadowCategory.AI_DEV_TOOL,
        "paths": ["/health", "/api/health"],
        "body_patterns": ["agenta"],
        "header_patterns": {},
        "port_hints": [3000],
        "risk": ShadowRisk.LOW,
        "description": "Agenta LLM evaluation platform",
    },
    {
        "name": "DSPy",
        "category": ShadowCategory.AI_DEV_TOOL,
        "paths": ["/api/status", "/health"],
        "body_patterns": ["dspy"],
        "header_patterns": {},
        "port_hints": [8000],
        "risk": ShadowRisk.LOW,
        "description": "DSPy LLM programming framework",
    },
    # ── Hermes / Agent Platforms ────────────────────────────────────────
    {
        "name": "Hermes Agent",
        "category": ShadowCategory.AI_DEV_TOOL,
        "paths": ["/health", "/api/status"],
        "body_patterns": ["hermes"],
        "header_patterns": {},
        "port_hints": [8337, 8777],
        "risk": ShadowRisk.MEDIUM,
        "description": "Hermes AI agent platform",
    },
    {
        "name": "Agent Gateway (generic)",
        "category": ShadowCategory.MCP_SERVER,
        "paths": ["/health", "/api/health", "/gateway/status"],
        "body_patterns": ["gateway", "agent"],
        "header_patterns": {},
        "port_hints": [8080, 8337, 9090],
        "risk": ShadowRisk.HIGH,
        "description": "Generic AI agent gateway",
    },
    # ── Audio/Media AI ──────────────────────────────────────────────────
    {
        "name": "ComfyUI",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/", "/health"],
        "body_patterns": ["comfy", "ComfyUI", "ComfyUI-frontend"],
        "header_patterns": {},
        "port_hints": [8188],
        "risk": ShadowRisk.HIGH,
        "description": "ComfyUI image generation server",
    },
    {
        "name": "Automatic1111 (Stable Diffusion)",
        "category": ShadowCategory.SELF_HOSTED_LLM,
        "paths": ["/", "/sdapi/v1/txt2img"],
        "body_patterns": ["stable diffusion", "sd-webui"],
        "header_patterns": {},
        "port_hints": [7860],
        "risk": ShadowRisk.HIGH,
        "description": "Stable Diffusion WebUI",
    },
    # ── Generic SaaS / Service Detection ────────────────────────────────
    {
        "name": "Generic OpenAI-compatible API",
        "category": ShadowCategory.AI_API,
        "paths": ["/v1/models", "/v1/chat/completions"],
        "body_patterns": ["object", "model", "data"],
        "header_patterns": {},
        "port_hints": [8000, 8080, 5000, 3000, 8337],
        "risk": ShadowRisk.MEDIUM,
        "description": "Unidentified OpenAI-compatible API server",
    },
    {
        "name": "Generic Web Service",
        "category": ShadowCategory.SAAS_APP,
        "paths": ["/", "/health", "/status"],
        "body_patterns": [],
        "header_patterns": {"content-type": "application/json"},
        "port_hints": [80, 443, 3000, 5000, 8000, 8080],
        "risk": ShadowRisk.UNKNOWN,
        "description": "Unidentified web service — further investigation needed",
    },
]


def get_fingerprints_by_category(category: str) -> list[dict]:
    """Get fingerprints matching a category."""
    return [f for f in FINGERPRINT_DB if f["category"].value == category]


def get_fingerprints_by_port(port: int) -> list[dict]:
    """Get fingerprints that commonly run on a given port."""
    return [f for f in FINGERPRINT_DB if port in f["port_hints"]]


def get_all_ports() -> set[int]:
    """Get all unique port hints across all fingerprints."""
    ports: set[int] = set()
    for f in FINGERPRINT_DB:
        ports.update(f["port_hints"])
    return ports


def match_fingerprint(
    url: str,
    status_code: int,
    body: str,
    headers: dict[str, str],
    port: int,
) -> dict | None:
    """Match an HTTP response against the fingerprint database.

    Returns the matching fingerprint dict, or None if no match.
    """
    body_lower = body.lower()
    candidates = get_fingerprints_by_port(port)

    for fp in candidates:
        # Check paths
        path_matches = any(p in url for p in fp["paths"])
        if not path_matches and fp["paths"] != ["/"]:
            # For root-only patterns, skip path check
            if fp["paths"] != ["/"]:
                continue

        # Check body patterns
        if fp["body_patterns"]:
            body_match = any(p.lower() in body_lower for p in fp["body_patterns"])
            if not body_match and fp["paths"] != ["/"]:
                continue

        # Check header patterns
        if fp["header_patterns"]:
            header_match = all(
                h.lower() in headers and v.lower() in headers.get(h, "").lower()
                if v else h.lower() in headers
                for h, v in fp["header_patterns"].items()
            )
            if not header_match:
                continue

        # If we got here and have at least body or header match
        if fp["body_patterns"] or fp["header_patterns"]:
            return fp

        # Fallback for generic services without patterns (match on port only)
        if not fp["body_patterns"] and not fp["header_patterns"] and status_code < 500:
            return fp

    return None


def classify_risk(category: str, auth_required: bool = False) -> str:
    """Get the default risk for a category, adjusted for auth."""
    base_risk = {
        "ai-api": "medium",
        "self-hosted-llm": "critical",
        "coding-agent": "medium",
        "ai-browser": "high",
        "vector-db": "high",
        "mcp-server": "high",
        "ai-dev-tool": "low",
        "browser-extension": "medium",
        "saas-app": "medium",
        "unknown": "unknown",
    }
    risk = base_risk.get(category, "unknown")
    # Self-hosted tools with auth are less risky
    if auth_required and risk in ("critical", "high"):
        return "medium"
    return risk
