"""对象存储抽象：local（默认）或 S3 兼容（可选 boto3）。"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import current_app


class ObjectStore:
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        raise NotImplementedError

    def get_bytes(self, uri: str) -> bytes:
        raise NotImplementedError

    def exists(self, uri: str) -> bool:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    def __init__(self, root: str | None = None):
        self.root = Path(root or os.path.join(current_app.config["UPLOAD_FOLDER"], "open_objects"))
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # 防穿越
        key = key.replace("\\", "/").lstrip("/")
        parts = [p for p in key.split("/") if p and p != ".."]
        path = self.root.joinpath(*parts)
        path.resolve().relative_to(self.root.resolve())
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"local://{key}"

    def get_bytes(self, uri: str) -> bytes:
        key = uri[len("local://"):] if uri.startswith("local://") else uri
        path = self._path(key)
        return path.read_bytes()

    def exists(self, uri: str) -> bool:
        key = uri[len("local://"):] if uri.startswith("local://") else uri
        try:
            return self._path(key).is_file()
        except ValueError:
            return False


class S3ObjectStore(ObjectStore):
    """需安装 boto3，并配置 S3_BUCKET / S3_ENDPOINT / AWS_*。"""

    def __init__(self):
        import boto3

        self.bucket = current_app.config["S3_BUCKET"]
        kwargs = {}
        endpoint = current_app.config.get("S3_ENDPOINT")
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        self.client = boto3.client("s3", **kwargs)
        self.prefix = (current_app.config.get("S3_PREFIX") or "tigerpro/").lstrip("/")

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        full = f"{self.prefix}{key.lstrip('/')}"
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        self.client.put_object(Bucket=self.bucket, Key=full, Body=data, **extra)
        return f"s3://{self.bucket}/{full}"

    def get_bytes(self, uri: str) -> bytes:
        # s3://bucket/key
        assert uri.startswith("s3://")
        _, _, rest = uri.partition("s3://")
        bucket, _, key = rest.partition("/")
        obj = self.client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()

    def exists(self, uri: str) -> bool:
        try:
            self.get_bytes(uri)
            return True
        except Exception:  # noqa: BLE001
            return False


def get_object_store() -> ObjectStore:
    backend = (current_app.config.get("OBJECT_STORE_BACKEND") or "local").lower()
    if backend == "s3":
        return S3ObjectStore()
    return LocalObjectStore()


def store_upload(data: bytes, *, prefix: str = "jobs", ext: str = ".bin",
                 content_type: str | None = None) -> str:
    key = f"{prefix}/{uuid.uuid4().hex}{ext}"
    return get_object_store().put_bytes(key, data, content_type=content_type)
