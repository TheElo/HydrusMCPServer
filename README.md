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

## UVX Setup (recommended)
To configure with LM Studio, use this JSON configuration:

```json
{
	"mcpServers": {
		"hydrus-mcp": {
			"command": "uvx",
			"args": [
				"hydrus-mcp"
			],
			"env": {
				"HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"], [\"Name2\", \"http://localhost:45870/\", \"APIKEY2\"]"
			}
		}
	}
}
```

### LM Studio (addition timeout parameter specific to this and some other hosts)
LM Studio has additional timeout paramater for each mcp server which can be useful for long queries.

```json
{
	"mcpServers": {
		"hydrus-mcp": {
			"command": "uvx",
			"args": [
				"hydrus-mcp"
			],
			"env": {
				"HYDRUS_CLIENTS": "[[\"Name1\", \"http://localhost:45869/\", \"APIKEY1\"], [\"Name2\", \"http://localhost:45870/\", \"APIKEY2\"]"
			},
			"timeout": 360000
		}
	}
}
```

## UV Setup (Local Development)

The UV setup is the method for running the Hydrus MCP Server. It uses uv (a Python package manager) to manage dependencies and run the server.

### Clone the Repo
Clone the repository to a directory of your choice, open a command prompt there, and run:

```bash
git clone https://github.com/TheElo/HydrusMCPServer
```

### Install uv
```bash
pip install uv
```


### Install dependencies
Run `uv sync` to create the virtual environment and install all dependencies:

```bash
uv sync
```

### Add LM Studio MCP Configuration

Add this configuration to your LM Studio mcp.json file. If you don't use LM Studio then you maybe need to remove the timeout block as it's maybe LM Studio specific. 

1. Replace the path to where you downloaded the github project ()"c:/PATH/TO/WHERE/UV/PROJECT/IS/HydrusMCPServer")
2. Configure your Hydrus client(s) by giving them a short name, the right adress and api key

```json
{
		"mcpServers": {
			"hydrus-mcp": {
			"command": "uv",
			"args": [
				"run",
				"--project",
				"c:/PATH/TO/WHERE/UV/PROJECT/IS/HydrusMCPServer",
				"-m",
				"hydrus_mcp.server"
			],
			"env": {
				"HYDRUS_CLIENTS": "[[\"Name1\", \"http://192.168.1.20:45869/\", \"APIKEY1\"], [\"Name2\", \"http://192.168.1.20:45870/\", \"APIKEY2\"]]"
			}
		}
	}
}
```

If this is your only MCP server, simply paste the contents into `mcp.json`. If you already have other MCP servers configured, add the content manually at the appropriate level in the hierarchy to avoid breaking anything.

### Add Context to Character
Add the provided character prompt to your frontend (LM Studio, OpenWebUI, etc.) where you use your LLM or create your own. Using hydrus is a intricate task, context can help a lot to make the llm behave as you expect it would. Include it in the system prompt or use it as a character prompt. The LLM should be able to use the tools without the character prompt but it will probably require a lot of user input to make it work well or a lot of trial and error by the llm.


_Now it should work_™

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