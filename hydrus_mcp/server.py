import os
import sys
import logging
import json
import math
import tempfile
from datetime import datetime, timezone
import httpx
import hydrus_api, hydrus_api.utils
import cv2
import numpy as np
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image
from mcp.types import ImageContent
from typing import Optional, Annotated
from pydantic import Field

# Import utility functions from the local module
from .functions import get_tags, get_tags_summary, parse_hydrus_tags, get_client_by_name, load_clients_from_secret, get_service_key_by_name, get_page_info, find_page_by_name, extract_tabs_from_pages

# Configure logging to stderr
# Set root logger to WARNING to suppress noisy debug messages from MCP library
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

# Set our custom logger to INFO for useful application-level messages
logger = logging.getLogger("hydrus_mcp.server")
logger.setLevel(logging.INFO)

# Initialize MCP server - NO PROMPT PARAMETER!
mcp = FastMCP("hydrus")

@mcp.tool()
async def hydrus_available_clients() -> str:
    """Check which Hydrus clients are available for use.

    This function verifies the availability of Hydrus clients by attempting to connect to each one.
    It returns a list of client names that were successfully connected to, along with an error message if no clients are available.
    """
    clients = load_clients_from_secret()

    if not clients:
        return "❌ Error: No Hydrus clients configured. Set HYDRUS_CLIENTS environment variable with client credentials."

    result = ""

    available = []
    for client in clients:
        try:
            api_client = hydrus_api.Client(access_key=client["apikey"], api_url=client["url"])
            # Try a simple API call to verify connection
            version = api_client.get_api_version()
            result += f", {client['name']}"
            available.append(client['name'])
        except Exception as e:
            pass

    if not available:
        return "❌ Error: No clients could be connected. Check your credentials and network settings."

    return f"Available clients: {', '.join(available)}"


@mcp.tool()
async def hydrus_available_tag_services(client_name: Annotated[str, Field(description="The name of the Hydrus client. Required.")] = "") -> str:
    """Get available tag services for a specific Hydrus client.

    This function retrieves the list of tag services configured in a specified Hydrus client.
    Tag services are used to organize and search tags within the client.

    Use this function to discover which tag services are available for searching and filtering.
    Tag services can be used with other functions to narrow down searches or limit results to a specific tag service.
    """
    if not client_name.strip():
        return "❌ Error: Client name is required"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join([c['name'] for c in load_clients_from_secret()])}"

    try:
        # Get services from the client and extract names instead of keys
        services_dict = client_obj.get_services()
        service_names = [service_info['name'] for service_info in services_dict['services'].values()]

        if not service_names:
            return f"❌ Error: No tag services found for client '{client_name}'"

        result = f"✅ Available tag services for {client_name}: "
        for name in service_names:
            result += f", '{name}'"

        return result.strip()

    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_search_tags(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    search: Annotated[str, Field(description="Search query string")] = "",
    tag_service: Annotated[str, Field(description="Tag service name (default: 'all known tags')")] = "all known tags",
    limit: Annotated[str, Field(description="Number of tags to be returned from the results by count from the top. (default: '150')")] = "150"
) -> str:
    """Search for tags in Hydrus using keywords and wildcards."""
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not search.strip():
        return "❌ Error: Search query is required"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"

    try:
        service_key = str(get_service_key_by_name(client_obj, tag_service))

        # Execute the search
        results = client_obj.search_tags(search=search, tag_service_key=service_key)

        # Format the output
        result = f"✅ Tag Search Results for '{search}' (from {client_name}) format 'tag_name'(count): "

        # Check if results are valid and contain tags
        if not results or 'tags' not in results:
            return "❌ Error: No tags found or invalid response format"

        # Get the tags list safely
        tags_list = results.get('tags', []) # 23Okt2025 testing
        # tags_list = results['tags']
        if not tags_list:
            return "❌ Error: No tags found matching your search criteria"

        # Convert limit to integer - handle both string and numeric formats
        try:
            trs_int = int(limit) if limit.strip().isdigit() else 150
        except (ValueError, AttributeError):
            trs_int = 150

        # Check if we need to limit the results based on limit
        total_tags = len(tags_list)
        if total_tags > trs_int:
            result += f" (Showing {trs_int} of {total_tags} tags due to limit parameter)"

            # Sort tags by count descending for consistent ordering
            sorted_tags = sorted(tags_list, key=lambda x: x.get('count', 0), reverse=True)
            tags_to_show = sorted_tags[:trs_int]
        else:
            tags_to_show = tags_list

        for tag_info in tags_to_show:
            tag_name = tag_info.get('value', 'unknown')
            count = tag_info.get('count', 0)
            result += f", '{tag_name}'({count})"

        return result.strip()

    except ValueError:
        return "❌ Error: Invalid search parameters"
    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_query(
    client_name: Annotated[str, Field(description="The name of the Hydrus client to query. Required.")] = "",
    query: Annotated[str, Field(description="The search query string containing tags to search for. Supports Hydrus tag syntax with wildcards and complex tags. Required.")] = "",
    tag_service: Annotated[str, Field(description="The tag service to use for the search. Default is 'all known tags'. You can specify a specific tag service name if needed.")] = "all known tags",
    file_sort_type: Annotated[str, Field(description="Sorting method for files. Default is '13' (sorted by 'has audio' as this is the fastest search). Other values may be supported depending on the Hydrus client version.")] = "13",
    trs: Annotated[str, Field(description="Threshold for returning results. Default is '100'. If the number of matching files exceeds this threshold, only a subset will be returned with information about the total count.")] = "100"
):
    """Query files in the Hydrus client using various search criteria.

    This function allows you to search for files in a Hydrus client based on tags and other parameters.
    It returns file IDs that match the search criteria, which can be used for further operations.

    The query parameter should use Hydrus tag syntax (e.g., "character:samus aran", "system:inbox", "system:limit is 100").
    For large result sets, consider adjusting the trs parameter to control performance.
    File IDs returned can be used with other Hydrus functions for further operations.
    """
    if not client_name.strip():
        return json.dumps({"error": "Client name is required"})
    if not query.strip():
        return json.dumps({"error": "Query is required"})

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return json.dumps({"error": f"Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"})

    try:
        # Convert parameters
        trs_int = int(trs) if trs.strip().isdigit() else 100
        file_sort_type_int = int(file_sort_type) if file_sort_type.strip().isdigit() else 13

        # Parse query - handle Hydrus tag syntax properly
        # only split on commas when they're not part of a more complex tag

        # Parse the query
        tags = parse_hydrus_tags(query)

        # Build the search parameters based on the query format
        search_params = {
            "tags": tags,
            "file_sort_type": file_sort_type_int
        }

        if tag_service and tag_service != "all known tags":
            service_key = get_service_key_by_name(client_obj, tag_service)
            if service_key:
                # search_params["tag_service_name"] = [service_key] #v
                search_params["tag_service_key"] = [service_key]

        # Execute the search
        file_ids = client_obj.search_files(**search_params)

        try:
            file_ids = file_ids["file_ids"]
        except:
            return json.dumps(file_ids)

        try:
            # count = len(file_ids["file_ids"]) #v
            count = len(file_ids)
        except:
            return json.dumps(file_ids)

        if int(trs) < count:
            # Return first trs file IDs when count exceeds threshold
            file_ids = file_ids[:trs_int]
            return f"Found {count} files, more than the threshold of {trs}, here are the first {trs_int} file ids from the results: {file_ids}"

        if len(file_ids) == 0:
            response = {"error": f"No files found for the query '{query}' on the client '{client_name}' in the tag service '{tag_service}'. Ensure that your query is correctly formatted, the tags exist on that tag service in that client or that there are actually existing files with that tag combination"}
        else:
            # Always return file IDs as an array in a JSON object
            response = {"file_ids": file_ids}

        # Return compact JSON without newlines or extra spaces
        return json.dumps(response, separators=(",", ":"))

    except ValueError:
        return json.dumps({"error": "Invalid numeric parameter"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def hydrus_get_tags(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    content: Annotated[str, Field(description="Content to process - query string, comma-separated file IDs, or page key")] = "",
    content_type: Annotated[str, Field(description="Type of content - 'file_ids', 'query', or 'page_key' (default: 'query')")] = "query",
    tag_service: Annotated[str, Field(description="Tag service name (default: 'all known tags')")] = "all known tags",
    trs: Annotated[str, Field(description="Threshold for summary view. If the threshold is lower than the received file ids (either directly or from query) then the summary view is used which only returns tags and their counts from the results instead (default: '100')")] = "50",
    limit: Annotated[str, Field(description="Limits the results to x files. Default 1000. Override if you need more or less results.")] = "1000",
    result_limit: Annotated[str, Field(description="Limits the number of top tags shown in summary view. Default 150.")] = "150"
) -> str:
    """Get tags for files in Hydrus client.

    Returns formatted result with tags.
    """
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not content.strip():
        return "❌ Error: Content is required (query, file IDs, or page key)"

    # Validate content_type parameter
    valid_content_types = ["file_ids", "query", "page_key"]
    if content_type not in valid_content_types:
        return f"❌ Error: Invalid content_type '{content_type}'. Valid options are: {', '.join(valid_content_types)}"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"

    try:
        # Get the content based on the content_type
        file_ids = []
        result_count = 0

        if content_type == "query":
            # Handle query - execute search and get file IDs
            try:

                # we will append a hardcoded limit for now, in the future this code should be made smarter by checking if "system:limit is*" tag is in the query and if yes, skipping adding this tag and also tell the llm that at least this limit is enabled or have it pass a value
                if not limit:
                    limit = str(1000)
                appended_tag = f'system:limit is {limit}'

                tags = parse_hydrus_tags(content, appended_tag)

                # todo: we should add a system:limit is {limit}. function here that adds that tag to the tags if not such tag is present, to limit results and prevent ctx overflow.

                tag_service_key = str(get_service_key_by_name(client_obj, tag_service))

                search_params = {
                    "tags": tags,
                    "file_sort_type": 13,
                    "tag_service_key": [tag_service_key]
                }

                # Execute the search
                file_ids_response = client_obj.search_files(**search_params)

                file_ids = file_ids_response['file_ids']
        
                result_count = len(file_ids)

                # Check threshold for summary view
                if int(trs) < result_count:
                    result = f"The count of {result_count} files from query '{content}' is above the threshold {trs}. Therefore you see a summary of the tags and the tag counts in the results. If you want to see the tags per file instead, then use less files or set the trs to be above the count of files. This shows the result_limit={result_limit} tags with the highest count. "
                    # Apply result_limit if provided
                    try:
                        result_limit_int = int(result_limit) if result_limit.strip().isdigit() else 100
                    except ValueError:
                        result_limit_int = 100

                    summary_result = get_tags_summary(client_obj, file_ids=file_ids, tag_service=tag_service)
                    # Limit the number of tags shown based on result_limit
                    if result_limit_int > 0 and len(summary_result) > result_limit_int:
                        summary_result = summary_result[:result_limit_int]
                        result = result + f" (Showing {len(summary_result)} of {len(file_ids)} files, top {result_limit_int} tags by count)"
                    result = result + str(summary_result)
                    return result
                if result_count == 0:
                    return f"❌ No files found for query '{tags}' (count: {result_count})'"

            except json.JSONDecodeError as e:
                return f"❌ Error: Invalid response from query - {str(e)}, content: {content}, content_type: {content_type}, tag_service: {tag_service}, trs = {trs}"
            except Exception as e:
                logger.error(f"Error executing query: {str(e)}")
                return f"❌ Error: Failed to execute query - {str(e)}"
        elif content_type == "page_key":
            # Handle page key - get page info and extract file IDs
            try:
                page_info_result = await hydrus_get_page_info(client_name, content)
                if not page_info_result.startswith("✅"):
                    return f"❌ Error: Failed to retrieve page information for page key '{content}'. {page_info_result}"

                # Parse the page info result to extract file IDs
                try:
                    # Extract the JSON part from the result string
                    start_idx = page_info_result.find('{')
                    end_idx = page_info_result.rfind('}')
                    if start_idx == -1 or end_idx == -1:
                        return "❌ Error: Could not parse page information. Expected JSON format not found."

                    json_str = page_info_result[start_idx:end_idx+1]
                    page_info = json.loads(json_str)

                    # Check if this is a media page with file IDs
                    if not page_info.get('is_media_page', False):
                        return f"❌ Error: Page key '{content}' does not contain media files. Only media pages can have tags retrieved."

                    # Extract file IDs from the media section
                    media = page_info.get('media', {})
                    hash_ids = media.get('hash_ids', [])
                    if not hash_ids:
                        return f"❌ Error: No file IDs found in page key '{content}'"

                    file_ids = hash_ids
                    result_count = len(file_ids)

                except json.JSONDecodeError as e:
                    return f"❌ Error: Could not parse page information JSON - {str(e)}. Raw response: {page_info_result}"
        
                # Handle case where no file IDs were found
                if not file_ids:
                    return f"❌ Error: No media files found in page key '{content}'. The page may not contain any files with tags."
        
            except Exception as e:
                return f"❌ Error: Failed to process page key '{content}' - {str(e)}"
        else:  # content_type == "file_ids"
            # Handle direct file IDs
            file_ids = [int(fid.strip()) for fid in content.split(',') if fid.strip().isdigit()]
            result_count = len(file_ids)

        # Get tags using the existing get_tags function (with summary logic)
        if int(trs) < len(file_ids):
            result = f"The count of {len(file_ids)} file ids is above the threshold {trs}. Therefore you see a summary of the tags and the tag counts in the results. If you want to see the tags per file instead, then use less file ids or set the trs to be above the count of file ids. "
            # Apply result_limit if provided
            try:
                result_limit_int = int(result_limit) if result_limit.strip().isdigit() else 100
            except ValueError:
                result_limit_int = 100

            summary_result = get_tags_summary(client_obj, file_ids=file_ids, tag_service=tag_service)
            # Limit the number of tags shown based on result_limit
            if result_limit_int > 0 and len(summary_result) > result_limit_int:
                summary_result = summary_result[:result_limit_int]
                result = result + f" (Showing {len(summary_result)} of {len(file_ids)} files, top {result_limit_int} tags by count)"
            result = result + str(summary_result)
        else:
            data = get_tags(client_obj, file_ids=file_ids, tag_service=tag_service)
            result = f"Found {len(data)} results: "
            result = result + str(data)

        return result

    except AttributeError as e:
        return f"❌ Error: Method not found in client API: {e}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_get_file_metadata(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_id: Annotated[str, Field(description="File ID to get metadata for. The file_id is expected to be in quotes for this function to work properly.")] = ""
) -> str:
    """Get metadata for a file by its ID from a specific client.

    Warning: This function returns a lot of data and therefore should be only used when something has not enough tags or a deep inspection of the metadata is necessary.
    """
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not file_id.strip():
        return "❌ Error: File ID is required"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join([c['name'] for c in load_clients_from_secret()])}"

    try:
        # Strip quotes from file_id if present (models often send quoted numbers)
        file_id_stripped = file_id.strip()
        if (file_id_stripped.startswith('"') and file_id_stripped.endswith('"')) or \
           (file_id_stripped.startswith("'") and file_id_stripped.endswith("'")):
            file_id_stripped = file_id_stripped[1:-1]
        file_id_int = int(file_id_stripped)
        metadata = client_obj.get_file_metadata(file_ids=[file_id_int])
        # metadata = metadata["metadata"] # doing that causes a issue where the "items" cannot be found in the later code.

        # Format the output
        result = f"✅ File Metadata for ID {file_id_int} (from {client_name}):"
        for key, value in metadata.items():
            if isinstance(value, dict):
                result += f"- {key}: {json.dumps(value)}"
            else:
                result += f"- {key}: {value}"

        return result.strip()

    except ValueError:
        return f"❌ Error: Invalid file ID - must be a number: {file_id}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_get_page_info(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    page_key: Annotated[str, Field(description="The page key to get information for")] = ""
) -> str:
    """Get page information for a specific tab using its page key.

    Returns formatted result with page information or error message.
    """
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not page_key.strip():
        return "❌ Error: Page key is required"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"

    try:
        page_info = get_page_info(client_obj, page_key)
        if not page_info:
            return "❌ Error: Failed to retrieve page information. Did you actually use a page key from hydrus_list_tabs with return_page_keys set to 'true'?"

        # Format the output
        result = f"✅ Page Information for key '{page_key}' (from {client_name}):"
        for key, value in page_info.items():
            if isinstance(value, dict):
                result += f"- {key}: {json.dumps(value)}"
            else:
                result += f"- {key}: {value}"

        return result.strip()

    except AttributeError as e:
        return f"❌ Error: Method not found in client API: {e}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_list_tabs(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    return_tab_keys: Annotated[bool, Field(description="If True, includes page keys in the output (default: False)")] = False
) -> str:
    """List open tabs in a Hydrus client. Optionally returns tab keys along with names."""
    if not client_name.strip():
        return "❌ Error: Client name is required"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"

    try:
        # Get pages from the client using get_pages()
        try:
            pages_response = client_obj.get_pages()

            # Log the raw response for debugging
            logger.debug(f"Raw get_pages() response: {json.dumps(pages_response, indent=2)}")
            logger.debug(f"Response type: {type(pages_response).__name__}")

            # Extract the actual page list from the response
            if not isinstance(pages_response, dict) or 'pages' not in pages_response:
                return f"❌ Error: Unexpected response format from get_pages(). Expected dict with 'pages' key, got {type(pages_response).__name__}. Response: {str(pages_response)[:200]}"

            page_list = pages_response['pages']

            # Handle both list and single dictionary cases
            if isinstance(page_list, list):
                # This is the expected case - a list of pages
                pass
            elif isinstance(page_list, dict):
                # Single page case - convert to list for consistent processing
                logger.debug("Converting single page response to list format")
                page_list = [page_list]
            else:
                return f"❌ Error: Unexpected response format for 'pages' in get_pages(). Expected list or dict, got {type(page_list).__name__}. Response: {str(page_list)[:200]}"

        except AttributeError as e:
            return f"❌ Error: Method not found in client API: {e}"
        except Exception as e:
            return f"❌ Error: Failed to get pages: {str(e)}"

        # Extract tab names and optionally keys from the page list (including nested pages)
        tabs, tab_keys = extract_tabs_from_pages(page_list, return_keys=return_tab_keys)

        result = f"✅ Open tabs for {client_name}: "
        if not tabs:
            return "❌ Error: No open tabs found"

        for i, tab in enumerate(tabs):
            if return_tab_keys and i < len(tab_keys) and tab_keys[i]:
                result += f", '{tab}' (key: {tab_keys[i]})"
            else:
                result += f", '{tab}'"

        return result.strip()

    except AttributeError as e:
        return f"❌ Error: Method not found in client API: {e}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_focus_on_tab(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    tab_name: Annotated[str, Field(description="Name of the tab to focus on")] = ""
) -> str:
    """Focus the Hydrus client on a specific tab."""
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not tab_name.strip():
        return "❌ Error: Tab name is required"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"

    try:
        # Get pages from the client using get_pages()
        try:
            pages_response = client_obj.get_pages()

            # Log the raw response for debugging
            logger.debug(f"Raw get_pages() response: {json.dumps(pages_response, indent=2)}")
            logger.debug(f"Response type: {type(pages_response).__name__}")

            # Extract the actual page list from the response
            if not isinstance(pages_response, dict) or 'pages' not in pages_response:
                return f"❌ Error: Unexpected response format from get_pages(). Expected dict with 'pages' key, got {type(pages_response).__name__}. Response: {str(pages_response)[:200]}"

            page_list = pages_response['pages']

            # Handle both list and single dictionary cases
            if isinstance(page_list, list):
                # This is the expected case - a list of pages
                pass
            elif isinstance(page_list, dict):
                # Single page case - convert to list for consistent processing
                logger.debug("Converting single page response to list format")
                page_list = [page_list]
            else:
                return f"❌ Error: Unexpected response format for 'pages' in get_pages(). Expected list or dict, got {type(page_list).__name__}. Response: {str(page_list)[:200]}"

        except AttributeError as e:
            return f"❌ Error: Method not found in client API: {e}"
        except Exception as e:
            return f"❌ Error: Failed to get pages: {str(e)}"

        target_page = find_page_by_name(page_list, tab_name)

        if not target_page:
            return f"❌ Error: Tab '{tab_name}' not found for client '{client_name}'"

        # Get the page ID to focus on
        page_id = target_page.get('page_key')
        if not page_id:
            return f"❌ Error: Could not get page key for tab '{tab_name}'"

        # Focus on the page using the Hydrus API
        try:
            client_obj.focus_page(page_id)
            return f"✅ Successfully focused on tab '{tab_name}' for client '{client_name}'"
        except AttributeError as e:
            return f"❌ Error: Method not found in client API: {e}"
        except Exception as e:
            return f"❌ Error: Failed to focus on tab: {str(e)}"

    except AttributeError as e:
        return f"❌ Error: Method not found in client API: {e}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_send_to_tab(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    tab_name: Annotated[str, Field(description="Name of the tab to send files to")] = "",
    content: Annotated[str, Field(description="Either a query string (use brackets for OR type queries) or comma-separated file IDs (do not use brackets when providing file ids)")] = "",
    is_query: Annotated[str, Field(description="True if content is a query (using tags, strings, filenames, etc.), False if it's numeric file IDs only (default: False)")] = "false",
    tag_service: Annotated[str, Field(description="When using queries, you can provide a specific tag service name (default: 'all known tags')")] = "all known tags"
) -> str:
    """Send files to a specific tab in Hydrus client.

    When sending file ids to a tab, set is_query to False or leave it out. You don't need to provide a tag service for file ids. The formatting for file ids is a comma separated list of integers without the use of brackets.
    When providing a query, pass at least the is_query=True parameter.

    Returns message indicating success and number of files sent.
    """
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not tab_name.strip():
        return "❌ Error: Tab name is required"
    if not content.strip():
        return "❌ Error: Content is required (either query or file IDs)"

    # Convert is_query to boolean - handle both string and boolean formats
    if isinstance(is_query, bool):
        is_query_bool = is_query
    elif isinstance(is_query, str):
        is_query_bool = is_query.lower().strip() == "true"
    else:
        is_query_bool = bool(is_query)

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"

    try:
        # Get the content based on whether it's a query or file IDs
        file_ids = []
        result_count = 0

        if is_query:
            # Handle query - execute search and get file IDs
            try:
                # query_result = await hydrus_query(client_name, content, tag_service)
                tags = parse_hydrus_tags(content)
                tag_service_key = get_service_key_by_name(client_obj, tag_service)
                search_params = {
                    "tags": tags,
                    "file_sort_type": 13,
                    "tag_service_key": tag_service_key
                }

                query_result = client_obj.search_files(**search_params)
                # query_result = client_obj.search_files(tags=tags, tag_service_key=tag_service_key)

                try:
                    # Parse the JSON response to get file IDs
                    query_response = query_result["file_ids"]
                    if isinstance(query_response, dict) and 'file_ids' in query_response:
                        file_ids = query_response['file_ids']
                    else:
                        file_ids = query_response

                    result_count = len(file_ids)

                    if result_count == 0:
                        return f"❌ No files found for query '{content}'"
                    elif result_count > 100:
                        response = f"✅ Query returned {result_count} files."

                except json.JSONDecodeError as e:
                    # If the response isn't valid JSON, it might be a raw string
                    # Try to handle it as a comma-separated list of file IDs or tags
                    if isinstance(query_result, str):
                        try:
                            # First try parsing as JSON array (most common case)
                            file_ids = json.loads(f"[{query_result}]")
                        except:
                            # If that fails, try splitting by commas and converting to integers
                            file_ids = [int(fid.strip()) for fid in query_result.split(',') if fid.strip().isdigit()]
                        result_count = len(file_ids)
                    else:
                        return f"❌ Error: Invalid response from query - {str(e)}, content: {content}"
            except Exception as e:
                return f"❌ Error: Failed to execute query - {str(e)}, {tags}, {query_result}, {tag_service_key}"
        else:
            # Handle direct file IDs - strip brackets if present and not a query
            # Remove brackets from the content string if it starts with '[' and ends with ']'
            if content.startswith('[') and content.endswith(']'):
                content = content[1:-1]
            file_ids = [int(fid.strip()) for fid in content.split(',') if fid.strip().isdigit()]
            result_count = len(file_ids)

        # Get pages from the client using get_pages()
        try:
            pages_response = client_obj.get_pages()

            # Log the raw response for debugging
            logger.debug(f"Raw get_pages() response: {json.dumps(pages_response, indent=2)}")
            logger.debug(f"Response type: {type(pages_response).__name__}")

            # Extract the actual page list from the response
            if not isinstance(pages_response, dict) or 'pages' not in pages_response:
                return f"❌ Error: Unexpected response format from get_pages(). Expected dict with 'pages' key, got {type(pages_response).__name__}. Response: {str(pages_response)[:200]}"

            page_list = pages_response['pages']

            # Handle both list and single dictionary cases
            if isinstance(page_list, list):
                # This is the expected case - a list of pages
                pass
            elif isinstance(page_list, dict):
                # Single page case - convert to list for consistent processing
                logger.debug("Converting single page response to list format")
                page_list = [page_list]
            else:
                return f"❌ Error: Unexpected response format for 'pages' in get_pages(). Expected list or dict, got {type(page_list).__name__}. Response: {str(page_list)[:200]}"

        except AttributeError as e:
            return f"❌ Error: Method not found in client API: {e}"
        except Exception as e:
            return f"❌ Error: Failed to get pages: {str(e)}"

        target_page = find_page_by_name(page_list, tab_name)

        if not target_page:
            return f"❌ Error: Tab '{tab_name}' not found for client '{client_name}'"

        # Get the page ID to focus on
        page_key = target_page.get('page_key')
        if not page_key:
            return f"❌ Error: Could not get page key for tab '{tab_name}'"

        # Send files to the tab using the Hydrus API
        try:
            client_obj.add_files_to_page(page_key=page_key, file_ids=file_ids)
            return f"✅ Successfully sent {result_count} files to tab '{tab_name}'"
        except Exception as e:
            return f"❌ Error: {str(e)}"

    except AttributeError as e:
        return f"❌ Error: Method not found in client API: {e}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_send(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    link: Annotated[str, Field(description="Direct link to file or base link for scraping")] = "",
    service_names_to_additional_tags: Annotated[Optional[str], Field(description="Optional JSON string mapping service names to tag lists, e.g., '{\"local\": [\"tag1\", \"tag2\"]}'")] = None,
    subdir: Annotated[bool, Field(description="If True, recursively scrape subdirectories from base link (default: False)")] = False,
    max_depth: Annotated[int, Field(description="Maximum depth for recursive scraping (default: 2)")] = 2,
    filename: Annotated[bool, Field(description="If True, extract filename and add as 'filename:' tag (default: True)")] = True,
    destination_page_name: Annotated[str, Field(description="Name of the destination page in Hydrus (default: 'hydrus_mcp')")] = "hydrus_mcp"
) -> str:
    """Send a link to be downloaded to Hydrus. Can send a direct file link or a base URL for recursive scraping.

    Returns message indicating success with file count or error message.
    """
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not link.strip():
        return "❌ Error: Link is required"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"

    try:
        # Parse service_names_to_additional_tags if provided
        service_keys_to_additional_tags = None
        if service_names_to_additional_tags:
            try:
                tags_dict = json.loads(service_names_to_additional_tags)
                service_keys_to_additional_tags = {}
                for service_name, tags_list in tags_dict.items():
                    service_key = get_service_key_by_name(client_obj, service_name)
                    if service_key:
                        service_keys_to_additional_tags[service_key] = tags_list
                    else:
                        logger.warning(f"Service '{service_name}' not found, skipping")
            except json.JSONDecodeError as e:
                return f"❌ Error: Invalid JSON for service_names_to_additional_tags: {str(e)}"

        if subdir:
            # Ensure link ends with / for directory scraping
            if not link.endswith('/'):
                link = link + '/'
                logger.info(f"Added trailing slash to link: {link}")

            # Recursive scraping mode
            import requests
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin, urlparse
            import os
            from urllib.parse import unquote

            def is_valid_url(url):
                parsed = urlparse(url)
                return bool(parsed.netloc) and bool(parsed.scheme)

            def is_subpath(base_url, target_url):
                """Ensure target_url is within base_url directory structure"""
                base = urlparse(base_url)
                target = urlparse(target_url)

                if base.scheme != target.scheme or base.netloc != target.netloc:
                    return False

                base_parts = base.path.strip('/').split('/')
                target_parts = target.path.strip('/').split('/')

                return base_parts[:len(base_parts)] == target_parts[:len(base_parts)]

            def scrape_links_recursive(base_url, file_types, depth=1, current_depth=0, visited=None):
                if visited is None:
                    visited = set()

                # Avoid revisiting URLs
                if base_url in visited or current_depth > depth:
                    return []

                visited.add(base_url)

                try:
                    response = requests.get(base_url, verify=False)
                except requests.RequestException as e:
                    logger.warning(f"Request failed for {base_url}: {e}")
                    return []

                # Handle HTTP errors with specific messages
                if response.status_code == 404:
                    logger.error(f"404 Not Found: {base_url}")
                    return []
                elif response.status_code == 503:
                    logger.error(f"503 Service Unavailable: {base_url}")
                    return []
                elif response.status_code == 429:
                    logger.error(f"429 Too Many Requests: {base_url}")
                    return []
                elif response.status_code != 200:
                    logger.warning(f"Failed to fetch {base_url}, status code: {response.status_code}")
                    return []

                soup = BeautifulSoup(response.text, 'html.parser')
                links = []

                for link_tag in soup.find_all('a', href=True):
                    href = link_tag['href']

                    # Ignore relative paths like '.' or '..'
                    if href.startswith(('.', '../')):
                        continue

                    absolute_url = urljoin(base_url, href)

                    # Ensure the discovered link is within the base directory structure
                    if not is_subpath(base_url, absolute_url):
                        continue

                    if is_valid_url(absolute_url) and not any(href.endswith(file_type) for file_type in file_types):
                        if href.endswith('/') or not urlparse(href).path:
                            links.extend(scrape_links_recursive(absolute_url, file_types, depth, current_depth + 1, visited))
                    elif any(href.endswith(file_type) for file_type in file_types):
                        links.append(absolute_url)

                return links

            file_types_of_interest = ['.mp4', '.pdf', '.mkv', '.avi', '.mov', '.mpg', '.wmv', '.flv', '.m4v', '.mp3', '.wav', '.aac', '.flac']
            links = scrape_links_recursive(link, file_types_of_interest, depth=max_depth)

            if not links:
                # Check if the link itself is a direct file link
                if any(link.endswith(file_type) for file_type in file_types_of_interest):
                    links = [link]
                else:
                    # Check if the base URL returned an error status code
                    try:
                        response = requests.get(link, verify=False)
                        if response.status_code == 404:
                            return f"❌ Error: 404 Not Found - The directory '{link}' does not exist"
                        elif response.status_code == 503:
                            return f"❌ Error: 503 Service Unavailable - The server is temporarily unable to handle the request"
                        elif response.status_code == 429:
                            return f"❌ Error: 429 Too Many Requests - Rate limit exceeded. Please wait before trying again"
                        elif response.status_code != 200:
                            return f"❌ Error: HTTP {response.status_code} - Failed to access directory '{link}'"
                    except requests.RequestException as e:
                        return f"❌ Error: Request failed - {str(e)}"
                    
                    return f"❌ Error: No files found in the directory structure and the link is not a direct file link"

            added_count = 0
            for file_link in links:
                try:
                    tags_to_add = {}
                    if service_keys_to_additional_tags:
                        tags_to_add = service_keys_to_additional_tags.copy()

                    if filename:
                        filename_without_extension, _ = os.path.splitext(unquote(file_link.split('/')[-1]))
                        filename_tag = "filename:" + filename_without_extension.lower()
                        # Add to local service if available
                        local_key = get_service_key_by_name(client_obj, "local")
                        if local_key:
                            if local_key not in tags_to_add:
                                tags_to_add[local_key] = []
                            tags_to_add[local_key].append(filename_tag)

                    client_obj.add_url(url=file_link, destination_page_name=destination_page_name, show_destination_page=True, service_keys_to_additional_tags=tags_to_add if tags_to_add else None)
                    added_count += 1
                except Exception as e:
                    logger.error(f"Failed to add URL {file_link}: {str(e)}")

            return f"✅ Successfully sent {added_count} files from recursive scraping of '{link}' to Hydrus"

        else:
            # Single link mode
            try:
                tags_to_add = {}
                if service_keys_to_additional_tags:
                    tags_to_add = service_keys_to_additional_tags.copy()

                if filename:
                    from urllib.parse import unquote
                    import os
                    filename_without_extension, _ = os.path.splitext(unquote(link.split('/')[-1]))
                    filename_tag = "filename:" + filename_without_extension.lower()
                    # Add to local service if available
                    local_key = get_service_key_by_name(client_obj, "local")
                    if local_key:
                        if local_key not in tags_to_add:
                            tags_to_add[local_key] = []
                        tags_to_add[local_key].append(filename_tag)

                client_obj.add_url(url=link, destination_page_name=destination_page_name, show_destination_page=True, service_keys_to_additional_tags=tags_to_add if tags_to_add else None)
                return f"✅ Successfully sent link '{link}' to Hydrus"

            except Exception as e:
                return f"❌ Error: Failed to add URL: {str(e)}"

    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_add_tags(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_ids: Annotated[int, Field(description="File ID or comma-separated file IDs to add tags to (e.g., 123 or 123,456,789)")] = 0,
    target_tag_service: Annotated[str, Field(description="Name of the tag service to add tags to")] = "",
    tags: Annotated[str, Field(description="Comma-separated list of tags to add (e.g., 'character:alice,rating:safe')")] = ""
) -> str:
    """Add tags to files in Hydrus client.
    
    This tool is only available if explicitly enabled in the MCP configuration.
    The client and tag service must be whitelisted in the configuration for this tool to work.
    """
    # Check if the tool is enabled via environment variable
    add_tags_enabled = os.getenv("HYDRUS_ADD_TAGS_ENABLED", "").lower() == "true"
    if not add_tags_enabled:
        return "❌ Error: The add_tags tool is disabled. Please enable it in your MCP configuration by setting HYDRUS_ADD_TAGS_ENABLED=true and configuring the whitelist."
    
    # Get whitelist configuration
    whitelist_config = os.getenv("HYDRUS_ADD_TAGS_WHITELIST", "")
    if not whitelist_config:
        return "❌ Error: The add_tags tool is not configured. Please set HYDRUS_ADD_TAGS_WHITELIST in your MCP configuration with allowed clients and their tag services."
    
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if file_ids == 0 or (isinstance(file_ids, str) and not file_ids.strip()):
        return "❌ Error: File IDs are required"
    if not target_tag_service.strip():
        return "❌ Error: Target tag service is required"
    if not tags.strip():
        return "❌ Error: Tags are required (comma-separated list)"
    
    # Parse whitelist configuration
    # Expected format: "client1:service1,service2|client2:service3,service4"
    try:
        whitelist = {}
        for client_entry in whitelist_config.split("|"):
            if ":" not in client_entry:
                continue
            client, services = client_entry.split(":", 1)
            whitelist[client.strip()] = [s.strip() for s in services.split(",")]
    except Exception as e:
        return f"❌ Error: Invalid whitelist configuration format: {str(e)}"
    
    # Check if client is whitelisted
    if client_name not in whitelist:
        available_clients = list(whitelist.keys())
        return f"❌ Error: Client '{client_name}' is not whitelisted for tag addition. Allowed clients: {', '.join(available_clients)}"
    
    # Check if tag service is whitelisted for this client
    allowed_services = whitelist[client_name]
    if target_tag_service not in allowed_services:
        return f"❌ Error: Tag service '{target_tag_service}' is not whitelisted for client '{client_name}'. Allowed services for this client: {', '.join(allowed_services)}"
    
    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"
    
    try:
        # Parse file IDs - handle both int and str types
        if isinstance(file_ids, int):
            file_ids_list = [file_ids]
        else:
            # Handle string input (comma-separated or single)
            file_ids_list = []
            for fid in file_ids.split(","):
                fid = fid.strip().strip('"').strip("'")
                if fid.isdigit():
                    file_ids_list.append(int(fid))
        if not file_ids_list:
            return "❌ Error: No valid file IDs provided"
        
        # Parse tags
        tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
        if not tags_list:
            return "❌ Error: No valid tags provided"
        
        # Get service key for the target tag service
        service_key = get_service_key_by_name(client_obj, target_tag_service)
        if not service_key:
            return f"❌ Error: Tag service '{target_tag_service}' not found on client '{client_name}'"
        
        # Add tags to files
        client_obj.add_tags(file_ids=file_ids_list, service_keys_to_tags={str(service_key): tags_list})
        
        return f"✅ The following {len(tags_list)} tags were added to the tag service '{target_tag_service}' on client '{client_name}' to the file ids {file_ids_list}"
    
    except ValueError as e:
        return f"❌ Error: Invalid parameter format - {str(e)}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_show_file(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_id: Annotated[int, Field(description="File ID to show the image or video for")] = 0,
    frame_count: Annotated[Optional[int], Field(description="If the file is a video, then this number of frames will be extracted and compiled into a grid image. Default 4 (2x2 grid). Supports 4 (2x2), 6 (3x2), 9 (3x3), 12 (4x3), etc.")] = 4
) -> Image:
    """Show an image or video file from Hydrus.
    
    Returns the actual image file for visual display.
    For images (PNG, JPEG, GIF), returns the image directly.
    For videos (MP4, WebM, AVI), extracts frames and compiles them into a single grid image.
    
    The frame_count parameter determines the grid layout for videos:
    - 4 frames = 2x2 grid
    - 6 frames = 3x2 grid (3 columns, 2 rows)
    - 9 frames = 3x3 grid
    - 12 frames = 4x3 grid (4 columns, 3 rows)
    """
    if not client_name.strip():
        return Image(data=b"", format="png")
    if file_id == 0:
        return Image(data=b"", format="png")
    
    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return Image(data=b"", format="png")
    
    try:
        # Get the file using the Hydrus API
        file_data = client_obj.get_file(file_id=file_id)
        
        # Get the content as bytes
        file_bytes = file_data.content
        
        # Detect format from content
        is_video = False
        if file_bytes.startswith(b'\xff\xd8\xff'):
            return Image(data=file_bytes, format="jpeg")
        elif file_bytes.startswith(b'GIF87a') or file_bytes.startswith(b'GIF89a'):
            return Image(data=file_bytes, format="gif")
        elif file_bytes.startswith(b'\x89PNG'):
            return Image(data=file_bytes, format="png")
        elif b'ftypmp42' in file_bytes[:64] or b'ftypisom' in file_bytes[:64] or b'ftypmp41' in file_bytes[:64]:
            is_video = True
        elif file_bytes.startswith(b'\x1a\x45\xdf\xa3'):
            is_video = True
        elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WEBV':
            is_video = True
        elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'AVI ':
            is_video = True
        
        if not is_video:
            # Unknown format, return as PNG
            return Image(data=file_bytes, format="png")
        
        # Handle video - extract frames and compile into grid image
        frame_count_int = frame_count if frame_count is not None else 4
        
        # Calculate grid dimensions (columns x rows)
        # Try to make it as square as possible, preferring more columns
        rows = int(math.ceil(math.sqrt(frame_count_int)))
        cols = int(math.ceil(frame_count_int / rows))
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_video:
            temp_video.write(file_bytes)
            temp_video_path = temp_video.name
        
        try:
            cap = cv2.VideoCapture(temp_video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            duration_seconds = total_frames / fps if fps > 0 else 0
            
            # Get frame dimensions
            frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            if total_frames == 0:
                cap.release()
                os.remove(temp_video_path)
                return Image(data=b"", format="png")
            
            # Calculate frame indices (equally spaced across video)
            frame_indices = []
            for i in range(frame_count_int):
                percentage = (i + 1) / (frame_count_int + 1)
                frame_indices.append(int(total_frames * percentage))
            
            # Extract frames
            frames = []
            for frame_idx in frame_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if ret:
                    frames.append(frame)
            
            cap.release()
            
            if not frames:
                os.remove(temp_video_path)
                return Image(data=b"", format="png")
            
            # Create composite image grid
            # Calculate the composite dimensions
            composite_width = cols * frame_width
            composite_height = rows * frame_height
            
            # Define maximum resolution threshold (pixels on the longest side)
            MAX_RESOLUTION = 2000
            
            # Check if scaling is needed
            if composite_width > MAX_RESOLUTION or composite_height > MAX_RESOLUTION:
                # Calculate scaling factor to fit within MAX_RESOLUTION
                scale_factor = MAX_RESOLUTION / max(composite_width, composite_height)
                target_width = int(frame_width * scale_factor)
                target_height = int(frame_height * scale_factor)
                logger.info(f"Scaling video frames from {frame_width}x{frame_height} to {target_width}x{target_height} to fit within {MAX_RESOLUTION}px")
            else:
                target_width = frame_width
                target_height = frame_height
            
            resized_frames = []
            for frame in frames:
                resized = cv2.resize(frame, (target_width, target_height))
                resized_frames.append(resized)
            
            # Pad with empty frames if we have fewer frames than requested
            while len(resized_frames) < frame_count_int:
                empty_frame = np.zeros((target_height, target_width, 3), dtype=np.uint8)
                resized_frames.append(empty_frame)
            
            # Create the grid
            composite_width = cols * target_width
            composite_height = rows * target_height
            composite = np.zeros((composite_height, composite_width, 3), dtype=np.uint8)
            
            for idx, frame in enumerate(resized_frames):
                row = idx // cols
                col = idx % cols
                y_start = row * target_height
                x_start = col * target_width
                composite[y_start:y_start+target_height, x_start:x_start+target_width] = frame
            
            # Encode composite as PNG
            _, buffer = cv2.imencode('.png', composite)
            os.remove(temp_video_path)
            
            return Image(data=buffer.tobytes(), format="png")
            
        except Exception as e:
            logger.error(f"Error processing video: {str(e)}")
            os.remove(temp_video_path)
            return Image(data=b"", format="png")
    
    except Exception as e:
        logger.error(f"Error showing file: {str(e)}")
        return Image(data=b"", format="png")


@mcp.tool()
async def hydrus_inspect_file(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_id: Annotated[int, Field(description="File ID of the file (image or video) to inspect")] = 0,
    prompt: Annotated[str, Field(description="The prompt/question to ask about the file")] = "",
    frame_count: Annotated[Optional[int], Field(description="If file is video: Number of frames to extract from video file (default: 5)")] = 5
) -> str:
    """Send a file (image or video) from Hydrus to a vision API for description/analysis.
    
    This tool retrieves a file from Hydrus and sends it to an OpenAI-compatible
    vision API endpoint along with a prompt. The API analyzes the file and returns
    a text description or answer to the prompt.
    
    Supports both images (PNG, JPEG, GIF) and videos (MP4, WebM, etc.).
    For videos, frames are extracted and sent as images since the vision API may not support video directly.
    
    Configuration (from environment variables):
    - VISION_API_URL: API endpoint URL (default: http://localhost:11434/v1/chat/completions)
    - VISION_API_KEY: API key for authentication (default: empty)
    - VISION_MODEL: Model name to use (default: llava)
    """
    import base64
    import tempfile

    # Configuration from environment variables
    API_URL = os.getenv("VISION_API_URL")
    API_KEY = os.getenv("VISION_API_KEY", "")
    MODEL = os.getenv("VISION_MODEL")

    if not client_name.strip():
        return "❌ Error: Client name is required"
    if file_id == 0:
        return "❌ Error: File ID is required"
    if not prompt.strip():
        return "❌ Error: Prompt is required"
    
    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"
    
    try:
        # Get the file using the Hydrus API
        file_data = client_obj.get_file(file_id=file_id)
        file_bytes = file_data.content
        
        # Detect mime type from content - supports images and videos
        is_video = False
        mime = "image/png"
        if file_bytes.startswith(b'\xff\xd8\xff'):
            mime = "image/jpeg"
        elif file_bytes.startswith(b'GIF87a') or file_bytes.startswith(b'GIF89a'):
            mime = "image/gif"
        elif file_bytes.startswith(b'\x89PNG'):
            mime = "image/png"
        elif b'ftypmp42' in file_bytes[:64] or b'ftypisom' in file_bytes[:64] or b'ftypmp41' in file_bytes[:64]:
            mime = "video/mp4"
            is_video = True
        elif file_bytes.startswith(b'\x1a\x45\xdf\xa3'):
            mime = "video/webm"
            is_video = True
        elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WEBV':
            mime = "video/webm"
            is_video = True
        elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'AVI':
            mime = "video/x-msvideo"
            is_video = True
        
        # Encode file as base64
        b64_data = base64.b64encode(file_bytes).decode('utf-8')
        
        # Prepare the API request
        headers = {
            "Content-Type": "application/json"
        }
        if API_KEY:
            headers["Authorization"] = f"Bearer {API_KEY}"
        
        # Build content array based on file type
        # Text first, then images (more stable for vision models)
        content_items: list[dict[str, str | dict[str, str]]] = [
            {"type": "text", "text": prompt}
        ]
        
        if is_video:
            # Extract multiple frames and send them as images
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_video:
                temp_video.write(file_bytes)
                temp_video_path = temp_video.name

            try:
                cap = cv2.VideoCapture(temp_video_path)
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                duration_seconds = total_frames / fps if fps > 0 else 0
                
                if total_frames > 0:
                    # Calculate frame indices based on frame_count parameter
                    # Distribute frames evenly across the video (equally spaced from center)
                    # 1 frame = 50%, 2 frames = 33%/66%, 3 frames = 25%/50%/75%, etc.
                    frame_count_int = frame_count if frame_count is not None else 5
                    frame_indices = []
                    for i in range(frame_count_int):
                        # Equally spaced: divide video into frame_count+1 segments, take frames at segment boundaries
                        percentage = (i + 1) / (frame_count_int + 1)
                        frame_indices.append(int(total_frames * percentage))
                    
                    frames_extracted = 0
                    timestamps = []
                    for frame_idx in frame_indices:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                        ret, frame = cap.read()
                        if ret:
                            # Calculate timestamp for this frame
                            frame_timestamp = frame_idx / fps if fps > 0 else 0
                            timestamps.append(f"{frame_timestamp:.1f}s")
                            
                            # Encode frame as JPEG
                            _, buffer = cv2.imencode('.jpg', frame)
                            frame_b64 = base64.b64encode(buffer).decode('utf-8')
                            # Use image_url format for OpenAI-compatible APIs (Ollama, etc.)
                            content_items.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{frame_b64}"
                                }
                            })
                            frames_extracted += 1
                        else:
                            logger.warning(f"Failed to extract frame at index {frame_idx}")
                    
                    cap.release()
                    
                    # Append video metadata to the prompt including timestamps
                    duration_formatted = f"{duration_seconds:.1f}s" if duration_seconds > 0 else "unknown"
                    timestamps_str = ", ".join(timestamps)
                    prompt_with_metadata = f"{prompt} (Video file: {mime}, duration: {duration_formatted}, {frames_extracted} frames provided at timestamps: {timestamps_str})"
                    content_items[0]["text"] = prompt_with_metadata
                else:
                    cap.release()
                    os.remove(temp_video_path)
                    return "❌ Error: Video has no frames"
            finally:
                os.remove(temp_video_path)
        else:
            # For images, use type "image_url" (OpenAI-compatible format)
            content_items.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{b64_data}"
                }
            })
        
        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": content_items
                }
            ],
            "max_tokens": 3000
        }
        
        # Send request to vision API
        async with httpx.AsyncClient() as session:
            response = await session.post(API_URL, json=payload, headers=headers, timeout=120.0)
            response.raise_for_status()
            result = response.json()
        
        # Extract the response text
        if "choices" in result and len(result["choices"]) > 0:
            message = result["choices"][0].get("message", {})
            content = message.get("content", "")
            if content:
                return f"✅ Vision API Response:\n\n{content}"
            return f"✅ Vision API Response:\n\n{result['choices'][0]}"
        
        return f"❌ Error: Unexpected API response format: {result}"
    
    except httpx.HTTPError as e:
        logger.error(f"HTTP error inspecting file: {str(e)}")
        # Get more details about the error response
        error_details = str(e)
        try:
            resp = getattr(e, 'response', None)
            if resp is not None:
                status = getattr(resp, 'status_code', 'unknown')
                text = getattr(resp, 'text', '')[:200]
                error_details = f"Status code: {status}, Response body: {text}"
        except Exception as inner_e:
            error_details = f"Original error: {str(e)}, Failed to get details: {str(inner_e)}"
        return f"❌ Error: HTTP request failed - {error_details}"
    except Exception as e:
        logger.error(f"Error inspecting file: {str(e)}")
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_transcribe_audio(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_id: Annotated[int, Field(description="File ID of the audio file (mp3, wav, aac, flac) or video file with audio track to transcribe")] = 0
) -> str:
    """Transcribe audio from a file (mp3, wav, aac, flac) or video (mp4, webm, avi) using the Parakeet TDT speech-to-text API.
    
    This tool retrieves an audio file or video file from Hydrus and sends it to an OpenAI-compatible
    speech-to-text API endpoint (like Parakeet TDT) for transcription. The API analyzes the audio
    and returns a raw text transcription.
    
    Supports audio files (MP3, WAV, AAC, FLAC, M4A) and video files (MP4, WebM, AVI, MOV).
    For video files, the audio track is automatically extracted and transcribed.
    
    Configuration (from environment variables):
    - STT_API_URL: API endpoint URL (default: http://localhost:5092/v1/audio/transcriptions)
    - STT_API_KEY: API key for authentication (default: sk-no-key-required)
    - STT_MODEL: Model name to use (default: parakeet-tdt-0.6b-v3)
    """
    import tempfile
    import subprocess

    # Configuration from environment variables
    API_URL = os.getenv("STT_API_URL", "http://localhost:5092/v1/audio/transcriptions")
    API_KEY = os.getenv("STT_API_KEY", "sk-no-key-required")
    MODEL = os.getenv("STT_MODEL", "parakeet-tdt-0.6b-v3")

    if not client_name.strip():
        return "❌ Error: Client name is required"
    if file_id == 0:
        return "❌ Error: File ID is required"
    
    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return f"❌ Error: Could not connect to '{client_name}'. Available clients: {', '.join(available_clients)}"
    
    try:
        # Get the file using the Hydrus API
        file_data = client_obj.get_file(file_id=file_id)
        file_bytes = file_data.content
        
        # Detect file type from content
        is_video = False
        file_extension = ".wav"  # default fallback
        
        if file_bytes.startswith(b'\xff\xfb') or file_bytes.startswith(b'\xff\xfa') or b'ID3' in file_bytes[:20]:
            # MP3 file
            file_extension = ".mp3"
        elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WAVE':
            # WAV file
            file_extension = ".wav"
        elif file_bytes.startswith(b'ftyp') and (b'mp42' in file_bytes[:16] or b'isom' in file_bytes[:16] or b'mp41' in file_bytes[:16]):
            # MP4 file - could be video or m4a audio
            # Check for audio-specific indicators
            if b'm4a' in file_bytes[:16] or b'm4b' in file_bytes[:16]:
                file_extension = ".m4a"
            else:
                is_video = True
                file_extension = ".mp4"
        elif file_bytes.startswith(b'\x1a\x45\xdf\xa3'):
            # WebM file
            is_video = True
            file_extension = ".webm"
        elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WEBV':
            # WebM video
            is_video = True
            file_extension = ".webm"
        elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'AVI ':
            # AVI video
            is_video = True
            file_extension = ".avi"
        elif b'fLaC' in file_bytes[:4]:
            # FLAC file
            file_extension = ".flac"
        elif file_bytes.startswith(b'ADIF'):
            # AAC/ADTS file
            file_extension = ".aac"
        else:
            # Default to treating as audio if we can't determine
            file_extension = ".wav"
        
        # Save file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file.write(file_bytes)
            source_file_path = temp_file.name
        
        audio_file_path = None
        
        try:
            # If it's a video file, extract audio track using ffmpeg
            if is_video:
                audio_file_path = tempfile.mktemp(suffix=".wav")
                logger.info(f"Extracting audio from video file: {source_file_path}")
                
                try:
                    # Use ffmpeg to extract audio track to WAV format
                    ffmpeg_cmd = [
                        "ffmpeg", "-i", source_file_path,
                        "-vn",  # No video
                        "-acodec", "pcm_s16le",  # WAV codec
                        "-ar", "16000",  # 16kHz sample rate (good for STT)
                        "-ac", "1",  # Mono audio
                        "-y",  # Overwrite output file
                        audio_file_path
                    ]
                    
                    result = subprocess.run(
                        ffmpeg_cmd,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    
                    if result.returncode != 0:
                        logger.error(f"FFmpeg error: {result.stderr}")
                        return f"❌ Error: Failed to extract audio from video - {result.stderr[:200]}"
                    
                    if not os.path.exists(audio_file_path):
                        return "❌ Error: Audio extraction completed but output file was not created"
                    
                    logger.info(f"Audio extracted successfully to: {audio_file_path}")
                    
                except subprocess.TimeoutExpired:
                    return "❌ Error: Audio extraction timed out (file may be too large)"
                except FileNotFoundError:
                    return "❌ Error: ffmpeg is not installed. Please install ffmpeg to transcribe video files."
                
            else:
                # For audio files, use the source file directly
                audio_file_path = source_file_path
            
            # Prepare the API request
            headers = {
                "Authorization": f"Bearer {API_KEY}"
            }
            
            # Send request to STT API
            # For OpenAI-compatible APIs, we need to send the file as multipart/form-data
            async with httpx.AsyncClient() as session:
                # Open the audio file and send it
                with open(audio_file_path, "rb") as audio_file:
                    files = {
                        "file": (f"audio{os.path.splitext(audio_file_path)[1]}", audio_file.read()),
                        "model": MODEL,
                    }
                    
                    # Add response_format if supported (text is default)
                    data = {
                        "response_format": "text",
                    }
                    
                    logger.info(f"Sending audio to STT API: {API_URL}")
                    response = await session.post(API_URL, files=files, data=data, headers=headers, timeout=300.0)
                    response.raise_for_status()
                    transcription = response.text
                
                # Clean up the transcription (remove leading/trailing whitespace)
                transcription = transcription.strip()
                
                if not transcription:
                    return "❌ Error: Transcription returned empty result"
                
                file_type_desc = "video" if is_video else "audio"
                return f"✅ Audio Transcription for {file_type_desc} file ID {file_id} (from {client_name}):\n\n{transcription}"
        
        finally:
            # Clean up temporary source file
            try:
                if os.path.exists(source_file_path):
                    os.remove(source_file_path)
            except Exception as e:
                logger.warning(f"Failed to remove temporary source file {source_file_path}: {str(e)}")
            
            # Clean up extracted audio file if it's different from source
            if audio_file_path and audio_file_path != source_file_path:
                try:
                    if os.path.exists(audio_file_path):
                        os.remove(audio_file_path)
                except Exception as e:
                    logger.warning(f"Failed to remove temporary audio file {audio_file_path}: {str(e)}")
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error transcribing audio: {str(e)}")
        # Get more details about the error response
        error_details = str(e)
        try:
            resp = getattr(e, 'response', None)
            if resp is not None:
                status = getattr(resp, 'status_code', 'unknown')
                text = getattr(resp, 'text', '')[:200]
                error_details = f"Status code: {status}, Response body: {text}"
        except Exception as inner_e:
            error_details = f"Original error: {str(e)}, Failed to get details: {str(inner_e)}"
        return f"❌ Error: HTTP request failed - {error_details}"
    except Exception as e:
        logger.error(f"Error transcribing audio: {str(e)}")
        return f"❌ Error: {str(e)}"


def main():
    """Main entry point for the Hydrus MCP server"""
    logger.info("Starting Hydrus MCP server...")

    # Check if clients are configured
    clients = load_clients_from_secret()
    if not clients:
        logger.warning("No Hydrus clients configured. Set HYDRUS_CLIENTS environment variable with client credentials.")
    else:
        logger.info(f"Configured clients: {', '.join([c['name'] for c in clients])}")

    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
