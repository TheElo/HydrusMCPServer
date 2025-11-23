# HydrusMCPServer
A MCP Server for Hydrus Network. Connecting your LLM to a inticate and very powerfule media manager with sophisticated tags managementen and features. 

# Setup

You need to have docker (I use desktop, win7) installed and I tried it with using LMStudio, and would recommend that for now as it gives the most control and shows all the data returned which is great for inspection.
In terms of models I use Devstral-2507, but any agentic model that can use tools should be good. Having a large context window can also be useful to manage all the data.


copy the git to a directory where you want, open a cmd there and then do 
git copy #WIP

Add Credentials
edit the hydrus_clients.json.template file, and add your credentials there, then remove the ".template" from the end of the filename and save it so it's named "hydrus_clients.json" after that.
You can use whatever name you want, but it makes sense to keep it short, I use 2 letter codes to reduce token use per call. 

Build
docker build -t hydrus-mcp-server -f ./Dockerfile .

Add to Docker Catalogue
I have not figured out yet how to a diffrent catalogue than the default one, my solution is probably overly complicated but that was based on a tutorial that I found helpful accomplish it working and found others a bit overwhelming.

Add this to the lm studio tools file



add the character prompt to your frontend (LMStudio, OpenWebUI, ...) where you use your LLM to the system prompt or if it has the character prompt.
The LLM should be able to use the tools without the character prompt but it will probably require a lot of user input to make it work well.



# Roadmap / Ideas

- Create a single client version -> to save tokens, ease up setup


# Issues and Limitations
The code is in early development so it's quite buggy

Stopped Working, tools gone?
Currently we add our tools to the docker-mcp catalogue which gets updated regularly. Just append the hydrus information again and it should work again. from custom.yaml to docker-mcp.yaml, leave out the first couple line till "hydrus".
