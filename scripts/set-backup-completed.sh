#!/bin/bash
# Script to update the backupCompleted flag in my-values.yaml after successful backup

set -e

echo "This script will update the postgres.upgrade.backupCompleted flag to true in my-values.yaml"
echo "This will prevent the backup job from running again on subsequent upgrades."
echo

read -p "Do you want to proceed? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Update the my-values.yaml file to set backupCompleted to true
    sed -i 's/backupCompleted: false/backupCompleted: true/' my-values.yaml

    echo "Updated postgres.upgrade.backupCompleted to true in my-values.yaml"
    echo "You can now safely upgrade/redeploy without running the backup job again."
else
    echo "Operation cancelled."
fi
