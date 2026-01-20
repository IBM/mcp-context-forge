# Pushing Updates to IBM/mcp-context-forge

## Pre-reqs
Create your own fork of the public repo

## Gather changes

Find commit related to PR

	git log --grep="CYFR-XXX"

Get get commit sha from the commit.

Create a diff file of the contents of the commit. Example

    git diff 171481d1109544f8ad7c94060fd16660747b8460^ 171481d1109544f8ad7c94060fd16660747b8460 > CYFR-XXX_changes.diff

## Apply changes to public github.com fork and create PR

On public forked repo, create a branch and apply the changes

    git apply CYFR-XXX_changes.diff

Create a PR from that branch into the public repo



