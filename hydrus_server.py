import os
import sys
import logging
import json
from datetime import datetime, timezone
import httpx
import hydrus_api, hydrus_api.utils
from mcp.server.fastmcp import FastMCP

# Import utility functions from the local module
from functions import get_tags, get_tags_summary, parse_hydrus_tags, get_client_by_name, load_clients_from_secret, get_service_key_by_name, get_page_info

# Configure logging to stderr
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("hydrus-server")

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
        return "❌ Error: No Hydrus clients configured. Set HYDRUS_CLIENTS secret with client credentials."

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
async def hydrus_available_tag_services(client_name: str = "") -> str:
    """Get available tag services for a specific Hydrus client.

    This function retrieves the list of tag services configured in a specified Hydrus client.
    Tag services are used to organize and search tags within the client.

    Args:
        client_name (str): The name of the Hydrus client. Required.

    Notes:
        - It connects to the specified client and retrieves tag service information
        - Use this function to discover which tag services are available for searching and filtering
        - Tag services can be used with other functions like to narrow down searches or limit the results to a specific tag service.
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
async def hydrus_search_tags(client_name: str = "", search: str = "", tag_service: str = "all known tags", limit: str = "150") -> str:
    """Search for tags in Hydrus using keywords and wildcards.

    Args:
        client_name (str): Name of the Hydrus client
        search (str): Search query string
        tag_service (str): Tag service name (default: "all known tags")
        limit (str): Number of tags to be returned from the results by count from the top. (default: "150") 
    """
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

        # Convert trs to integer with default of 100
        trs_int = int(limit)

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
async def hydrus_query(client_name: str = "", query: str = "", tag_service: str = "all known tags", file_sort_type: str = "13", trs: str = "100"):
    """Query files in the Hydrus client using various search criteria.

    This function allows you to search for files in a Hydrus client based on tags and other parameters.
    It returns file IDs that match the search criteria, which can be used for further operations.

    Args:
        client_name (str): The name of the Hydrus client to query. Required.
        query (str): The search query string containing tags to search for.
                     Supports Hydrus tag syntax with wildcards and complex tags.
                     Required.
        tag_service (str): The tag service to use for the search. Default is "all known tags".
                           You can specify a specific tag service name if needed.
        file_sort_type (str): Sorting method for files. Default is "13" (sorted by "has audio" as this is the fastest search).
                              Other values may be supported depending on the Hydrus client version.
        trs (str): Threshold for returning results. Default is "100".
                   If the number of matching files exceeds this threshold,
                   only a subset will be returned with information about the total count.

    Notes:
        - The query parameter should use Hydrus tag syntax (e.g., "character:samus aran", "system:inbox", "system:limit is 100")
        - For large result sets, consider adjusting the trs parameter to control performance
        - File IDs returned can be used with other Hydrus functions for further operations
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
            # file_ids = file_ids["file_ids"][:10] #v
            file_ids = file_ids[:10]
            return f"Found {count} files, more than the treshold of {trs}, here are 10 the first 10 file ids from the results: {file_ids}"

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
async def hydrus_get_tags(client_name: str = "", content: str = "", content_type: str = "query", tag_service: str = "all known tags", trs: str = "50", limit: str = "1000", result_limit: str = "150") -> str:
    """Get tags for files in Hydrus client.

    Args:
        client_name (str): Name of the Hydrus client
        content (str): Content to process - query string, comma-separated file IDs, or page key
        content_type (str): Type of content - "file_ids", "query", or "page_key" (default: "query")
        tag_service (str): Tag service name (default: "all known tags")
        trs (str): Threshold for summary view, if the treshold is lower than the received file ids (eiher directly or from query) then the summary view is used which only returns tags and their counts from the results instead (default: "100")
        limit (str): limits the results to x files. Default 1000. Override if you need more or less results.
        result_limit (str): limits the number of top tags shown in summary view. Default 150.

    Returns:
        str: Formatted result with tags
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
async def hydrus_get_file_metadata(client_name: str = "", file_id: str = "") -> str:
    """Get metadata for a file by its ID from a specific client. Warning: This function returns a lot of data and therefore should be only used when something has not enough tags or a deep inspection of the metadata is necessary."""
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not file_id.strip():
        return "❌ Error: File ID is required"

    # Get the specified client
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        return f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join([c['name'] for c in load_clients_from_secret()])}"

    try:
        file_id_int = int(file_id)
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
async def hydrus_get_page_info(client_name: str = "", page_key: str = "") -> str:
    """Get page information for a specific tab using its page key.

    Args:
        client_name (str): Name of the Hydrus client
        page_key (str): The page key to get information for

    Returns:
        str: Formatted result with page information or error message
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
            return "❌ Error: Failed to retrieve page information"

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
async def hydrus_list_tabs(client_name: str = "", return_tab_keys: bool = False) -> str:
    """List open tabs in a Hydrus client. Optionally returns tab keys along with names.

    Args:
        client_name (str): Name of the Hydrus client
        return_tab_keys (bool): If True, includes page keys in the output (default: False)
    """
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
        tabs = []
        tab_keys = []

        def extract_tabs_from_pages(pages_list):
            """Recursively extract tab names and keys from a list of pages"""
            for page_info in pages_list:
                # Validate that each page_info is a dictionary
                if not isinstance(page_info, dict):
                    logger.error(f"Unexpected page_info format: {type(page_info).__name__}. Content: {str(page_info)[:200]}")
                    continue

                # Prioritize name field, fall back to title or page ID
                name = page_info.get('name', page_info.get('title', f"Page {page_info.get('id', 'unknown')}"))
                tabs.append(name)

                # Get the page key if available and requested
                if return_tab_keys:
                    page_key = page_info.get('page_key')
                    if page_key:
                        tab_keys.append(page_key)
                    else:
                        logger.warning(f"No page_key found for tab: {name}")

                # Recursively extract tabs from nested pages if they exist
                if 'pages' in page_info:
                    extract_tabs_from_pages(page_info['pages'])

        extract_tabs_from_pages(page_list)

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
async def hydrus_focus_on_tab(client_name: str = "", tab_name: str = "") -> str:
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

        target_page = None

        def find_page_by_name(pages_list, tab_name):
            """Recursively search for a page by name"""
            for page_info in pages_list:
                # Validate that each page_info is a dictionary
                if not isinstance(page_info, dict):
                    logger.error(f"Unexpected page_info format: {type(page_info).__name__}. Content: {str(page_info)[:200]}")
                    continue

                name = page_info.get('name', '')
                title = page_info.get('title', '')

                # Check if this is the page we're looking for
                if (tab_name.lower() == name.lower()) or (tab_name.lower() == title.lower()):
                    return page_info

                # Recursively search nested pages
                if 'pages' in page_info:
                    nested_page = find_page_by_name(page_info['pages'], tab_name)
                    if nested_page:
                        return nested_page

            return None

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
async def hydrus_send_to_tab(client_name: str = "", tab_name: str = "", content: str = "", is_query: bool = False, tag_service: str = "all known tags") -> str:
    """Send files to a specific tab in Hydrus client. When sending file ids to a tab, you set is_query to "False" or just leave it out, you also don't need to provide a tag service for file ids, the formatting for the file ids a is comma separated list of integers without the use of brackets. When providing a query, then also pass at least the is_query = "True" parameter. 

    Args:
        client_name (str): Name of the Hydrus client
        tab_name (str): Name of the tab to send files to
        content (str): Either a query string or comma-separated file IDs (do not use brackets when prviding file ids)
        is_query (bool): True if content is a query, False if it's file IDs (default: False)
        tag_service (str): Tag service name (default: "all known tags")

    Returns:
        str: Message indicating success and number of files sent
    """
    if not client_name.strip():
        return "❌ Error: Client name is required"
    if not tab_name.strip():
        return "❌ Error: Tab name is required"
    if not content.strip():
        return "❌ Error: Content is required (either query or file IDs)"

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

        # Find the target tab
        target_page = None

        def find_page_by_name(pages_list, tab_name):
            """Recursively search for a page by name"""
            for page_info in pages_list:
                # Validate that each page_info is a dictionary
                if not isinstance(page_info, dict):
                    logger.error(f"Unexpected page_info format: {type(page_info).__name__}. Content: {str(page_info)[:200]}")
                    continue

                name = page_info.get('name', '')
                title = page_info.get('title', '')

                # Check if this is the page we're looking for
                if (tab_name.lower() == name.lower()) or (tab_name.lower() == title.lower()):
                    return page_info

                # Recursively search nested pages
                if 'pages' in page_info:
                    nested_page = find_page_by_name(page_info['pages'], tab_name)
                    if nested_page:
                        return nested_page

            return None

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
        except:
            return f"❌ Error: {str(Exception)}"


    except AttributeError as e:
        return f"❌ Error: Method not found in client API: {e}"
    except Exception as e:
        return f"❌ Error: {str(e)}"
    

if __name__ == "__main__":
    logger.info("Starting Hydrus MCP server...")

    # Check if clients are configured
    clients = load_clients_from_secret()
    if not clients:
        logger.warning("No Hydrus clients configured. Set HYDRUS_CLIENTS secret with client credentials.")
    else:
        logger.info(f"Configured clients: {', '.join([c['name'] for c in clients])}")

    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
