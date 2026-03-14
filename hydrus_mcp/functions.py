import hydrus_api, os, json, math
import numpy as np
from typing import Any


def load_clients_from_secret() -> list[dict[str, str]]:
    """Load client credentials from environment variable
    
    Returns:
        List of client dictionaries with name, url, apikey, and description
    """
    clients_secret = os.environ.get("HYDRUS_CLIENTS", "[]").strip()
    
    try:
        clients = json.loads(clients_secret)
        
        valid_clients: list[dict[str, str]] = []
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
    except (json.JSONDecodeError, TypeError):
        return []


def get_client_by_name(client_name: str) -> hydrus_api.Client | None:
    """Get a Hydrus client by name (returns client object)
    
    Args:
        client_name: The name of the client to find
        
    Returns:
        hydrus_api.Client instance or None if not found
    """
    if not client_name:
        return None
    
    # Strip quotes from client name (models often send quoted strings)
    client_name_stripped = client_name.strip()
    if (client_name_stripped.startswith('"') and client_name_stripped.endswith('"')) or \
       (client_name_stripped.startswith("'") and client_name_stripped.endswith("'")):
        client_name_stripped = client_name_stripped[1:-1]
    
    clients = load_clients_from_secret()
    for client in clients:
        if client["name"].lower() == client_name_stripped.lower():
            return hydrus_api.Client(access_key=client["apikey"], api_url=client["url"])
    return None


def get_page_info(client_obj: hydrus_api.Client, page_key: str) -> dict | None:
    """Get page information for a specific tab using its page key"""
    return client_obj.get_page_info(page_key=page_key)


def get_service_key_by_name(client: hydrus_api.Client, service_name: str) -> str | None:
    """Get the service key for a given service name"""
    services_dict = client.get_services()
    for key, service_info in services_dict["services"].items():
        if service_info["name"] == service_name:
            return key
    return None


def get_tags(client_obj: hydrus_api.Client, file_ids: list[int], tag_service: str = "all known tags") -> list[list[Any]]:
    tag_service_key = get_service_key_by_name(client_obj, tag_service)

    # Process in batches of 3
    batch_size = 3
    MyDict: list[list[Any]] = []

    for i in range(0, len(file_ids), batch_size):
        # Get current batch of file IDs (up to batch_size)
        batch_file_ids = file_ids[i : i + batch_size]

        try:
            # Get metadata for this batch
            a = client_obj.get_file_metadata(file_ids=batch_file_ids)

            # Process each item in the batch
            for y in range(0, len(a)):  # type: ignore[arg-type]
                try:
                    metadata = a.get("metadata")
                    tags = metadata[y]["tags"][f"{tag_service_key}"]["storage_tags"]["0"]
                except Exception as e:
                    tags = [f"Error processing file: {str(e)}"]

                MyDict.append([batch_file_ids[y], tags])
        except Exception:
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
        except Exception:
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
            continue
        
        name = page_info.get('name', page_info.get('title', f"Page {page_info.get('id', 'unknown')}"))
        tabs.append(name)
        
        if return_keys:
            page_key = page_info.get('page_key')
            if page_key:
                tab_keys.append(page_key)
        
        if 'pages' in page_info:
            nested_tabs, nested_keys = extract_tabs_from_pages(page_info['pages'], return_keys)
            tabs.extend(nested_tabs)
            tab_keys.extend(nested_keys)
    
    return tabs, tab_keys


def get_file_path(client_obj, file_id: int) -> dict | None:
    """Get the local file path for a file by its ID.
    
    This function retrieves the filesystem path where Hydrus stores the file locally.
    This is useful for large files where downloading the entire content would be inefficient.
    
    Args:
        client_obj: The hydrus_api.Client instance
        file_id: The numerical file ID
        
    Returns:
        Dictionary with 'path', 'filetype', and 'size' keys, or None if file not found locally
        or if the API key doesn't have 'See Local Paths' permission.
    """
    import httpx
    
    try:
        # Get the API URL and access key from the client object
        # The hydrus_api.Client stores these as api_url and access_key (public attributes)
        api_url = client_obj.api_url.rstrip('/')
        access_key = client_obj.access_key
        
        headers = {
            "Hydrus-Client-API-Access-Key": access_key
        }
        
        # Make synchronous request for simplicity
        with httpx.Client() as http_client:
            response = http_client.get(
                f"{api_url}/get_files/file_path?file_id={file_id}",
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            elif response.status_code == 403:
                return None
            else:
                return None
    except Exception:
        return None


def safe_int_convert(value, default: int = 0) -> int:
    """Safely convert a value to integer, handling both string and int types.
    
    This function handles various input formats including:
    - Direct integers
    - String representations of numbers
    - Quoted strings (e.g., '"123"' or "'123'")
    - Invalid values (returns default)
    
    Args:
        value: The value to convert (can be int, str, or None)
        default: The default value to return if conversion fails (default: 0)
        
    Returns:
        The converted integer or the default value
    """
    if isinstance(value, int):
        return value
    
    if value is None or value == "":
        return default
    
    # Convert to string and strip whitespace
    value_str = str(value).strip()
    
    # Strip quotes if present (models often send quoted numbers)
    if (value_str.startswith('"') and value_str.endswith('"')) or \
       (value_str.startswith("'") and value_str.endswith("'")):
        value_str = value_str[1:-1]
    
    # Try to convert to int
    try:
        return int(value_str)
    except (ValueError, TypeError):
        return default


def safe_bool_convert(value, default: bool = False) -> bool:
    """Safely convert a value to boolean, handling both string and bool types.
    
    This function handles various input formats including:
    - Direct booleans
    - String representations ("true", "false", "True", "False", etc.)
    - Other truthy/falsy values
    
    Args:
        value: The value to convert (can be bool, str, or other)
        default: The default value to return if conversion fails (default: False)
        
    Returns:
        The converted boolean or the default value
    """
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        return value.lower().strip() == "true"
    
    return bool(value) if value is not None else default


def parse_file_ids(file_ids) -> list[int]:
    """Parse file IDs from various input formats into a list of integers.
    
    This function handles various input formats including:
    - Single integer
    - Comma-separated string of integers
    - String with brackets (e.g., "[123, 456]")
    - Quoted numbers
    
    Args:
        file_ids: The file IDs to parse (can be int, str, or list)
        
    Returns:
        List of valid file IDs as integers
    """
    result = []
    
    if isinstance(file_ids, int):
        return [file_ids]
    
    if isinstance(file_ids, list):
        for fid in file_ids:
            if isinstance(fid, int):
                result.append(fid)
            elif isinstance(fid, str):
                fid_stripped = fid.strip().strip('"').strip("'")
                if fid_stripped.isdigit():
                    result.append(int(fid_stripped))
        return result
    
    # Handle string input
    if isinstance(file_ids, str):
        # Strip brackets if present
        content = file_ids.strip()
        if content.startswith('[') and content.endswith(']'):
            content = content[1:-1]
        
        # Split by comma and convert each part
        for fid in content.split(','):
            fid = fid.strip().strip('"').strip("'")
            if fid.isdigit():
                result.append(int(fid))
    
    return result

def validate_client(client_name: str) -> tuple[hydrus_api.Client, None] | tuple[None, str]:
    """Validate client name and return client object or error message.
    
    Args:
        client_name: Name of the Hydrus client to connect to
        
    Returns:
        Tuple of (client_obj, error_message). If successful, error_message is None.
        If failed, client_obj is None and error_message contains the error.
    """
    if not client_name or not client_name.strip():
        return None, "❌ Error: Client name is required"
    
    client_obj = get_client_by_name(client_name)
    if not client_obj:
        available_clients = [c['name'] for c in load_clients_from_secret()]
        return None, f"❌ Error: Could not connect to client '{client_name}'. Available clients: {', '.join(available_clients)}"
    
    return client_obj, None


def get_page_list(client_obj) -> tuple[list | None, str | None]:
    """Get and normalize page list from client.
    
    Args:
        client_obj: Hydrus API client object
        
    Returns:
        Tuple of (page_list, error_message). If successful, error_message is None.
    """
    try:
        pages_response = client_obj.get_pages()
        
        if not isinstance(pages_response, dict) or 'pages' not in pages_response:
            return None, f"❌ Error: Unexpected response format from get_pages(). Expected dict with 'pages' key, got {type(pages_response).__name__}. Response: {str(pages_response)[:200]}"
        
        page_list = pages_response['pages']
        
        # Handle both list and single dictionary cases
        if isinstance(page_list, list):
            pass
        elif isinstance(page_list, dict):
            page_list = [page_list]
        else:
            return None, f"❌ Error: Unexpected response format for 'pages' in get_pages(). Expected list or dict, got {type(page_list).__name__}. Response: {str(page_list)[:200]}"
        
        return page_list, None
        
    except AttributeError as e:
        return None, f"❌ Error: Method not found in client API: {e}"
    except Exception as e:
        return None, f"❌ Error: Failed to get pages: {str(e)}"


def detect_file_type_from_path(file_path: str) -> dict:
    """Detect file type from file path extension.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Dictionary with 'is_video', 'is_animated_gif', 'mime_type', and 'file_extension' keys
    """
    file_path_lower = file_path.lower()
    
    # Video extensions
    video_extensions = {'.mp4', '.webm', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.m4v'}
    # Audio extensions
    audio_extensions = {'.mp3', '.wav', '.aac', '.flac', '.m4a'}
    # Image extensions
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif'}
    
    # Get file extension
    for ext in video_extensions | audio_extensions | image_extensions:
        if file_path_lower.endswith(ext):
            file_extension = ext
            break
    else:
        file_extension = '.unknown'
    
    is_video = file_extension in video_extensions
    is_animated_gif = file_extension == '.gif'
    
    # Determine mime type
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.mp4': 'video/mp4', '.webm': 'video/webm', '.avi': 'video/x-msvideo',
        '.mkv': 'video/x-matroska', '.mov': 'video/quicktime', '.wmv': 'video/x-ms-wmv',
        '.flv': 'video/x-flv', '.m4v': 'video/x-m4v',
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.aac': 'audio/aac',
        '.flac': 'audio/flac', '.m4a': 'audio/mp4'
    }
    mime_type = mime_map.get(file_extension, 'application/octet-stream')
    
    return {
        'is_video': is_video,
        'is_animated_gif': is_animated_gif,
        'mime_type': mime_type,
        'file_extension': file_extension
    }


def detect_file_type_from_bytes(file_bytes: bytes) -> dict:
    """Detect file type from file content bytes.
    
    Args:
        file_bytes: Raw file content
        
    Returns:
        Dictionary with 'is_video', 'is_animated_gif', 'mime_type', and 'file_extension' keys
    """
    is_video = False
    is_animated_gif = False
    mime_type = 'image/png'  # default
    file_extension = '.png'  # default
    
    if file_bytes.startswith(b'\xff\xd8\xff'):
        mime_type = 'image/jpeg'
        file_extension = '.jpg'
    elif file_bytes.startswith(b'GIF87a') or file_bytes.startswith(b'GIF89a'):
        mime_type = 'image/gif'
        file_extension = '.gif'
        # Check if animated GIF (multiple frames)
        if file_bytes.count(b'\x2c') > 1:
            is_animated_gif = True
    elif file_bytes.startswith(b'\x89PNG'):
        mime_type = 'image/png'
        file_extension = '.png'
    elif b'ftypmp42' in file_bytes[:64] or b'ftypisom' in file_bytes[:64] or b'ftypmp41' in file_bytes[:64]:
        mime_type = 'video/mp4'
        file_extension = '.mp4'
        is_video = True
    elif file_bytes.startswith(b'\x1a\x45\xdf\xa3'):
        mime_type = 'video/webm'
        file_extension = '.webm'
        is_video = True
    elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WEBV':
        mime_type = 'video/webm'
        file_extension = '.webm'
        is_video = True
    elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'AVI ':
        mime_type = 'video/x-msvideo'
        file_extension = '.avi'
        is_video = True
    elif file_bytes.startswith(b'\xff\xfb') or file_bytes.startswith(b'\xff\xfa') or b'ID3' in file_bytes[:20]:
        mime_type = 'audio/mpeg'
        file_extension = '.mp3'
    elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WAVE':
        mime_type = 'audio/wav'
        file_extension = '.wav'
    elif b'fLaC' in file_bytes[:4]:
        mime_type = 'audio/flac'
        file_extension = '.flac'
    elif file_bytes.startswith(b'ADIF'):
        mime_type = 'audio/aac'
        file_extension = '.aac'
    
    return {
        'is_video': is_video,
        'is_animated_gif': is_animated_gif,
        'mime_type': mime_type,
        'file_extension': file_extension
    }


def calculate_grid_dimensions(frame_count: int) -> tuple[int, int]:
    """Calculate grid dimensions (rows, cols) for a given frame count.
    
    Args:
        frame_count: Number of frames to display
        
    Returns:
        Tuple of (rows, cols) for the grid layout
    """
    rows = int(math.ceil(math.sqrt(frame_count)))
    cols = int(math.ceil(frame_count / rows))
    return rows, cols


def calculate_frame_indices(total_frames: int, frame_count: int) -> list[int]:
    """Calculate frame indices for evenly spaced frame extraction.
    
    Args:
        total_frames: Total number of frames in the video
        frame_count: Number of frames to extract
        
    Returns:
        List of frame indices to extract
    """
    frame_indices = []
    for i in range(frame_count):
        percentage = (i + 1) / (frame_count + 1)
        frame_indices.append(int(total_frames * percentage))
    return frame_indices


def create_frame_grid(frames: list, frame_width: int, frame_height: int, frame_count: int) -> np.ndarray:
    """Create a composite image grid from multiple frames.
    
    Args:
        frames: List of numpy array frames
        frame_width: Width of individual frames
        frame_height: Height of individual frames
        frame_count: Total number of frames (for grid calculation)
        
    Returns:
        Numpy array of the composite grid image
    """
    rows, cols = calculate_grid_dimensions(frame_count)
    
    # Calculate composite dimensions
    composite_width = cols * frame_width
    composite_height = rows * frame_height
    
    # Create the grid at original resolution
    composite = np.zeros((composite_height, composite_width, 3), dtype=np.uint8)
    
    for idx, frame in enumerate(frames):
        row = idx // cols
        col = idx % cols
        y_start = row * frame_height
        x_start = col * frame_width
        composite[y_start:y_start+frame_height, x_start:x_start+frame_width] = frame
    
    return composite


def scale_image_if_needed(image: np.ndarray, max_resolution: int = 1000) -> np.ndarray:
    """Scale image down if it exceeds maximum resolution on longest side.
    
    Args:
        image: Input numpy array image
        max_resolution: Maximum allowed pixels on longest side
        
    Returns:
        Scaled numpy array image
    """
    import cv2
    
    height, width = image.shape[:2]
    
    if width > max_resolution or height > max_resolution:
        scale_factor = max_resolution / max(width, height)
        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)
        image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
    
    return image


def extract_frames_from_video(file_path: str, frame_count: int) -> tuple[list[np.ndarray] | None, dict]:
    """Extract frames from a video file.
    
    Args:
        file_path: Path to the video file
        frame_count: Number of frames to extract
        
    Returns:
        Tuple of (frames_list, metadata_dict). frames_list is None if extraction failed.
        metadata_dict contains 'total_frames', 'fps', 'duration', 'frame_width', 'frame_height'
    """
    import cv2
    
    cap = cv2.VideoCapture(file_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration_seconds = total_frames / fps if fps > 0 else 0
    
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    metadata = {
        'total_frames': total_frames,
        'fps': fps,
        'duration': duration_seconds,
        'frame_width': frame_width,
        'frame_height': frame_height
    }
    
    if total_frames == 0:
        cap.release()
        return None, metadata
    
    # Calculate and extract frames
    frame_indices = calculate_frame_indices(total_frames, frame_count)
    frames = []
    
    for frame_idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    
    cap.release()
    
    if not frames:
        return None, metadata
    
    return frames, metadata

def get_viewing_stat(file_metadata: dict, stat_key: str, default) -> Any:
    """Extract viewing statistics from file_metadata.
    
    Searches through file_viewing_statistics list and sums up the stat across all canvas types.
    """
    stats_list = file_metadata.get('file_viewing_statistics', [])
    total = default
    for stat in stats_list:
        if isinstance(stat, dict) and stat_key in stat:
            val = stat[stat_key]
            if isinstance(total, int) and isinstance(val, (int, float)):
                total += int(val)
            elif isinstance(total, float) and isinstance(val, (int, float)):
                total += val
            elif stat_key == 'last_viewed_timestamp' and val is not None:
                if total is None or val > total:
                    total = val
    return total


def format_timestamp(timestamp) -> str:
    """Format Unix timestamp to yyyy.mm.dd hh:mm:ss format.
    
    Hydrus API returns timestamps in seconds since Unix epoch (e.g., 1700000000 for Nov 2023).
    Valid range for dates between 1970 and 2100 is approximately 0 to 4,102,441,200 seconds.
    
    Args:
        timestamp: Unix timestamp (int or float) in seconds since epoch
        
    Returns:
        Formatted date string or 'N/A' if invalid
    """
    if timestamp is None:
        return "N/A"
    try:
        from datetime import datetime
        
        # Convert to numeric type
        ts = float(timestamp)
        
        # Hydrus API returns timestamps in seconds since Unix epoch
        # Valid range for reasonable dates (year 1970-2100): 0 to ~4.1 billion seconds
        # 
        # If timestamp is outside this range, it might be in milliseconds or microseconds
        # - Milliseconds would be ~1.7 trillion for 2024 (e.g., 1700000000000)
        # - Microseconds would be ~1.7 quadrillion for 2024 (e.g., 1700000000000000)
        #
        # Handle timestamps that are too large (milliseconds/microseconds)
        if ts > 4102441200:  # Year 2100 in seconds
            # Likely milliseconds or microseconds - divide by 1000
            ts = ts / 1000.0
            # If still > year 2100, it was microseconds - divide again
            if ts > 4102441200:
                ts = ts / 1000.0
        # Handle timestamps that are too small (negative or before epoch)
        elif ts < 0:
            return "N/A"
        
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y.%m.%d %H:%M:%S")
    except (ValueError, TypeError, OSError, OverflowError):
        return "N/A"


def extract_tags_by_service(tags_dict: dict, service_names: list[str] = None, tag_type: str = "display_tags") -> dict[str, list[str]]:
    """Extract tags grouped by tag service name.
    
    Args:
        tags_dict: The tags dictionary from file metadata
        service_names: Optional list of service names to filter. If None, returns all services EXCEPT 'all known tags'.
                       Can also be passed as a comma-separated string.
                       Note: 'all known tags' is only included when explicitly requested in service_names, as it's the sum of all tag services.
        tag_type: Which tag type to extract - 'display_tags' or 'storage_tags' (default: 'display_tags')
                       
    Returns:
        Dictionary mapping service names to their tag lists
    """
    # Handle service_names as comma-separated string
    if isinstance(service_names, str):
        service_names = [s.strip() for s in service_names.split(',') if s.strip()]
    
    # Validate tag_type
    if tag_type not in ('display_tags', 'storage_tags'):
        tag_type = 'display_tags'
    
    result = {}
    
    for service_key, service_data in tags_dict.items():
        if not isinstance(service_data, dict):
            continue
            
        service_name = service_data.get('name', service_key)
        
        # Skip 'all known tags' unless explicitly requested
        # This is because 'all known tags' is just the sum of all other tag services
        # and including it would be redundant and waste data/tokens
        if service_name == 'all known tags' and (service_names is None or service_name not in service_names):
            continue
        
        # Skip if service_names filter is specified and this service is not in the list
        if service_names and service_name not in service_names:
            continue
        
        all_tags = []
        if tag_type in service_data:
            tag_category = service_data[tag_type]
            if isinstance(tag_category, dict):
                for category_key, tag_list in tag_category.items():
                    if isinstance(tag_list, list):
                        all_tags.extend(tag_list)
        
        if all_tags:
            result[service_name] = all_tags
    
    return result
