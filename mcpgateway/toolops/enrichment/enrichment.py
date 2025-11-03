import logging
from pathlib import Path
import base64
import datetime
import os
import json 
import tomli as tomllib
from typing import Any
from mcpgateway.schemas import ToolRead

from mcpgateway.toolops.enrichment.prompt_utils import generate_enriched_tool_description
from mcpgateway.toolops.exceptions import ToolEnrichmentError

logger = logging.getLogger(__name__)

class ToolOpsEnrichment:
    def __init__(self, llm_model_id : str | None, llm_platform : str = "WATSONX"):
        self.llm_config: dict[str, Any] = {}
        file_path = Path(__file__)
        absolute_path = file_path.resolve()
        cfg_file = absolute_path.parent / "conf/llm_config.toml"
        with Path(cfg_file).open(mode="rb") as task_file:
            self.llm_config = tomllib.load(task_file)

        if llm_model_id:
            file_path = Path(__file__)
            absolute_path = file_path.resolve()
            cfg_file = (
                absolute_path.parent / "conf/task_definitions.toml"
            )
            with Path(cfg_file).open(mode="rb") as task_file:
                task_definitions = tomllib.load(task_file)
            llm_model_id = task_definitions["default"]["DEFAULT_MODEL_ID"]

        if not llm_model_id:
            exception = "Please configure the llm model id for ToolOps Enrichment."
            raise ToolEnrichmentError("ToolOpsEnrichment", exception)

        # print("Using modelid: " + llm_model_id)
        logger.info("Using modelid: " + llm_model_id)
        self.llm_model_id = llm_model_id
        self.llm_platform = llm_platform
        self.sessionid = self._get_unique_sessionid()

    def _get_unique_sessionid(self) -> str:
        timestamp = ""
        timestamp = datetime.datetime.now().strftime(
            "%Y-%m-%dT%H-%M-%S.%fZ-"
        ) + base64.urlsafe_b64encode(os.urandom(6)).decode("ascii")

        return timestamp

    async def process(self,tool_schema: ToolRead, debug_mode: bool = False, logfolder:str = "log/")->str:
        logger.info("in process!!!!")
        tool_name = tool_schema.name
        current_tool_description = ""
        if tool_schema.description:
            current_tool_description = tool_schema.description
        if current_tool_description:
            current_tool_description = current_tool_description.replace(
                "\n", "\\n"
            )
        input_schema = tool_schema.input_schema
        if debug_mode:
            logfolder = "log/" + self.sessionid
            os.makedirs(logfolder, exist_ok=True)

        enriched_description = await generate_enriched_tool_description(
            tool_name,
            current_tool_description,
            input_schema,
            self.llm_model_id,
            self.llm_config,
            logfolder,
            debug_mode
        )
        return enriched_description
