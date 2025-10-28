#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workaround script for mutmut v3 stats collection failure.
Generates mutants and then runs them despite stats failure.
"""

# Standard
import os
from pathlib import Path
import subprocess
import sys


def run_command(cmd):
    """Run a shell command and return output."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def main():
    # Check for command line arguments
    sample_mode = "--sample" in sys.argv or len(sys.argv) == 1  # Default to sample mode
    sample_size = 20  # Default sample size

    if "--full" in sys.argv:
        sample_mode = False
        print("🧬 Starting FULL mutation testing (this will take a long time)...")
    else:
        print("🧬 Starting mutation testing (sample mode)...")
        print("💡 Tip: Use 'python run_mutmut.py --full' for complete testing")

    # Clean previous runs
    print("🧹 Cleaning previous mutants...")
    os.system("rm -rf mutants .mutmut-cache")

    # Generate mutants (will fail at stats but mutants are created)
    print("📝 Generating mutants (this may take a minute)...")
    stdout, stderr, _ = run_command("mutmut run --max-children 2 2>&1 || true")

    # Show some output to indicate progress
    if "done in" in stdout:
        # Standard
        import re

        match = re.search(r"done in (\d+)ms", stdout)
        if match:
            print(f"  Generated in {int(match.group(1)) / 1000:.1f} seconds")

    # Check if mutants were generated
    if not Path("mutants").exists():
        print("❌ Failed to generate mutants")
        return 1

    print("✅ Mutants generated successfully")

    # Get list of mutants
    print("📊 Getting list of mutants...")
    stdout, stderr, _ = run_command("mutmut results 2>&1 | grep -E 'mutmut_[0-9]+:' | cut -d: -f1")
    all_mutants = [m.strip() for m in stdout.strip().split("\n") if m.strip()]

    if not all_mutants:
        print("❌ No mutants found")
        return 1

    # Sample mutants for quicker testing
    # Standard
    import random

    print(f"🔍 Found {len(all_mutants)} total mutants")

    if sample_mode:
        actual_sample_size = min(sample_size, len(all_mutants))
        mutants = random.sample(all_mutants, actual_sample_size)
        print(f"📈 Testing a sample of {len(mutants)} mutants for quick results")
    else:
        mutants = all_mutants
        print(f"🚀 Testing ALL {len(mutants)} mutants (this will take a while)...")

    # Run each mutant
    results = {"killed": 0, "survived": 0, "timeout": 0, "error": 0}
    survived_mutants = []

    for i, mutant in enumerate(mutants, 1):
        print(f"  [{i}/{len(mutants)}] Testing {mutant}...", end=" ", flush=True)

        # Run the mutant with a shorter timeout and minimal tests
        cmd = f"timeout 10 bash -c 'cd mutants && MUTANT_UNDER_TEST={mutant} python -m pytest tests/unit/mcpgateway/utils/ -x --tb=no -q 2>&1'"
        stdout, stderr, returncode = run_command(cmd)

        if returncode == 124:  # timeout
            print("⏰ TIMEOUT")
            results["timeout"] += 1
        elif returncode == 0:  # tests passed = mutant survived
            print("🙁 SURVIVED")
            results["survived"] += 1
            survived_mutants.append(mutant)
        elif "FAILED" in stdout or returncode != 0:  # tests failed = mutant killed
            print("🎉 KILLED")
            results["killed"] += 1
        else:
            print("❓ ERROR")
            results["error"] += 1

    # Print summary
    print("\n" + "=" * 50)
    print("📊 MUTATION TESTING RESULTS:")
    print("=" * 50)
    print(f"🎉 Killed:    {results['killed']} mutants")
    print(f"🙁 Survived:  {results['survived']} mutants")
    print(f"⏰ Timeout:   {results['timeout']} mutants")
    print(f"❓ Error:     {results['error']} mutants")

    total = sum(results.values())
    if total > 0:
        score = (results["killed"] / total) * 100
        print(f"\n📈 Mutation Score: {score:.1f}%")

        if sample_mode and len(all_mutants) > len(mutants):
            estimated_total_score = score  # Rough estimate
            print(f"📊 Estimated overall score: ~{estimated_total_score:.1f}% (based on sample)")

    # Show surviving mutants if any
    if survived_mutants and len(survived_mutants) <= 5:
        print("\n⚠️  Surviving mutants (need better tests):")
        for mutant in survived_mutants[:5]:
            print(f"  - {mutant}")
            print(f"    View with: mutmut show {mutant}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
