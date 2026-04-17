# Repository Guidelines

## Maintenance Mode
- Prioritize safe, incremental maintenance work over broad refactors.
- Prefer minimal diffs that preserve existing behavior unless a behavior change is explicitly requested.
- Respect existing architecture and naming patterns before introducing new abstractions.
- When fixing bugs, identify the smallest reliable fix first, then add tests around the changed behavior.
- Do not touch unrelated services or infrastructure while making a focused maintenance change.

## Repository Boundary Rules
- Treat the currently opened repository as the only allowed filesystem scope unless the user explicitly approves otherwise for the current task.
- Never search, read, list, glob, or infer from files outside the current repository root.
- This prohibition includes parent directories, sibling repositories, home-directory files, hidden directories, mounted volumes, and tool-default search roots.
- Explicitly forbidden examples include paths or patterns such as `..`, `../*`, `~`, `~/*`, `/`, `/tmp`, `/var`, `/home/*`, and sibling repo paths.
- Explicitly forbidden targets include any external `.env` files, secret stores, model directories, SSH config, cloud credentials, shell history, and editor history.
- Do not run broad searches that can escape the repository boundary, such as unscoped `rg`, `grep`, `find`, or globbing from a parent or home directory.
- Before reading any config or env file, first constrain the path to a file or directory inside this repository.
- If a needed value is not available inside the repository, stop and ask for explicit approval before accessing anything outside it.
- A guess based on filenames, shell completion, prior habits, or nearby directories does not count as approval.
- Repository boundary and secret-handling rules override convenience. Do not expand search scope for speed, completeness, or debugging.

## Configuration & Security Notes
- Store secrets in environment variables (e.g., `API_TOKEN`, `DATABASE_URL`, `NEWS_LLM_BASE_URL`).
- Do not commit tokens or model paths; use `.env` or system envs when running locally.
- Repository-internal env/config files may be inspected only when needed for the current task, and only within this repository root.
- Allowed examples include `backend/.env`, `backend/.env.example`, and `backend/.env.secrets.example` when they exist in this repository.
- Read the minimum necessary scope only. Prefer targeted lookups such as `rg '^KEY=' backend/.env backend/.env.example backend/.env.secrets.example` over opening full files.
- Never search, read, or print environment files outside this repository unless the user explicitly approves it for the current task.
- This includes parent directories, sibling repositories, home-directory files, and generic secret locations such as `~/.env`, `~/.config`, `~/.aws`, `~/.ssh`, `~/ai-models`, or any `*.env` outside the repo.
- Never use indirect rendering commands that can expand or print secret values from outside the repository, even if they do not open the secret file explicitly.
- This includes commands such as `docker compose config`, `docker-compose config`, `env`, `printenv`, `set`, `export`, or templating/debug commands that may resolve `${VAR}` or `env_file` values into output.
- If compose inspection is needed, use targeted reads of repository files only, and avoid commands that materialize merged environment output unless the user explicitly approves that exact secret exposure for the current task.
- Do not use broad filesystem searches for secrets or config, including commands/patterns that start from `..`, `~`, `/`, or any non-repo root.
- Do not “helpfully” inspect adjacent projects, cached workspaces, or similarly named repositories.
- If a required secret/config value is not present inside the repository, state that it was not found in the repository and request explicit user approval before checking anywhere else.
- When referencing repo-internal env files, never print unrelated secrets; reveal only the specific key or line needed for the task.

### Safe search examples
- `rg '^DATABASE_URL=' backend/.env backend/.env.example`
- `rg '^NEWS_LLM_BASE_URL=' backend/.env.example backend/.env.secrets.example`
- `ls backend`
- `find backend -maxdepth 2 -type f`

### Forbidden search examples
- `rg 'DATABASE_URL|API_TOKEN' ..`
- `find .. -name '*.env'`
- `find ~ -name '*.env'`
- `rg 'NEWS_LLM_BASE_URL' /home`
- `ls ../other-repo`
- `cat ~/.env`
- `cat ~/ai-models/*.env`
- `docker compose config`
- `docker-compose config`
- `env | grep API_TOKEN`
