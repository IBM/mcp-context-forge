from toolops.enrichment.python_tool_enrichment.enrichment_utils.tool.utils import CustomException


def validate_llm_config(llm_config, modelid):
    if modelid not in llm_config:
        if "default" not in llm_config:
            raise CustomException(
                "Invalid LLM Config. default config not found! " + modelid
            )
        if "max_new_tokens" not in llm_config["default"]:
            raise CustomException(
                "Invalid LLM Config. max_new_tokens not found for default config!"
            )
        if "stop_sequences" not in llm_config["default"]:
            raise CustomException(
                "Invalid LLM Config. stop_sequences not found for default config!"
            )
    else:
        if "max_new_tokens" not in llm_config[modelid]:
            raise CustomException(
                "Invalid LLM Config. max_new_tokens not found for model: " + modelid
            )
        if "stop_sequences" not in llm_config[modelid]:
            raise CustomException(
                "Invalid LLM Config. stop_sequences not found for model: " + modelid
            )
