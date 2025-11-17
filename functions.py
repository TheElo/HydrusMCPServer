import hydrus_api, hydrus_api.utils, logging, os, json

logger = logging.getLogger("functions")

def load_clients_from_secret():
    """Load client credentials from environment variable or Docker secrets"""
    # Try to read from the Docker secret file if it exists
    secret_file = "/run/secrets/HYDRUS_CLIENTS"
    if os.path.exists(secret_file):
        try:
            with open(secret_file, 'r') as f:
                clients_secret = f.read().strip()
            logger.info("Loaded HYDRUS_CLIENTS from Docker secret file")
        except Exception as e:
            logger.error(f"Failed to read HYDRUS_CLIENTS secret file: {e}")
            return []
    else:
        logger.debug(f"Secret file not found at {secret_file}, checking environment variable")
        # Fallback to environment variable
        clients_secret = os.environ.get("HYDRUS_CLIENTS", "[]").strip()

    try:
        # Parse the JSON string to get client list
        clients = json.loads(clients_secret)
        logger.info(f"Loaded {len(clients)} Hydrus clients from secrets")
        logger.debug(f"Raw clients data: {clients_secret}")

        # Validate each client entry has required fields
        valid_clients = []
        for client in clients:
            if len(client) >= 3:  # At least client_name, url, apikey
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
        logger.error(f"Failed to parse HYDRUS_CLIENTS secret: {e}")
        logger.debug(f"Raw clients data that failed to parse: {repr(clients_secret)}")
        return []

def get_client_by_name(client_name):
    """Get a Hydrus client by name"""
    clients = load_clients_from_secret()
    for client in clients:
        if client["name"].lower() == client_name.lower():
            try:
                return hydrus_api.Client(access_key=client["apikey"], api_url=client["url"])
            except Exception as e:
                logger.error(f"Failed to create client {client_name}: {e}")
                return None

def get_page_info(client_obj, page_key):
    """Get page information for a specific tab using its page key"""
    try:
        return client_obj.get_page_info(page_key=page_key)
    except Exception as e:
        logger.error(f"Failed to get page info for page_key {page_key}: {e}")
        return None
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
                    import re

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
