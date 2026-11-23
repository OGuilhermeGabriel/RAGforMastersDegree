import os
import re
from pathlib import Path

import boto3
from django.conf import settings


def build_s3_key(user_id, document_id, filename: str) -> str:
    safe_name = os.path.basename(filename).strip()
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", safe_name) or "document.pdf"
    return f"users/{user_id}/{document_id}/{safe_name}"


def _resolve_local_path(s3_key: str) -> Path:
    base_dir = Path(settings.LOCAL_STORAGE_DIR).resolve()
    target_path = (base_dir / s3_key).resolve()
    if base_dir not in target_path.parents:
        raise ValueError("Caminho de arquivo inválido.")
    return target_path


def save_pdf(s3_key: str, file_bytes: bytes) -> None:
    if settings.STORAGE_BACKEND == "s3":
        client = boto3.client("s3", region_name=settings.AWS_REGION)
        client.put_object(
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=s3_key,
            Body=file_bytes,
            ContentType="application/pdf",
        )
        return

    target_path = _resolve_local_path(s3_key)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(file_bytes)


def delete_pdf(s3_key: str) -> None:
    if settings.STORAGE_BACKEND == "s3":
        client = boto3.client("s3", region_name=settings.AWS_REGION)
        client.delete_object(
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=s3_key,
        )
        return

    target_path = _resolve_local_path(s3_key)
    if target_path.exists():
        target_path.unlink()