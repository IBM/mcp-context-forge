import json
from copy import deepcopy


wxo_tool_spec_template = {"binding": {
                                "python": {
                                "connections": {},
                                "function": "mcp-cf-tool-default",
                                "requirements": []
                                }
                            },
                            "description": None,
                            "display_name": None,
                            "id": None,
                            "input_schema": {
                                "description": None,
                                "properties": {},
                                "required": [],
                                "type": "object"
                            },
                            "is_async": False,
                            "name": None,
                            "output_schema": {
                                "description": None,
                                "properties": {},
                                "required": [],
                                "type": "object"
                            },
                            "permission": "read_only"
                            }

def convert_to_wxo_tool_spec(mcp_cf_tool):
    wxo_tool_spec = deepcopy(wxo_tool_spec_template)
    wxo_tool_spec['description']= mcp_cf_tool.get('description',None)
    wxo_tool_spec['display_name']= mcp_cf_tool.get('displayName',None)
    wxo_tool_spec['id']= mcp_cf_tool.get('id',None)
    wxo_tool_spec['input_schema']['description']=mcp_cf_tool.get('inputSchema',{}).get('description',None)
    wxo_tool_spec['input_schema']['properties']=mcp_cf_tool.get('inputSchema',{}).get('properties',{})
    wxo_tool_spec['input_schema']['required']=mcp_cf_tool.get('inputSchema',{}).get('required',[])
    wxo_tool_spec['name']=mcp_cf_tool.get('name',None)
    wxo_tool_spec['output_schema']['description']=mcp_cf_tool.get('outputSchema',{}).get('description',None)
    wxo_tool_spec['output_schema']['properties']=mcp_cf_tool.get('outputSchema',{}).get('properties',{})
    wxo_tool_spec['output_schema']['required']=mcp_cf_tool.get('outputSchema',{}).get('required',[])
    return wxo_tool_spec


if __name__=="__main__":
    mcp_cf_tools = json.load(open('./list_of_tools_from_mcp_cf.json','r'))
    for mcp_cf_tool in mcp_cf_tools:
        wxo_tool_spec = convert_to_wxo_tool_spec(mcp_cf_tool)
        print(wxo_tool_spec)
