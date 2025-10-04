
# Package for sample rego policies
# Copyright 2025
# SPDX-License-Identifier: Apache-2.0
# Authors: Shriti Priya
# This file is responsible for rego policies for each type of requests made, it could be prompt, resource or tool requests

package example



# Default policy values for all the policies
default allow := false


# Policies applied for pre tool invocations
allow if {
    contains(input.payload.args.repo_path, "IBM")
}
