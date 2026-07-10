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


def setup_cors(app, mount_path: str):
    """Setup CORS middleware and OPTIONS handler for MCP app.
    
    Args:
        app: Starlette app to add middleware/routes to
        mount_path: The mount path for the MCP server
    """
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    # CORS for browser-based MCP clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*", "MCP-Session-Id", "MCP-Protocol-Version"],
        expose_headers=["MCP-Session-Id", "MCP-Protocol-Version"],
    )

    # Handle CORS preflight requests
    async def options_handler(request: Request) -> Response:
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*"),
                "Access-Control-Max-Age": "86400",
            },
        )

    app.add_route(mount_path, options_handler, methods=["OPTIONS"])
    return options_handler

# Import utility functions from the local module
from .functions import (
    detect_file_type_from_bytes, detect_file_type_from_path, extract_frames_from_video,
    extract_tabs_from_pages, calculate_frame_indices, calculate_grid_dimensions,
    scale_image_if_needed, create_frame_grid, get_page_list, validate_client,
    parse_file_ids, safe_bool_convert, safe_int_convert, get_file_path,
    find_page_by_name, get_page_info, get_service_key_by_name, load_clients_from_secret,
    get_client_by_name, parse_hydrus_tags, get_tags_summary, get_tags, get_viewing_stat,
    format_timestamp, extract_tags_by_service, format_single_metadata,
    get_audio_codec_config, build_ffmpeg_cmd, extract_audio_from_video,
    send_to_stt_api, format_transcription_result
)

# Initialize MCP server - NO PROMPT PARAMETER!
mcp = FastMCP("hydrus")

# Import and register tab tools from modular implementation
from .tools.tab_tools import (
    hydrus_get_page_info,
    hydrus_list_tabs,
    hydrus_focus_on_tab,
    hydrus_send_to_tab,
)

# Import and register sense tools from modular implementation
from .tools.sense_tools import (
    hydrus_show_files,
    hydrus_inspect_files,
    hydrus_transcribe_audio,
)

# Register tab tools with MCP server
mcp.tool()(hydrus_get_page_info)
mcp.tool()(hydrus_list_tabs)
mcp.tool()(hydrus_focus_on_tab)
mcp.tool()(hydrus_send_to_tab)

# Register sense tools with MCP server
mcp.tool()(hydrus_show_files)
mcp.tool()(hydrus_inspect_files)
mcp.tool()(hydrus_transcribe_audio)

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
        tags_list = results.get('tags', [])
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
    file_sort_type: Annotated[Any, Field(description="Sorting method for files. Default is '13' (sorted by 'has audio' as this is the fastest search). Available options: 0=FILE_SIZE, 1=DURATION, 2=IMPORT_TIME, 3=FILE_TYPE, 4=RANDOM, 5=WIDTH, 6=HEIGHT, 7=RATIO, 8=NUMBER_OF_PIXELS, 9=NUMBER_OF_TAGS, 10=NUMBER_OF_MEDIA_VIEWS, 11=TOTAL_MEDIA_VIEWTIME, 12=APPROXIMATE_BITRATE, 13=HAS_AUDIO, 14=MODIFIED_TIME, 15=FRAMERATE, 16=NUMBER_OF_FRAMES, 18=LAST_VIEWED_TIME, 19=ARCHIVE_TIMESTAMP, 20=HASH_HEX, 21=PIXEL_HASH_HEX, 22=BLURHASH.")] = "13",
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
                search_params["tag_service_key"] = [service_key]

        # Execute the search
        file_ids = client_obj.search_files(**search_params)

        try:
            file_ids = file_ids["file_ids"]
        except (KeyError, TypeError):
            return json.dumps(file_ids)

        try:
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


def _coverage_note(tag_service, diag):
    """Render get_tags_summary diagnostics as text — only when something didn't fully account,
    so a clean run stays quiet. Surfaces WHICH files came back without tags and what their
    metadata actually contained, instead of silently dropping them from the denominator."""
    if not diag.get("no_metadata") and not diag.get("empty_tags"):
        return ""
    parts = [f"COVERAGE: counted {diag['counted']} of {diag['matched']} files"]
    if diag.get("no_metadata"):
        parts.append(f"{diag['no_metadata']} returned no metadata at all")
    if diag.get("empty_tags"):
        parts.append(f"{diag['empty_tags']} had no tags via '{tag_service}' "
                     f"(expected service key {diag['expected_service_key']}); "
                     f"sample {diag['empty_sample']}")
    return " " + "; ".join(parts) + "."


@mcp.tool()
async def hydrus_get_tags(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    content: Annotated[Any, Field(description="Content to process - query string, comma-separated file IDs, or page key")] = "",
    content_type: Annotated[str, Field(description="Type of content - 'file_ids', 'query', or 'page_key' (default: 'query')")] = "query",
    tag_service: Annotated[str, Field(description="Tag service name (default: 'all known tags')")] = "all known tags",
    trs: Annotated[Any, Field(description="Threshold for summary view. If the threshold is lower than the received file ids (either directly or from query) then the summary view is used which only returns tags and their counts from the results instead (default: '100')")] = "50",
    limit: Annotated[Any, Field(description="Caps the SAMPLE of files the tag distribution is computed over (default 1000). The TRUE total match count is always reported separately. Set to 0 for the full match set (accurate but slower on large queries).")] = "1000",
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

                # Search WITHOUT a baked-in `system:limit` so result_count is the TRUE match
                # total. `limit` now caps only the SAMPLE the tag distribution is computed over
                # (the true total is always reported); limit<=0 computes over the full match set.
                tags = parse_hydrus_tags(content)

                tag_service_key = str(get_service_key_by_name(client_obj, tag_service))

                search_params = {
                    "tags": tags,
                    "file_sort_type": 13,
                    "tag_service_key": [tag_service_key]
                }

                # Execute the search
                file_ids_response = client_obj.search_files(**search_params)
                file_ids = file_ids_response['file_ids']
                result_count = len(file_ids)   # TRUE total match count

                if result_count == 0:
                    return f"❌ No files found for query '{content}' (count: 0)"

                limit_int = safe_int_convert(limit, 1000)
                sample_ids = file_ids if limit_int <= 0 else file_ids[:limit_int]

                # Check threshold for summary view
                if trs_int < result_count:
                    result_limit_int = safe_int_convert(result_limit, 150)
                    summary_result, diag = get_tags_summary(
                        client_obj, file_ids=sample_ids, tag_service=tag_service)
                    total_distinct = len(summary_result)
                    if result_limit_int > 0 and total_distinct > result_limit_int:
                        summary_result = summary_result[:result_limit_int]
                    sampled = len(sample_ids)
                    sample_note = ("" if sampled >= result_count else
                                   f" The distribution below is a SAMPLE over the first {sampled} of "
                                   f"{result_count} matching files — raise `limit` or set it to 0 for "
                                   f"the full set.")
                    cover_note = _coverage_note(tag_service, diag)
                    result = (f"Query '{content}' matched {result_count} files total, above the trs "
                              f"threshold {trs}, so here is a tag-count summary (showing the top "
                              f"{len(summary_result)} of {total_distinct} distinct tags by count)."
                              f"{sample_note}{cover_note} ")
                    return result + str(summary_result)
                # under threshold → fall through to the per-file path with the sampled ids
                file_ids = sample_ids

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
            result_limit_int = safe_int_convert(result_limit, 150)
            summary_result, diag = get_tags_summary(
                client_obj, file_ids=file_ids, tag_service=tag_service)
            total_distinct = len(summary_result)
            if result_limit_int > 0 and total_distinct > result_limit_int:
                summary_result = summary_result[:result_limit_int]
            cover_note = _coverage_note(tag_service, diag)
            result = (f"The {len(file_ids)} given file ids are above the trs threshold {trs}, so "
                      f"here is a tag-count summary (showing the top {len(summary_result)} of "
                      f"{total_distinct} distinct tags by count).{cover_note} ")
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
    file_id: Annotated[Optional[Any], Field(description="File ID or comma-separated list of file IDs to get metadata for (e.g., 123 or '123,456,789'). Can be provided as a number (123) or string ('123'). Mutually exclusive with 'hashes'.")] = None,
    hashes: Annotated[Optional[str], Field(description="Single hash or comma-separated list of file hashes (SHA256) to get metadata for. Mutually exclusive with 'file_id'. Example: 'abc123...' or 'abc123...,def456...'")] = None,
    filter: Annotated[Optional[str], Field(description="Optional filter to return only specific fields. Comma-separated list: 'file_id', 'hash', 'size', 'mime', 'dimensions', 'duration', 'views', 'viewtime', 'last_viewed', 'time_modified', 'tags'. For tags, use 'tags(service1,service2)' to filter by specific tag services. Leave empty for full metadata.")] = None
) -> str:
    """Get metadata for one or more files by their IDs or hashes from a specific client.

    Warning: This function returns a lot of data and therefore should be only used when something has not enough tags or a deep inspection of the metadata is necessary.
    Use the filter parameter to reduce output size (e.g., 'hash' for just hashes, or 'hash,size,duration' for multiple fields).
    
    You can use either 'file_id' or 'hashes' parameter, but not both.
    """
    # Internal configuration: which tag type to use for tags filter
    TAG_TYPE_FOR_FILTER = "display_tags"  # Options: "display_tags" or "storage_tags"
    
    client_obj, error = validate_client(client_name)
    if error:
        return error
    
    # Check that exactly one of file_id or hashes is provided
    has_file_id = file_id is not None and file_id != 0 and (not isinstance(file_id, str) or file_id.strip())
    has_hashes = hashes is not None and hashes.strip()
    
    if not has_file_id and not has_hashes:
        return "❌ Error: Either 'file_id' or 'hashes' parameter is required"
    if has_file_id and has_hashes:
        return "❌ Error: Cannot use both 'file_id' and 'hashes' parameters. Please use only one."

    try:
        # Parse filter keys early to determine if we can use only_return_identifiers optimization
        filter_keys = []
        tags_services = None
        valid_keys = {'file_id', 'hash', 'size', 'mime', 'dimensions', 'duration', 'views', 'viewtime', 'last_viewed', 'time_modified', 'tags'}
        
        if filter:
            # Parse comma-separated filter keys
            raw_filter_keys = [k.strip() for k in filter.split(',')]
            for fk in raw_filter_keys:
                if fk.startswith('tags(') and fk.endswith(')'):
                    # Extract service names from tags(service1,service2)
                    services_part = fk[5:-1]  # Remove 'tags(' and ')'
                    tags_services = services_part
                else:
                    filter_keys.append(fk)
            
            filter_keys = [k for k in filter_keys if k in valid_keys or k == 'tags']
            if tags_services:
                filter_keys.append('tags')
        
        # Determine which optimization to use for get_file_metadata
        # Priority: only_return_identifiers > only_return_basic_information > no optimization
        # only_return_identifiers: best for file_id and/or hash only
        # only_return_basic_information: good for file_id, hash, size, mime, dimensions, duration, has_audio
        use_only_return_identifiers = False
        use_only_return_basic_information = False

        if filter:
            # Check for only_return_identifiers optimization (highest priority)
            # Valid when filter contains only 'file_id' and/or 'hash'
            if set(filter_keys).issubset({'file_id', 'hash'}):
                use_only_return_identifiers = True
            # Check for only_return_basic_information optimization
            # Valid when filter contains only basic file info fields
            elif set(filter_keys).issubset({'file_id', 'hash', 'size', 'mime', 'dimensions', 'duration'}):
                use_only_return_basic_information = True

        # Determine what to pass to get_file_metadata
        if has_hashes:
            # Parse hashes - split by comma and strip whitespace
            hash_list = [h.strip() for h in hashes.split(',') if h.strip()]
            if not hash_list:
                return "❌ Error: No valid hashes provided"
            # Pass hashes directly to get_file_metadata (Hydrus API accepts hashes)
            if use_only_return_identifiers:
                metadata = client_obj.get_file_metadata(hashes=hash_list, only_return_identifiers=True)
            elif use_only_return_basic_information:
                metadata = client_obj.get_file_metadata(hashes=hash_list, only_return_basic_information=True)
            else:
                metadata = client_obj.get_file_metadata(hashes=hash_list)
            # For display purposes, use the hashes as identifiers
            identifiers = hash_list
            identifier_type = "hash"
        else:
            # Parse file IDs using parse_file_ids function (handles single IDs, strings, lists, etc.)
            file_ids_list = parse_file_ids(file_id)
            if not file_ids_list:
                return "❌ Error: No valid file IDs provided"
            # Pass file IDs to get_file_metadata
            if use_only_return_identifiers:
                metadata = client_obj.get_file_metadata(file_ids=file_ids_list, only_return_identifiers=True)
            elif use_only_return_basic_information:
                metadata = client_obj.get_file_metadata(file_ids=file_ids_list, only_return_basic_information=True)
            else:
                metadata = client_obj.get_file_metadata(file_ids=file_ids_list)
            identifiers = file_ids_list
            identifier_type = "ID"

        # Handle filter parameter
        if filter:
            if not filter_keys:
                return f"❌ Error: No valid filter keys provided. Valid options: {', '.join(valid_keys)}"
            
            # OPTIMIZATION: When filtering only for file_id or hash, return compact comma-separated list
            if set(filter_keys) == {'file_id'} or set(filter_keys) == {'hash'}:
                # Extract just the requested values and return as comma-separated list
                if isinstance(metadata, dict) and 'metadata' in metadata:
                    file_metadata_list = metadata['metadata']
                    values = []
                    for file_metadata in file_metadata_list:
                        if isinstance(file_metadata, dict):
                            if 'file_id' in filter_keys:
                                values.append(str(file_metadata.get('file_id', '')))
                            elif 'hash' in filter_keys and 'hash' in file_metadata:
                                values.append(file_metadata['hash'])
                    return ','.join(values)
                elif isinstance(metadata, list):
                    values = []
                    for file_metadata in metadata:
                        if isinstance(file_metadata, dict):
                            if 'file_id' in filter_keys:
                                values.append(str(file_metadata.get('file_id', '')))
                            elif 'hash' in filter_keys and 'hash' in file_metadata:
                                values.append(file_metadata['hash'])
                    return ','.join(values)
            
            result = f"✅ File Metadata (filtered: {', '.join(filter_keys)}) for {len(identifiers)} file(s):\n"
            
            # Extract metadata list from response (handles both dict with 'metadata' key and direct list)
            file_metadata_list = metadata.get('metadata', []) if isinstance(metadata, dict) else (metadata if isinstance(metadata, list) else [])
            
            for idx, file_metadata in enumerate(file_metadata_list):
                if isinstance(file_metadata, dict) and idx < len(identifiers):
                    result += format_single_metadata(
                        file_metadata, identifiers[idx], identifier_type, filter_keys, tags_services, TAG_TYPE_FOR_FILTER
                    )
            if not file_metadata_list:
                result += "filter requires metadata list in response"
            return result.strip()

        # Full metadata output (default behavior)
        result = f"✅ File Metadata for {len(identifiers)} file(s) (from {client_name}):"
        
        if isinstance(metadata, list):
            # Multiple files returned
            for idx, file_metadata in enumerate(metadata):
                identifier = identifiers[idx]
                result += f"\n\n{'='*60}"
                result += f"\nFile {identifier_type} {identifier}:"
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
            identifier = identifiers[0] if len(identifiers) == 1 else identifiers
            result += f"\n\nFile {identifier_type}(s) {identifier}:"
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
async def hydrus_send(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    link: Annotated[str, Field(description="Direct link to file or base link for scraping")] = "",
    service_names_to_additional_tags: Annotated[Optional[str], Field(description="Optional JSON string mapping service names to tag lists, e.g., '{\"local\": [\"tag1\", \"tag2\"]}'")] = None,
    subdir: Annotated[Any, Field(description="If True, recursively scrape subdirectories from base link (default: False)")] = False,
    max_depth: Annotated[Any, Field(description="Maximum depth for recursive scraping (default: 2)")] = 2,
    filename: Annotated[Any, Field(description="If True, extract filename and add as 'filename:' tag (default: True)")] = True,
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

    # Convert boolean parameters using safe conversion to handle various input formats
    subdir = safe_bool_convert(subdir, False)
    filename = safe_bool_convert(filename, True)

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


@mcp.tool()    
async def hydrus_execute(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    action: Annotated[str, Field(description="Action to perform: 'list' to list available methods, or a method name to call (e.g., 'search_files', 'add_tags', 'get_file_metadata')")] = "list",
    kwargs: Annotated[Optional[str | dict], Field(description="JSON string or object of keyword arguments for the method. Example: '{\"tags\": [\"rating:safe\"], \"file_sort_type\": 13}'. Only used when calling a method, not for 'list' action.")] = None
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
            # Handle both string (JSON) and dict (already parsed by framework)
            if isinstance(kwargs, str):
                method_kwargs = json.loads(kwargs)
            elif isinstance(kwargs, dict):
                method_kwargs = kwargs
            else:
                return f"❌ Error: 'kwargs' must be a JSON string or object, got {type(kwargs).__name__}"
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

    # Get transport configuration from environment variables
    # Default to 'stdio' for backward compatibility
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8000"))
    mount_path = os.getenv("MCP_MOUNT_PATH", "/mcp")

    # Normalize mount_path (must start with '/', no trailing '/' except root)
    if not mount_path.startswith("/"):
        mount_path = "/" + mount_path
    if mount_path != "/" and mount_path.endswith("/"):
        mount_path = mount_path.rstrip("/")

    # Disable DNS rebinding protection for web UI transport modes
    if transport in ("streamable-http", "sse"):
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    if transport == "streamable-http":
        print(f"Starting MCP server with streamable-http transport on {host}:{port} with mount path {mount_path}")
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.settings.streamable_http_path = mount_path
        mcp.settings.mount_path = mount_path

        app = mcp.streamable_http_app()
        options_handler = setup_cors(app, mount_path)
        message_path = mount_path + "/message" if mount_path != "/" else "/message"
        app.add_route(message_path, options_handler, methods=["OPTIONS"])

        import uvicorn
        uvicorn.run(app, host=host, port=port)

    elif transport == "sse":
        print(f"Starting MCP server with SSE transport on {host}:{port} with mount path {mount_path}")
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.settings.mount_path = mount_path
        mcp.settings.sse_path = mount_path

        app = mcp.sse_app(mount_path)
        options_handler = setup_cors(app, mount_path)
        message_path = mount_path + mcp.settings.message_path
        app.add_route(message_path, options_handler, methods=["OPTIONS"])

        import uvicorn
        uvicorn.run(app, host=host, port=port)

    else:
        print("Starting MCP server with stdio transport")
        mcp.run(transport='stdio')


if __name__ == "__main__":
    main()
