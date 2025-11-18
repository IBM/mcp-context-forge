-- Set colorcolumn to 200 for Python files only
vim.api.nvim_create_autocmd("FileType", {
    pattern = "python",
    callback = function()
        vim.opt_local.colorcolumn = "200"
    end,
})

-- Set up for line formatting .md files to a 120-character limit
vim.api.nvim_create_autocmd("FileType", {
    pattern = "markdown",
    callback = function()
        vim.opt_local.colorcolumn = "120"
        vim.opt_local.textwidth = 120
    end,
})

--
--  Project settings for ALE (Asynchronous Lint Engine)
--  ALE is available at https://github.com/dense-analysis/ale
--
vim.g.ale_linters = {
    make = {},
    python = { "mypy", "ruff", "flake8", "pylint" },
    markdown = { "markdownlint" },
}
vim.g.ale_python_auto_uv = 1

vim.g.ale_python_mypy_options = "--no-pretty"
vim.g.ale_python_ruff_options = "--extend-select I"
vim.g.ale_markdown_markdownlint_executable = "markdownlint-cli2"

vim.g.ale_fixers = {
    python = { "ruff", "black" },
}
