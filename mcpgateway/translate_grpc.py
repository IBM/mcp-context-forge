# -*- coding: utf-8 -*-
"""位置: ./mcpgateway/translate_grpc.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

gRPC 到 MCP 的转换模块

本模块提供 gRPC 到 MCP 协议转换的能力。
通过 gRPC 服务器反射（server reflection）自动发现服务，
从而把 gRPC 服务以 MCP 工具的形式暴露为 HTTP/SSE 端点。
"""

# 标准库
import asyncio
import base64
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence

try:
    # 第三方库
    from google.protobuf import descriptor_pool, json_format, message_factory
    from google.protobuf.descriptor_pb2 import FileDescriptorProto  # pylint: disable=no-name-in-module
    from google.protobuf.message import DecodeError
    import grpc
    from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc  # pylint: disable=no-member

    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    # 当 grpc 不可用时的占位值
    descriptor_pool = None  # type: ignore
    json_format = None  # type: ignore
    message_factory = None  # type: ignore
    FileDescriptorProto = None  # type: ignore
    grpc = None  # type: ignore
    reflection_pb2 = None  # type: ignore
    reflection_pb2_grpc = None  # type: ignore

# 第一方（项目内部）模块
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.grpc_validation import _validate_grpc_target, _validate_tls_path

# 初始化日志
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


@lru_cache(maxsize=1)
def _warn_trusted_local_once() -> None:
    """每个进程最多告警一次：SSRF/TLS 校验被跳过。"""
    logger.warning("GrpcEndpoint.start() called with trusted_local=True: SSRF/TLS target validation is skipped. The caller is responsible for having validated the target address and TLS paths.")


PROTO_TO_JSON_TYPE_MAP = {
    1: "number",  # TYPE_DOUBLE（双精度浮点）
    2: "number",  # TYPE_FLOAT（单精度浮点）
    3: "integer",  # TYPE_INT64（64 位有符号整数）
    4: "integer",  # TYPE_UINT64（64 位无符号整数）
    5: "integer",  # TYPE_INT32（32 位有符号整数）
    8: "boolean",  # TYPE_BOOL（布尔）
    9: "string",  # TYPE_STRING（字符串）
    12: "string",  # TYPE_BYTES（字节串，以 base64 编码）
    13: "integer",  # TYPE_UINT32（32 位无符号整数）
    14: "string",  # TYPE_ENUM（枚举）
}


class GrpcEndpoint:
    """gRPC channel 的封装，附带基于反射的接口自省能力。"""

    def __init__(
        self,
        target: str,
        reflection_enabled: bool = True,
        tls_enabled: bool = False,
        tls_cert_path: Optional[str] = None,
        tls_key_path: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        channel: Optional[grpc.Channel] = None,
        pool: Optional[Any] = None,
        method_class_cache: Optional[Dict[str, Any]] = None,
        owns_channel: bool = True,
    ):
        """初始化 gRPC 端点。

        参数:
            target: gRPC 服务器地址（host:port）
            reflection_enabled: 是否启用服务器反射以进行服务发现
            tls_enabled: 连接是否使用 TLS
            tls_cert_path: TLS 证书路径
            tls_key_path: TLS 密钥路径
            metadata: gRPC 元数据请求头
            channel: 可选，预先创建好的 channel；传入时直接复用，而不是在
                ``start`` 里重新创建。给出时，``owns_channel`` 决定 ``close``
                是否允许关闭它。
            pool: 可选，预先创建的描述符池（供运行时缓存使用）。缺省时为每个
                端点创建一个独立的私有池。
            method_class_cache: 可选的共享 ``{完整类型名: MessageClass}`` 映射，
                使得基于缓存池构建的消息类可以在多次调用间复用，而无需每次
                重新构建。
            owns_channel: 为 False 时，``close`` 永远不会关闭注入的 channel
                （由持有方保留生命周期控制权）。
        """
        self._target = target
        self._reflection_enabled = reflection_enabled
        self._tls_enabled = tls_enabled
        self._tls_cert_path = tls_cert_path
        self._tls_key_path = tls_key_path
        self._metadata = metadata or {}
        self._channel: Optional[grpc.Channel] = channel
        self._injected_channel = channel is not None
        self._owns_channel = owns_channel
        self._services: Dict[str, Any] = {}
        self._descriptors: Dict[str, Any] = {}
        self._last_call_metadata: Dict[str, Any] = {"headers": {}, "trailers": {}, "status": None}
        # 每个端点独立的私有描述符池。绝不要使用 ``descriptor_pool.Default()``：
        # 反射得到的描述符来自不受信任的上游服务，把它们加入进程级的默认池
        # 可能造成跨请求的类型混淆或符号冲突。
        self._pool = pool if pool is not None else descriptor_pool.DescriptorPool()
        self._method_class_cache = method_class_cache if method_class_cache is not None else {}
        self._factory = message_factory.MessageFactory(pool=self._pool)

    @staticmethod
    def _metadata_values(values) -> Dict[str, List[str]]:
        """把 gRPC 元数据转换成 JSON 安全格式的列表，同时保留重复项。"""
        result: Dict[str, List[str]] = {}
        for key, value in values or ():
            rendered = base64.b64encode(value).decode() if isinstance(value, bytes) else str(value)
            result.setdefault(str(key), []).append(rendered)
        return result

    def get_call_metadata(self) -> Dict[str, Any]:
        """返回上次调用的 JSON 安全格式的初始元数据、trailer 和最终状态。"""
        return {
            "headers": dict(self._last_call_metadata.get("headers") or {}),
            "trailers": dict(self._last_call_metadata.get("trailers") or {}),
            "status": self._last_call_metadata.get("status"),
        }

    def _validate_target_and_tls(self) -> None:
        """根据 SSRF / 路径穿越规则校验目标地址及任何 TLS 路径。

        复用 ``mcpgateway.utils.grpc_validation`` 中的共享校验器。

        抛出:
            GrpcServiceError: 如果目标地址或某个 TLS 路径被拒绝。
        """
        _validate_grpc_target(self._target)
        if self._tls_cert_path:
            _validate_tls_path(self._tls_cert_path, "TLS cert path")
        if self._tls_key_path:
            _validate_tls_path(self._tls_key_path, "TLS key path")

    async def start(self, timeout: Optional[float] = None, trusted_local: bool = False) -> None:
        """初始化 gRPC channel，若启用反射则执行服务发现。

        参数:
            timeout: 单次调用的 gRPC 截止时间（deadline），会传播给反射 RPC，
                避免上游响应过慢时在调用方的 asyncio 取消之外继续阻塞执行器。
            trusted_local: 为 False（默认值）时，在打开任何 channel 之前，
                目标地址及 TLS 证书/密钥路径会先按平台的 SSRF 和路径穿越规则
                校验，防止直接调用方被引导到被拦截的目的地（例如云元数据
                端点）。只有在调用方已自行校验过目标时才设为 True；设为 True
                时校验被跳过，并每个进程记录一次告警。

        抛出:
            GrpcServiceError: 如果 trusted_local 为 False，且目标地址或某个
                TLS 路径被 SSRF / 路径穿越校验器拒绝。
        """
        if trusted_local:
            _warn_trusted_local_once()
        else:
            self._validate_target_and_tls()

        logger.info(f"Starting gRPC endpoint connection to {self._target}")

        # 创建 channel
        if self._channel is not None:
            # 注入的 channel（运行时缓存命中）原样复用；生命周期控制权归持有方，
            # 因此 start() 不得重建它。
            logger.debug("Reusing injected gRPC channel for %s", self._target)
        elif self._tls_enabled:
            if self._tls_cert_path and self._tls_key_path:
                cert = await asyncio.to_thread(Path(self._tls_cert_path).read_bytes)
                key = await asyncio.to_thread(Path(self._tls_key_path).read_bytes)
                credentials = grpc.ssl_channel_credentials(root_certificates=cert, private_key=key)
                self._channel = grpc.secure_channel(self._target, credentials)
            else:
                credentials = grpc.ssl_channel_credentials()
                self._channel = grpc.secure_channel(self._target, credentials)
        else:
            self._channel = grpc.insecure_channel(self._target)

        # 若启用反射则执行服务发现
        if self._reflection_enabled:
            await self._discover_services(timeout=timeout)

    async def _discover_services(self, timeout: Optional[float] = None) -> None:
        """使用 gRPC 反射发现服务和方法。

        参数:
            timeout: 应用于每个反射 RPC 的单次调用 gRPC 截止时间。

        抛出:
            Exception: 如果服务发现失败
        """
        logger.info(f"Discovering services on {self._target} via reflection")

        try:
            stub = reflection_pb2_grpc.ServerReflectionStub(self._channel)

            # 列出所有服务
            request = reflection_pb2.ServerReflectionRequest(list_services="")  # pylint: disable=no-member

            response = stub.ServerReflectionInfo(iter([request]), timeout=timeout) if timeout is not None else stub.ServerReflectionInfo(iter([request]))

            service_names = []
            for resp in response:
                if resp.HasField("list_services_response"):
                    for svc in resp.list_services_response.service:
                        service_name = svc.name
                        # 跳过反射服务本身
                        if "ServerReflection" in service_name:
                            continue
                        service_names.append(service_name)
                        logger.debug(f"Discovered service: {service_name}")

            # 为每个服务获取文件描述符
            for service_name in service_names:
                await self._discover_service_details(stub, service_name, timeout=timeout)

            logger.info(f"Discovered {len(self._services)} gRPC services")

        except Exception as e:
            logger.error(f"Service discovery failed: {e}")
            raise

    async def _discover_service_details(self, stub, service_name: str, timeout: Optional[float] = None) -> None:
        """发现服务的详细信息，包括方法和消息类型。

        参数:
            stub: gRPC 反射 stub
            service_name: 要发现的服务名称
            timeout: 应用于反射 RPC 的单次调用 gRPC 截止时间。
        """
        try:  # pylint: disable=too-many-nested-blocks
            # 请求包含此服务的文件描述符
            request = reflection_pb2.ServerReflectionRequest(file_containing_symbol=service_name)  # pylint: disable=no-member

            response = stub.ServerReflectionInfo(iter([request]), timeout=timeout) if timeout is not None else stub.ServerReflectionInfo(iter([request]))

            for resp in response:
                if resp.HasField("file_descriptor_response"):
                    # 处理所有文件描述符
                    for file_desc_proto_bytes in resp.file_descriptor_response.file_descriptor_proto:
                        file_desc_proto = FileDescriptorProto()
                        file_desc_proto.ParseFromString(file_desc_proto_bytes)

                        # 加入池中（已存在则忽略）
                        try:
                            self._pool.Add(file_desc_proto)
                        except Exception as e:  # pylint: disable=broad-except
                            # 描述符已在池中，跳过是安全的
                            logger.debug(f"Descriptor already in pool: {e}")

                        # 提取服务和方法的描述信息
                        for service_desc in file_desc_proto.service:
                            if service_desc.name in service_name or service_name.endswith(service_desc.name):
                                full_service_name = f"{file_desc_proto.package}.{service_desc.name}" if file_desc_proto.package else service_desc.name

                                methods = []
                                for method_desc in service_desc.method:
                                    methods.append(
                                        {
                                            "name": method_desc.name,
                                            "input_type": method_desc.input_type,
                                            "output_type": method_desc.output_type,
                                            "client_streaming": method_desc.client_streaming,
                                            "server_streaming": method_desc.server_streaming,
                                        }
                                    )

                                self._services[full_service_name] = {
                                    "name": full_service_name,
                                    "methods": methods,
                                    "package": file_desc_proto.package,
                                }

                                # 存储此服务的描述符
                                self._descriptors[full_service_name] = file_desc_proto

                                logger.debug(f"Service {full_service_name} has {len(methods)} methods")

        except Exception as e:
            logger.warning(f"Failed to get details for {service_name}: {e}")
            # 即使详情获取失败，也仍然添加基本服务信息
            self._services[service_name] = {
                "name": service_name,
                "methods": [],
            }

    async def invoke(
        self,
        service: str,
        method: str,
        request_data: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """使用 JSON 请求数据调用 gRPC 方法。

        参数:
            service: 服务名称
            method: 方法名称
            request_data: JSON 请求数据
            timeout: 单次 RPC 的截止时间（秒）。设置后，底层 gRPC 调用会被
                赋予一个服务端截止时间，即使包装它的 asyncio 协程被取消，
                慢速上游也无法一直占用执行器线程。

        返回:
            JSON 响应数据

        抛出:
            ValueError: 如果服务或方法不存在
            Exception: 如果调用失败
        """
        logger.debug(f"Invoking {service}.{method}")

        # 获取方法信息
        if service not in self._services:
            raise ValueError(f"Service {service} not found")

        method_info = None
        for m in self._services[service]["methods"]:
            if m["name"] == method:
                method_info = m
                break

        if not method_info:
            raise ValueError(f"Method {method} not found in service {service}")

        if method_info["client_streaming"] or method_info["server_streaming"]:
            raise ValueError(f"Method {method} is streaming, use invoke_streaming instead")

        # 从池中获取消息描述符
        input_type = method_info["input_type"].lstrip(".")
        output_type = method_info["output_type"].lstrip(".")

        try:
            input_desc = self._pool.FindMessageTypeByName(input_type)
            output_desc = self._pool.FindMessageTypeByName(output_type)
        except KeyError as e:
            raise ValueError(f"Message type not found in descriptor pool: {e}")

        # protobuf>=5.x 移除了 MessageFactory.GetPrototype；改用绑定到我们私有池的
        # 模块级辅助函数。消息类会被缓存（按端点，或通过注入的缓存共享），
        # 这样重复调用可以省去构建类的开销。
        request_class = self._message_class(input_type, input_desc)
        response_class = self._message_class(output_type, output_desc)

        # 把 JSON 转换成 protobuf 消息
        request_msg = json_format.ParseDict(request_data, request_class())

        # 创建通用 stub 并调用
        channel = self._channel
        method_path = f"/{service}/{method}"

        # 绑定单次 RPC 的截止时间（服务端超时），使慢速上游无法在包装协程被
        # asyncio.wait_for 取消后仍然存活。
        unary = channel.unary_unary(method_path, request_serializer=request_msg.SerializeToString, response_deserializer=response_class.FromString)

        def _call(req):
            """同步的 gRPC 一元调用，分发到线程执行器；设置 ``timeout`` 时绑定之。"""
            metadata = list(self._metadata.items())
            return unary.with_call(req, timeout=timeout, metadata=metadata) if timeout is not None else unary.with_call(req, metadata=metadata)

        response_msg, call = await asyncio.get_event_loop().run_in_executor(None, _call, request_msg)
        self._last_call_metadata = {
            "headers": self._metadata_values(call.initial_metadata()),
            "trailers": self._metadata_values(call.trailing_metadata()),
            "status": call.code().name if call.code() is not None else None,
        }

        # 把 protobuf 响应转换成 JSON。
        # protobuf>=5 把 `including_default_value_fields` 改名为
        # `always_print_fields_with_no_presence`；不要改回去。
        response_dict = json_format.MessageToDict(response_msg, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)

        logger.debug(f"Successfully invoked {service}.{method}")
        return response_dict

    async def invoke_streaming(
        self,
        service: str,
        method: str,
        request_data: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """调用一个服务端流式（server-streaming）gRPC 方法。

        参数:
            service: 服务名称
            method: 方法名称
            request_data: JSON 请求数据
            timeout: 单次 RPC 的截止时间（秒）

        产出:
            JSON 响应数据块

        抛出:
            ValueError: 如果服务或方法不存在，或不是流式方法
            grpc.RpcError: 如果流式 RPC 失败
        """
        logger.debug(f"Invoking streaming {service}.{method}")

        # 获取方法信息
        if service not in self._services:
            raise ValueError(f"Service {service} not found")

        method_info = None
        for m in self._services[service]["methods"]:
            if m["name"] == method:
                method_info = m
                break

        if not method_info:
            raise ValueError(f"Method {method} not found in service {service}")

        if not method_info["server_streaming"]:
            raise ValueError(f"Method {method} is not server-streaming")

        if method_info["client_streaming"]:
            raise ValueError("Client streaming not yet supported")

        # 从池中获取消息描述符
        input_type = method_info["input_type"].lstrip(".")
        output_type = method_info["output_type"].lstrip(".")

        try:
            input_desc = self._pool.FindMessageTypeByName(input_type)
            output_desc = self._pool.FindMessageTypeByName(output_type)
        except KeyError as e:
            raise ValueError(f"Message type not found in descriptor pool: {e}")

        # 与 invoke() 相同，这里同样使用模块级辅助函数（protobuf>=5.x 移除了
        # MessageFactory.GetPrototype）。
        request_class = self._message_class(input_type, input_desc)
        response_class = self._message_class(output_type, output_desc)

        # 把 JSON 转换成 protobuf 消息
        request_msg = json_format.ParseDict(request_data, request_class())

        # 创建流式调用
        channel = self._channel
        method_path = f"/{service}/{method}"

        stream_call = channel.unary_stream(method_path, request_serializer=request_msg.SerializeToString, response_deserializer=response_class.FromString)(
            request_msg,
            timeout=timeout,
            metadata=list(self._metadata.items()),
        )

        # 逐个产出响应
        stream_completed = False

        def _final_metadata():
            """在执行器线程中读取流结束时的元数据。"""
            code = stream_call.code()
            return stream_call.trailing_metadata(), code.name if code is not None else None

        try:
            iterator = iter(stream_call)

            def _initial_metadata():
                """在执行器线程中读取流的初始元数据。"""
                return stream_call.initial_metadata()

            initial_metadata = await asyncio.get_running_loop().run_in_executor(None, _initial_metadata)
            self._last_call_metadata = {"headers": self._metadata_values(initial_metadata), "trailers": {}, "status": None}

            def _next_response():
                """读取流中的下一项，避免把 StopIteration 泄漏进 asyncio。"""
                try:
                    return next(iterator)
                except StopIteration:
                    return None

            while True:
                response_msg = await asyncio.get_running_loop().run_in_executor(None, _next_response)
                if response_msg is None:
                    stream_completed = True
                    break
                # 见 invoke() 中关于 protobuf >=5.x 关键字参数改名的注释。
                response_dict = json_format.MessageToDict(response_msg, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)
                yield response_dict
        except grpc.RpcError as e:
            logger.error(f"Streaming RPC error: {e}")
            raise
        finally:
            if not stream_completed:
                stream_call.cancel()

            try:
                trailing_metadata, status_code = await asyncio.get_running_loop().run_in_executor(None, _final_metadata)
                self._last_call_metadata["trailers"] = self._metadata_values(trailing_metadata)
                self._last_call_metadata["status"] = status_code
            except Exception:  # pylint: disable=broad-except
                logger.debug("Unable to capture final gRPC streaming metadata", exc_info=True)
            if stream_completed:
                stream_call.cancel()

        logger.debug(f"Streaming complete for {service}.{method}")

    async def close(self) -> None:
        """当该端点拥有 channel 时，关闭这个 gRPC channel。"""
        if self._channel is not None and self._owns_channel:
            self._channel.close()
            logger.info("Closed gRPC connection to %s", self._target)

    def _message_class(self, type_name: str, message_descriptor: Any) -> Any:
        """返回绑定到本池的 ``type_name`` 对应的缓存 MessageClass。

        消息类由 protobuf 的消息工厂根据池中的描述符派生而来。缓存它们
        （按端点，或放入共享的运行时缓存）可以避免每次调用同一个 RPC 时
        都重新构建类。

        参数:
            type_name: protobuf 消息类型的完整名称。
            message_descriptor: ``type_name`` 对应的已解析描述符。

        返回:
            消息类。
        """
        cached = self._method_class_cache.get(type_name)
        if cached is None:
            cached = message_factory.GetMessageClass(message_descriptor)
            self._method_class_cache[type_name] = cached
        return cached

    def load_file_descriptors(self, file_descriptor_protos: Sequence[bytes]) -> None:
        """把序列化的 FileDescriptorProto 字节加载进描述符池。

        这会把消息类型定义填充进池中，使 invoke() 无需反射往返即可
        完成请求的序列化/反序列化。

        参数:
            file_descriptor_protos: 原始 FileDescriptorProto 字节的序列。
                直接传单个 ``bytes`` 对象会被拒绝，因为 Python 会把它
                逐字节静默迭代。

        抛出:
            TypeError: 如果传入的是单个 bytes 对象而不是序列。
            ValueError: 如果无法解析 protobuf 描述符。
        """
        if isinstance(file_descriptor_protos, (bytes, bytearray)):
            raise TypeError("file_descriptor_protos must be a sequence of bytes, not a single bytes object")
        for proto_bytes in file_descriptor_protos:
            fd = FileDescriptorProto()
            try:
                fd.ParseFromString(proto_bytes)
            except DecodeError as err:
                logger.error("Failed to decode protobuf: %s", proto_bytes[:100])
                raise ValueError("Unable to parse protobuf descriptor") from err

            try:
                self._pool.Add(fd)
            except TypeError as conflict_err:
                # 当同名文件已注册且内容冲突时，protobuf 会抛出 TypeError。
                # 已存在的描述符仍具有权威性；这并非真正意义上的空操作，
                # 但把它当作"跳过并记录日志"处理与先前的意图一致，
                # 同时不会掩盖真正的编程错误。
                logger.debug("Descriptor pool conflict for %s: %s", fd.name, conflict_err)

    def get_services(self) -> List[str]:
        """获取已发现的服务名称列表。

        返回:
            服务名称列表
        """
        return list(self._services.keys())

    def get_methods(self, service: str) -> List[str]:
        """获取某个服务的方法列表。

        参数:
            service: 服务名称

        返回:
            方法名称列表
        """
        if service in self._services:
            return [m["name"] for m in self._services[service].get("methods", [])]
        return []


class GrpcToMcpTranslator:
    """在 gRPC 和 MCP 协议之间进行转换。"""

    def __init__(self, endpoint: GrpcEndpoint):
        """初始化转换器。

        参数:
            endpoint: 要转换的 gRPC 端点
        """
        self._endpoint = endpoint

    def grpc_service_to_mcp_server(self, service_name: str) -> Dict[str, Any]:
        """把一个 gRPC 服务转换为 MCP 虚拟服务器定义。

        参数:
            service_name: gRPC 服务名称

        返回:
            MCP 服务器定义
        """
        return {
            "name": service_name,
            "description": f"gRPC service: {service_name}",
            "transport": ["sse", "http"],
            "tools": self.grpc_methods_to_mcp_tools(service_name),
        }

    def grpc_methods_to_mcp_tools(self, service_name: str) -> List[Dict[str, Any]]:
        """把 gRPC 方法转换为 MCP 工具定义。

        参数:
            service_name: gRPC 服务名称

        返回:
            MCP 工具定义列表
        """
        # pylint: disable=protected-access
        if service_name not in self._endpoint._services:
            return []

        service_info = self._endpoint._services[service_name]
        tools = []

        for method_info in service_info.get("methods", []):
            method_name = method_info["name"]
            input_type = method_info["input_type"].lstrip(".")

            # 尝试从描述符获取输入 schema
            try:
                input_desc = self._endpoint._pool.FindMessageTypeByName(input_type)
                input_schema = self.protobuf_to_json_schema(input_desc)
            except KeyError:
                # 描述符找不到时，回退到通用 schema
                input_schema = {"type": "object", "properties": {}}

            tools.append({"name": f"{service_name}.{method_name}", "description": f"gRPC method {service_name}.{method_name}", "inputSchema": input_schema})

        return tools

    def protobuf_to_json_schema(self, message_descriptor: Any) -> Dict[str, Any]:
        """把 protobuf 消息描述符转换为 JSON schema。

        参数:
            message_descriptor: protobuf 消息描述符

        返回:
            JSON schema
        """
        schema = {"type": "object", "properties": {}, "required": []}

        # 遍历消息中的字段
        for field in message_descriptor.fields:
            field_name = field.name
            field_schema = self._protobuf_field_to_json_schema(field)
            schema["properties"][field_name] = field_schema

            # 如果字段是必填的则加入 required（proto2/proto3 处理）
            if hasattr(field, "label") and field.label == 2:  # LABEL_REQUIRED
                schema["required"].append(field_name)

        return schema

    def _protobuf_field_to_json_schema(self, field: Any) -> Dict[str, Any]:
        """把一个 protobuf 字段转换为 JSON schema 类型。

        参数:
            field: protobuf 字段描述符

        返回:
            该字段对应的 JSON schema
        """
        # 把 protobuf 类型映射为 JSON schema 类型
        type_map = {
            1: "number",  # TYPE_DOUBLE（双精度浮点）
            2: "number",  # TYPE_FLOAT（单精度浮点）
            3: "integer",  # TYPE_INT64（64 位有符号整数）
            4: "integer",  # TYPE_UINT64（64 位无符号整数）
            5: "integer",  # TYPE_INT32（32 位有符号整数）
            6: "integer",  # TYPE_FIXED64（64 位固定长度整数）
            7: "integer",  # TYPE_FIXED32（32 位固定长度整数）
            8: "boolean",  # TYPE_BOOL（布尔）
            9: "string",  # TYPE_STRING（字符串）
            11: "object",  # TYPE_MESSAGE（嵌套消息）
            12: "string",  # TYPE_BYTES（字节串，以 base64 编码）
            13: "integer",  # TYPE_UINT32（32 位无符号整数）
            14: "string",  # TYPE_ENUM（枚举）
            15: "integer",  # TYPE_SFIXED32（32 位有符号固定长度整数）
            16: "integer",  # TYPE_SFIXED64（64 位有符号固定长度整数）
            17: "integer",  # TYPE_SINT32（32 位有符号整数）
            18: "integer",  # TYPE_SINT64（64 位有符号整数）
        }

        field_type = type_map.get(field.type, "string")

        # 处理重复字段（repeated）
        if hasattr(field, "label") and field.label == 3:  # LABEL_REPEATED
            return {"type": "array", "items": {"type": field_type}}

        # 处理消息类型（嵌套对象）
        if field.type == 11:  # TYPE_MESSAGE
            try:
                nested_desc = field.message_type
                return self.protobuf_to_json_schema(nested_desc)
            except Exception:
                return {"type": "object"}

        return {"type": field_type}


# 供 CLI 使用的工具函数


async def expose_grpc_via_sse(
    target: str,
    port: int = 9000,
    tls_enabled: bool = False,
    tls_cert: Optional[str] = None,
    tls_key: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
) -> None:
    """通过 SSE/HTTP 端点暴露一个 gRPC 服务。

    参数:
        target: gRPC 服务器地址（host:port）
        port: 要监听的 HTTP 端口
        tls_enabled: gRPC 连接是否使用 TLS
        tls_cert: TLS 证书路径
        tls_key: TLS 密钥路径
        metadata: gRPC 元数据请求头
    """
    logger.info(f"Exposing gRPC service {target} via SSE on port {port}")

    endpoint = GrpcEndpoint(
        target=target,
        reflection_enabled=True,
        tls_enabled=tls_enabled,
        tls_cert_path=tls_cert,
        tls_key_path=tls_key,
        metadata=metadata,
    )

    try:
        await endpoint.start()

        logger.info(f"gRPC service exposed. Discovered services: {endpoint.get_services()}")
        logger.info("To expose via HTTP/SSE, register this service in the gateway admin UI")
        logger.info(f"  Target: {target}")
        logger.info(f"  Discovered: {len(endpoint.get_services())} services")

        # 保持端点连接存活
        # 注意: 完整的 HTTP/SSE 暴露需要经由网关 admin API 注册服务，
        # 那样它才能通过现有的多协议服务器基础设施被访问到。
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await endpoint.close()
