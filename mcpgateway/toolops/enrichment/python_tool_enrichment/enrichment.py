import logging
from pathlib import Path
from typing import Any

import aiofiles
import tomli as tomllib
import yaml
from toolops.utils.llm_util import check_llm_env_vars

from toolops.enrichment.python_tool_enrichment.enrichment_utils.tool.service import enrich_tool
from toolops.enrichment.python_tool_enrichment.enrichment_utils.tool.utils import (
    ToolEnrichmentConfig,
    ToolEnrichmentOptions,
    ToolInputDetails,
    ToolLLMConfig,
    ToolOutputConfig,
    ToolUserInput,
    get_unique_sessionid,
    has_function_with_decorator,
)
from toolops.exceptions import ToolEnrichmentError

logger = logging.getLogger(__name__)


class ToolOpsEnrichment:
    def __init__(self, llm_model_id, llm_platform="WATSONX"):
        self.llm_config = {}
        file_path = Path(__file__)
        absolute_path = file_path.resolve()
        cfg_file = absolute_path.parent / "enrichment_utils/conf/llm_config.toml"
        with Path(cfg_file).open(mode="rb") as task_file:
            self.llm_config = tomllib.load(task_file)

        if llm_model_id is None:
            # from orchestrate if no model is sent, we use default
            file_path = Path(__file__)
            absolute_path = file_path.resolve()
            cfg_file = (
                absolute_path.parent / "enrichment_utils/conf/task_definitions.toml"
            )
            with Path(cfg_file).open(mode="rb") as task_file:
                task_definitions = tomllib.load(task_file)
            llm_model_id = task_definitions["default"]["DEFAULT_MODEL_ID"]

        print("Using modelid: " + llm_model_id)
        self.llm_model_id = llm_model_id
        self.llm_platform = llm_platform
        self.sessionid = get_unique_sessionid()

        check_llm_env_vars(llm_platform)

        if self.llm_model_id == None:
            exception = "Please configure the llm model id for ToolOps Enrichment."
            raise ToolEnrichmentError("ToolOpsEnrichment", exception)

    async def process(
        self,
        input_file1: str,
        options: dict[str, Any],
        logfolder: str,
        kind: str,
        debug_mode: bool = False,
        iterative_mode=False,
        enrichment_type="",
        user_feedback: dict[str, Any] | None = None,
    ):
        enrichment_info: dict[str, Any] = {}
        input_file_contents = ""
        # with open(input_file1, encoding="utf-8") as inp_file:
        #     input_file_contents = inp_file.read()
        async with aiofiles.open(input_file1) as f:
            input_file_contents = await f.read()

        if kind:
            if kind == "python" and not input_file1.endswith(".py"):
                enrichment_info["error"] = (
                    "Invalid kind value. Input File does not have .py extension"
                )
            elif kind == "openapi" and not input_file1.endswith(".json"):
                enrichment_info["error"] = (
                    "Invalid kind value. Input File does not have .json extension"
                )
            elif kind not in ["openapi", "python"]:
                enrichment_info["error"] = (
                    "Invalid kind value. kind value should be openapi / python"
                )
        else:
            enrichment_info["error"] = "kind value (openapi or python) not specified."
            return "", enrichment_info

        inp_path = Path(input_file1)
        input_filename_without_extn = inp_path.stem

        file_extn = ""
        if kind == "python" and input_file1.endswith(".py"):
            file_extn = ".py"
        elif kind == "openapi" and input_file1.endswith(".json"):
            file_extn = ".json"
        filename = input_filename_without_extn + file_extn

        enriched_file_contents, enrichment_info = await self.process2(
            input_file_contents,
            options,
            logfolder,
            kind,
            debug_mode,
            filename,
            iterative_mode,
            enrichment_type,
            user_feedback,
        )

        model_id2 = (
            self.llm_model_id.split("/")[1]
            if "/" in self.llm_model_id
            else self.llm_model_id
        )

        original_filename_fullpath = ""
        if debug_mode:
            original_filename = (
                model_id2
                + "_"
                + input_filename_without_extn
                + "_before_enrichment"
                + file_extn
            )
            original_filename_fullpath = logfolder + "/" + original_filename
            # with open(original_filename_fullpath, "w", encoding="utf-8") as f:
            #     f.write(input_file_contents)
            async with aiofiles.open(
                original_filename_fullpath, mode="w", encoding="utf-8"
            ) as f:
                await f.write(input_file_contents)

        enriched_filename = (
            input_filename_without_extn + "_" + model_id2 + "_en" + file_extn
        )
        enriched_filename_fullpath = logfolder + "/" + enriched_filename
        # with open(enriched_filename_fullpath, "w", encoding="utf-8") as f:
        #     f.write(enriched_file_contents)
        async with aiofiles.open(
            enriched_filename_fullpath, mode="w", encoding="utf-8"
        ) as f:
            await f.write(enriched_file_contents)

        return enriched_filename_fullpath, enrichment_info

    async def process2(
        self,
        input_file_contents: str,
        options: dict[str, Any],
        logfolder: str,
        kind: str,
        debug_mode: bool = False,
        input_filename: str = "",
        iterative_mode=False,
        enrichment_type="",
        user_feedback: dict[str, Any] | None = None,
    ) -> tuple[str, dict]:
        if not options:
            file_path = Path(__file__)
            absolute_path = file_path.resolve()
            # print("absolute_path: " + str(absolute_path))
            cfg_file = (
                absolute_path.parent
                / "enrichment_utils/conf/wxo_enrichment_config.yaml"
            )
            print("cfg_file: " + str(cfg_file))
            async with aiofiles.open(cfg_file) as f:
                content = await f.read()
                options = yaml.safe_load(content)

        enrichment_info: dict[str, Any] = {}
        # enriched_filename_fullpath = ""
        enriched_file_contents: str = ""

        prompts_folder = logfolder + "/debug_enrichment/"
        if debug_mode:
            Path(prompts_folder).mkdir(parents=True, exist_ok=True)

        if kind == "python":
            if "tool_enrichment" not in options:
                print(
                    "tool_enrichment key not found in input cfg file!",
                )
                enrichment_info["error"] = (
                    "tool_enrichment key not found in input cfg file!"
                )

            if not has_function_with_decorator(input_file_contents, "tool"):
                print(
                    "Invalid python tool file as it does not have a function with @tool decorator"
                )
                enrichment_info["error"] = (
                    "Invalid python tool file as it does not have a function with @tool decorator. inp_file: "
                    + input_file_contents
                )
            else:
                # flattened_data = flatten_dict(options["tool_enrichment"])
                # result_string = ", ".join(
                #     [f"{k}: {v}" for k, v in flattened_data.items()]
                # )
                # print("options: " + result_string)
                tool_en_options = ToolEnrichmentOptions(**options["tool_enrichment"])

                if input_filename:
                    tool_name_mod = "".join(
                        char for char in input_filename if char.isalnum()
                    )
                    prefix = tool_name_mod
                else:
                    prefix = "python_tool"

                toolfile = input_filename if input_filename else "python_tool.py"
                input_details = ToolInputDetails(
                    tool_source_code=input_file_contents,
                    options=tool_en_options,
                    prefix=prefix,
                    tools_file=toolfile,
                )
                output_config = ToolOutputConfig(
                    logfolder=logfolder,
                    prompts_log_folder=prompts_folder,
                    debug_mode=debug_mode,
                )
                tool_llm_config = ToolLLMConfig(
                    model_id=self.llm_model_id,
                    llm_platform=self.llm_platform,
                    llm_config=self.llm_config,
                )

                user_input = ToolUserInput(
                    iterative_mode=iterative_mode,
                    user_feedback=user_feedback,
                    enrichment_type=enrichment_type,
                )

                enrich_cfg = ToolEnrichmentConfig(
                    input_details=input_details,
                    user_input=user_input,
                    output_config=output_config,
                    tool_llm_config=tool_llm_config,
                )

                enriched_code, _, enrichments, original_filename_fullpath = enrich_tool(
                    enrich_cfg
                )

                enriched_file_contents = enriched_code
                enrichment_info["enrichments"] = enrichments
                enrichment_info["original_filename_fullpath"] = (
                    original_filename_fullpath
                )
        else:
            enrichment_info["error"] = (
                f"Invalid kind value: {kind}. It needs to be 'python''"
            )

        # return enriched_filename_fullpath, enrichment_info
        return enriched_file_contents, enrichment_info
