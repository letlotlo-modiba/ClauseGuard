"""
AWS AgentCore Runtime Wrapper for ClauseGuard.
Provides:
1. Native BedrockAgentCoreApp entrypoint (when bedrock-agentcore is available).
2. Standard Bedrock AgentCore / SageMaker microVM HTTP runtime protocol:
   - GET  /ping        -> Health check
   - POST /invocations -> Agent invocation endpoint
3. Structured OpenTelemetry & AWS CloudWatch observability logging with trace correlation.
4. Flexible input handling: local document path, base64 file payload, or raw text.
"""

import base64
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

from agent import create_clauseguard_agent, triage_contract
from models import TriageReport

# ---------------------------------------------------------------------------
# Observability & Structured CloudWatch Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("ClauseGuard.AgentCore")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

# Ensure console handler with JSON formatting
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        json.dumps({
            "timestamp": "%(asctime)s",
            "level": "%(levelname)s",
            "logger": "%(name)s",
            "message": "%(message)s",
        })
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def log_telemetry_event(
    event_type: str,
    request_id: str,
    trace_id: str,
    data: dict[str, Any],
) -> None:
    """Emits structured JSON telemetry log for CloudWatch / AgentCore traces."""
    payload = {
        "event_type": event_type,
        "request_id": request_id,
        "trace_id": trace_id,
        "runtime": "AWS AgentCore Runtime (microVM)",
        **data,
    }
    logger.info(json.dumps(payload))


# ---------------------------------------------------------------------------
# Core AgentCore Invocation Handler
# ---------------------------------------------------------------------------

def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Primary entrypoint for AWS AgentCore Runtime.
    Accepts:
      - document_path: local file path to contract (.docx, .pdf, .txt)
      - contract_type: optional string (e.g. 'Freelance Agreement', 'SaaS Terms')
      - file_name & file_bytes_base64: optional base64 encoded document
      - contract_text: optional raw string text of contract
    Returns:
      Structured JSON dictionary conforming to TriageReport with execution telemetry.
    """
    request_id = str(uuid.uuid4())
    trace_id = payload.get("trace_id") or os.environ.get("_X_AMZN_TRACE_ID", str(uuid.uuid4()))
    start_time = time.perf_counter()

    log_telemetry_event(
        "INVOCATION_STARTED",
        request_id=request_id,
        trace_id=trace_id,
        data={
            "contract_type": payload.get("contract_type", "General Contract"),
            "input_mode": "document_path" if "document_path" in payload else ("base64" if "file_bytes_base64" in payload else "raw_text"),
        },
    )

    contract_type = payload.get("contract_type", "General Contract")
    cleanup_temp_file = None

    try:
        # Determine document path
        if "document_path" in payload:
            target_path = Path(payload["document_path"])
        elif "file_bytes_base64" in payload:
            # Handle uploaded base64 file
            file_name = payload.get("file_name", "uploaded_contract.txt")
            ext = Path(file_name).suffix or ".txt"
            temp_file = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            file_bytes = base64.b64decode(payload["file_bytes_base64"])
            temp_file.write(file_bytes)
            temp_file.close()
            target_path = Path(temp_file.name)
            cleanup_temp_file = target_path
        elif "contract_text" in payload:
            # Handle raw text
            temp_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
            temp_file.write(payload["contract_text"].encode("utf-8"))
            temp_file.close()
            target_path = Path(temp_file.name)
            cleanup_temp_file = target_path
        else:
            raise ValueError(
                "Payload must contain one of 'document_path', 'file_bytes_base64', or 'contract_text'."
            )

        # Run triage pipeline via Strands Agent
        report = triage_contract(str(target_path), contract_type=contract_type)
        report_dict = report.to_dict()

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Attach AgentCore runtime metadata
        report_dict["agentcore_metadata"] = {
            "runtime": "AWS Bedrock AgentCore Runtime",
            "request_id": request_id,
            "trace_id": trace_id,
            "latency_ms": latency_ms,
            "orchestrator": "Strands Agents SDK",
            "model_provider": "Amazon Bedrock",
        }

        log_telemetry_event(
            "INVOCATION_COMPLETED",
            request_id=request_id,
            trace_id=trace_id,
            data={
                "status": "SUCCESS",
                "latency_ms": latency_ms,
                "reviewed_clauses": report_dict["total_clauses_reviewed"],
                "flagged_clauses": report_dict["flagged_count"],
                "risk_score": report_dict["risk_score"],
            },
        )

        return report_dict

    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        log_telemetry_event(
            "INVOCATION_FAILED",
            request_id=request_id,
            trace_id=trace_id,
            data={
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "latency_ms": latency_ms,
            },
        )
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "agentcore_metadata": {
                "runtime": "AWS Bedrock AgentCore Runtime",
                "request_id": request_id,
                "trace_id": trace_id,
                "latency_ms": latency_ms,
            },
        }

    finally:
        if cleanup_temp_file and cleanup_temp_file.exists():
            try:
                cleanup_temp_file.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Bedrock AgentCore SDK App Integration (if package present)
# ---------------------------------------------------------------------------

try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def agentcore_entrypoint(payload: dict[str, Any]) -> dict[str, Any]:
        return invoke(payload)

except ImportError:
    app = None


# ---------------------------------------------------------------------------
# MicroVM HTTP Server (AWS SageMaker / Bedrock Container Protocol)
# ---------------------------------------------------------------------------

class AgentCoreHttpHandler(BaseHTTPRequestHandler):
    """Handles /ping (health) and /invocations (execution) for AgentCore containers."""

    def do_GET(self):
        if self.path == "/ping" or self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "Healthy", "service": "ClauseGuard"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/invocations":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8")

            try:
                payload = json.loads(post_body) if post_body else {}
                result = invoke(payload)
                status_code = 200 if result.get("status") != "error" else 400
            except Exception as e:
                result = {"status": "error", "message": f"Malformed request: {e}"}
                status_code = 400

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default noisy stdio logging in favor of structured logger
        pass


def run_server(port: int = 8080):
    """Runs the AgentCore runtime HTTP server."""
    server_address = ("", port)
    httpd = HTTPServer(server_address, AgentCoreHttpHandler)
    logger.info(f"ClauseGuard AgentCore Runtime listening on port {port}")
    httpd.serve_forever()


if __name__ == "__main__":
    port = int(os.environ.get("AGENTCORE_PORT", os.environ.get("PORT", 8080)))
    if app is not None and "--server" not in sys.argv:
        app.run()
    else:
        run_server(port)
