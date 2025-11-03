class InvalidOAPISpecification(Exception):
    def __init__(self, error_message):
        super().__init__()
        self.error_message = error_message

    def __str__(self):
        return f"Invalid API specification is provided and the error is : {self.error_message}"

class LLMPlatformError(Exception):
    def __init__(self, error_message):
        super().__init__()
        self.error_message = error_message

    def __str__(self):
        return "Invalid LLM inference Platform details provided - "+self.error_message

class AuthError(Exception):
    def __init__(self, error_message):
        super().__init__()
        self.error_message = error_message

    def __str__(self):
        return "Invalid Authentication format. Details provided - "+self.error_message

class ToolCreationError(Exception):
    def __init__(self, tool_name, error_message):
        super().__init__()
        self.error_message = error_message
        self.tool_name = tool_name
    def __str__(self):
        return "Error in creating the tool - "+self.tool_name+" and the details are - "+self.error_message
    
class ToolDetailsError(Exception):
    def __init__(self):
        super().__init__()
        self.error_message = "Tools are not provided in correct format, example format [{'tool_name':tool_name,'tool_def_str': tool_def_str}]"
    def __str__(self):
        return self.error_message


class ToolEnrichmentError(Exception):
    def __init__(self, tool_name, error_message):
        super().__init__()
        self.error_message = error_message
        self.tool_name = tool_name
    def __str__(self):
        return "Error in enriching the tool - "+self.tool_name+" and the details are - "+self.error_message

class TestCaseCreationError(Exception):
    def __init__(self, tool_name, error_message):
        super().__init__()
        self.error_message = error_message
        self.tool_name = tool_name
    def __str__(self):
        return "Error in creating test cases - "+self.tool_name+" and the details are - "+self.error_message
    
class NLTestCaseGenearationError(Exception):
    def __init__(self, tool_name, error_message):
        super().__init__()
        self.error_message = error_message
        self.tool_name = tool_name
    def __str__(self):
        return "Error in generating NL test cases - "+self.tool_name+" and the details are - "+self.error_message

class AgentCreationError(Exception):
    def __init__(self, agent_name, error_message):
        super().__init__()
        self.error_message = error_message
        self.agent_name = agent_name
    def __str__(self):
        return "Error in creating the agent - "+self.agent_name+" and the details are - "+self.error_message
    
class AgentLLMConfigurationError(Exception):
    def __init__(self, llm_model_id , agent_name, error_message):
        super().__init__()
        self.error_message = error_message
        self.llm_model_id = llm_model_id
        self.agent_name = agent_name
    def __str__(self):
        return "Error in configuring LLM for the LLM model: "+self.llm_model_id +", agent: "+self.agent_name+" and the details are - "+self.error_message
    
class AgenticEnvCreationError(Exception):
    def __init__(self, tool_name,agent_type, error_message):
        super().__init__()
        self.error_message = error_message
        self.tool_name = tool_name
        self.agent_type = agent_type
    def __str__(self):
        return "Error in creating the agentic environment - for tool: "+self.tool_name+" , agent: "+self.agent_type\
                +"and the details are - "+self.error_message
    
class ToolExecutionError(Exception):
    def __init__(self, tool_name,error_message):
        super().__init__()
        self.error_message = error_message
        self.tool_name = tool_name
    def __str__(self):
        return "Error in executing the tool - "+self.tool_name+" and the details are - "+self.error_message

class ToolAnalysisError(Exception):
    def __init__(self, tool_name, error_message):
        super().__init__()
        self.error_message = error_message
        self.tool_name = tool_name
    def __str__(self):
        return "Error in analysing the tool execution events - "+self.tool_name+" and the details are - "+self.error_message

class ReportGenerationError(Exception):
    def __init__(self, tool_name, error_message):
        super().__init__()
        self.error_message = error_message
        self.tool_name = tool_name
    def __str__(self):
        return "Error in generating the tool testing report - "+self.tool_name+" and the details are - "+self.error_message