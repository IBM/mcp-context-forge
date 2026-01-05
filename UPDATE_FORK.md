git remote add upstream https://github.com/IBM/mcp-context-forge.git
git remote -v
git fetch upstream

git checkout main
git merge upstream/main
git push origin main
