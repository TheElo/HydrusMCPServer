"""Sense tools for Hydrus MCP server.

These tools provide sensory capabilities for interacting with media files:
- hydrus_show_files: Display images and videos from Hydrus
- hydrus_inspect_files: Send images/videos to vision API for analysis
- hydrus_transcribe_audio: Transcribe audio from files using STT API

Note: Tools are defined as plain async functions here and registered with @mcp.tool()
in server.py to avoid circular import issues.
"""

import base64
import os
import tempfile
from typing import Any

import cv2
import httpx
import numpy as np
from mcp.server.fastmcp.utilities.types import Image
from pydantic import Field
from typing import Annotated, Optional

# Import utility functions from the local module
from ..functions import (
    detect_file_type_from_bytes,
    detect_file_type_from_path,
    extract_audio_from_video,
    extract_frames_from_video,
    calculate_frame_indices,
    calculate_grid_dimensions,
    scale_image_if_needed,
    create_frame_grid,
    validate_client,
    parse_file_ids,
    safe_int_convert,
    get_file_path,
    get_audio_codec_config,
    send_to_stt_api,
    format_transcription_result,
)


async def hydrus_show_files(
    client_name: Annotated[str, Field(description="Name of the Hydrus client")] = "",
    file_ids: Annotated[Any, Field(description="File ID or comma-separated list of file IDs to show (e.g., 123 or '123,456,789'). Can be provided as a number (123) or string ('123').")] = 0,
    frame_count: Annotated[Optional[Any], Field(description="If files are videos, this number of frames will be extracted per video and compiled into a grid image. Default 4 (2x2 grid).")] = 4
) -> Any:
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

    log_message("=" * 60)
    log_message(f"STARTING TRANSCRIPTION - client: {client_name}, file_id: {file_id}")
    log_message(f"STT_API_URL: {API_URL}, MODEL: {MODEL}")

    # Get codec config for audio extraction
    _, audio_suffix, _ = get_audio_codec_config(AUDIO_FORMAT)

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

            audio_file_path = None
            try:
                # If it's a video file, extract audio track using ffmpeg
                if is_video:
                    log_message(f"Starting audio extraction from video ({source_file_size / (1024*1024):.1f}MB)")
                    log_message(f"Source file path: {source_file_path}")
                    extract_start = time.time()

                    audio_file_path = tempfile.mktemp(suffix=audio_suffix)
                    log_message(f"Audio output path: {audio_file_path}")

                    success, error_msg, audio_file_size = extract_audio_from_video(
                        source_file_path, audio_file_path, AUDIO_FORMAT, verbose=True, log_message=log_message
                    )
                    extract_time = time.time() - extract_start
                    log_message(f"Audio extraction completed in {extract_time:.1f}s")

                    if not success:
                        return f"❌ Error: {error_msg}"
                else:
                    # For audio files, use the source file directly
                    audio_file_path = source_file_path
                    audio_file_size = source_file_size
                    log_message(f"Using audio file directly: {audio_file_path} ({audio_file_size / (1024*1024):.1f}MB)")

                # Send to STT API
                api_start = time.time()
                transcription, api_error = await send_to_stt_api(
                    audio_file_path, API_URL, API_KEY, MODEL, log_message
                )
                api_time = time.time() - api_start
                log_message(f"API transcription completed in {api_time:.1f}s")

                if api_error:
                    return f"❌ Error: {api_error}"

                # Clean up the transcription (remove leading/trailing whitespace)
                transcription = transcription.strip()

                if not transcription:
                    log_message("Transcription returned empty result")
                    return "❌ Error: Transcription returned empty result"

                total_time = time.time() - start_time
                file_type_desc = "video" if is_video else "audio"
                log_message(f"SUCCESS - Total time: {total_time:.1f}s")
                return format_transcription_result(file_type_desc, file_id, client_name, total_time, transcription)

            finally:
                # Clean up extracted audio file if it's different from source
                if audio_file_path and audio_file_path != source_file_path:
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

                    audio_file_path = tempfile.mktemp(suffix=audio_suffix)
                    log_message(f"Audio output path: {audio_file_path}")

                    success, error_msg, audio_file_size = extract_audio_from_video(
                        source_file_path, audio_file_path, AUDIO_FORMAT, verbose=False, log_message=log_message
                    )
                    extract_time = time.time() - extract_start
                    log_message(f"Audio extraction completed in {extract_time:.1f}s")

                    if not success:
                        return f"❌ Error: {error_msg}"
                else:
                    # For audio files, use the source file directly
                    audio_file_path = source_file_path
                    audio_file_size = source_file_size
                    log_message(f"Using audio file directly: {audio_file_path} ({audio_file_size / (1024*1024):.1f}MB)")

                # Send to STT API
                api_start = time.time()
                transcription, api_error = await send_to_stt_api(
                    audio_file_path, API_URL, API_KEY, MODEL, log_message
                )
                api_time = time.time() - api_start
                log_message(f"API transcription completed in {api_time:.1f}s")

                if api_error:
                    return f"❌ Error: {api_error}"

                # Clean up the transcription (remove leading/trailing whitespace)
                transcription = transcription.strip()

                if not transcription:
                    log_message("Transcription returned empty result")
                    return "❌ Error: Transcription returned empty result"

                total_time = time.time() - start_time
                file_type_desc = "video" if is_video else "audio"
                log_message(f"SUCCESS - Total time: {total_time:.1f}s")
                return format_transcription_result(file_type_desc, file_id, client_name, total_time, transcription)

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
    