"""Resilient HTTP client with retry backoff, error categorization, and streaming support."""

import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse
import requests
from requests.exceptions import (
    ConnectionError,
    ConnectTimeout,
    ReadTimeout,
    SSLError,
    Timeout,
)


class ErrorCategory:
    """Standardized error categories for the scraping pipeline."""
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    HTTP_403 = "HTTP_403"
    HTTP_404 = "HTTP_404"
    HTTP_500 = "HTTP_500"
    SSL_ERROR = "SSL_ERROR"
    PARSING_ERROR = "PARSING_ERROR"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    FILESYSTEM_ERROR = "FILESYSTEM_ERROR"
    LOGIC_ERROR = "LOGIC_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class HttpResponseResult:
    """Container for HTTP response results or categorized errors."""

    def __init__(
        self,
        success: bool,
        status_code: Optional[int] = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        attempts: int = 1,
    ):
        self.success = success
        self.status_code = status_code
        self.data = data
        self.headers = headers or {}
        self.error_type = error_type
        self.error_message = error_message
        self.attempts = attempts

    @property
    def is_retryable(self) -> bool:
        if self.success:
            return False
        if self.status_code in {429, 500, 502, 503, 504}:
            return True
        if self.error_type in {
            ErrorCategory.NETWORK_ERROR,
            ErrorCategory.TIMEOUT,
            ErrorCategory.RATE_LIMIT,
        }:
            return True
        return False


class ResilientHttpClient:
    """Robust HTTP client equipped with custom headers, backoff, and diagnostics."""

    def __init__(
        self,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 45,
        max_retries: int = 3,
        retry_delays: Optional[list] = None,
    ):
        self.headers = headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
        }
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delays = retry_delays or [2.0, 5.0, 10.0]
        self.session = requests.Session()

    def classify_exception(self, exc: Exception) -> Tuple[str, str]:
        """Classify Python requests exception into standardized pipeline error categories."""
        if isinstance(exc, SSLError):
            return ErrorCategory.SSL_ERROR, f"SSL Certificate Error: {exc}"
        if isinstance(exc, (ConnectTimeout, ReadTimeout, Timeout)):
            return ErrorCategory.TIMEOUT, f"Request Timeout after {self.timeout}s: {exc}"
        if isinstance(exc, ConnectionError):
            return ErrorCategory.NETWORK_ERROR, f"Network Connection Failed: {exc}"
        return ErrorCategory.UNKNOWN_ERROR, f"Unexpected error: {exc}"

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        auth: Optional[Tuple[str, str]] = None,
    ) -> HttpResponseResult:
        """Fetch JSON endpoint with automated retry and error classification."""
        last_error_type = ErrorCategory.UNKNOWN_ERROR
        last_error_msg = ""
        last_status_code = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=self.headers,
                    params=params,
                    auth=auth,
                    timeout=self.timeout,
                )
                last_status_code = response.status_code

                if response.status_code == 200:
                    try:
                        data = response.json()
                        return HttpResponseResult(
                            success=True,
                            status_code=200,
                            data=data,
                            headers=dict(response.headers),
                            attempts=attempt,
                        )
                    except Exception as parse_err:
                        return HttpResponseResult(
                            success=False,
                            status_code=200,
                            error_type=ErrorCategory.PARSING_ERROR,
                            error_message=f"JSON Decode failed: {parse_err}",
                            attempts=attempt,
                        )

                if response.status_code == 404:
                    return HttpResponseResult(
                        success=False,
                        status_code=404,
                        error_type=ErrorCategory.HTTP_404,
                        error_message="Resource not found (404)",
                        attempts=attempt,
                    )

                if response.status_code == 403:
                    return HttpResponseResult(
                        success=False,
                        status_code=403,
                        error_type=ErrorCategory.HTTP_403,
                        error_message="Access Forbidden (403). Check auth or anti-bot rules.",
                        attempts=attempt,
                    )

                if response.status_code == 429:
                    last_error_type = ErrorCategory.RATE_LIMIT
                    last_error_msg = "Rate limit exceeded (429)"
                elif response.status_code >= 500:
                    last_error_type = ErrorCategory.HTTP_500
                    last_error_msg = f"Server error ({response.status_code})"
                else:
                    last_error_type = ErrorCategory.NETWORK_ERROR
                    last_error_msg = f"HTTP Error {response.status_code}: {response.text[:200]}"

            except Exception as exc:
                last_error_type, last_error_msg = self.classify_exception(exc)

            if attempt < self.max_retries:
                delay = self.retry_delays[min(attempt - 1, len(self.retry_delays) - 1)]
                time.sleep(delay)

        return HttpResponseResult(
            success=False,
            status_code=last_status_code,
            error_type=last_error_type,
            error_message=last_error_msg,
            attempts=self.max_retries,
        )

    def download_file(
        self,
        url: str,
        destination_path: str,
        auth: Optional[Tuple[str, str]] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
    ) -> HttpResponseResult:
        """Stream download file directly to disk with atomic write and size validation."""
        from pathlib import Path

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp_dest = dest.with_suffix(f"{dest.suffix}.tmp")

        eff_timeout = timeout or self.timeout
        eff_retries = max_retries if max_retries is not None else self.max_retries

        last_error_type = ErrorCategory.UNKNOWN_ERROR
        last_error_msg = ""
        last_status_code = None

        for attempt in range(1, eff_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    stream=True,
                    auth=auth,
                    timeout=eff_timeout,
                )
                last_status_code = response.status_code

                if response.status_code == 200:
                    bytes_written = 0
                    with open(temp_dest, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                                bytes_written += len(chunk)

                    if bytes_written == 0:
                        if temp_dest.exists():
                            temp_dest.unlink()
                        return HttpResponseResult(
                            success=False,
                            status_code=200,
                            error_type=ErrorCategory.SCHEMA_ERROR,
                            error_message="Downloaded file is 0 bytes",
                            attempts=attempt,
                        )

                    # Atomic replace
                    if dest.exists():
                        dest.unlink()
                    temp_dest.rename(dest)

                    return HttpResponseResult(
                        success=True,
                        status_code=200,
                        data={"bytes": bytes_written, "path": str(dest.as_posix())},
                        headers=dict(response.headers),
                        attempts=attempt,
                    )

                if response.status_code == 404:
                    return HttpResponseResult(
                        success=False,
                        status_code=404,
                        error_type=ErrorCategory.HTTP_404,
                        error_message="File not found on remote server (404)",
                        attempts=attempt,
                    )

                if response.status_code == 403:
                    return HttpResponseResult(
                        success=False,
                        status_code=403,
                        error_type=ErrorCategory.HTTP_403,
                        error_message="Access forbidden (403)",
                        attempts=attempt,
                    )

                if response.status_code == 429:
                    last_error_type = ErrorCategory.RATE_LIMIT
                    last_error_msg = "Rate limit reached during file download"
                else:
                    last_error_type = ErrorCategory.NETWORK_ERROR
                    last_error_msg = f"HTTP {response.status_code} during download"

            except Exception as exc:
                if temp_dest.exists():
                    try:
                        temp_dest.unlink()
                    except Exception:
                        pass
                last_error_type, last_error_msg = self.classify_exception(exc)

            if attempt < self.max_retries:
                delay = self.retry_delays[min(attempt - 1, len(self.retry_delays) - 1)]
                time.sleep(delay)

        return HttpResponseResult(
            success=False,
            status_code=last_status_code,
            error_type=last_error_type,
            error_message=last_error_msg,
            attempts=self.max_retries,
        )

    def is_external_url(self, target_url: str, base_url: str) -> bool:
        """Check whether target_url belongs to an external domain."""
        try:
            target_netloc = urlparse(target_url).netloc.lower()
            base_netloc = urlparse(base_url).netloc.lower()
            if not target_netloc:
                return False
            return target_netloc != base_netloc
        except Exception:
            return False
