# HydrusMCPServer
An MCP Server for Hydrus Network. Connecting your LLM to an elaborate and very powerful media manager with sophisticated tag management and features.

# Demonstration

![oh_wow.jpg]

![tag_analysis.jpg]

# Tools

The Hydrus MCP Server provides the following tools:

1. `hydrus_available_clients()` - Check which Hydrus clients are available for use
2. `hydrus_available_tag_services(client_name)` - Get available tag services for a specific Hydrus client
3. `hydrus_search_tags(client_name, search, tag_service, limit)` - Search for tags in Hydrus using keywords and wildcards
4. `hydrus_query(client_name, query, tag_service, file_sort_type, trs)` - Query files in the Hydrus client using various search criteria
5. `hydrus_get_tags(client_name, content, content_type, tag_service, trs, limit, result_limit)` - Get tags for files in Hydrus client
6. `hydrus_get_file_metadata(client_name, file_id)` - Get metadata for a file by its ID
7. `hydrus_get_page_info(client_name, page_key)` - Get page information for a specific tab using its page key
8. `hydrus_list_tabs(client_name, return_tab_keys)` - List open tabs in a Hydrus client
9. `hydrus_focus_on_tab(client_name, tab_name)` - Focus the Hydrus client on a specific tab
10. `hydrus_send_to_tab(client_name, tab_name, content, is_query, tag_service)` - Send files to a specific tab in Hydrus client
11. `hydrus_send(client_name, link, service_names_to_additional_tags, subdir, max_depth, filename, destination_page_name)` - Send a link to be downloaded to Hydrus

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

## UVX Setup
To configure with LM Studio, use this JSON configuration:

```json
{
	"mcpServers": {
		"hydrus-mcp-server": {
			"command": "uvx",
			"args": [
				"hydrus-mcp"
			],
			"env": {
				"HYDRUS_CLIENTS": "[[\"Name1\", \"http://192.168.1.20:45869/\", \"APIKEY1\"], [\"Name2\", \"http://192.168.1.20:45870/\", \"APIKEY2\"]"
			},
			"timeout": 360000
		}
	}
}
```

## UV Setup (Local Development)

The UV setup is the new recommended method for running the Hydrus MCP Server. It uses uv (a Python package manager) to manage dependencies and run the server.

### Clone the Repo
Clone the repository to a directory of your choice, open a command prompt there, and run:

```bash
git clone https://github.com/TheElo/HydrusMCPServer
```

### Install uv
If you don't have uv installed, install it with:

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
		"hydrus-mcp-server": {
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
			},
			"timeout": 360000
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


# Todo 
- Provide `parcour.md` - a test prompt to verify system functionality.
- enhance env variables to alter default settings

# Issues and Limitations
You may quickly exceed your context window limit if you set the default limits too generously.
