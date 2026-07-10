"""Cloudflare R2 (S3-compatible) storage client."""

from typing import Optional

import boto3
from botocore.config import Config

from app.config import settings

_r2_client: Optional[object] = None


def get_r2_client():
    """Get or create the R2 client (boto3 S3-compatible)."""
    global _r2_client
    if _r2_client is None:
        if all([
            settings.r2_account_id,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
        ]):
            _r2_client = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                config=Config(signature_version="s3v4"),
            )
        else:
            _r2_client = _NoopR2Client()
    return _r2_client


class _NoopR2Client:
    """Fallback stub when R2 is not configured."""

    async def upload_fileobj(self, fileobj, bucket: str, key: str) -> None:
        pass

    async def generate_presigned_url(self, *args, **kwargs) -> str:
        return "https://placeholder.r2.dev/mock.jpg"


async def upload_from_url(source_url: str, key: str) -> str:
    """Download from source URL and upload to R2. Returns the public URL."""
    import httpx

    client = get_r2_client()
    if isinstance(client, _NoopR2Client):
        return source_url

    async with httpx.AsyncClient() as http:
        resp = await http.get(source_url)
        resp.raise_for_status()
        client.upload_fileobj(
            BytesIO(resp.content),
            settings.r2_bucket,
            key,
        )

    return f"{settings.r2_public_url}/{key}"
