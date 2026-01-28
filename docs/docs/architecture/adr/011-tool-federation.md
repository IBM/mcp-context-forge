# ADR-0011: Allow gateways to add tools with the same server side name to the MCP Gateway without conflict

- *Status:* Implemented
- *Date:* 2025-06-22
- *Deciders:* Core Engineering Team
- *Implemented by*: https://github.com/IBM/mcp-context-forge/issues/116

## Context

The current functionality only supports unique names for tools, making it hard for addition of tools from different gateways with similar common names.

This needs to be updated so that tool names are allowed with a combination of gateway name (slugified namespace) and tool name. This would allow servers to add their own versions of the tools.

The tool names would be stored along with their original name in the database so that the correct server side name is passed while invoking it.

## Decision

We implemented this by making the following changes:

1. **Update IDs from integers to UUIDs**:
   - Modify the data type of `id` in `Gateway`, `Tool` and `Server` SQLAlchemy ORM classes from **int** to **str**
   - Use a default value of `uuid.uuid4().hex` for the IDs
   - Modify `server_id` and `tool_id` to *String* in `server_tool_association` table

2. **Separate server side and gateway side names for tools**:
   - Add a new field called `original_name` in Tool ORM class to store the MCP server side name used for invocation
   - Define a hybrid operator `name` to capture how the gateway exposes the tool. Set it as `f"{slugify(self.gateway.name)}{settings.gateway_tool_name_separator}{self.original_name}"`
   - Slugified `self.gateway.name` is used to remove spaces in new tool names
   - Hybrid operator is used so it can be used in Python and SQL code for filtering and querying
   - Add a new field called `gateway_slug` which is defined as the `slug` of the Gateway linked via `self.gateway_id`. This field is later used to extract the original name from name passed from APIs

3. **Addition of configurable environmental variable `GATEWAY_TOOL_NAME_SEPARATOR`** to set how the tool name looks like:
   - By default, this is set to `-` in config.py

4. **Updates Python object schemas, function data types** to match database ORM changes**
   - Change data type of `gateway_id`, `tool_id` and `server_id` from **int** to **str** in API functions
   - When storing and updating tools, use `original_name` in `DbTool` objects to store the original name coming from `_initiate_gateway`.
   - Remove check for only storing tools without matching original names
   - Check if `gateway.url` exists instead of `gateway.name` exists before thowing `GatewayNameConflictError`.
   - Check for existing tools on `original_name` and `gateway_id` instead of just `name` (as earlier) in **update_gateway** and **set_gateway_state** code.
   - Set `name` and `gateway_slug` just before passing to `ToolRead` seprately since these don't come from the database as these are properties and not columns.
   - To obtain tool from database for invocation, handle the case that `name` from the API is not stored as a column in the database, but is a property by making an appropriate comparison as `DbTool.gateway_slug + settings.gateway_tool_name_separator + DbTool.original_name == name`

5. **Handle tool changes from the gateway** by adding and removing tools based on latest deactivate/activate or edit:
   - Step 1: Add all tools not present in database based on `original_name` to `gateway.tools`
   - Step 2: Remove any tools not sent in the latest call to `_initialize_gateway` from `gateway.tools`.

6. **Show row index in UI**:
   - Display the index of the row with `loop.index` in a new column called `S. No.` in **Gateways**, **Tools** and **Servers** screens.

## Consequences

- Two gateways can have the tools with the same native name on the gateway. e.g. `gateway-1-get_system_time` and `gateway-2-get_system_time`.
- If the tools on a gateway change, they will reflect after **Deactivate/Activate** cycle or after **Edit Gateway** action.

## Alternatives Considered

| Option                           | Why Not                                                             |
|----------------------------------|----------------------------------------------------------------------|
| **Use qualified_name as display name and name as native MCP server name**        | Requires changes at more places since most clients display and call with the field `name`|

## Status

PR created: []()
