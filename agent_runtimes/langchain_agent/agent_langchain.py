import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator

from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.tools import Tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .mcp_client import MCPClient, ToolDef
from .models import AgentConfig

logger = logging.getLogger(__name__)

class MCPTool(BaseTool):
    """Langchain tool wrapper for MCP tools"""
    
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    mcp_client: MCPClient = Field(..., description="MCP client instance")
    tool_id: str = Field(..., description="MCP tool ID")
    
    class Config:
        arbitrary_types_allowed = True
    
    def _run(self, **kwargs) -> str:
        """Synchronous tool execution"""
        try:
            result = self.mcp_client.invoke_tool(self.tool_id, kwargs)
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Tool {self.tool_id} execution failed: {e}")
            return f"Error executing tool: {str(e)}"
    
    async def _arun(self, **kwargs) -> str:
        """Asynchronous tool execution"""
        # Run in thread pool since MCP client might not be async
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run, **kwargs)

class LangchainMCPAgent:
    """Langchain agent that integrates with MCP Gateway"""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.mcp_client = MCPClient.from_env(config.mcp_gateway_url)
        self.mcp_client.debug = config.debug_mode
        
        self.llm = ChatOpenAI(
            model=config.default_model,
            temperature=config.temperature,
            streaming=config.streaming_enabled
        )
        
        self.tools: List[MCPTool] = []
        self.agent_executor: Optional[AgentExecutor] = None
        self._initialized = False
    
    @classmethod
    def from_config(cls, config: AgentConfig) -> "LangchainMCPAgent":
        """Create agent from configuration"""
        return cls(config)
    
    async def initialize(self):
        """Initialize the agent and load tools"""
        try:
            # Check if tools are restricted via environment variable (ticket requirement)
            if self.config.tools_allowlist:
                logger.info(f"Using tool allowlist from TOOLS env var: {self.config.tools_allowlist}")
                logger.info("Skipping gateway autodiscovery as per ticket requirement")
                await self._load_allowlisted_tools()
            else:
                # Auto-discover from gateway
                logger.info("Auto-discovering tools from MCP Gateway")
                await self._load_mcp_tools()
            
            # Create the agent
            await self._create_agent()
            
            self._initialized = True
            logger.info(f"Agent initialized with {len(self.tools)} tools")
            
        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            raise
    
    async def _load_allowlisted_tools(self):
        """Load only tools specified in the allowlist (no autodiscovery)"""
        try:
            # Clean the allowlist
            allowlist = [tool.strip() for tool in self.config.tools_allowlist if tool.strip()]
            logger.info(f"Loading allowlisted tools: {allowlist}")
            
            self.tools = []
            for tool_id in allowlist:
                # Create a basic tool definition for allowlisted tools
                # In a production setup, you might want to fetch schema from gateway
                mcp_tool = MCPTool(
                    name=tool_id.replace(".", "-").replace("_", "-"),
                    description=f"Allowlisted tool: {tool_id}",
                    mcp_client=self.mcp_client,
                    tool_id=tool_id
                )
                self.tools.append(mcp_tool)
                logger.info(f"Added allowlisted tool: {tool_id}")
                
        except Exception as e:
            logger.error(f"Failed to load allowlisted tools: {e}")
            raise
    
    async def _load_mcp_tools(self):
        """Load tools from MCP Gateway"""
        try:
            # Add debug info about the connection
            logger.info(f"Connecting to MCP Gateway at: {self.mcp_client.base_url}")
            logger.info(f"Using token: {'Yes' if self.mcp_client.token else 'No'}")
            
            tool_defs = self.mcp_client.list_tools()
            logger.info(f"Found {len(tool_defs)} tools from MCP Gateway")
            
            if len(tool_defs) == 0:
                logger.warning("No tools found from MCP Gateway. Check if:")
                logger.warning("  1. Gateway is running on the expected URL")
                logger.warning("  2. Authentication token is valid")
                logger.warning("  3. Gateway has tools configured")
            
            self.tools = []
            for tool_def in tool_defs:
                mcp_tool = MCPTool(
                    name=tool_def.name or tool_def.id,
                    description=tool_def.description or f"MCP tool: {tool_def.id}",
                    mcp_client=self.mcp_client,
                    tool_id=tool_def.id
                )
                self.tools.append(mcp_tool)
                logger.info(f"Loaded tool: {tool_def.id} ({tool_def.name})")
                
        except Exception as e:
            logger.error(f"Failed to load MCP tools: {e}")
            raise
    
    async def _create_agent(self):
        """Create the Langchain agent executor"""
        try:
            # Define the system prompt
            system_prompt = """You are a helpful AI assistant with access to various tools through the MCP (Model Context Protocol) Gateway.
            
Use the available tools to help answer questions and complete tasks. When using tools:
1. Read tool descriptions carefully to understand their purpose
2. Provide the correct arguments as specified in the tool schema
3. Interpret tool results and provide helpful responses to the user
4. If a tool fails, try alternative approaches or explain the limitation

Available tools: {tool_names}

Always strive to be helpful, accurate, and honest in your responses."""
            
            # Create prompt template
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ])
            
            # Create the agent
            agent = create_openai_functions_agent(
                llm=self.llm,
                tools=self.tools,
                prompt=prompt
            )
            
            # Create agent executor
            self.agent_executor = AgentExecutor(
                agent=agent,
                tools=self.tools,
                max_iterations=self.config.max_iterations,
                verbose=self.config.debug_mode,
                return_intermediate_steps=True
            )
            
            logger.info("Langchain agent created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create agent: {e}")
            raise
    
    def is_initialized(self) -> bool:
        """Check if agent is initialized"""
        return self._initialized
    
    async def check_readiness(self) -> bool:
        """Check if agent is ready to handle requests"""
        try:
            return (
                self._initialized and 
                self.agent_executor is not None and 
                len(self.tools) >= 0 and  # Allow 0 tools for testing
                await self.test_gateway_connection()
            )
        except Exception:
            return False
    
    async def test_gateway_connection(self) -> bool:
        """Test connection to MCP Gateway"""
        try:
            # Try to list tools as a connectivity test
            tools = self.mcp_client.list_tools()
            return True
        except Exception as e:
            logger.error(f"Gateway connection test failed: {e}")
            return False
    
    def get_available_tools(self) -> List[ToolDef]:
        """Get list of available tools"""
        try:
            return self.mcp_client.list_tools()
        except Exception:
            return []
    
    async def run_async(
        self, 
        messages: List[Dict[str, str]], 
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tools_enabled: bool = True
    ) -> str:
        """Run the agent asynchronously"""
        if not self._initialized:
            raise RuntimeError("Agent not initialized. Call initialize() first.")
        
        try:
            # Convert messages to input format
            if messages:
                latest_message = messages[-1]
                input_text = latest_message.get("content", "")
            else:
                input_text = ""
            
            # Prepare chat history (all messages except the last one)
            chat_history = []
            for msg in messages[:-1]:
                if msg["role"] == "user":
                    chat_history.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    chat_history.append(AIMessage(content=msg["content"]))
                elif msg["role"] == "system":
                    chat_history.append(SystemMessage(content=msg["content"]))
            
            # Run the agent
            result = await self.agent_executor.ainvoke({
                "input": input_text,
                "chat_history": chat_history,
                "tool_names": [tool.name for tool in self.tools]
            })
            
            return result["output"]
            
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return f"I encountered an error while processing your request: {str(e)}"
    
    async def stream_async(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tools_enabled: bool = True
    ) -> AsyncGenerator[str, None]:
        """Stream agent response asynchronously"""
        if not self._initialized:
            raise RuntimeError("Agent not initialized. Call initialize() first.")
        import asyncio
