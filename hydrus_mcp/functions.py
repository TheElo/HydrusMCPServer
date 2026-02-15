import hydrus_api, hydrus_api.utils, logging, os, json
from typing import List, Dict

logger = logging.getLogger("hydrus_mcp.functions")


def load_clients_from_secret() -> List[Dict[str, str]]:
    """Load client credentials from environment variable
    
    Returns:
        List of client dictionaries with name, url, apikey, and description
    """
    clients_secret = os.environ.get("HYDRUS_CLIENTS", "[]").strip()
    
    try:
        clients = json.loads(clients_secret)
        logger.info(f"Loaded {len(clients)} Hydrus clients from environment variable")
        logger.debug(f"Raw clients data: {clients_secret}")
        
        valid_clients = []
        for client in clients:
            if len(client) >= 3:
                client_name = client[0]
                url = client[1]
                apikey = client[2]
                description = client[3] if len(client) > 3 else ""
                
                valid_clients.append({
                    "name": client_name,
                    "url": url,
                    "apikey": apikey,
                    "description": description
                })
        
        return valid_clients
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Failed to parse HYDRUS_CLIENTS: {e}")
        logger.debug(f"Raw clients data that failed to parse: {repr(clients_secret)}")
        return []


def get_client_by_name(client_name: str) -> hydrus_api.Client | None:
    """Get a Hydrus client by name (returns client object)
    
    Args:
        client_name: The name of the client to find
        
    Returns:
        hydrus_api.Client instance or None if not found
    """
    clients = load_clients_from_secret()
    for client in clients:
        if client["name"].lower() == client_name.lower():
            try:
                return hydrus_api.Client(access_key=client["apikey"], api_url=client["url"])
            except Exception as e:
                logger.error(f"Failed to create client {client_name}: {e}")
                return None
    return None

def get_page_info(client_obj, page_key):
    """Get page information for a specific tab using its page key"""
    try:
        return client_obj.get_page_info(page_key=page_key)
    except Exception as e:
        logger.error(f"Failed to get page info for page_key {page_key}: {e}")
        return None

def get_service_key_by_name(client, service_name):
    """Get the service key for a given service name"""
    try:
        services_dict = client.get_services()
        for key, service_info in services_dict['services'].items():
            if service_info['name'] == service_name:
                return key
        return None
    except Exception as e:
        return None
    
def get_tags(client_obj, file_ids, tag_service="all known tags"):
    tag_service_key = get_service_key_by_name(client_obj, tag_service)

    # Process in batches of 3
    batch_size = 3
    MyDict = []

    for i in range(0, len(file_ids), batch_size):
        # Get current batch of file IDs (up to batch_size)
        batch_file_ids = file_ids[i:i + batch_size]

        try:
            # Get metadata for this batch
            a = client_obj.get_file_metadata(file_ids=batch_file_ids)

            # Process each item in the batch
            for y in range(0, len(a)):
                try:
                    metadata = a.get("metadata")
                    tags = metadata[y]["tags"][f"{tag_service_key}"]["storage_tags"]["0"]
                except Exception as e:
                    tags = [f"Error processing file: {str(e)}"]

                MyDict.append([batch_file_ids[y], tags])
        except Exception as e:
            logger.error(f"Failed to get metadata for batch starting with {batch_file_ids[0]}: {e}")
            # Add error information to results
            for file_id in batch_file_ids:
                if not any(existing[0] == file_id for existing in MyDict):
                    MyDict.append([file_id, [f"Error processing file: {str(e)}"]])

    return MyDict



def get_tags_summary(client_obj, file_ids, tag_service=None, result_limit=None):
    if tag_service:
        tag_service_key = get_service_key_by_name(client_obj, tag_service)
    else:
        tag_service_key = get_service_key_by_name(client_obj, "all known tags")

    # Process in batches of 3
    batch_size = 3
    tag_counts = {}

    for i in range(0, len(file_ids), batch_size):
        # Get current batch of file IDs (up to batch_size)
        batch_file_ids = file_ids[i:i + batch_size]

        try:
            # Get metadata for this batch
            a = client_obj.get_file_metadata(file_ids=batch_file_ids)

            # Process each item in the batch
            for y in range(0, len(a)):
                try:
                    metadata = a.get("metadata")
                    tags = metadata[y]["tags"][f"{tag_service_key}"]["storage_tags"]["0"]
                except Exception as e:
                    tags = [f"Error processing file: {str(e)}"]

                if tags:
                    for tag in tags:
                        if tag in tag_counts:
                            tag_counts[tag] += 1
                        else:
                            tag_counts[tag] = 1
        except Exception as e:
            logger.error(f"Failed to get metadata for batch starting with {batch_file_ids[0]}: {e}")
            # Add error information to counts
            for file_id in batch_file_ids:
                if not any(existing[0] == file_id for existing in tag_counts):
                    tag_counts[f"Error processing file {file_id}"] = 1

    # Convert to list of [tag, count] pairs sorted by count (highest to lowest)
    result = [[tag, count] for tag, count in tag_counts.items()]
    result.sort(key=lambda x: x[1], reverse=True)  # Sort by count descending

    # Apply result_limit if provided and valid
    if result_limit is not None:
        try:
            result_limit_int = int(result_limit)
            if result_limit_int > 0 and len(result) > result_limit_int:
                return result[:result_limit_int]
        except (ValueError, TypeError):
            pass

    return result

def parse_hydrus_tags(query, additional_tags=None):
            """Parse Hydrus query string into proper tag structure

            Args:
                query: The query string to parse
                additional_tags: Optional list of tags to append to the result
            """
            if isinstance(query, list):
                # Handle list inputs directly - convert to consistent string format
                result = []
                for item in query:
                    if isinstance(item, str):
                        # For strings, parse normally but preserve complex tags and strip quotes
                        parsed = parse_hydrus_tags(item)
                        if isinstance(parsed, list):
                            processed_tags = []
                            for tag in parsed:
                                if isinstance(tag, str):
                                    # Check if this is a quoted string and strip the quotes
                                    stripped_tag = tag
                                    if (tag.startswith('"') and tag.endswith('"')) or \
                                       (tag.startswith("'") and tag.endswith("'")):
                                        stripped_tag = tag[1:-1]
                                    processed_tags.append(stripped_tag)
                                else:
                                    processed_tags.append(tag)
                            result.extend(processed_tags if processed_tags else parsed)
                        else:
                            result.extend(parsed)
                    elif isinstance(item, list):
                        # For nested lists, recurse and convert to string format
                        parsed = parse_hydrus_tags(item)
                        if isinstance(parsed, list) and len(parsed) == 1:
                            result.append(parsed[0])
                        else:
                            result.append(parsed)

                # Append additional tags if provided
                if additional_tags:
                    if not isinstance(additional_tags, list):
                        additional_tags = [additional_tags]
                    result.extend(additional_tags)

                return result
            elif not query or query == "[]":
                result = []
                if additional_tags:
                    if not isinstance(additional_tags, list):
                        additional_tags = [additional_tags]
                    result.extend(additional_tags)
                return result

            if isinstance(query, str):
                # First, check for OR groups marked by brackets
                has_or_groups = '[' in query and ']' in query

                if has_or_groups:
                    # Handle OR groups: [tag1, tag2] means OR condition
                    tags = []
                    current_tag = ''
                    or_group = False
                    or_tags = []

                    for char in query:
                        if char == '[' and not or_group:
                            or_group = True
                            or_tags = []
                        elif char == ']' and or_group:
                            or_group = False
                            # Parse the contents of the OR group properly
                            parsed_or_tags = parse_hydrus_tags(current_tag)
                            tags.append(parsed_or_tags)
                            current_tag = ''
                        elif char == ',' and not or_group:
                            if current_tag.strip():
                                # Strip quotes from main tags (outside OR groups)
                                stripped_tag = current_tag.strip()
                                if (stripped_tag.startswith('"') and stripped_tag.endswith('"')) or \
                                   (stripped_tag.startswith("'") and stripped_tag.endswith("'")):
                                    stripped_tag = stripped_tag[1:-1]
                                tags.append(stripped_tag)
                                current_tag = ''
                        else:
                            current_tag += char

                    if current_tag.strip():
                        # Handle any remaining text after the last bracket
                        if or_group:
                            parsed_or_tags = parse_hydrus_tags(current_tag)
                            tags.append(parsed_or_tags)
                        else:
                            # Strip quotes from main tags (outside OR groups)
                            stripped_tag = current_tag.strip()
                            if (stripped_tag.startswith('"') and stripped_tag.endswith('"')) or \
                               (stripped_tag.startswith("'") and stripped_tag.endswith("'")):
                                stripped_tag = stripped_tag[1:-1]
                            tags.append(stripped_tag)

                    # Append additional tags if provided
                    if additional_tags:
                        if not isinstance(additional_tags, list):
                            additional_tags = [additional_tags]
                        tags.extend(additional_tags)

                    return tags
                else:
                    # No OR groups, just split by commas (preserving complex tags)
                    def split_preserving_complex_tags(text):
                        """Split text by commas while preserving complex tags"""
                        if not text:
                            return []

                        result = []
                        current_part = ''
                        in_quotes = False
                        quote_char = None

                        for char in text:
                            if (char == '"' or char == "'") and (not in_quotes):
                                # Start of quoted section - preserve the quotes for now
                                in_quotes = True
                                quote_char = char
                                current_part = char
                            elif in_quotes and quote_char is not None:
                                if char == quote_char:
                                    # End of quoted section - keep the quotes in the result
                                    in_quotes = False
                                    current_part += char
                                    result.append(current_part)
                                    current_part = ''
                                elif char == ',':
                                    # Don't split on commas inside quotes
                                    current_part += char
                                else:
                                    current_part += char
                            elif char == ',' and not in_quotes:
                                if current_part.strip():
                                    result.append(current_part.strip())
                                    current_part = ''
                            else:
                                current_part += char

                        if current_part.strip():
                            result.append(current_part.strip())

                        return result

                    # Split the query into parts, preserving complex tags
                    parts = split_preserving_complex_tags(query)
                    result = []

                    for part in parts:
                        stripped = part.strip()
                        if stripped:  # Only add non-empty parts
                            # Strip quotes from tags to ensure consistent format
                            if (stripped.startswith('"') and stripped.endswith('"')) or \
                               (stripped.startswith("'") and stripped.endswith("'")):
                                inner_content = stripped[1:-1]
                                result.append(inner_content)
                            else:
                                result.append(stripped)

                    # Append additional tags if provided
                    if additional_tags:
                        if not isinstance(additional_tags, list):
                            additional_tags = [additional_tags]
                        result.extend(additional_tags)

                    return result
            else:
                result = []
                if additional_tags:
                    if not isinstance(additional_tags, list):
                        additional_tags = [additional_tags]
                    result.extend(additional_tags)
                return result


def find_page_by_name(pages_list: list, tab_name: str) -> dict | None:
    """Recursively search for a page by name (case-insensitive)
    
    Args:
        pages_list: List of page dictionaries from get_pages() response
        tab_name: Name of the tab to find
        
    Returns:
        Page dictionary if found, None otherwise
    """
    for page_info in pages_list:
        if not isinstance(page_info, dict):
            logger.error(f"Unexpected page_info format: {type(page_info).__name__}")
            continue
        
        name = page_info.get('name', '')
        title = page_info.get('title', '')
        
        if (tab_name.lower() == name.lower()) or (tab_name.lower() == title.lower()):
            return page_info
        
        if 'pages' in page_info:
            nested_page = find_page_by_name(page_info['pages'], tab_name)
            if nested_page:
                return nested_page
    
    return None


def extract_tabs_from_pages(pages_list: list, return_keys: bool = False) -> tuple[list, list]:
    """Extract tab names and optionally keys from pages
    
    Args:
        pages_list: List of page dictionaries
        return_keys: Whether to extract page keys
        
    Returns:
        Tuple of (tab_names, tab_keys)
    """
    tabs = []
    tab_keys = []
    
    for page_info in pages_list:
        if not isinstance(page_info, dict):
            logger.error(f"Unexpected page_info format: {type(page_info).__name__}")
            continue
        
        name = page_info.get('name', page_info.get('title', f"Page {page_info.get('id', 'unknown')}"))
        tabs.append(name)
        
        if return_keys:
            page_key = page_info.get('page_key')
            if page_key:
                tab_keys.append(page_key)
            else:
                logger.warning(f"No page_key found for tab: {name}")
        
        if 'pages' in page_info:
            nested_tabs, nested_keys = extract_tabs_from_pages(page_info['pages'], return_keys)
            tabs.extend(nested_tabs)
            tab_keys.extend(nested_keys)
    
    return tabs, tab_keys
