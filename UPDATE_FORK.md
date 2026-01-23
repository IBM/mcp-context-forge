To merge latest changes into fork
Create a new branch
```
git switch main
git pull
git branch <New_branch>
git switch <New_branch>
```

Pull latest content from public github

```
git remote add upstream https://github.com/IBM/mcp-context-forge.git
git remote -v
git fetch upstream

git merge upstream/main
git push origin <New_branch>
```

Create a PR and verify that build is working
