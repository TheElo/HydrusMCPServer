# HydrusMCP
An MCP Server for Hydrus Network. Connecting your LLM to an elaborate and very powerful media manager with sophisticated tag management and features.

# Demonstration
#WIP
![oh_wow.jpg]

![tag_analysis.jpg]

# Tools

The Hydrus MCP Server provides the following tools:

1. `hydrus_available_clients()` - Check which Hydrus clients are available for use
2. `hydrus_available_tag_services(client_name)` - Get available tag services for a specific Hydrus client
3. `hydrus_search_tags(client_name, search, tag_service, limit)` - Search for tags in Hydrus using keywords and wildcards
4. `hydrus_query(client_name, query, tag_service, file_sort_type, trs)` - Query files in the Hydrus client using various search criteria
5. `hydrus_get_tags(client_name, content, content_type, tag_service, trs, limit, result_limit)` - Get tags for files in Hydrus client
6. `hydrus_get_file_metadata(client_name, file_id, hashes, filter)` - Get metadata for one or more files by their IDs or SHA256 hashes (supports multiple file IDs/hashes and optional field filtering)
7. `hydrus_get_page_info(client_name, page_key)` - Get page information for a specific tab using its page key
8. `hydrus_list_tabs(client_name, return_tab_keys)` - List open tabs in a Hydrus client
9. `hydrus_focus_on_tab(client_name, tab_name)` - Focus the Hydrus client on a specific tab
10. `hydrus_send_to_tab(client_name, tab_name, content, is_query, tag_service)` - Send files to a specific tab in Hydrus client
11. `hydrus_send(client_name, link, service_names_to_additional_tags, subdir, max_depth, filename, destination_page_name)` - Send a link to be downloaded to Hydrus
12. `hydrus_add_tags(client_name, file_ids, target_tag_service, tags)` - Add tags to files in Hydrus client (requires explicit enablement)
13. `hydrus_show_files(client_name, file_ids, frame_count)` - Show multiple image or video files from Hydrus (optimized for large files using direct disk access)
14. `hydrus_inspect_files(client_name, file_ids, prompt, frame_count)` - Send multiple images or videos from Hydrus to a vision API for description/analysis (requires vision API configuration)
15. `hydrus_transcribe_audio(client_name, file_id)` - Transcribe audio from audio files (mp3, wav, aac, flac) or video files (mp4, webm, avi) using a speech-to-text API (requires STT API configuration)
16. `hydrus_execute(client_name, action, kwargs)` - Execute any hydrus_api.Client method dynamically or list available methods (requires EXEC_WHITELIST configuration)

# Abilities

The server enables the LLM to:

- **Discover and connect** to multiple Hydrus clients simultaneously
- **Search and query** files using complex tag syntax with wildcards
- **Analyze tag distributions** across large file collections with summary views
- **Retrieve detailed metadata** for individual files including timestamps, file types, and all associated tags
- **Manage tabs and pages** within Hydrus client interface
- **Send files for download** from URLs with optional recursive directory scraping
- **Organize files** by sending them to specific tabs with custom tags
- **Handle large result sets** with configurable limits and threshold-based summary views

## Example Prompts

...

# Setup

## Quick Start (Minimal Config)

The absolute minimum to get started:

```json
{
  "mcpServers": {
    "hydrus-mcp": {
      "command": "uvx",
      "args": ["hydrus-mcp"],
      "env": {
        "HYDRUS_CLIENTS": "[[\"myhydrus\", \"http://localhost:45869/\", \"YOUR_API_KEY\"]]"
      }
    }
  }
}
```


**That's it!** Replace `YOUR_API_KEY` with your actual Hydrus API key and you're done.

---

## Complete Configuration Reference

Here's the full configuration with all optional features:



```json
{
  "mcpServers": {
    "hydrus-mcp": {
      "command": "uvx",
      "args": ["hydrus-mcp"],
      "env": {
        "HYDRUS_CLIENTS": "[[\"name1\", \"http://localhost:45869/\", \"apikey1\"], [\"name2\", \"http://localhost:45870/\", \"apikey2\"]]",
        "MCP_TRANSPORT": "stdio",
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": "8000",
        "VISION_API_URL": "http://localhost:11434/v1/chat/completions",
        "VISION_API_KEY": "",
        "VISION_MODEL": "llava",
        "STT_API_URL": "http://localhost:5092/v1/audio/transcriptions",
        "STT_API_KEY": "sk-no-key-required",
        "STT_MODEL": "parakeet-tdt-0.6b-v3",
        "HYDRUS_ADD_TAGS_ENABLED": "true",
        "HYDRUS_ADD_TAGS_WHITELIST": "myhydrus:llm_tags,auto_tags",
        "EXEC_WHITELIST": "get_api_version,get_mr_bones"
      },
      "timeout": 360000
    }
  }
}
```

---

## Environment Variable Reference

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `HYDRUS_CLIENTS` | JSON array of `[name, url, apikey]` tuples | `"[["myhydrus", "http://localhost:45869/", "ABC123"]]"` |

### Optional - Transport Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `stdio` | Transport mode: `stdio`, `streamable-http`, or `sse` |
| `MCP_HOST` | `127.0.0.1` | Host to bind to (use `0.0.0.0` for external access) |
| `MCP_PORT` | `8000` | Port for HTTP transports |

**When to use streamable-http:** Web-based clients like llama-server webui, OpenWebUI, or remote access scenarios.

### Optional - Vision API

Enable image/video analysis with tools like `hydrus_inspect_files`.

| Variable | Required | Description |
|----------|----------|-------------|
| `VISION_API_URL` | Yes | OpenAI-compatible vision API endpoint |
| `VISION_API_KEY` | No | API key (if required) |
| `VISION_MODEL` | Yes | Model name (e.g., `llava`, `bakllava`) |

### Optional - Speech-to-Text

Enable audio transcription with `hydrus_transcribe_audio`.

| Variable | Required | Description |
|----------|----------|-------------|
| `STT_API_URL` | Yes | OpenAI-compatible STT API endpoint |
| `STT_API_KEY` | No | API key (default: `sk-no-key-required`) |
| `STT_MODEL` | Yes | Model name (e.g., `parakeet-tdt-0.6b-v3`) |

**Note:** Requires `ffmpeg` installed on the system for video files.

### Optional - Tag Addition (DANGEROUS)

Allows the LLM to add tags to files. **Use with extreme caution.**

| Variable | Description |
|----------|-------------|
| `HYDRUS_ADD_TAGS_ENABLED` | Set to `"true"` to enable |
| `HYDRUS_ADD_TAGS_WHITELIST` | Format: `client_name:service1,service2\|client2:service3` |

**Recommendation:** Create a dedicated tag service for LLM use to avoid polluting existing tags.

### Optional - Dynamic API Execution

Allows calling any Hydrus API method dynamically via `hydrus_execute`.

| Variable | Description |
|----------|-------------|
| `EXEC_WHITELIST` | Comma-separated list of allowed method names |

**Security:** Deny-by-default. Only `action='list'` is allowed without whitelist.

### Optional - LM Studio Specific

| Variable | Description |
|----------|-------------|
| `timeout` | Request timeout in milliseconds (LM Studio only) |

---

## Common Setup Examples

### Example 1: Basic Local Setup (LM Studio)

LM Studio has additional timeout paramater for each mcp server which can be useful for long queries.
```json
{
  "mcpServers": {
    "hydrus-mcp": {
      "command": "uvx",
      "args": ["hydrus-mcp"],
      "env": {
        "HYDRUS_CLIENTS": "[[\"main\", \"http://localhost:45869/\", \"YOUR_API_KEY\"]]"
      },
      "timeout": 360000
    }
  }
}
```

### Example 2: With Vision API (Ollama)

```json
{
  "mcpServers": {
    "hydrus-mcp": {
      "command": "uvx",
      "args": ["hydrus-mcp"],
      "env": {
        "HYDRUS_CLIENTS": "[[\"main\", \"http://localhost:45869/\", \"YOUR_API_KEY\"]]",
        "VISION_API_URL": "http://localhost:11434/v1/chat/completions",
        "VISION_MODEL": "llava"
      }
    }
  }
}
```

### Example 3: Web Client (llama-server webui)

```json
{
  "mcpServers": {
    "hydrus-mcp": {
      "url": "http://localhost:8000"
    }
  }
}
```

Then run the server separately:
```bash
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 HYDRUS_CLIENTS='[["main", "http://localhost:45869/", "KEY"]] uvx hydrus-mcp
```

### Example 4: Full Feature Setup

```json
{
  "mcpServers": {
    "hydrus-mcp": {
      "command": "uvx",
      "args": ["hydrus-mcp"],
      "env": {
        "HYDRUS_CLIENTS": "[[\"main\", \"http://localhost:45869/\", \"KEY\"]]",
        "VISION_API_URL": "http://localhost:11434/v1/chat/completions",
        "VISION_MODEL": "llava",
        "STT_API_URL": "http://localhost:5092/v1/audio/transcriptions",
        "STT_MODEL": "parakeet-tdt-0.6b-v3",
        "HYDRUS_ADD_TAGS_ENABLED": "true",
        "HYDRUS_ADD_TAGS_WHITELIST": "main:llm_tags"
      }
    }
  }
}
```

---

## UV Setup (Local Development)

For local development instead of `uvx`:

```bash
git clone https://github.com/TheElo/HydrusMCPServer
cd HydrusMCPServer
pip install uv
uv sync
```

Then use this configuration:

```json
{
  "mcpServers": {
    "hydrus-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "c:/PATH/TO/HydrusMCPServer",
        "-m",
        "hydrus_mcp.server"
      ],
      "env": {
        "HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"]]"
      }
    }
  }
}
```

---

## Add Context to Character (Recommended)

Add the provided `character_prompt.md` to your frontend (LM Studio, OpenWebUI, etc.) where you use your LLM. Using Hydrus is an intricate task -- context helps the LLM behave as expected. The LLM can use the tools without the character prompt, but it will require more user input or trial and error.

_Now it should work_™

---

## Tips

1. **Use short client names** - Saves tokens on every API call (e.g., `mh` instead of `my_hydrus_client`)
2. **Provide context** - Add information about your Hydrus structure to your system prompt for better results
3. **Start minimal** - Only add optional features as you need them
4. **Backup before enabling tag addition** - The LLM can pollute your tags if not carefully configured

---

## Troubleshooting

**"No Hydrus clients configured"**
- Check that `HYDRUS_CLIENTS` is set correctly
- Ensure the JSON format is valid
- Verify your API key is correct

**Connection timeout**
- Increase the `timeout` value (LM Studio)
- Check that your Hydrus server is running and accessible

**Vision/STT tools not working**
- Ensure the respective environment variables are set
- Verify the API endpoints are accessible

# Tipps & Tricks
- provide more context about your structure, content, usecases, strategies as context to your llm either in the chat or in the agent prompt. Hydrus is tricky to use already for a human, a llm needs also some context to understand how to use the tools and when. 
- Use short names (like 2 letter codes) for your clients to save tokens per call

# Roadmap / Ideas

- adding tag suggestion functionality
- better context size managment and settings
- Explore using the description field of clients to provide detailed context about content and special tag meanings.
- solo client mode over a env variable, so the llm does not have to state the client name each time


# Todo 
- Provide `parcour.md` - a test prompt to verify system functionality.
- enhance env variables to alter default settings

# Issues and Limitations
You may quickly exceed your context window limit if you set the default limits too generously.

# Warning
Some of the tools can damage your hydrus setup, ideally do not allow the llm to use them without explicit approval or deactivate them. 
By most dangerous first:

`hydrus_add_tags`
This is the most dangerous one directly for you. By allowing the llm to add tags to a tag service, it can fill a tag service with wrong tags or garbage and by that make the tag service so polluted that it's useles. Have a backup of your client handy if you want to enable this and know exactly what you want to do.

`hydrus_send`
This tool can send links to your hydrus client. The files itself can be harmful. It could send too many links which would fill up your hard drive. It could attempt to send legally questionable links to your client which could lead to legal action against you. 

`hydrus_send_to_tab`
This tool can send files to tabs. Theoretically your llm could add files to tabs you currently work on and disturb that tab session. In an extreme case this tool can be used to fill tabs with garbage till the session becomes to large for your system or hitting a unexpected limit.

# Advanced: Enabling Tag Addition

The `hydrus_add_tags` tool allows the LLM to add tags to files, but it is **disabled by default** for safety reasons. This tool can modify your Hydrus database, so it requires explicit configuration.
Recommendation: Create a tag service specifically for your LLM, this way it won't pollute existing tag services.

## Security Features

- **Opt-in enablement:** The tool is disabled unless explicitly enabled via environment variable
- **Client whitelist:** Only specific clients can be allowed to use this feature
- **Tag service whitelist:** Only specific tag services per client can be used
- **Per-client validation:** A tag service whitelisted on one client does not grant access on another client

## Configuration

Add the following environment variables to your MCP configuration:

```json
{
    "mcpServers": {
        "hydrus-mcp": {
            "command": "uvx",
            "args": [
                "hydrus-mcp"
            ],
            "env": {
				"HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"], [\"Name2\", \"http://localhost:45870/\", \"APIKEY2\"]]",
                "HYDRUS_ADD_TAGS_ENABLED": "true",
                "HYDRUS_ADD_TAGS_WHITELIST": "Name1:tag_service_name1,tag_service_name2|Name2:tag_service_name3"
            }
        }
    }
}
```

# Optional: Vision API for Image Description

The `hydrus_inspect_file` tool allows the LLM to send images or videos from Hydrus to a vision API for description and analysis. This requires an OpenAI-compatible vision API endpoint (e.g., Ollama, LM Studio, or other local LLM servers with vision capabilities).

## Configuration

Add the following environment variables to your MCP configuration to enable the vision API:

```json
{
    "mcpServers": {
        "hydrus-mcp": {
            "command": "uvx",
            "args": [
                "hydrus-mcp"
            ],
            "env": {
                "HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"], [\"Name2\", \"http://localhost:45870/\", \"APIKEY2\"]]",
                "VISION_API_URL": "http://localhost:11434/v1/chat/completions",
                "VISION_API_KEY": "",
                "VISION_MODEL": "llava"
            }
        }
    }
}
```

# Optional: Speech-to-Text API for Audio Transcription

The `hydrus_transcribe_audio` tool allows the LLM to transcribe audio from audio files (MP3, WAV, AAC, FLAC, M4A) or video files (MP4, WebM, AVI) using an OpenAI-compatible speech-to-text API.

This has been tested with [Parakeet TDT](https://github.com/groxaxo/parakeet-tdt-0.6b-v3-fastapi-openai).

## Configuration

Add the following environment variables to your MCP configuration to enable the STT API:

```json
{
    "mcpServers": {
        "hydrus-mcp": {
            "command": "uvx",
            "args": [
                "hydrus-mcp"
            ],
            "env": {
                "HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"], [\"Name2\", \"http://localhost:45870/\", \"APIKEY2\"]]",
                "STT_API_URL": "http://localhost:5092/v1/audio/transcriptions",
                "STT_API_KEY": "sk-no-key-required",
                "STT_MODEL": "parakeet-tdt-0.6b-v3"
            }
        }
    }
}
```

## Requirements

- **ffmpeg** must be installed on the system for video file audio extraction

## Supported Formats

- **Audio files**: MP3, WAV, AAC, FLAC, M4A
- **Video files**: MP4, WebM, AVI (audio track is automatically extracted)

# Optional: Streamable HTTP Transport

By default, the Hydrus MCP Server uses the `stdio` transport, which is suitable for local MCP clients like Claude Desktop or LM Studio. However, you can also run the server with `streamable-http` or `sse` transport for web-based clients and remote access.

## When to Use Streamable HTTP

- **Web-based MCP clients** (e.g., llama-server webui, OpenWebUI)
- **Remote access** to the MCP server from other machines
- **Containerized deployments** (Docker, Kubernetes)
- **Load-balanced or distributed setups**

## Configuration

Add the following environment variables to your MCP configuration:

```json
{
    "mcpServers": {
        "hydrus-mcp": {
            "command": "uvx",
            "args": [
                "hydrus-mcp"
            ],
            "env": {
                "HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"]]",
                "MCP_TRANSPORT": "streamable-http",
                "MCP_HOST": "0.0.0.0",
                "MCP_PORT": "8000"
            }
        }
    }
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `stdio` | Transport type: `stdio`, `streamable-http`, or `sse` |
| `MCP_HOST` | `127.0.0.1` | Host address to bind to (use `0.0.0.0` for external access) |
| `MCP_PORT` | `8000` | Port number for HTTP transport |

### Client Configuration for Streamable HTTP

When using streamable-http transport, configure your MCP client to connect via URL:

```json
{
    "mcpServers": {
        "hydrus-mcp": {
            "url": "http://localhost:8000"
        }
    }
}
```

### Using with mcp-remote Proxy

Some clients only support stdio but you want to use a remote HTTP server. You can use the `mcp-remote` proxy:

```json
{
    "mcpServers": {
        "hydrus-mcp": {
            "command": "npx",
            "args": [
                "-y",
                "mcp-remote",
                "http://localhost:8000"
            ],
            "env": {
                "HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"]]"
            }
        }
    }
}
```

## Running as a Standalone HTTP Server

You can also run the server as a standalone HTTP service:

```bash
export MCP_TRANSPORT=streamable-http
export MCP_HOST=0.0.0.0
export MCP_PORT=8000
export HYDRUS_CLIENTS='[["Name1", "http://localhost:45869/", "APIKEY1"]]'
uv run -m hydrus_mcp.server
```

Or with uvx:

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8000 HYDRUS_CLIENTS='[["Name1", "http://localhost:45869/", "APIKEY1"]] uvx hydrus-mcp
```

Or with local development (uv run):

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=8070 HYDRUS_CLIENTS='[["Hy1", "http://localhost:45869/", "xyz"]]' uv run -m hydrus_mcp.server
```

The server will start and listen on the specified host and port.

### Multi-Machine Setup

For multi-machine configurations (e.g., Hydrus on one machine, LLM on another, web interface on a third), the server includes CORS middleware to handle cross-origin requests. Without proper CORS configuration, you may encounter 405 Method Not Allowed errors.

The server supports custom mount paths via the `MCP_MOUNT_PATH` environment variable (default: `/mcp`).

---

# Optional: Execute Any Hydrus API Method

The `hydrus_execute` tool allows the LLM to call ANY method available on the `hydrus_api.Client` object dynamically. This provides access to all 62+ Hydrus API methods that may not have dedicated MCP tools.

## Security Model

This tool uses a **deny-by-default** security model:
- By default, only `action='list'` is allowed (to list available methods)
- All other method calls require explicit whitelisting via the `EXEC_WHITELIST` environment variable
- This prevents accidental or malicious execution of dangerous API methods

## Configuration

Add the `EXEC_WHITELIST` environment variable to your MCP configuration:

```json
{
    "mcpServers": {
        "hydrus-mcp": {
            "command": "uvx",
            "args": [
                "hydrus-mcp"
            ],
            "env": {
                "HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"]]",
                "EXEC_WHITELIST": "get_api_version,get_mr_bones"
            }
        }
    }
}
```


**Only whitelist methods you explicitly want the LLM to use and understand the risks of. Currently the commands are whitelisted for ALL clients.**

# Limitations

## hydrus_show_file
- Animated GIFs work up to a size of ~2 MB

# Notes

You maybe need to replace "localhost" with your actual IP