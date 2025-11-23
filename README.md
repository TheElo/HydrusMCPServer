# HydrusMCPServer
An MCP Server for Hydrus Network. Connecting your LLM to an elaborate and very powerful media manager with sophisticated tag management and features.

# Setup

You need to have Docker (I use Desktop, Windows 7) installed. I've tried it with LMStudio and would recommend that for now as it gives the most control and shows all the data returned, which is great for inspection.
In terms of models I use Devstral-2507, but any agentic model that can use tools should be good. Having a large context window can also be useful to manage all the data.


Clone the repository to a directory of your choice, open a command prompt there, and run:
```bash
git clone github.com/TheElo/HydrusMCPServer
```


Add Credentials
edit the hydrus_clients.json.template file, and add your credentials there, then remove the ".template" from the end of the filename and save it so it's named "hydrus_clients.json" after that.
You can use whatever name you want, but it makes sense to keep it short, I use 2 letter codes to reduce token use per call. Adding credentials over the docker secrets hasn't worked so far, the code will probably be removed at a later stage.


Build
docker build -t hydrus-mcp-server -f ./Dockerfile .


Add Docker Catalogue
Copy the hydrus_mcp.yaml to the docker catalogue folder.


The Docker MCP catalog directory is typically located at:
```
%USERPROFILE%\.docker\mcp\catalogs`
```

On Windows, you can open this folder by:
1. Press `Win + R` to open the Run dialog
2. Type `%USERPROFILE%\.docker\mcp\catalogs` and press Enter

Copy the hydrus_mcp.yaml file to this directory. This is where Docker will look for MCP catalog definitions.


Registry Configuration
After adding your catalog file, you may need to edit the registry file:

```
%USERPROFILE%\.docker\mcp\registry.yaml
```

Add this (registry.yaml) entry under the existing `registry:` key:

```yaml
  registry:
    hydrus:
      ref: ""
```

This tells Docker about your custom MCP server.

Add the content of the mcp_lm.json to your lm studio mcp.json file. Be smart about it: If this is your only mcp server in lm studio then you can just paste the contents to the mcp.json, if you already have mcp server set up then add the content manually in the right level of the hierarchy to not break anything (basically append json data with the right brackets and position).

add the character prompt to your frontend (LMStudio, OpenWebUI, ...) where you use your LLM to the system prompt or if it has the character prompt. (#WIP, prompt is in the works)
The LLM should be able to use the tools without the character prompt but it will probably require a lot of user input to make it work well.

_Now it should work_™

# Roadmap / Ideas

- Create a single client version -> to save tokens, ease up setup
- Have different profiles with default limits for different sized context windows
- explore idea of using the description field of a client to add very detailed context about the content, special tags meanings etc.
- adding tag suggestion functionality

# Todo 
- provide character.md
- provide parcour.md - a test prompt you can give the llm to see if all works well


# Issues and Limitations
The code is in early development so it's quite buggy
You might overfill your context window very fast if you you set the default limits loose. The values are not well optimized yet. 
