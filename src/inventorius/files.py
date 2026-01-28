"""
File upload and serving for Inventorius.

Handles image uploads with automatic resizing and thumbnail generation.
Files are stored on disk in INVENTORIUS_UPLOADS_PATH volume.
Metadata is stored in MongoDB 'files' collection.
"""

from flask import Blueprint, request, Response, send_file, url_for, current_app
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
import os
import uuid
import mimetypes

from inventorius.db import db
from inventorius.util import no_cache
import inventorius.util_error_responses as problem

# Optional: image processing with Wand (ImageMagick)
try:
    from wand.image import Image
    from wand.exceptions import WandException
    WAND_AVAILABLE = True
except ImportError:
    WAND_AVAILABLE = False
    print("Warning: Wand not available, image processing disabled")

files = Blueprint("files", __name__)

# Configuration
MAX_UPLOAD_SIZE = int(os.getenv("INVENTORIUS_MAX_UPLOAD_SIZE", 10 * 1024 * 1024))  # 10MB
UPLOADS_PATH = os.getenv("INVENTORIUS_UPLOADS_PATH", "/var/lib/inventorius/uploads")
MAX_IMAGE_DIMENSION = 2000  # Resize images larger than this
THUMBNAIL_SIZE = 256

# Allowed MIME types
ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
}

# Image MIME types (for thumbnail generation)
IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}


def get_file_path(file_id: str) -> str:
    """Get the filesystem path for a file."""
    shard = file_id[:2]
    return os.path.join(UPLOADS_PATH, "files", shard, file_id)


def get_thumb_path(file_id: str) -> str:
    """Get the filesystem path for a thumbnail."""
    shard = file_id[:2]
    return os.path.join(UPLOADS_PATH, "thumbs", shard, file_id)


def ensure_dir(path: str) -> None:
    """Ensure directory exists."""
    os.makedirs(os.path.dirname(path), exist_ok=True)


def detect_mime_type(file_stream) -> str:
    """Detect MIME type from file magic bytes."""
    # Read first few bytes for magic number detection
    header = file_stream.read(16)
    file_stream.seek(0)

    # PNG: 89 50 4E 47
    if header[:4] == b'\x89PNG':
        return "image/png"
    # JPEG: FF D8 FF
    if header[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    # GIF: GIF87a or GIF89a
    if header[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    # WebP: RIFF....WEBP
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return "image/webp"
    # PDF: %PDF
    if header[:4] == b'%PDF':
        return "application/pdf"

    return "application/octet-stream"


def process_image(input_path: str, output_path: str, max_dim: int) -> tuple[int, int]:
    """
    Resize image if larger than max_dim, preserving aspect ratio.
    Returns (width, height) of the output image.
    """
    if not WAND_AVAILABLE:
        # Just copy if Wand not available
        import shutil
        shutil.copy(input_path, output_path)
        return (0, 0)

    with Image(filename=input_path) as img:
        # Auto-orient based on EXIF
        img.auto_orient()

        width, height = img.width, img.height

        # Resize if too large
        if width > max_dim or height > max_dim:
            if width > height:
                new_width = max_dim
                new_height = int(height * (max_dim / width))
            else:
                new_height = max_dim
                new_width = int(width * (max_dim / height))
            img.resize(new_width, new_height)
            width, height = new_width, new_height

        img.save(filename=output_path)
        return (width, height)


def generate_thumbnail(input_path: str, output_path: str, size: int = THUMBNAIL_SIZE) -> bool:
    """Generate a thumbnail. Returns True if successful."""
    if not WAND_AVAILABLE:
        return False

    try:
        with Image(filename=input_path) as img:
            img.auto_orient()

            # Calculate thumbnail dimensions (fit within size x size)
            width, height = img.width, img.height
            if width > height:
                new_width = size
                new_height = int(height * (size / width))
            else:
                new_height = size
                new_width = int(width * (size / height))

            img.resize(new_width, new_height)

            # Convert to PNG for consistent thumbnail format
            img.format = 'png'
            ensure_dir(output_path)
            img.save(filename=output_path)
            return True
    except WandException as e:
        print(f"Thumbnail generation failed: {e}")
        return False


@files.route('/api/files', methods=['POST'])
@no_cache
def files_post():
    """
    Upload a file.

    Expects multipart/form-data with 'file' field.
    Returns file metadata including ID for future reference.

    TODO: Add @login_required for authentication
    """
    if 'file' not in request.files:
        return problem.invalid_params_response_simple("file", "No file provided")

    file = request.files['file']

    if file.filename == '':
        return problem.invalid_params_response_simple("file", "No file selected")

    # Check file size
    file.seek(0, 2)  # Seek to end
    size = file.tell()
    file.seek(0)  # Seek back to start

    if size > MAX_UPLOAD_SIZE:
        return problem.invalid_params_response_simple(
            "file",
            f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024*1024)}MB"
        )

    # Detect and validate MIME type
    content_type = detect_mime_type(file.stream)
    if content_type not in ALLOWED_TYPES:
        return problem.invalid_params_response_simple(
            "file",
            f"File type not allowed. Allowed types: {', '.join(ALLOWED_TYPES)}"
        )

    # Generate file ID
    file_id = str(uuid.uuid4())

    # Determine paths
    file_path = get_file_path(file_id)
    thumb_path = get_thumb_path(file_id)

    # Save file
    ensure_dir(file_path)

    is_image = content_type in IMAGE_TYPES
    width, height = None, None
    has_thumbnail = False

    if is_image and WAND_AVAILABLE:
        # Save to temp, process, then move
        temp_path = file_path + ".tmp"
        file.save(temp_path)

        try:
            width, height = process_image(temp_path, file_path, MAX_IMAGE_DIMENSION)
            os.remove(temp_path)

            # Generate thumbnail
            has_thumbnail = generate_thumbnail(file_path, thumb_path)
        except Exception as e:
            # If processing fails, just save the original
            os.rename(temp_path, file_path)
            print(f"Image processing failed: {e}")
    else:
        # Non-image or no Wand: save directly
        file.save(file_path)

    # Get final file size
    final_size = os.path.getsize(file_path)

    # Store metadata in MongoDB
    metadata = {
        "_id": file_id,
        "original_filename": secure_filename(file.filename),
        "content_type": content_type,
        "size": final_size,
        "uploaded_at": datetime.now(timezone.utc),
        "uploaded_by": None,  # TODO: get from current_user when auth added
        "is_image": is_image,
        "has_thumbnail": has_thumbnail,
        "width": width,
        "height": height,
    }

    db.files.insert_one(metadata)

    # Build response
    state = {
        "id": file_id,
        "filename": metadata["original_filename"],
        "content_type": content_type,
        "size": final_size,
        "is_image": is_image,
    }

    if has_thumbnail:
        state["thumbnail_url"] = url_for("files.file_thumb_get", id=file_id)

    response = Response()
    response.status_code = 201
    response.mimetype = "application/json"

    import json
    response.data = json.dumps({
        "Id": url_for("files.file_get", id=file_id),
        "state": state,
        "operations": [
            {"rel": "delete", "method": "DELETE", "href": url_for("files.file_delete", id=file_id)},
        ]
    })

    return response


@files.route('/api/files/<id>', methods=['GET'])
def file_get(id):
    """Serve a file by ID."""
    # Validate ID format (UUID)
    try:
        uuid.UUID(id)
    except ValueError:
        return problem.missing_resource_response("file", id)

    # Check if file exists in DB
    metadata = db.files.find_one({"_id": id})
    if not metadata:
        return problem.missing_resource_response("file", id)

    # Check if file exists on disk
    file_path = get_file_path(id)
    if not os.path.exists(file_path):
        return problem.missing_resource_response("file", id)

    # Determine Content-Disposition
    is_image = metadata.get("is_image", False)
    filename = metadata.get("original_filename", "file")

    if is_image:
        disposition = "inline"
    else:
        disposition = f"attachment; filename=\"{filename}\""

    response = send_file(
        file_path,
        mimetype=metadata.get("content_type", "application/octet-stream"),
    )
    response.headers["Content-Disposition"] = disposition
    response.headers["Cache-Control"] = "public, max-age=31536000"  # 1 year (immutable content)

    return response


@files.route('/api/files/<id>/thumb', methods=['GET'])
def file_thumb_get(id):
    """Serve a thumbnail by file ID."""
    # Validate ID format
    try:
        uuid.UUID(id)
    except ValueError:
        return problem.missing_resource_response("thumbnail", id)

    # Check if file has thumbnail
    metadata = db.files.find_one({"_id": id})
    if not metadata or not metadata.get("has_thumbnail"):
        return problem.missing_resource_response("thumbnail", id)

    thumb_path = get_thumb_path(id)
    if not os.path.exists(thumb_path):
        return problem.missing_resource_response("thumbnail", id)

    response = send_file(thumb_path, mimetype="image/png")
    response.headers["Cache-Control"] = "public, max-age=31536000"

    return response


@files.route('/api/files/<id>', methods=['DELETE'])
@no_cache
def file_delete(id):
    """
    Delete a file.

    TODO: Add @login_required and ownership check
    """
    # Validate ID format
    try:
        uuid.UUID(id)
    except ValueError:
        return problem.missing_resource_response("file", id)

    # Check if file exists
    metadata = db.files.find_one({"_id": id})
    if not metadata:
        return problem.missing_resource_response("file", id)

    # Delete from filesystem
    file_path = get_file_path(id)
    thumb_path = get_thumb_path(id)

    if os.path.exists(file_path):
        os.remove(file_path)
    if os.path.exists(thumb_path):
        os.remove(thumb_path)

    # Delete from MongoDB
    db.files.delete_one({"_id": id})

    response = Response()
    response.status_code = 200
    response.mimetype = "application/json"

    import json
    response.data = json.dumps({
        "Id": url_for("files.file_delete", id=id),
        "status": "deleted"
    })

    return response
