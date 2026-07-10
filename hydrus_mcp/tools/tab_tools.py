"""Tab management tools for Hydrus MCP server.

These tools provide functionality for managing tabs/pages in Hydrus clients:
- Listing open tabs
- Getting page information
- Focusing on specific tabs
- Sending files to tabs

Note: Tools are defined as plain async functions here and registered with @mcp.tool()
in server.py to avoid circular import issues.
"""

import json
from typing import Any

from pydantic import Field
from typing import Annotated

from ..functions import (
    extract_tabs_from_pages,
    find_page_by_name,
    get_page_info,
    get_page_list,
    get_service_key_by_name,
    parse_file_ids,
    parse_hydrus_tags,
    safe_bool_convert,
    validate_client,
)


async def hydrus_get_page_info(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    page_key: Annotated[str, Field(description="The page key to get information for")] = ""
) -> str:
    """Get page information for a specific tab using its page key.

    Returns formatted result with page information or error message.
    """
    client_obj, error = validate_client(client_name)
    if error:
        return error

    if not page_key.strip():
        return "❌ Error: Page key is required"

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


async def hydrus_list_tabs(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    return_tab_keys: Annotated[Any, Field(description="If True, includes page keys in the output (default: False)")] = False
) -> str:
    """List open tabs in a Hydrus client. Optionally returns tab keys along with names."""
    client_obj, error = validate_client(client_name)
    if error:
        return error

    # Convert return_tab_keys to boolean using safe conversion to handle various input formats
    return_tab_keys = safe_bool_convert(return_tab_keys, False)

    # Get pages from the client using get_page_list helper
    page_list, error = get_page_list(client_obj)
    if error:
        return error

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


async def hydrus_focus_on_tab(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    tab_name: Annotated[str, Field(description="Name of the tab to focus on")] = ""
) -> str:
    """Focus the Hydrus client on a specific tab."""
    client_obj, error = validate_client(client_name)
    if error:
        return error

    if not tab_name.strip():
        return "❌ Error: Tab name is required"

    # Get pages from the client using get_page_list helper
    page_list, error = get_page_list(client_obj)
    if error:
        return error

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


async def hydrus_send_to_tab(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    tab_name: Annotated[str, Field(description="Name of the tab to send files to")] = "",
    content: Annotated[Any, Field(description="Either a query string (use brackets for OR type queries) or comma-separated file IDs (do not use brackets when providing file ids)")] = "",
    is_query: Annotated[Any, Field(description="True if content is a query (using tags, strings, filenames, etc.), False if it's numeric file IDs only (default: False). Accepts: true, True, \"true\", 1, or any truthy value")] = False,
    tag_service: Annotated[str, Field(description="When using queries, you can provide a specific tag service name (default: 'all known tags')")] = "all known tags"
) -> str:
    """Send files to a specific tab in Hydrus client.

    When sending file ids to a tab, set is_query to False or leave it out. You don't need to provide a tag service for file ids. The formatting for file ids is a comma separated list of integers without the use of brackets.
    When providing a query, pass at least the is_query=True parameter.

    Returns message indicating success and number of files sent.
    """
    client_obj, error = validate_client(client_name)
    if error:
        return error

    if not tab_name.strip():
        return "❌ Error: Tab name is required"
    if not str(content).strip():
        return "❌ Error: Content is required (either query or file IDs)"

    # Convert is_query to boolean using safe conversion to handle various input formats
    is_query = safe_bool_convert(is_query, False)

    try:
        # Get the content based on whether it's a query or file IDs
        file_ids = []
        result_count = 0

        if is_query:
            # Handle query - execute search and get file IDs
            try:
                tags = parse_hydrus_tags(content)
                tag_service_key = get_service_key_by_name(client_obj, tag_service)
                search_params = {
                    "tags": tags,
                    "file_sort_type": 13,
                    "tag_service_key": tag_service_key
                }

                query_result = client_obj.search_files(**search_params)

                # Parse the response to get file IDs
                query_response = query_result["file_ids"]
                if isinstance(query_response, dict) and 'file_ids' in query_response:
                    file_ids = query_response['file_ids']
                else:
                    file_ids = query_response

                result_count = len(file_ids)

                if result_count == 0:
                    return f"❌ No files found for query '{content}'"
            except Exception as e:
                return f"❌ Error: Failed to execute query - {str(e)}, {tags}, {query_result}, {tag_service_key}"
        else:
            # Handle direct file IDs using parse_file_ids function
            file_ids = parse_file_ids(content)
            result_count = len(file_ids)

        # Get pages from the client using get_page_list helper
        page_list, error = get_page_list(client_obj)
        if error:
            return error

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
