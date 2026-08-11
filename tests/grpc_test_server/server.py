# -*- coding: utf-8 -*-
"""Test gRPC server for integration testing the full gRPC→MCP chain.

Supports:
- Plaintext and TLS (--tls)
- Server reflection (on by default, --no-reflection to disable)
- Unary, server-streaming, metadata auth, slow echo, schema v1/v2
"""

import argparse
import logging
import os
import sys
import time
import uuid
from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

# Generated protobuf code (imported after path setup)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
import echo_pb2
import echo_pb2_grpc

SERVER_ID = uuid.uuid4().hex[:8]
logger = logging.getLogger("grpc_test_server")

REQUIRED_AUTH = "Bearer test-token"


class EchoService(echo_pb2_grpc.EchoServiceServicer):
    """Implementation of all EchoService RPCs."""

    def Echo(self, request, context):
        """Basic unary echo."""
        logger.info("Echo: message=%r value=%d", request.message, request.value)
        return echo_pb2.EchoResponse(
            message=f"echo: {request.message}",
            value=request.value * 2,
            server_id=SERVER_ID,
        )

    def EchoStream(self, request, context):
        """Server-streaming: 5 chunks with incrementing sequence."""
        logger.info("EchoStream: message=%r value=%d", request.message, request.value)
        for i in range(1, 6):
            yield echo_pb2.EchoResponse(
                message=f"chunk {i}: {request.message}",
                value=request.value * i,
                server_id=SERVER_ID,
            )

    def EchoWithMetadata(self, request, context):
        """Authenticated echo: requires authorization metadata."""
        auth = dict(context.invocation_metadata()).get("authorization", "")
        if auth != REQUIRED_AUTH:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, f"expected '{REQUIRED_AUTH}', got '{auth}'")
        logger.info("EchoWithMetadata: message=%r (authenticated)", request.message)
        return echo_pb2.EchoResponse(
            message=f"authenticated: {request.message}",
            value=request.value,
            server_id=SERVER_ID,
        )

    def EchoSlow(self, request, context):
        """Slow echo: 3-second delay for deadline/timeout testing."""
        logger.info("EchoSlow: sleeping 3s, message=%r", request.message)
        time.sleep(3)
        return echo_pb2.EchoResponse(
            message=f"slow: {request.message}",
            value=request.value,
            server_id=SERVER_ID,
        )

    def EchoV1(self, request, context):
        """Schema v1: 2-field echo for migration testing."""
        logger.info("EchoV1: name=%r value=%d", request.name, request.value)
        return echo_pb2.EchoV1Response(
            name=request.name,
            value=request.value,
            result=f"v1: {request.name}={request.value}",
        )

    def EchoV2(self, request, context):
        """Schema v2: 3-field echo with priority for migration testing."""
        logger.info("EchoV2: name=%r value=%d priority=%d", request.name, request.value, request.priority)
        return echo_pb2.EchoV2Response(
            name=request.name,
            value=request.value,
            priority=request.priority,
            result=f"v2: {request.name}={request.value} prio={request.priority}",
        )


def build_server(port, use_tls=False):
    """Build a gRPC server with optional TLS and reflection."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    echo_pb2_grpc.add_EchoServiceServicer_to_server(EchoService(), server)

    if use_tls:
        # Read self-signed cert/key from the test server directory
        cert_path = os.path.join(_THIS_DIR, "server.crt")
        key_path = os.path.join(_THIS_DIR, "server.key")
        with open(key_path, "rb") as f:
            private_key = f.read()
        with open(cert_path, "rb") as f:
            certificate_chain = f.read()
        credentials = grpc.ssl_server_credentials([(private_key, certificate_chain)])
        server.add_secure_port(f"[::]:{port}", credentials)
        logger.info("TLS enabled (cert=%s)", cert_path)
    else:
        server.add_insecure_port(f"[::]:{port}")

    return server


def enable_reflection(server):
    """Register the reflection service so clients can discover methods."""
    SERVICE_NAMES = (
        echo_pb2.DESCRIPTOR.services_by_name["EchoService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)


def generate_self_signed_cert():
    """Generate a self-signed certificate for TLS testing."""
    cert_path = os.path.join(_THIS_DIR, "server.crt")
    key_path = os.path.join(_THIS_DIR, "server.key")
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return  # already generated
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime
    import ipaddress

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]), critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Generated self-signed cert: %s", cert_path)


def main():
    parser = argparse.ArgumentParser(description="Test gRPC Echo Server")
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--no-reflection", action="store_true", dest="no_reflection")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.tls:
        generate_self_signed_cert()

    server = build_server(args.port, use_tls=args.tls)

    if not args.no_reflection:
        enable_reflection(server)
        logger.info("Reflection enabled")
    else:
        logger.info("Reflection disabled")

    server.start()
    logger.info("Test gRPC server listening on port %d (TLS=%s, reflection=%s)",
                args.port, args.tls, not args.no_reflection)

    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.stop(0)


if __name__ == "__main__":
    main()
