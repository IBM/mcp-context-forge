
# Package for sample rego policies
# Copyright 2025
# SPDX-License-Identifier: Apache-2.0
# Authors: Shriti Priya
# This file is responsible for rego policies for each type of requests made, it could be prompt, resource or tool requests

package example


# Default policy values for all the policies
default allow := false
default allow_tool_pre_invoke := false
default allow_tool_post_invoke := false
default allow_prompt_pre_fetch := false
default allow_prompt_post_fetch := false
default allow_resource_pre_fetch := false
default allow_resource_post_fetch := false


barred_pattern := `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z0-9-.]+`

contains_word(pattern) if {
    some key
    value := input.payload.args[key]
    contains(value,pattern)
}

parse_url_regex(url) := components if {
    # Regex pattern: (protocol)://(domain)(port)?(path)?
    pattern := `(https?)://([^:^/]*)(:\d*)?(.*)?`
    matches := regex.find_all_string_submatch_n(pattern, url, 1)

    match := matches[0]
    components := {
        "protocol": match[1],
        "domain": match[2],
        "port": trim_prefix(match[3], ":"),
        "path": match[4]
    }
}

contains_regex_pattern if {
    some i
    value := input.payload.text[i]
    output := regex.find_all_string_submatch_n(barred_pattern, value, -1)
    count(output)>0
}

allow if {
    contains(input.payload.args.repo_path, "IBM")
}

allow_tool_pre_invoke if {
    input.mode == "input"
    contains_word("IBM")
}

allow_prompt_pre_fetch if {
    input.mode == "input"
    not contains_word("curseword1")
}

allow_tool_post_invoke if {
    input.mode == "output"
    not contains_regex_pattern
}

allow_prompt_post_fetch if {
    input.mode == "output"
    not contains_regex_pattern
}

allow_resource_post_fetch if {
    input.mode == "output"
    not contains_regex_pattern
}

allow_resource_pre_fetch if {
    components := parse_url_regex(input.payload.uri)
    not contains(components.path, "root")
}
