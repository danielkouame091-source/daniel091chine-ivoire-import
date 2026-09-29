"""
Service de stockage abstrait — S3 / MinIO / Local.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Abstraction S3-compatible (AWS S3, MinIO, Wasabi, Backblaze)."""

    def __init__(self) -> None:
        self.bucket = getattr(settings, "S3_BUCKET", "mtech-docs")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=getattr(settings, "S3_ENDPOINT", None),
                aws_access_key_id=getattr(settings, "S3_ACCESS_KEY", None),
                aws_secret_access_key=getattr(settings, "S3_SECRET_KEY", None),
                region_name=getattr(settings, "S3_REGION", "eu-west-3"),
            )
        return self._client

    async def upload(
        self, key: str, content: bytes, mime_type: str
    ) -> str:
        """Upload un fichier et retourne l'URL S3 (pas signée)."""
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=mime_type,
                ServerSideEncryption="AES256",   # Chiffrement au repos
            )
            # Retourner l'URL S3 (clé interne, pas exposée directement)
            return f"s3://{self.bucket}/{key}"
        except ClientError as exc:
            logger.exception(f"[storage] Échec upload {key}")
            raise

    async def delete(self, url: str) -> None:
        """Supprime un fichier."""
        key = self._extract_key(url)
        if key:
            try:
                self.client.delete_object(Bucket=self.bucket, Key=key)
            except ClientError:
                logger.exception(f"[storage] Échec suppression {key}")

    async def get_signed_url(self, url: str, expiration_minutes: int = 15) -> str:
        """Génère une URL signée temporaire pour téléchargement direct."""
        key = self._extract_key(url)
        if not key:
            return url

        try:
            signed = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expiration_minutes * 60,
            )
            return signed
        except ClientError:
            logger.exception(f"[storage] Échec signature {key}")
            return url

    async def download(self, url: str) -> bytes:
        """Télécharge le contenu d'un fichier."""
        key = self._extract_key(url)
        if not key:
            raise ValueError(f"URL invalide : {url}")
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            logger.exception(f"[storage] Échec download {key}")
            raise

    @staticmethod
    def _extract_key(url: str) -> str | None:
        """Extrait la clé S3 depuis une URL s3:// ou https://."""
        if url.startswith("s3://"):
            parts = url[5:].split("/", 1)
            return parts[1] if len(parts) > 1 else None
        if "amazonaws.com/" in url:
            return url.split("amazonaws.com/", 1)[1].split("?", 1)[0]
        return None
