#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: cidr_allocate
author: Ansible
version_added: "1.0.0"
short_description: Allocate available CIDR blocks from a master range
description:
    - Finds and allocates one or more available CIDR blocks of a specified size within a master CIDR range.
    - Avoids conflicts with already-allocated CIDR blocks.
    - Uses a best-fit algorithm to efficiently utilize the address space by preferring the smallest available gap.
    - Can allocate multiple non-overlapping CIDR blocks in a single call.
options:
    master_cidr:
        description:
            - The master CIDR range from which to allocate (e.g., '172.16.0.0/12').
        required: true
        type: str
    used_cidrs:
        description:
            - List of CIDR blocks that are already in use and should be avoided.
            - Can be of varying prefix lengths.
        required: false
        type: list
        elements: str
        default: []
    prefix_length:
        description:
            - The desired prefix length for the new CIDR block(s) (e.g., 24 for a /24 network).
            - Must be >= the master CIDR's prefix length and <= 32.
        required: true
        type: int
    count:
        description:
            - The number of CIDR ranges to allocate.
            - Each range will be allocated using the best-fit algorithm.
            - Each allocation considers previously allocated ranges in the same call.
        required: false
        type: int
        default: 1
notes:
    - This module uses a best-fit algorithm to find the smallest available gap that can accommodate the requested CIDR block.
    - The allocated CIDR blocks will be properly aligned on network boundaries.
    - If insufficient blocks are available, the module will fail with an error message.
    - When allocating multiple blocks, each successive allocation treats previous allocations as used.
"""

EXAMPLES = r"""
# Allocate a single /24 network from a master /12 range
- name: Allocate single CIDR block
  cidr_allocate:
    master_cidr: '172.16.0.0/12'
    prefix_length: 24
    used_cidrs: []
  register: cidr_result

- name: Show allocated CIDR
  debug:
    msg: "{{ cidr_result.allocated_cidrs }}"

# Allocate a /24 avoiding already-used blocks
- name: Allocate CIDR block with exclusions
  cidr_allocate:
    master_cidr: '172.16.0.0/12'
    prefix_length: 24
    used_cidrs:
      - '172.16.0.0/16'
      - '172.17.0.0/16'
      - '172.18.5.0/24'
  register: cidr_result

# Allocate multiple CIDR blocks at once
- name: Allocate 3 /24 networks
  cidr_allocate:
    master_cidr: '10.0.0.0/8'
    prefix_length: 24
    count: 3
    used_cidrs: "{{ existing_cidrs }}"
  register: cidr_result

- name: Use the allocated CIDRs
  debug:
    msg: "Allocated CIDRs: {{ cidr_result.allocated_cidrs }}"
"""

RETURN = r"""
allocated_cidrs:
    description:
        - List of allocated CIDR blocks in standard notation (e.g., ['172.16.5.0/24'])
        - Will contain one element if count=1, or multiple elements if count > 1
    type: list
    elements: str
    returned: always
count:
    description:
        - The number of CIDR blocks that were allocated
    type: int
    returned: always
"""

import ipaddress
from ansible.module_utils.basic import AnsibleModule


class CIDRAllocator:
    """
    Handles the logic for finding and allocating available CIDR blocks.
    Uses a best-fit algorithm to minimize address space fragmentation.
    """

    def __init__(self, master_cidr, used_cidrs, prefix_length):
        """
        Initialize the CIDR allocator.

        Args:
            master_cidr: String representation of the master CIDR (e.g., '172.16.0.0/12')
            used_cidrs: List of already-allocated CIDR strings
            prefix_length: Desired prefix length for the new allocation (e.g., 24)
        """
        try:
            self.master_network = ipaddress.ip_network(master_cidr, strict=False)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid master CIDR '{master_cidr}': {str(e)}")

        self.prefix_length = prefix_length
        self.used_networks = []

        # Validate prefix length
        if not isinstance(prefix_length, int):
            raise ValueError(f"prefix_length must be an integer, got {type(prefix_length).__name__}")

        if prefix_length < self.master_network.prefixlen:
            raise ValueError(f"Requested prefix length ({prefix_length}) is smaller than master CIDR " f"prefix length ({self.master_network.prefixlen})")

        if prefix_length > 32:
            raise ValueError(f"Requested prefix length ({prefix_length}) must be <= 32")

        # Parse and validate used CIDRs
        for cidr in used_cidrs:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
                # Only include networks that overlap with master range
                if self._networks_overlap(network, self.master_network):
                    self.used_networks.append(network)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid CIDR in used_cidrs '{cidr}': {str(e)}")

        # Sort used networks by starting address for easier gap finding
        self.used_networks.sort(key=lambda net: net.network_address)

    def _networks_overlap(self, net1, net2):
        """Check if two networks overlap."""
        return net1.overlaps(net2)

    def _merge_overlapping_ranges(self):
        """
        Merge overlapping or adjacent used networks into contiguous ranges.
        Returns a list of (start_int, end_int) tuples representing used IP ranges.
        """
        if not self.used_networks:
            return []

        # Convert networks to integer ranges
        ranges = []
        for network in self.used_networks:
            start = int(network.network_address)
            end = int(network.broadcast_address)
            ranges.append((start, end))

        # Merge overlapping ranges
        merged = []
        current_start, current_end = ranges[0]

        for start, end in ranges[1:]:
            if start <= current_end + 1:  # Overlapping or adjacent
                current_end = max(current_end, end)
            else:
                merged.append((current_start, current_end))
                current_start, current_end = start, end

        merged.append((current_start, current_end))
        return merged

    def _find_available_gaps(self):
        """
        Find all gaps (unused ranges) in the master CIDR.
        Returns a list of (start_int, end_int) tuples.
        """
        master_start = int(self.master_network.network_address)
        master_end = int(self.master_network.broadcast_address)

        used_ranges = self._merge_overlapping_ranges()
        gaps = []

        # Check for gap before first used range
        if not used_ranges:
            gaps.append((master_start, master_end))
            return gaps

        if used_ranges[0][0] > master_start:
            gaps.append((master_start, used_ranges[0][0] - 1))

        # Check for gaps between used ranges
        for i in range(len(used_ranges) - 1):
            gap_start = used_ranges[i][1] + 1
            gap_end = used_ranges[i + 1][0] - 1
            if gap_start <= gap_end:
                gaps.append((gap_start, gap_end))

        # Check for gap after last used range
        if used_ranges[-1][1] < master_end:
            gaps.append((used_ranges[-1][1] + 1, master_end))

        return gaps

    def _find_aligned_cidr_in_gap(self, gap_start, gap_end):
        """
        Find a properly-aligned CIDR block of the desired prefix length within a gap.

        Args:
            gap_start: Starting IP address (as integer) of the gap
            gap_end: Ending IP address (as integer) of the gap

        Returns:
            ipaddress.IPv4Network object if found, None otherwise
        """
        # Calculate the size of the network we want to allocate
        network_size = 2 ** (32 - self.prefix_length)

        # Find the alignment requirement (CIDR blocks must start on specific boundaries)
        alignment = network_size

        # Find the first aligned address >= gap_start
        aligned_start = gap_start
        if gap_start % alignment != 0:
            aligned_start = ((gap_start // alignment) + 1) * alignment

        # Check if the aligned network fits in the gap
        aligned_end = aligned_start + network_size - 1

        if aligned_end <= gap_end:
            # Create and return the network
            network_addr = ipaddress.IPv4Address(aligned_start)
            return ipaddress.ip_network(f"{network_addr}/{self.prefix_length}", strict=False)

        return None

    def allocate_single(self):
        """
        Find and return a single available CIDR block using best-fit algorithm.

        Returns:
            String representation of the allocated CIDR block

        Raises:
            ValueError if no suitable block can be found
        """
        gaps = self._find_available_gaps()

        if not gaps:
            raise ValueError(f"No available address space in master CIDR {self.master_network}. " f"All addresses are allocated.")

        # For each gap, try to find a valid CIDR allocation
        # Store tuples of (gap_size, cidr_network, gap_info) for best-fit selection
        candidates = []

        for gap_start, gap_end in gaps:
            cidr = self._find_aligned_cidr_in_gap(gap_start, gap_end)
            if cidr:
                gap_size = gap_end - gap_start + 1
                candidates.append((gap_size, cidr, (gap_start, gap_end)))

        if not candidates:
            # Calculate how much space we need
            needed_size = 2 ** (32 - self.prefix_length)
            raise ValueError(
                f"Cannot allocate /{self.prefix_length} network in {self.master_network}. "
                f"No suitable gaps found. Need {needed_size} contiguous addresses. "
                f"Available gaps: {[f'{ipaddress.IPv4Address(s)}-{ipaddress.IPv4Address(e)} '
                f'({e-s+1} addresses)' for s, e in gaps]}"
            )

        # Sort by gap size (smallest first) for best-fit algorithm
        candidates.sort(key=lambda x: x[0])

        # Return the CIDR from the smallest gap
        _, best_cidr, _ = candidates[0]
        return str(best_cidr)

    def allocate_multiple(self, count):
        """
        Allocate multiple non-overlapping CIDR blocks.

        Args:
            count: Number of CIDR blocks to allocate

        Returns:
            List of allocated CIDR block strings

        Raises:
            ValueError if the requested count cannot be satisfied
        """
        allocated = []

        for i in range(count):
            try:
                cidr = self.allocate_single()
                allocated.append(cidr)
                # Add the newly allocated CIDR to used_networks for next iteration
                network = ipaddress.ip_network(cidr, strict=False)
                self.used_networks.append(network)
                # Re-sort used networks
                self.used_networks.sort(key=lambda net: net.network_address)
            except ValueError as e:
                raise ValueError(f"Could only allocate {len(allocated)} of {count} requested CIDR blocks. " f"Error: {str(e)}")

        return allocated


def run_module():
    """
    Main module execution.
    """
    # Define module arguments
    module_args = dict(
        master_cidr=dict(type="str", required=True),
        used_cidrs=dict(type="list", elements="str", default=[]),
        prefix_length=dict(type="int", required=True),
        count=dict(type="int", default=1),
    )

    # Initialize module
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    # Get parameters
    master_cidr = module.params["master_cidr"]
    used_cidrs = module.params["used_cidrs"]
    prefix_length = module.params["prefix_length"]
    count = module.params["count"]

    # Validate count
    if count < 1:
        module.fail_json(msg=f"count must be at least 1, got {count}")

    try:
        # Create allocator and find available CIDRs
        allocator = CIDRAllocator(master_cidr, used_cidrs, prefix_length)

        if count == 1:
            allocated_cidrs = [allocator.allocate_single()]
        else:
            allocated_cidrs = allocator.allocate_multiple(count)

        # Return success with allocated CIDRs
        module.exit_json(changed=False, allocated_cidrs=allocated_cidrs, count=len(allocated_cidrs))  # This is a read-only operation

    except ValueError as e:
        module.fail_json(msg=str(e))
    except Exception as e:
        module.fail_json(msg=f"Unexpected error: {str(e)}")


def main():
    run_module()


if __name__ == "__main__":
    main()
