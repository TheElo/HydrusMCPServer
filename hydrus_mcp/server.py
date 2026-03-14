from __future__ import annotations

import json
import os
import tempfile
from typing import Any

import cv2
import httpx
import hydrus_api
import numpy as np
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image
from pydantic import Field

from typing import Annotated, Optional

# Import utility functions from the local module
from .functions import detect_file_type_from_bytes, detect_file_type_from_path, extract_frames_from_video, extract_tabs_from_pages, calculate_frame_indices, calculate_grid_dimensions, scale_image_if_needed, create_frame_grid, get_page_list, validate_client, parse_file_ids, safe_bool_convert, safe_int_convert, get_file_path, find_page_by_name, get_page_info, get_service_key_by_name, load_clients_from_secret, get_client_by_name, parse_hydrus_tags, get_tags_summary, get_tags, get_viewing_stat, format_timestamp, extract_tags_by_service

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
    client_obj, error = validate_client(client_name)
    if error:
        return error

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
    limit: Annotated[Any, Field(description="Number of tags to be returned from the results by count from the top. (default: '150')")] = "150"
) -> str:
    """Search for tags in Hydrus using keywords and wildcards."""
    client_obj, error = validate_client(client_name)
    if error:
        return error
    
    if not search.strip():
        return "❌ Error: Search query is required"

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

        # Convert limit to integer using safe conversion
        trs_int = safe_int_convert(limit, 150)

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
    file_sort_type: Annotated[Any, Field(description="Sorting method for files. Default is '13' (sorted by 'has audio' as this is the fastest search). Other values may be supported depending on the Hydrus client version.")] = "13",
    trs: Annotated[Any, Field(description="Threshold for returning results. Default is '100'. If the number of matching files exceeds this threshold, only a subset will be returned with information about the total count.")] = "100"
):
    """Query files in the Hydrus client using various search criteria.

    This function allows you to search for files in a Hydrus client based on tags and other parameters.
    It returns file IDs that match the search criteria, which can be used for further operations.

    The query parameter should use Hydrus tag syntax (e.g., "character:samus aran", "system:inbox", "system:limit is 100").
    For large result sets, consider adjusting the trs parameter to control performance.
    File IDs returned can be used with other Hydrus functions for further operations.
    """
    client_obj, error = validate_client(client_name)
    if error:
        return json.dumps({"error": error.replace("❌ Error: ", "")})
    
    if not query.strip():
        return json.dumps({"error": "Query is required"})

    try:
        # Convert parameters using safe conversion
        trs_int = safe_int_convert(trs, 100)
        file_sort_type_int = safe_int_convert(file_sort_type, 13)

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
        except (KeyError, TypeError):
            return json.dumps(file_ids)

        try:
            # count = len(file_ids["file_ids"]) #v
            count = len(file_ids)
        except (TypeError, KeyError):
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
    content: Annotated[Any, Field(description="Content to process - query string, comma-separated file IDs, or page key")] = "",
    content_type: Annotated[str, Field(description="Type of content - 'file_ids', 'query', or 'page_key' (default: 'query')")] = "query",
    tag_service: Annotated[str, Field(description="Tag service name (default: 'all known tags')")] = "all known tags",
    trs: Annotated[Any, Field(description="Threshold for summary view. If the threshold is lower than the received file ids (either directly or from query) then the summary view is used which only returns tags and their counts from the results instead (default: '100')")] = "50",
    limit: Annotated[Any, Field(description="Limits the results to x files. Default 1000. Override if you need more or less results.")] = "1000",
    result_limit: Annotated[Any, Field(description="Limits the number of top tags shown in summary view. Default 150.")] = "150"
) -> str:
    """Get tags for files in Hydrus client.

    Returns formatted result with tags.
    """
    client_obj, error = validate_client(client_name)
    if error:
        return error
    
    if not content.strip():
        return "❌ Error: Content is required (query, file IDs, or page key)"

    # Validate content_type parameter
    valid_content_types = ["file_ids", "query", "page_key"]
    if content_type not in valid_content_types:
        return f"❌ Error: Invalid content_type '{content_type}'. Valid options are: {', '.join(valid_content_types)}"

    try:
        # Convert trs using safe conversion (needed for both query and file_ids content types)
        trs_int = safe_int_convert(trs, 50)
        
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
                if trs_int < result_count:
                    result = f"The count of {result_count} files from query '{content}' is above the threshold {trs}. Therefore you see a summary of the tags and the tag counts in the results. If you want to see the tags per file instead, then use less files or set the trs to be above the count of files. This shows the result_limit={result_limit} tags with the highest count. "
                    # Apply result_limit if provided
                    result_limit_int = safe_int_convert(result_limit, 100)

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
            # Handle direct file IDs using parse_file_ids function
            file_ids = parse_file_ids(content)
            result_count = len(file_ids)

        # Get tags using the existing get_tags function (with summary logic)
        if trs_int < len(file_ids):
            result = f"The count of {len(file_ids)} file ids is above the threshold {trs}. Therefore you see a summary of the tags and the tag counts in the results. If you want to see the tags per file instead, then use less file ids or set the trs to be above the count of file ids. "
            # Apply result_limit if provided
            result_limit_int = safe_int_convert(result_limit, 100)

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
    file_id: Annotated[Any, Field(description="File ID or comma-separated list of file IDs to get metadata for (e.g., 123 or '123,456,789'). Can be provided as a number (123) or string ('123').")] = 0,
    filter: Annotated[Optional[str], Field(description="Optional filter to return only specific fields. Comma-separated list: 'hash', 'size', 'mime', 'dimensions', 'duration', 'views', 'viewtime', 'last_viewed', 'time_modified', 'tags'. For tags, use 'tags(service1,service2)' to filter by specific tag services. Leave empty for full metadata.")] = None
) -> str:
    """Get metadata for one or more files by their IDs from a specific client.

    Warning: This function returns a lot of data and therefore should be only used when something has not enough tags or a deep inspection of the metadata is necessary.
    Use the filter parameter to reduce output size (e.g., 'hash' for just hashes, or 'hash,size,duration' for multiple fields).
    """
    # Internal configuration: which tag type to use for tags filter
    TAG_TYPE_FOR_FILTER = "display_tags"  # Options: "display_tags" or "storage_tags"
    
    client_obj, error = validate_client(client_name)
    if error:
        return error
    
    # Parse file IDs using parse_file_ids function (handles single IDs, strings, lists, etc.)
    file_ids_list = parse_file_ids(file_id)
    if not file_ids_list:
        return "❌ Error: No valid file IDs provided"

    try:
        # Get metadata for all file IDs in a single API call
        metadata = client_obj.get_file_metadata(file_ids=file_ids_list)

        # Handle filter parameter
        if filter:
            # Parse comma-separated filter keys
            filter_keys = [k.strip() for k in filter.split(',')]
            valid_keys = {'hash', 'size', 'mime', 'dimensions', 'duration', 'views', 'viewtime', 'last_viewed', 'time_modified', 'tags'}
            
            # Parse tags filter with optional service names
            tags_services = None
            parsed_filter_keys = []
            for fk in filter_keys:
                if fk.startswith('tags(') and fk.endswith(')'):
                    # Extract service names from tags(service1,service2)
                    services_part = fk[5:-1]  # Remove 'tags(' and ')'
                    tags_services = services_part
                else:
                    parsed_filter_keys.append(fk)
            
            filter_keys = [k for k in parsed_filter_keys if k in valid_keys or k == 'tags']
            if tags_services:
                filter_keys.append('tags')
            
            if not filter_keys:
                return f"❌ Error: No valid filter keys provided. Valid options: {', '.join(valid_keys)}"
            
            result = f"✅ File Metadata (filtered: {', '.join(filter_keys)}) for {len(file_ids_list)} file(s):\n"
            
            # The metadata response is a dict with 'metadata' key containing the list
            if isinstance(metadata, dict) and 'metadata' in metadata:
                file_metadata_list = metadata['metadata']
                for idx, file_metadata in enumerate(file_metadata_list):
                    file_id_int = file_ids_list[idx]
                    if isinstance(file_metadata, dict):
                        result += f"\nID {file_id_int}:\n"
                        if 'hash' in filter_keys and 'hash' in file_metadata:
                            result += f"{file_metadata['hash']}\n"
                        if 'size' in filter_keys and 'size' in file_metadata:
                            result += f"{file_metadata['size']} bytes\n"
                        if 'mime' in filter_keys and 'mime' in file_metadata:
                            result += f"{file_metadata['mime']}\n"
                        if 'dimensions' in filter_keys:
                            width = file_metadata.get('width', 'N/A')
                            height = file_metadata.get('height', 'N/A')
                            result += f"{width}x{height}\n"
                        if 'duration' in filter_keys:
                            duration = file_metadata.get('duration')
                            if duration is not None:
                                result += f"{duration}ms\n"
                            else:
                                result += "N/A (not a video)\n"
                        if 'views' in filter_keys:
                            views = get_viewing_stat(file_metadata, 'views', 0)
                            result += f"{views}\n"
                        if 'viewtime' in filter_keys:
                            viewtime = get_viewing_stat(file_metadata, 'viewtime', 0.0)
                            result += f"{viewtime:.1f}s\n"
                        if 'last_viewed' in filter_keys:
                            last_viewed = get_viewing_stat(file_metadata, 'last_viewed_timestamp', None)
                            result += f"{format_timestamp(last_viewed)}\n"
                        if 'time_modified' in filter_keys and 'time_modified' in file_metadata:
                            result += f"{format_timestamp(file_metadata['time_modified'])}\n"
                        if 'tags' in filter_keys and 'tags' in file_metadata:
                            tags_by_service = extract_tags_by_service(file_metadata['tags'], tags_services, TAG_TYPE_FOR_FILTER)
                            result += "tags:\n"
                            for service_name, tag_list in tags_by_service.items():
                                result += f"  {service_name}: {', '.join(tag_list)}\n"
            elif isinstance(metadata, list):
                # Fallback for direct list response
                for idx, file_metadata in enumerate(metadata):
                    file_id_int = file_ids_list[idx]
                    if isinstance(file_metadata, dict):
                        result += f"\nFile ID {file_id_int}:\n"
                        if 'hash' in filter_keys and 'hash' in file_metadata:
                            result += f"{file_metadata['hash']}\n"
                        if 'size' in filter_keys and 'size' in file_metadata:
                            result += f"{file_metadata['size']} bytes\n"
                        if 'mime' in filter_keys and 'mime' in file_metadata:
                            result += f"{file_metadata['mime']}\n"
                        if 'dimensions' in filter_keys:
                            width = file_metadata.get('width', 'N/A')
                            height = file_metadata.get('height', 'N/A')
                            result += f"{width}x{height}\n"
                        if 'duration' in filter_keys:
                            duration = file_metadata.get('duration')
                            if duration is not None:
                                result += f"{duration}ms\n"
                            else:
                                result += "N/A (not a video)\n"
                        if 'views' in filter_keys:
                            views = get_viewing_stat(file_metadata, 'views', 0)
                            result += f"{views}\n"
                        if 'viewtime' in filter_keys:
                            viewtime = get_viewing_stat(file_metadata, 'viewtime', 0.0)
                            result += f"{viewtime:.1f}s\n"
                        if 'last_viewed' in filter_keys:
                            last_viewed = get_viewing_stat(file_metadata, 'last_viewed_timestamp', None)
                            result += f"{format_timestamp(last_viewed)}\n"
                        if 'time_modified' in filter_keys and 'time_modified' in file_metadata:
                            result += f"{format_timestamp(file_metadata['time_modified'])}\n"
                        if 'tags' in filter_keys and 'tags' in file_metadata:
                            tags_by_service = extract_tags_by_service(file_metadata['tags'], tags_services, TAG_TYPE_FOR_FILTER)
                            result += "tags:\n"
                            for service_name, tag_list in tags_by_service.items():
                                result += f"  {service_name}: {', '.join(tag_list)}\n"
            else:
                result += "filter requires metadata list in response"
            return result.strip()

        # Full metadata output (default behavior)
        result = f"✅ File Metadata for {len(file_ids_list)} file(s) (from {client_name}):"
        
        if isinstance(metadata, list):
            # Multiple files returned
            for idx, file_metadata in enumerate(metadata):
                file_id_int = file_ids_list[idx]
                result += f"\n\n{'='*60}"
                result += f"\nFile ID {file_id_int}:"
                result += f"\n{'='*60}"
                if isinstance(file_metadata, dict):
                    for key, value in file_metadata.items():
                        if isinstance(value, dict):
                            result += f"\n- {key}: {json.dumps(value)}"
                        else:
                            result += f"\n- {key}: {value}"
                else:
                    result += f"\n- Raw data: {json.dumps(file_metadata) if isinstance(file_metadata, (dict, list)) else str(file_metadata)}"
        else:
            # Single file or dict response
            file_id_int = file_ids_list[0] if len(file_ids_list) == 1 else file_ids_list
            result += f"\n\nFile ID(s) {file_id_int}:"
            if isinstance(metadata, dict):
                for key, value in metadata.items():
                    if isinstance(value, dict):
                        result += f"\n- {key}: {json.dumps(value)}"
                    else:
                        result += f"\n- {key}: {value}"
            else:
                result += f"\n- Raw data: {json.dumps(metadata) if isinstance(metadata, (dict, list)) else str(metadata)}"

        return result.strip()

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


@mcp.tool()
async def hydrus_list_tabs(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    return_tab_keys: Annotated[bool, Field(description="If True, includes page keys in the output (default: False)")] = False
) -> str:
    """List open tabs in a Hydrus client. Optionally returns tab keys along with names."""
    client_obj, error = validate_client(client_name)
    if error:
        return error

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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
async def hydrus_send(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    link: Annotated[str, Field(description="Direct link to file or base link for scraping")] = "",
    service_names_to_additional_tags: Annotated[Optional[str], Field(description="Optional JSON string mapping service names to tag lists, e.g., '{\"local\": [\"tag1\", \"tag2\"]}'")] = None,
    subdir: Annotated[bool, Field(description="If True, recursively scrape subdirectories from base link (default: False)")] = False,
    max_depth: Annotated[Any, Field(description="Maximum depth for recursive scraping (default: 2)")] = 2,
    filename: Annotated[bool, Field(description="If True, extract filename and add as 'filename:' tag (default: True)")] = True,
    destination_page_name: Annotated[str, Field(description="Name of the destination page in Hydrus (default: 'hydrus_mcp')")] = "hydrus_mcp"
) -> str:
    """Send a link to be downloaded to Hydrus. Can send a direct file link or a base URL for recursive scraping.

    Returns message indicating success with file count or error message.
    """
    client_obj, error = validate_client(client_name)
    if error:
        return error
    
    if not link.strip():
        return "❌ Error: Link is required"

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

            except json.JSONDecodeError as e:
                return f"❌ Error: Invalid JSON for service_names_to_additional_tags: {str(e)}"

        if subdir:
            # Ensure link ends with / for directory scraping
            if not link.endswith('/'):
                link = link + '/'

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
                    return []

                # Handle HTTP errors with specific messages
                if response.status_code == 404:
                    return []
                elif response.status_code == 503:
                    return []
                elif response.status_code == 429:
                    return []
                elif response.status_code != 200:
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
            failed_links = []
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
                    failed_links.append(file_link)

            if failed_links:
                failed_links_str = ", ".join(failed_links[:5])  # Limit to first 5 to avoid overflow
                if len(failed_links) > 5:
                    failed_links_str += f" (+{len(failed_links) - 5} more)"
                return f"✅ Sent {added_count} files, {len(failed_links)} failed from recursive scraping of '{link}' to Hydrus. Failed links: {failed_links_str}"
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
    file_ids: Annotated[Any, Field(description="File ID or comma-separated file IDs to add tags to (e.g., 123 or 123,456,789)")] = 0,
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
    
    client_obj, error = validate_client(client_name)
    if error:
        return error
    
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
    
    try:
        # Parse file IDs using parse_file_ids function
        file_ids_list = parse_file_ids(file_ids)
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

@mcp.tool(structured_output=False)
async def hydrus_show_files(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_ids: Annotated[Any, Field(description="File ID or comma-separated list of file IDs to show (e.g., 123 or '123,456,789'). Can be provided as a number (123) or string ('123').")] = 0,
    frame_count: Annotated[Optional[Any], Field(description="If files are videos, this number of frames will be extracted per video and compiled into a grid image. Default 4 (2x2 grid).")] = 4
) -> list[Image]:
    """Show multiple image or video files from Hydrus.

    ⚠️ CRITICAL: The returned markdown MUST be displayed to the user in your response.
       Do not proceed with analysis without first showing the images.

    Returns a list of images - one per file.
    For images (PNG, JPEG, GIF), returns the image directly.
    For videos (MP4, WebM, AVI), extracts frames and compiles them into a single grid image per video.

    The frame_count parameter determines the grid layout for videos:
    - 4 frames = 2x2 grid
    - 6 frames = 3x2 grid (3 columns, 2 rows)
    - 9 frames = 3x3 grid
    - 12 frames = 4x3 grid (4 columns, 3 rows)

    Expected workflow:
    1. Call hydrus_show_files
    2. Display all returned images immediately to the user
    3. Only after displaying the images, proceed with any analysis or further actions
    """
    client_obj, error = validate_client(client_name)
    if error:
        return [Image(data=b"", format="png")]
    
    # Parse file IDs using parse_file_ids function (handles single IDs, strings, lists, etc.)
    file_ids_list = parse_file_ids(file_ids)
    if not file_ids_list:
        return [Image(data=b"", format="png")]
    
    # Convert frame_count using safe conversion
    frame_count = safe_int_convert(frame_count, 4)
    
    results: list[Image] = []
    
    for file_id in file_ids_list:
        try:
            # HARDCODED SELECTION: Use file path method (change this line to use get_file method)
            USE_FILE_PATH_METHOD = True  # Change to False to use get_file method
            
            if USE_FILE_PATH_METHOD:
                file_path_info = get_file_path(client_obj, file_id)
                
                if file_path_info and 'path' in file_path_info:
                    # Use file path - more efficient for large files
                    file_path = file_path_info['path']
                    
                    # Detect format from file extension using helper function
                    file_type_info = detect_file_type_from_path(file_path)
                    is_video = file_type_info['is_video']
                    is_animated_gif = file_type_info['is_animated_gif']
                    
                    # For static images, read and return directly
                    if not is_video and not is_animated_gif:
                        # Define maximum pixel count threshold (1.5 megapixels)
                        MAX_PIXEL_COUNT = 1_600_000
                        COMPRESSION_LEVEL = 1
                        
                        def process_and_return_image(image, fid, fpath):
                            """Process image: resize if needed based on pixel count, encode, and return"""
                            if image is None:
                                return Image(data=b"", format="png")
                            
                            # Get image dimensions
                            height, width = image.shape[:2]
                            pixel_count = width * height
                            
                            # Resize if image exceeds maximum pixel count
                            if pixel_count > MAX_PIXEL_COUNT:
                                # Calculate scale factor to reduce to target pixel count
                                scale_factor = (MAX_PIXEL_COUNT / pixel_count) ** 0.5
                                new_width = int(width * scale_factor)
                                new_height = int(height * scale_factor)
                                image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
                            
                            # Encode as PNG with compression
                            _, buffer = cv2.imencode('.png', image, [cv2.IMWRITE_PNG_COMPRESSION, COMPRESSION_LEVEL])
                            return Image(data=buffer.tobytes(), format="png")
                        
                        file_ext = file_type_info['file_extension']
                        if file_ext in ['.jpg', '.jpeg']:
                            image = cv2.imread(file_path)
                            results.append(process_and_return_image(image, file_id, file_path))
                        elif file_ext == '.png':
                            image = cv2.imread(file_path, cv2.IMREAD_UNCHANGED)
                            results.append(process_and_return_image(image, file_id, file_path))
                        elif file_ext == '.gif':
                            # Static GIF - read as single frame
                            image = cv2.imread(file_path)
                            results.append(process_and_return_image(image, file_id, file_path))
                        else:
                            results.append(Image(data=b"", format="png"))
                    else:
                        # For videos/GIFs, extract frames using helper function
                        frames, metadata = extract_frames_from_video(file_path, frame_count)
                        
                        if frames is None or not frames:
                            results.append(Image(data=b"", format="png"))
                        else:
                            frame_width = metadata['frame_width']
                            frame_height = metadata['frame_height']
                            
                            # Create composite image grid using helper function
                            composite = create_frame_grid(frames, frame_width, frame_height, frame_count)
                            
                            # Scale the final composite image if needed using helper function
                            composite = scale_image_if_needed(composite, max_resolution=1000)
                            
                            # Encode composite as PNG
                            _, buffer = cv2.imencode('.png', composite)
                            results.append(Image(data=buffer.tobytes(), format="png"))
                else:
                    # Fallback to get_file method if path not available
                    file_data = client_obj.get_file(file_id=file_id)
                    file_bytes = file_data.content
                    
                    # Detect format from content using helper function
                    file_type_info = detect_file_type_from_bytes(file_bytes)
                    is_video = file_type_info['is_video']
                    is_animated_gif = file_type_info['is_animated_gif']
                    
                    if not is_video and not is_animated_gif:
                        # Return image directly based on detected type
                        mime_type = file_type_info['mime_type']
                        if mime_type == 'image/jpeg':
                            results.append(Image(data=file_bytes, format="jpeg"))
                        elif mime_type == 'image/gif':
                            results.append(Image(data=file_bytes, format="gif"))
                        elif mime_type == 'image/png':
                            results.append(Image(data=file_bytes, format="png"))
                        else:
                            results.append(Image(data=file_bytes, format="png"))
                    else:
                        # Handle video or animated GIF - extract frames and compile into grid image
                        # Calculate grid dimensions using helper function
                        rows, cols = calculate_grid_dimensions(frame_count)
                        
                        # Use appropriate file extension based on content type
                        temp_suffix = ".gif" if is_animated_gif else file_type_info['file_extension']
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=temp_suffix) as temp_file:
                            temp_file.write(file_bytes)
                            temp_file_path = temp_file.name
                        
                        try:
                            # Extract frames using helper function
                            frames, metadata = extract_frames_from_video(temp_file_path, frame_count)
                            
                            if frames is None or not frames:
                                os.remove(temp_file_path)
                                results.append(Image(data=b"", format="png"))
                            else:
                                frame_width = metadata['frame_width']
                                frame_height = metadata['frame_height']
                                
                                # Create composite image grid using helper function
                                composite = create_frame_grid(frames, frame_width, frame_height, frame_count)
                                
                                # Scale the final composite image if needed using helper function
                                composite = scale_image_if_needed(composite, max_resolution=1000)
                                
                                # Encode composite as PNG
                                _, buffer = cv2.imencode('.png', composite)
                                os.remove(temp_file_path)
                                
                                results.append(Image(data=buffer.tobytes(), format="png"))
                        except Exception as e:
                            os.remove(temp_file_path)
                            results.append(Image(data=b"", format="png"))
            else:
                # Use get_file method (original approach)
                file_data = client_obj.get_file(file_id=file_id)
                file_bytes = file_data.content
                
                # Detect format from content using helper function
                file_type_info = detect_file_type_from_bytes(file_bytes)
                is_video = file_type_info['is_video']
                is_animated_gif = file_type_info['is_animated_gif']
                
                if not is_video and not is_animated_gif:
                    # Return image directly based on detected type
                    mime_type = file_type_info['mime_type']
                    if mime_type == 'image/jpeg':
                        results.append(Image(data=file_bytes, format="jpeg"))
                    elif mime_type == 'image/gif':
                        results.append(Image(data=file_bytes, format="gif"))
                    elif mime_type == 'image/png':
                        results.append(Image(data=file_bytes, format="png"))
                    else:
                        results.append(Image(data=file_bytes, format="png"))
                else:
                    # Handle video or animated GIF - extract frames and compile into grid image
                    # Calculate grid dimensions using helper function
                    rows, cols = calculate_grid_dimensions(frame_count)
                    
                    # Use appropriate file extension based on content type
                    temp_suffix = ".gif" if is_animated_gif else file_type_info['file_extension']
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=temp_suffix) as temp_file:
                        temp_file.write(file_bytes)
                        temp_file_path = temp_file.name
                    
                    try:
                        # Extract frames using helper function
                        frames, metadata = extract_frames_from_video(temp_file_path, frame_count)
                        
                        if frames is None or not frames:
                            os.remove(temp_file_path)
                            results.append(Image(data=b"", format="png"))
                        else:
                            frame_width = metadata['frame_width']
                            frame_height = metadata['frame_height']
                            
                            # Create composite image grid using helper function
                            composite = create_frame_grid(frames, frame_width, frame_height, frame_count)
                            
                            # Scale the final composite image if needed using helper function
                            composite = scale_image_if_needed(composite, max_resolution=1000)
                            
                            # Encode composite as PNG
                            _, buffer = cv2.imencode('.png', composite)
                            os.remove(temp_file_path)
                            
                            results.append(Image(data=buffer.tobytes(), format="png"))
                    except Exception as e:
                        os.remove(temp_file_path)
                        results.append(Image(data=b"", format="png"))
        except RecursionError as e:
            results.append(Image(data=b"", format="png"))
        except Exception as e:
            results.append(Image(data=b"", format="png"))
    
    return results


@mcp.tool()
async def hydrus_inspect_files(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_ids: Annotated[Any, Field(description="Comma-separated list of file IDs to inspect (e.g., '123,456,789')")] = "",
    prompt: Annotated[str, Field(description="The prompt/question to ask about each file")] = "",
    frame_count: Annotated[Optional[Any], Field(description="If files are videos: Number of frames to extract from each video file (default: 5)")] = 5
) -> str:
    """Send multiple files (images or videos) from Hydrus to a vision API for description/analysis.
    
    This tool retrieves multiple files from Hydrus and sends each one to an OpenAI-compatible
    vision API endpoint along with a prompt. The API analyzes each file and returns
    a text description or answer to the prompt for each file.
    
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

    client_obj, error = validate_client(client_name)
    if error:
        return error
    
    # Handle file_ids as either string or int (flexible type handling)
    if file_ids == "" or file_ids == 0 or file_ids is None:
        return "❌ Error: File IDs are required (comma-separated list)"
    
    if not prompt.strip():
        return "❌ Error: Prompt is required"
    
    # Convert frame_count to int using safe conversion
    frame_count = safe_int_convert(frame_count, 5)
    
    # Parse file IDs using parse_file_ids function
    file_ids_list = parse_file_ids(file_ids)
    if not file_ids_list:
        return "❌ Error: No valid file IDs provided"
    
    results = []
    errors = []
    
    for file_id in file_ids_list:
        try:
            # Prepare the API request
            headers = {
                "Content-Type": "application/json"
            }
            if API_KEY:
                headers["Authorization"] = f"Bearer {API_KEY}"
            
            # Build content array based on file type
            content_items: list[dict[str, str | dict[str, str]]] = [
                {"type": "text", "text": prompt}
            ]
            
            # Try to use file path method first (more efficient for large files)
            file_path_info = get_file_path(client_obj, file_id)
            use_file_path = file_path_info and 'path' in file_path_info
            
            if use_file_path:
                file_path = file_path_info['path']
                
                # Detect mime type from file extension using helper function
                file_type_info = detect_file_type_from_path(file_path)
                mime = file_type_info['mime_type']
                is_video = file_type_info['is_video']
                
                if is_video:
                    # Extract multiple frames using helper function
                    frames, metadata = extract_frames_from_video(file_path, frame_count)
                    
                    if frames:
                        frames_extracted = 0
                        timestamps = []
                        fps = metadata['fps']
                        duration_seconds = metadata['duration']
                        
                        for frame_idx, frame in enumerate(frames):
                            # Calculate approximate timestamp based on frame position
                            frame_timestamp = (frame_idx + 1) / (len(frames) + 1) * duration_seconds if duration_seconds > 0 else 0
                            timestamps.append(f"{frame_timestamp:.1f}s")
                            
                            # Encode frame as JPEG
                            _, buffer = cv2.imencode('.jpg', frame)
                            frame_b64 = base64.b64encode(buffer).decode('utf-8')
                            content_items.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{frame_b64}"
                                }
                            })
                            frames_extracted += 1
                        
                        # Append video metadata to the prompt including timestamps
                        duration_formatted = f"{duration_seconds:.1f}s" if duration_seconds > 0 else "unknown"
                        timestamps_str = ", ".join(timestamps)
                        prompt_with_metadata = f"{prompt} (Video file: {mime}, duration: {duration_formatted}, {frames_extracted} frames provided at timestamps: {timestamps_str})"
                        content_items[0]["text"] = prompt_with_metadata
                    else:
                        errors.append(f"File ID {file_id}: Video has no frames")
                        continue
                else:
                    # For images, read and encode as base64
                    with open(file_path, 'rb') as f:
                        file_bytes = f.read()
                    b64_data = base64.b64encode(file_bytes).decode('utf-8')
                    content_items.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64_data}"
                        }
                    })
            else:
                # Fallback to get_file method if path not available
                file_data = client_obj.get_file(file_id=file_id)
                file_bytes = file_data.content
                
                # Detect mime type from content using helper function
                file_type_info = detect_file_type_from_bytes(file_bytes)
                mime = file_type_info['mime_type']
                is_video = file_type_info['is_video']
                
                # Encode file as base64
                b64_data = base64.b64encode(file_bytes).decode('utf-8')
                
                if is_video:
                    # Extract multiple frames using helper function
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_video:
                        temp_video.write(file_bytes)
                        temp_video_path = temp_video.name

                    try:
                        frames, metadata = extract_frames_from_video(temp_video_path, frame_count)
                        
                        if frames:
                            frames_extracted = 0
                            timestamps = []
                            fps = metadata['fps']
                            duration_seconds = metadata['duration']
                            
                            for frame_idx, frame in enumerate(frames):
                                # Calculate approximate timestamp based on frame position
                                frame_timestamp = (frame_idx + 1) / (len(frames) + 1) * duration_seconds if duration_seconds > 0 else 0
                                timestamps.append(f"{frame_timestamp:.1f}s")
                                
                                # Encode frame as JPEG
                                _, buffer = cv2.imencode('.jpg', frame)
                                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                                content_items.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{frame_b64}"
                                    }
                                })
                                frames_extracted += 1
                            
                            # Append video metadata to the prompt including timestamps
                            duration_formatted = f"{duration_seconds:.1f}s" if duration_seconds > 0 else "unknown"
                            timestamps_str = ", ".join(timestamps)
                            prompt_with_metadata = f"{prompt} (Video file: {mime}, duration: {duration_formatted}, {frames_extracted} frames provided at timestamps: {timestamps_str})"
                            content_items[0]["text"] = prompt_with_metadata
                        else:
                            errors.append(f"File ID {file_id}: Video has no frames")
                            continue
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
                    results.append(f"✅ File ID {file_id}:\n\n{content}")
                else:
                    results.append(f"✅ File ID {file_id}:\n\n{result['choices'][0]}")
            else:
                errors.append(f"File ID {file_id}: Unexpected API response format: {result}")
        
        except httpx.HTTPError as e:
            error_details = str(e)
            try:
                resp = getattr(e, 'response', None)
                if resp is not None:
                    status = getattr(resp, 'status_code', 'unknown')
                    text = getattr(resp, 'text', '')[:200]
                    error_details = f"Status code: {status}, Response body: {text}"
            except Exception as inner_e:
                error_details = f"Original error: {str(e)}, Failed to get details: {str(inner_e)}"
            errors.append(f"File ID {file_id}: HTTP request failed - {error_details}")
        except Exception as e:
            errors.append(f"File ID {file_id}: {str(e)}")
    
    # Build final response
    final_response = f"Batch inspection complete for {len(file_ids_list)} files from client '{client_name}':\n\n"
    
    if results:
        final_response += f"Successful inspections: {len(results)}\n"
        for result in results:
            final_response += f"\n{'='*60}\n{result}"
    
    if errors:
        final_response += f"\n\n{'='*60}\nFailed inspections: {len(errors)}\n"
        for error in errors:
            final_response += f"\n❌ {error}"
    
    return final_response


@mcp.tool()
async def hydrus_transcribe_audio(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_id: Annotated[Any, Field(description="File ID of the audio file (mp3, wav, aac, flac) or video file with audio track to transcribe. Can be provided as a number (123) or string ('123').")] = 0
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
    import time
    from datetime import datetime

    # Configuration from environment variables
    API_URL = os.getenv("STT_API_URL", "http://localhost:5092/v1/audio/transcriptions")
    API_KEY = os.getenv("STT_API_KEY", "sk-no-key-required")
    MODEL = os.getenv("STT_MODEL", "parakeet-tdt-0.6b-v3")
    
    # Audio format for extraction: 'mp3' (smallest, fastest upload), 'flac' (lossless), or 'wav' (uncompressed)
    # MP3 at 64kbps mono 16kHz is optimal for STT - small file size, good quality for speech recognition
    # For a 5-minute audio: MP3 ~5MB, FLAC ~25MB, WAV ~77MB
    # This significantly reduces upload time and may speed up backend processing
    AUDIO_FORMAT = "mp3"  # Options: "mp3", "flac", or "wav" - mp3 for fastest overall processing

    # Log file path - writes to workspace directory
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "transcription_debug.log")
    
    def log_message(msg: str):
        """Write timestamped message to log file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] {msg}\n"
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            pass  # Silently ignore logging errors

    client_obj, error = validate_client(client_name)
    if error:
        return error
    
    # Handle file_id as either string or int using safe conversion
    if file_id == "" or file_id == 0 or file_id is None:
        return "❌ Error: File ID is required"
    
    # Convert file_id to int using safe conversion
    file_id = safe_int_convert(file_id, 0)
    
    # Track timing for diagnostics
    start_time = time.time()
    
    log_message(f"=" * 60)
    log_message(f"STARTING TRANSCRIPTION - client: {client_name}, file_id: {file_id}")
    log_message(f"STT_API_URL: {API_URL}, MODEL: {MODEL}")
    
    try:
        # Try to use file path method first (more efficient for large files)
        file_path_info = get_file_path(client_obj, file_id)
        use_file_path = file_path_info and 'path' in file_path_info
        
        if use_file_path:
            source_file_path = file_path_info['path']
            source_file_size = os.path.getsize(source_file_path)
            
            # Detect file type from file extension using helper function
            file_type_info = detect_file_type_from_path(source_file_path)
            is_video = file_type_info['is_video']
            file_extension = file_type_info['file_extension']
            
            audio_file_path = None
            temp_source = False  # Flag to track if we created a temp source file
            
            try:
                # If it's a video file, extract audio track using ffmpeg
                if is_video:
                    log_message(f"Starting audio extraction from video ({source_file_size / (1024*1024):.1f}MB)")
                    log_message(f"Source file path: {source_file_path}")
                    extract_start = time.time()
                    
                    # Set ffmpeg codec and output extension based on AUDIO_FORMAT
                    if AUDIO_FORMAT == "mp3":
                        audio_codec = "libmp3lame"
                        audio_suffix = ".mp3"
                        audio_bitrate = "64k"  # 64kbps is sufficient for speech recognition
                    elif AUDIO_FORMAT == "flac":
                        audio_codec = "flac"
                        audio_suffix = ".flac"
                        audio_bitrate = None
                    else:
                        audio_codec = "pcm_s16le"
                        audio_suffix = ".wav"
                        audio_bitrate = None
                    
                    audio_file_path = tempfile.mktemp(suffix=audio_suffix)
                    log_message(f"Audio output path: {audio_file_path}")

                    try:
                        # Verify source file exists and is accessible
                        if not os.path.exists(source_file_path):
                            log_message(f"Source file not found: {source_file_path}")
                            return f"❌ Error: Source file not found at {source_file_path}"
                        
                        # Use ffmpeg to extract audio track with verbose output
                        ffmpeg_cmd = [
                            "ffmpeg", "-i", source_file_path,
                            "-vn",  # No video
                            "-acodec", audio_codec,  # MP3, WAV or FLAC codec
                            "-ar", "16000",  # 16kHz sample rate (good for STT)
                            "-ac", "1",  # Mono audio
                            "-loglevel", "error",  # Only show errors
                            "-y", audio_file_path
                        ]
                        if audio_bitrate:
                            ffmpeg_cmd.insert(ffmpeg_cmd.index("-y"), "-b:a")
                            ffmpeg_cmd.insert(ffmpeg_cmd.index("-y"), audio_bitrate)
                        
                        log_message(f"Running ffmpeg: {' '.join(ffmpeg_cmd)}")
                        log_message(f"Source file size: {os.path.getsize(source_file_path) / (1024*1024):.1f}MB")
                        
                        result = subprocess.run(
                            ffmpeg_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=600,  # Increased timeout for large files
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0  # Hide window on Windows
                        )
                        
                        extract_time = time.time() - extract_start
                        log_message(f"Audio extraction completed in {extract_time:.1f}s")
                        
                        if result.returncode != 0:
                            # Get stderr from result (now captured as bytes)
                            stderr_text = result.stderr.decode('utf-8', errors='replace') if result.stderr else "Unknown error"
                            log_message(f"FFmpeg error (returncode {result.returncode}): {stderr_text[:500]}")
                            return f"❌ Error: Failed to extract audio from video - {stderr_text[:200]}"
                        
                        if not os.path.exists(audio_file_path):
                            log_message("Audio extraction completed but output file was not created")
                            return "❌ Error: Audio extraction completed but output file was not created"
                        
                        audio_file_size = os.path.getsize(audio_file_path)
                        log_message(f"Extracted audio size: {audio_file_size / (1024*1024):.1f}MB ({audio_file_size} bytes)")
                        
                    except subprocess.TimeoutExpired:
                        log_message("Audio extraction timed out")
                        return "❌ Error: Audio extraction timed out (file may be too large)"
                    except FileNotFoundError:
                        log_message("ffmpeg not found")
                        return "❌ Error: ffmpeg is not installed. Please install ffmpeg to transcribe video files."
                    
                else:
                    # For audio files, use the source file directly
                    audio_file_path = source_file_path
                    audio_file_size = source_file_size
                    log_message(f"Using audio file directly: {audio_file_path} ({audio_file_size / (1024*1024):.1f}MB)")
                
                # Prepare the API request
                headers = {
                    "Authorization": f"Bearer {API_KEY}"
                }
                
                # Send request to STT API
                # For OpenAI-compatible APIs, we need to send the file as multipart/form-data
                log_message(f"Starting transcription API request to {API_URL}")
                log_message(f"Audio file size to upload: {audio_file_size / (1024*1024):.1f}MB ({audio_file_size} bytes)")
                api_start = time.time()
                
                async with httpx.AsyncClient() as session:
                    # Open the audio file and send it
                    with open(audio_file_path, "rb") as audio_file:
                        audio_content = audio_file.read()
                        log_message(f"Read {len(audio_content)} bytes from audio file, starting POST request")
                        files = {
                            "file": (f"audio{os.path.splitext(audio_file_path)[1]}", audio_content),
                            "model": MODEL,
                        }
                        
                        # Add response_format if supported (text is default)
                        data = {
                            "response_format": "text",
                        }
                        
                        response = await session.post(API_URL, files=files, data=data, headers=headers, timeout=600.0)
                        log_message(f"API response received: status={response.status_code}")
                        response.raise_for_status()
                        transcription = response.text
                        log_message(f"Transcription received: {len(transcription)} characters")
                
                api_time = time.time() - api_start
                log_message(f"API transcription completed in {api_time:.1f}s")
                
                # Clean up the transcription (remove leading/trailing whitespace)
                transcription = transcription.strip()
                
                if not transcription:
                    log_message("Transcription returned empty result")
                    return "❌ Error: Transcription returned empty result"
                
                total_time = time.time() - start_time
                file_type_desc = "video" if is_video else "audio"
                log_message(f"SUCCESS - Total time: {total_time:.1f}s")
                timing_info = f" (Total: {total_time:.1f}s)"
                return f"✅ Audio Transcription for {file_type_desc} file ID {file_id} (from {client_name}){timing_info}:\n\n{transcription}"
            
            finally:
                # Clean up extracted audio file if it's different from source
                if audio_file_path and audio_file_path != source_file_path and not temp_source:
                    try:
                        if os.path.exists(audio_file_path):
                            os.remove(audio_file_path)
                    except Exception as e:
                        pass
        else:
            # Fallback to get_file method if path not available
            log_message("Using fallback get_file method (file path not available)")
            file_data = client_obj.get_file(file_id=file_id)
            file_bytes = file_data.content
            log_message(f"Downloaded file from Hydrus: {len(file_bytes) / (1024*1024):.1f}MB")
            
            # Detect file type from content using helper function
            file_type_info = detect_file_type_from_bytes(file_bytes)
            is_video = file_type_info['is_video']
            file_extension = file_type_info['file_extension']
            
            # Save file to temporary location
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                temp_file.write(file_bytes)
                source_file_path = temp_file.name
            
            source_file_size = len(file_bytes)
            audio_file_path = None
            log_message(f"Saved to temp file: {source_file_path}")
            
            try:
                # If it's a video file, extract audio track using ffmpeg
                if is_video:
                    log_message(f"Starting audio extraction from video ({source_file_size / (1024*1024):.1f}MB)")
                    extract_start = time.time()
                    
                    # Set ffmpeg codec and output extension based on AUDIO_FORMAT
                    if AUDIO_FORMAT == "mp3":
                        audio_codec = "libmp3lame"
                        audio_suffix = ".mp3"
                        audio_bitrate = "64k"  # 64kbps is sufficient for speech recognition
                    elif AUDIO_FORMAT == "flac":
                        audio_codec = "flac"
                        audio_suffix = ".flac"
                        audio_bitrate = None
                    else:
                        audio_codec = "pcm_s16le"
                        audio_suffix = ".wav"
                        audio_bitrate = None
                    
                    audio_file_path = tempfile.mktemp(suffix=audio_suffix)
                    log_message(f"Audio output path: {audio_file_path}")
                    
                    try:
                        # Use ffmpeg to extract audio track
                        ffmpeg_cmd = [
                            "ffmpeg", "-i", source_file_path,
                            "-vn",  # No video
                            "-acodec", audio_codec,  # MP3, WAV or FLAC codec
                            "-ar", "16000",  # 16kHz sample rate (good for STT)
                            "-ac", "1",  # Mono audio
                            "-loglevel", "quiet",  # Suppress output to prevent hanging
                            "-y", audio_file_path
                        ]
                        if audio_bitrate:
                            ffmpeg_cmd.insert(ffmpeg_cmd.index("-y"), "-b:a")
                            ffmpeg_cmd.insert(ffmpeg_cmd.index("-y"), audio_bitrate)
                        
                        log_message(f"Running ffmpeg: {' '.join(ffmpeg_cmd)}")
                        
                        result = subprocess.run(
                            ffmpeg_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=600  # Increased timeout for large files
                        )
                        
                        extract_time = time.time() - extract_start
                        log_message(f"Audio extraction completed in {extract_time:.1f}s")
                        
                        if result.returncode != 0:
                            # Get stderr from result (now captured as bytes)
                            stderr_text = result.stderr.decode('utf-8', errors='replace') if result.stderr else "Unknown error"
                            log_message(f"FFmpeg error (returncode {result.returncode}): {stderr_text[:500]}")
                            return f"❌ Error: Failed to extract audio from video - {stderr_text[:200]}"
                        
                        if not os.path.exists(audio_file_path):
                            log_message("Audio extraction completed but output file was not created")
                            return "❌ Error: Audio extraction completed but output file was not created"
                        
                        audio_file_size = os.path.getsize(audio_file_path)
                        log_message(f"Extracted audio size: {audio_file_size / (1024*1024):.1f}MB ({audio_file_size} bytes)")
                        
                    except subprocess.TimeoutExpired:
                        log_message("Audio extraction timed out")
                        return "❌ Error: Audio extraction timed out (file may be too large)"
                    except FileNotFoundError:
                        log_message("ffmpeg not found")
                        return "❌ Error: ffmpeg is not installed. Please install ffmpeg to transcribe video files."
                    
                else:
                    # For audio files, use the source file directly
                    audio_file_path = source_file_path
                    audio_file_size = source_file_size
                    log_message(f"Using audio file directly: {audio_file_path} ({audio_file_size / (1024*1024):.1f}MB)")
                
                # Prepare the API request
                headers = {
                    "Authorization": f"Bearer {API_KEY}"
                }
                
                # Send request to STT API
                # For OpenAI-compatible APIs, we need to send the file as multipart/form-data
                log_message(f"Starting transcription API request to {API_URL}")
                log_message(f"Audio file size to upload: {audio_file_size / (1024*1024):.1f}MB ({audio_file_size} bytes)")
                api_start = time.time()
                
                async with httpx.AsyncClient() as session:
                    # Open the audio file and send it
                    with open(audio_file_path, "rb") as audio_file:
                        audio_content = audio_file.read()
                        log_message(f"Read {len(audio_content)} bytes from audio file, starting POST request")
                        files = {
                            "file": (f"audio{os.path.splitext(audio_file_path)[1]}", audio_content),
                            "model": MODEL,
                        }
                        
                        # Add response_format if supported (text is default)
                        data = {
                            "response_format": "text",
                        }
                        
                        response = await session.post(API_URL, files=files, data=data, headers=headers, timeout=600.0)
                        log_message(f"API response received: status={response.status_code}")
                        response.raise_for_status()
                        transcription = response.text
                        log_message(f"Transcription received: {len(transcription)} characters")
                
                api_time = time.time() - api_start
                log_message(f"API transcription completed in {api_time:.1f}s")
                
                # Clean up the transcription (remove leading/trailing whitespace)
                transcription = transcription.strip()
                
                if not transcription:
                    log_message("Transcription returned empty result")
                    return "❌ Error: Transcription returned empty result"
                
                total_time = time.time() - start_time
                file_type_desc = "video" if is_video else "audio"
                log_message(f"SUCCESS - Total time: {total_time:.1f}s")
                timing_info = f" (Total: {total_time:.1f}s)"
                return f"✅ Audio Transcription for {file_type_desc} file ID {file_id} (from {client_name}){timing_info}:\n\n{transcription}"
            
            finally:
                # Clean up temporary source file
                try:
                    if os.path.exists(source_file_path):
                        os.remove(source_file_path)
                except Exception as e:
                    pass
                
                # Clean up extracted audio file if it's different from source
                if audio_file_path and audio_file_path != source_file_path:
                    if os.path.exists(audio_file_path):
                        os.remove(audio_file_path)
    except httpx.HTTPError as e:
        # Get more details about the error response
        error_details = str(e)
        log_message(f"HTTP Error occurred: {error_details}")
        try:
            resp = getattr(e, 'response', None)
            if resp is not None:
                status = getattr(resp, 'status_code', 'unknown')
                text = getattr(resp, 'text', '')[:200]
                error_details = f"Status code: {status}, Response body: {text}"
                log_message(f"HTTP Error details - Status: {status}, Body: {text}")
                
                # Special handling for 413 (Request Entity Too Large)
                if status == 413:
                    log_message("File too large error (HTTP 413)")
                    return f"❌ Error: File too large for transcription (HTTP 413). The STT API has a maximum file size limit (typically 2GB). Consider splitting the audio into smaller chunks or using a shorter video clip."
        except Exception as inner_e:
            error_details = f"Original error: {str(e)}, Failed to get details: {str(inner_e)}"
            log_message(f"Failed to get error details: {inner_e}")
        log_message(f"Returning HTTP error: {error_details}")
        return f"❌ Error: HTTP request failed - {error_details}"
    except Exception as e:
        log_message(f"Unexpected error: {type(e).__name__}: {str(e)}")
        return f"❌ Error: {str(e)}"


@mcp.tool()
async def hydrus_execute(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    action: Annotated[str, Field(description="Action to perform: 'list' to list available methods, or a method name to call (e.g., 'search_files', 'add_tags', 'get_file_metadata')")] = "list",
    kwargs: Annotated[Optional[str], Field(description="JSON string of keyword arguments for the method. Example: '{\"tags\": [\"rating:safe\"], \"file_sort_type\": 13}'. Only used when calling a method, not for 'list' action.")] = None
) -> str:
    """Execute any hydrus_api.Client method dynamically, or list available methods.
    
    This is a universal tool that allows calling ANY method available on the hydrus_api.Client object.
    
    When action='list': Returns a list of all available methods with their endpoint paths.
    When action=<method_name>: Calls that method with the provided kwargs.
    
    Args:
        client_name: Name of the Hydrus client to connect to
        action: Either 'list' to list methods, or a method name to call
        kwargs: JSON string of keyword arguments (only used when calling a method)
    
    Returns:
        For 'list': Formatted list of available methods
        For method calls: The method's return value as JSON, or an error message
    
    Examples:
        - List methods: action="list"
        - Search files: action="search_files", kwargs='{"tags": ["rating:safe"], "file_sort_type": 13}'
        - Add tags: action="add_tags", kwargs='{"file_ids": [123], "service_keys_to_tags": {"key": ["new:tag"]}}'
        - Get metadata: action="get_file_metadata", kwargs='{"file_ids": [123, 456]}'
    """
    client_obj, error = validate_client(client_name)
    if error:
        return error
    
    # Strip quotes from action (models often send quoted strings)
    action_stripped = action.strip()
    if (action_stripped.startswith('"') and action_stripped.endswith('"')) or \
       (action_stripped.startswith("'") and action_stripped.endswith("'")):
        action_stripped = action_stripped[1:-1]
    
    # Handle 'list' action - list all available methods
    if action_stripped.lower() == "list":
        try:
            # Get all public methods (not starting with _)
            methods = [m for m in dir(client_obj) if not m.startswith('_') and callable(getattr(client_obj, m))]
            
            # Get endpoint paths for reference
            paths = {m: getattr(client_obj, m) for m in dir(client_obj) if m.endswith('_PATH')}
            
            result = f"✅ Available methods for client '{client_name}':\n\n"
            result += f"Total: {len(methods)} methods\n\n"
            
            # Group methods by category
            categories = {}
            for method in sorted(methods):
                # Find associated path if exists
                path = None
                for path_name, path_value in paths.items():
                    if path_value and not path_value.startswith('/manage_'):
                        # Try to match method to path
                        if method.replace('_', '') in path_value.replace('/', '').replace('_', ''):
                            path = path_value
                            break
                
                # Categorize by first part of name
                parts = method.split('_')
                if parts[0] in ('get', 'add', 'delete', 'search', 'set', 'focus', 'archive', 'unarchive', 'undelete', 'clean', 'associate', 'lock', 'unlock', 'verify', 'request'):
                    category = parts[0]
                else:
                    category = 'other'
                
                if category not in categories:
                    categories[category] = []
                categories[category].append((method, path))
            
            for category in sorted(categories.keys()):
                result += f"[{category.upper()}]\n"
                for method, path in sorted(categories[category]):
                    path_str = f" -> {path}" if path else ""
                    result += f"  - {method}{path_str}\n"
                result += "\n"
            
            return result.strip()
        
        except Exception as e:
            return f"❌ Error listing methods: {str(e)}"
    
    # Handle method call action
    method_name = action_stripped
    
    # Get action whitelist configuration from environment variable
    # Format: comma-separated list of allowed method names (e.g., "search_files,get_file_metadata,get_api_version")
    # If not set, NO actions are allowed except 'list' (deny-by-default security model)
    action_whitelist = os.getenv("EXEC_WHITELIST", "")
    
    # Check action whitelist (only for non-list actions)
    # If whitelist is not configured, deny all actions except 'list'
    if method_name.lower() != "list":
        if not action_whitelist:
            return f"❌ Error: Method '{method_name}' is not allowed. The EXEC_WHITELIST environment variable is not configured.\n\nTo enable this method, set EXEC_WHITELIST with a comma-separated list of allowed methods (e.g., 'search_files,get_file_metadata,get_api_version')."
        
        allowed_methods = [m.strip() for m in action_whitelist.split(",") if m.strip()]
        if method_name not in allowed_methods:
            return f"❌ Error: Method '{method_name}' is not in the action whitelist. \n\nAllowed actions: {', '.join(sorted(allowed_methods))}\n\nTo add this method to the whitelist, update the EXEC_WHITELIST environment variable."
    
    # Validate method exists
    if not hasattr(client_obj, method_name):
        available = [m for m in dir(client_obj) if not m.startswith('_') and callable(getattr(client_obj, m))]
        return f"❌ Error: Method '{method_name}' not found. Use action='list' to see available methods.\n\nAvailable: {', '.join(sorted(available)[:20])}..."
    
    # Parse kwargs if provided
    method_kwargs = {}
    if kwargs:
        try:
            method_kwargs = json.loads(kwargs)
        except json.JSONDecodeError as e:
            return f"❌ Error: Invalid JSON in 'kwargs' parameter - {str(e)}"
    
    try:
        # Get and call the method
        method = getattr(client_obj, method_name)
        result = method(**method_kwargs)
        
        # Format the result
        if isinstance(result, (dict, list)):
            return f"✅ Method '{method_name}' executed successfully:\n{json.dumps(result, indent=2, default=str)}"
        elif result is None:
            return f"✅ Method '{method_name}' executed successfully (no return value)"
        else:
            return f"✅ Method '{method_name}' executed successfully: {str(result)}"
    
    except TypeError as e:
        return f"❌ Error calling '{method_name}': {str(e)}\nCheck that your kwargs match the method's expected parameters."
    except Exception as e:
        return f"❌ Error calling '{method_name}': {str(e)}"


def main():
    """Main entry point for the Hydrus MCP server"""

    # Check if clients are configured
    clients = load_clients_from_secret()
    if not clients:
        print("Warning: No Hydrus clients configured. Set HYDRUS_CLIENTS environment variable with client credentials.")

    mcp.run(transport='stdio')



if __name__ == "__main__":
    main()
