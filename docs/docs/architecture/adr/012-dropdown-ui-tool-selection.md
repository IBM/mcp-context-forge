# ADR-0012: Display available tools in a dropdown and allow selection from there for creating a server

- *Status:* Draft
- *Date:* 2025-06-22
- *Deciders:* Core Engineering Team

## Context

The current solution provides a text box for users where they can enter tool ids to link to a server

With the change of IDs from integers to UUIDs, this process is more cumbursome.

This is modified so that users can select from tool names from a drop down.

## Decision

We implemented this by making the following changes:

1. **Replace text box with a dropdown element** keeping the styling consistent with the to the tailwind styling used
   - Users select names, but the selected tool `id`s are sent to the API for databse storage
   - Make this change in server creation and editing screens

2. **Add a span to display selected tools**
   - Display the selected tools below the dropdown
   - Show a warning if more than 6 tools are selected in a server. This is to encourage small servers more suited for use with agents.

## Screenshots
![Tool selection screen](tool-selection-screen.png)
*Tool selection screen*

![Tool count warning](tool-count-warning.png)
*Tool count warning*
## Status

PR created: []()