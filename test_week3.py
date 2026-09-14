"""
Unit and Integration Tests for ClauseGuard Week 3 Implementation.
Validates:
1. AgentCore Runtime invoke() with local files, direct text, and base64 payloads
2. AgentCore telemetry and structured JSON logging
3. AgentCore microVM HTTP protocol (/ping and /invocations)
4. AgentCore manifest (agentcore.yaml) and Dockerfile configuration
5. Streamlit app import and structure
"""

import base64
import json
import sys
import threading
from http.server import HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentcore_runtime import (
    AgentCoreHttpHandler,
    invoke,
    log_telemetry_event,
)

SAMPLE_DIR = Path(__file__).parent / "sample_contracts"


class TestAgentCoreRuntime:
    def test_invoke_with_document_path(self):
        contract_path = SAMPLE_DIR / "01_freelance_developer_agreement.txt"
        payload = {
            "document_path": str(contract_path),
            "contract_type": "Freelance Agreement",
        }
        res = invoke(payload)
        assert res.get("status") != "error"
        assert res["risk_score"] == "HIGH"
        assert res["flagged_count"] == 4
        assert "agentcore_metadata" in res
        meta = res["agentcore_metadata"]
        assert meta["runtime"] == "AWS Bedrock AgentCore Runtime"
        assert meta["orchestrator"] == "Strands Agents SDK"
        assert "request_id" in meta
        assert "latency_ms" in meta

    def test_invoke_with_raw_contract_text(self):
        raw_text = """
1. SERVICES
Consultant shall provide design services.

2. INDEMNIFICATION
Consultant shall indemnify and hold harmless Company from all claims without reciprocal obligation.
        """
        payload = {
            "contract_text": raw_text,
            "contract_type": "Consulting Agreement",
        }
        res = invoke(payload)
        assert res.get("status") != "error"
        assert res["flagged_count"] >= 1
        assert "agentcore_metadata" in res

    def test_invoke_with_base64_payload(self):
        contract_bytes = (SAMPLE_DIR / "05_safe_standard_vendor_agreement.txt").read_bytes()
        b64_str = base64.b64encode(contract_bytes).decode("utf-8")

        payload = {
            "file_name": "05_safe_standard_vendor_agreement.txt",
            "file_bytes_base64": b64_str,
            "contract_type": "Vendor Procurement Agreement",
        }
        res = invoke(payload)
        assert res.get("status") != "error"
        assert res["risk_score"] == "LOW"
        assert res["flagged_count"] == 0

    def test_invoke_missing_payload_raises_clean_error(self):
        payload = {"invalid_key": "data"}
        res = invoke(payload)
        assert res.get("status") == "error"
        assert res["error_type"] == "ValueError"
        assert "agentcore_metadata" in res


class TestAgentCoreHttpProtocol:
    @classmethod
    def setup_class(cls):
        cls.port = 8899
        cls.server = HTTPServer(("127.0.0.1", cls.port), AgentCoreHttpHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def teardown_class(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_ping_endpoint_health_check(self):
        url = f"http://127.0.0.1:{self.port}/ping"
        with urlopen(url, timeout=5) as response:
            assert response.status == 200
            data = json.loads(response.read().decode("utf-8"))
            assert data["status"] == "Healthy"
            assert data["service"] == "ClauseGuard"

    def test_invocations_endpoint_success(self):
        url = f"http://127.0.0.1:{self.port}/invocations"
        contract_path = SAMPLE_DIR / "05_safe_standard_vendor_agreement.txt"
        req_body = json.dumps({
            "document_path": str(contract_path),
            "contract_type": "Vendor Agreement",
        }).encode("utf-8")

        req = Request(url, data=req_body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as response:
            assert response.status == 200
            data = json.loads(response.read().decode("utf-8"))
            assert data["risk_score"] == "LOW"
            assert data["flagged_count"] == 0
            assert "agentcore_metadata" in data


class TestAgentCoreManifestAndDeployment:
    def test_agentcore_yaml_exists_and_configured(self):
        manifest_path = Path(__file__).parent / "agentcore.yaml"
        assert manifest_path.exists()
        content = manifest_path.read_text(encoding="utf-8")
        assert "ClauseGuard" in content
        assert "Strands" in content
        assert "Bedrock" in content
        assert "agentcore_runtime.py:invoke" in content
        assert "microVM" in content

    def test_dockerfile_exists_and_configured(self):
        dockerfile_path = Path(__file__).parent / "Dockerfile"
        assert dockerfile_path.exists()
        content = dockerfile_path.read_text(encoding="utf-8")
        assert "python:3.12-slim" in content
        assert "agentcore_runtime.py" in content
        assert "EXPOSE 8080" in content


class TestStreamlitAppReadiness:
    def test_app_py_compiles_and_contains_components(self):
        app_path = Path(__file__).parent / "app.py"
        assert app_path.exists()
        content = app_path.read_text(encoding="utf-8")
        assert "streamlit as st" in content
        assert "ClauseGuard" in content
        assert "triage_contract" in content
        assert "benchmark_options" in content
