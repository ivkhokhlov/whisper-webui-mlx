from dataclasses import dataclass
import logging
import mimetypes
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid

from mlx_ui.db import JobRecord

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    chat_id: str


def read_telegram_config() -> TelegramConfig | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return TelegramConfig(token=token, chat_id=chat_id)


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return f"{'*' * (len(value) - visible)}{value[-visible:]}"


def maybe_send_telegram(
    job: JobRecord,
    result_path: Path,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    config = read_telegram_config()
    if config is None:
        return

    result_path = Path(result_path)
    if not result_path.is_file():
        logger.warning(
            "Telegram delivery skipped for job %s: missing result %s",
            job.id,
            result_path,
        )
        return

    errors: list[tuple[str, Exception]] = []
    try:
        send_telegram_message(
            config,
            f"Transcription complete: {job.filename}",
            timeout=timeout,
        )
    except Exception as exc:
        errors.append(("message", exc))

    try:
        send_telegram_document(config, result_path, timeout=timeout)
    except Exception as exc:
        errors.append(("document", exc))

    if errors:
        masked_token = mask_secret(config.token)
        for kind, exc in errors:
            logger.warning(
                "Telegram %s delivery failed for job %s (chat_id=%s, token=%s): %s",
                kind,
                job.id,
                config.chat_id,
                masked_token,
                _describe_telegram_error(exc, config),
            )


def send_telegram_message(
    config: TelegramConfig,
    text: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    payload = urllib.parse.urlencode(
        {"chat_id": config.chat_id, "text": text}
    ).encode("utf-8")
    request = urllib.request.Request(
        _api_url(config.token, "sendMessage"),
        data=payload,
        method="POST",
    )
    _perform_request(request, timeout)


def send_telegram_document(
    config: TelegramConfig,
    file_path: Path,
    caption: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    file_path = Path(file_path)
    content_type = (
        mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    )
    fields: dict[str, str] = {"chat_id": config.chat_id}
    if caption:
        fields["caption"] = caption
    body, content_type_header = _encode_multipart(
        fields,
        {"document": (file_path.name, file_path.read_bytes(), content_type)},
    )
    request = urllib.request.Request(
        _api_url(config.token, "sendDocument"),
        data=body,
        method="POST",
        headers={
            "Content-Type": content_type_header,
            "Content-Length": str(len(body)),
        },
    )
    _perform_request(request, timeout)


def _perform_request(request: urllib.request.Request, timeout: float) -> None:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def _encode_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body_parts: list[bytes] = []
    for name, value in fields.items():
        body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
        body_parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        body_parts.append(str(value).encode("utf-8"))
        body_parts.append(b"\r\n")
    for name, (filename, content, content_type) in files.items():
        body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
        body_parts.append(
            (
                'Content-Disposition: form-data; name="'
                f'{name}"; filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        body_parts.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body_parts.append(content)
        body_parts.append(b"\r\n")
    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(body_parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _describe_telegram_error(exc: Exception, config: TelegramConfig) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        reason_text = str(reason)
        return _mask_token(reason_text, config.token)
    return exc.__class__.__name__


def _mask_token(text: str, token: str) -> str:
    if not token or token not in text:
        return text
    return text.replace(token, mask_secret(token))
