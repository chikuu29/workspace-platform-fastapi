import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
import anyio
from fastapi import UploadFile
from app.core.config import settings
from app.core.context import OrgContext
from app.core.errors import ApiError
from app.modules.system.repository import AppRepository
from app.core.logger import create_logger


UPLOAD_CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_FILE_SIZE = 25 * 1024 * 1024
DEFAULT_MAX_FILES = 10


class AppService:
    def __init__(self, repository: AppRepository):
        self.repository = repository
        self.logger = create_logger("app_service")

    def _create_upload_name(self, original_name: str) -> str:
        original_path = Path(original_name or "file")
        suffix = original_path.suffix.lower()
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", original_path.stem).strip("-._")
        return f"{uuid.uuid4().hex}-{stem or 'file'}{suffix}"

    def _safe_storage_part(self, value: str) -> str:
        """Keep org/app/process directory names predictable and path-safe."""
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
        return cleaned or "default"

    def _parse_positive_int(self, value: Any, default: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(1, min(parsed, maximum))

    def _accepts_file(self, upload: UploadFile, accept: str | None) -> bool:
        if not accept or accept.strip() in {"*", "*/*"}:
            return True

        content_type = (upload.content_type or "").lower()
        suffix = Path(upload.filename or "").suffix.lower()

        for raw_rule in accept.split(","):
            rule = raw_rule.strip().lower()
            if not rule:
                continue
            if rule.startswith(".") and suffix == rule:
                return True
            if rule.endswith("/*") and content_type.startswith(rule[:-1]):
                return True
            if "/" in rule and content_type == rule:
                return True

        return False

    async def _write_upload_stream(
        self,
        upload: UploadFile,
        destination: Path,
        max_size_bytes: int,
    ) -> int:
        """
        Stream the multipart temp file to disk in chunks.

        This avoids `await upload.read()` with no size, which loads the entire
        upload into memory and becomes unsafe for large files or many users.
        """
        total_size = 0
        try:
            async with await anyio.open_file(destination, "wb") as output:
                while True:
                    chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break

                    total_size += len(chunk)
                    if total_size > max_size_bytes:
                        raise ApiError(413, "Uploaded file is larger than the configured limit.")

                    await output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        return total_size

    async def get_templates(self, query: Dict[str, Any]) -> List[Any]:
        self.logger.debug(f"Fetching templates with query={query}")
        return await self.repository.get_templates(query)

    async def get_app_configuration(self) -> Optional[Dict[str, Any]]:
        self.logger.debug("Fetching app menu configuration")
        config_doc = await self.repository.get_menu_config()
        if config_doc:
            return config_doc.get("config")
        self.logger.warning("Menu configuration not found in DB")
        return None

    def get_notifications(self) -> List[Dict[str, Any]]:
        return [
            {"id": 1, "info": "You have a new message", "aName": "Alice"},
            {"id": 2, "info": "Class starts at 6 PM", "aName": "Gym"},
        ]

    async def get_db_statistics(self) -> Dict[str, Any]:
        return await self.repository.get_db_stats()

    async def upload_files(
        self,
        files: List[UploadFile],
        ctx: OrgContext,
        process_name: str = "files",
        accept: str | None = None,
        max_size_bytes: int = DEFAULT_MAX_FILE_SIZE,
        max_files: int = DEFAULT_MAX_FILES,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not files:
            raise ApiError(400, "No files uploaded.")

        max_files = self._parse_positive_int(max_files, DEFAULT_MAX_FILES, DEFAULT_MAX_FILES)
        max_size_bytes = self._parse_positive_int(max_size_bytes, DEFAULT_MAX_FILE_SIZE, DEFAULT_MAX_FILE_SIZE)

        if len(files) > max_files:
            raise ApiError(400, f"Too many files uploaded. Maximum allowed is {max_files}.")

        app_name = self._safe_storage_part(ctx.app_code)
        org_name = self._safe_storage_part(str(ctx.org_name or ctx.org_id))
        process_part = self._safe_storage_part(process_name)

        self.logger.info(
            "Processing upload of %s files for org=%s app=%s process=%s",
            len(files),
            ctx.org_id,
            ctx.app_code,
            process_name,
        )

        # Directory layout keeps files isolated by org and app while leaving
        # URLs stable under the existing /public/storage static mount.
        storage_directory = settings.STORAGE_ROOT / org_name / app_name / process_part
        storage_directory.mkdir(parents=True, exist_ok=True)

        file_details = []
        for upload in files:
            if not self._accepts_file(upload, accept):
                raise ApiError(
                    400,
                    f"File type is not allowed for '{upload.filename}'.",
                    payload={"accept": accept},
                )

            file_name = self._create_upload_name(upload.filename)
            destination = storage_directory / file_name
            size = await self._write_upload_stream(upload, destination, max_size_bytes)
            mime_type = upload.content_type or mimetypes.guess_type(upload.filename or "")[0]
            object_path = f"public/storage/{org_name}/{app_name}/{process_part}/{file_name}"

            file_details.append(
                {
                    "filename": file_name,
                    "originalName": upload.filename,
                    "size": size,
                    "mimeType": mime_type,
                    "absolutePath": str(destination),
                    "accessObjectPath": object_path,
                    "accessUrl": f"{settings.FILE_UPLOAD_URL.rstrip('/')}/{org_name}/{app_name}/{process_part}/{file_name}",
                }
            )

        if file_details:
            self.logger.debug(f"Saving upload details to DB for {len(file_details)} files")
            await self.repository.save_upload_details(
                {
                    "_org": ctx.to_org_block(),
                    "processName": process_name,
                    "uploadFiles": file_details,
                    "uploadedBy": {
                        "userId": ctx.user_id,
                        "userName": ctx.user_name,
                        "userType": ctx.user_type,
                    },
                    "config": {
                        "accept": accept,
                        "maxSizeBytes": max_size_bytes,
                        "maxFiles": max_files,
                    },
                    "meta": extra_meta or {},
                }
            )

        self.logger.info("File upload processing complete")
        return file_details
