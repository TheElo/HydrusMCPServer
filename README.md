# HydrusMCPServer
An MCP Server for Hydrus Network. Connecting your LLM to an elaborate and very powerful media manager with sophisticated tag management and features.

# Demonstration

![oh_wow.jpg]

![tag_analysis.jpg]

## Example Prompts

...

# Setup

You need to have Docker (I use Desktop, Windows 7) installed. I've tried it with LMStudio and would recommend that for now as it gives the most control and shows all the data returned, which is great for inspection.
In terms of models I use Devstral-2507, but any agentic model that can use tools should be good. Having a large context window can also be useful to manage all the data.


## Docker Setup 

###  Clone the Repo
Clone the repository to a directory of your choice, open a command prompt there, and run:

```bash
git clone https://github.com/TheElo/HydrusMCPServer
```

###  Add Credentials
Edit the `hydrus_clients.json.template` file, and add your credentials there. Then remove the ".template" extension and save it as "hydrus_clients.json".
You can use any name you prefer, but keeping it short is advisable. I use 2-letter codes to reduce token usage per call. Note that adding credentials via Docker secrets hasn't worked reliably yet, and this functionality may be removed in future versions.


### Build The Imagge
```
docker build -t hydrus-mcp-server -f ./Dockerfile .
```

### Add Docker Catalogue
Copy the `hydrus_mcp.yaml` to the docker catalogue folder.


The Docker MCP catalog directory is typically located at:

On Windows:
```
%USERPROFILE%\.docker\mcp\catalogs
```

You can open this folder by:
1. Press `Win + R` to open the Run dialog
2. Type `%USERPROFILE%\.docker\mcp\catalogs` and press Enter

Copy the `hydrus_mcp.yaml` file to this directory. This is where Docker will look for MCP catalog definitions.


#### Docker MCP Registry Configuration
edit the registry file:

```
%USERPROFILE%\.docker\mcp\registry.yaml
```

Add this `registry.yaml` entry under the existing `registry:` key:

```yaml
registry:
  hydrus:
    ref: ""
```

## LM Studio Setup

### Edit the mcp.json
Add the content of `mcp_lm.json` to your LM Studio's `mcp.json` file. If this is your only MCP server, simply paste the contents into `mcp.json`. If you already have other MCP servers configured, add the content manually at the appropriate level in the hierarchy to avoid breaking anything. If you don't use LM Studio, then you can remove the `timeout` in case it might create compatability issues.

### Add Context to Character
Add the character prompt to your frontend (LM Studio, OpenWebUI, etc.) where you use your LLM. Include it in the system prompt or use it as a character prompt. The LLM should be able to use the tools without the character prompt but it will probably require a lot of user input to make it work well.


_Now it should work_™

# Roadmap / Ideas

- adding tag suggestion functionality
- Have different profiles with default limits for different sized context windows
- Explore using the description field of clients to provide detailed context about content and special tag meanings.

On Hold
- Create a singular client version to reduce token usage and streamline setup -> on hold, not necessary at this stage, only minor performance expected (slightly less token use)

# Todo 
- Provide `parcour.md` - a test prompt to verify system functionality.

# Issues and Limitations
You may quickly exceed your context window limit if you set the default limits too generously.
