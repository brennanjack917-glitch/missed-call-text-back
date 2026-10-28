# Going public: checklist

Do this before switching the GitHub repo from private to public. Checked 2026-10-27.

## What the scan found

- **No secrets** in the files or the Git history: no API keys, passwords, `.env` or database.
- **Your email address is on every commit.** Git stamps the author's email on each commit, and anyone can read it on a public repo.
- **Old personal notes are in the history.** The first commits contain the old CLAUDE.md (your job and other projects). The current CLAUDE.md no longer has them, but the history keeps every old version.

## Recommended: publish from a fresh copy

This gives the public repo a clean history with one starting commit, and keeps the current private repo as your full archive.

1. **Hide your email on future commits.** On github.com: Settings → Emails → tick **Keep my email addresses private**. Copy the address it shows (it ends in `@users.noreply.github.com`). In GitHub Desktop: File → Options → Git → set **Email** to that address.
2. **Make a clean copy of the project folder** without its history. Copy `C:\Claude\missed call text back` to a new folder, for example `C:\Claude\missed-call-text-back-public`, then delete the hidden `.git` folder inside the copy (and `.venv`, `data` and `.env`, which aren't needed there).
3. **Create the new repo:** in GitHub Desktop, File → Add local repository → choose the copy → "create a repository" → Publish, and **untick "Keep this code private"**.
4. **Check it on github.com:** the README shows the screenshots and diagram, the Tests badge turns green after the first run, and `.env` is not listed.
5. **Rename or archive the old private repo** so the names don't clash, and update the badge links in README.md if the new repo has a different name.

## Before either option

- [ ] Run the secrets scan again (ask Claude: "run the going-public secrets scan").
- [ ] Decide on a license. For now there is none: people can read the code but not reuse it, which keeps the option to sell open.
- [ ] Set a monthly spend limit for this project's workspace in the Anthropic Console (the key never goes to GitHub, but the limit is a backstop).
- [x] Optional: record a 30-second demo video (Win + Shift + R in Snipping Tool) for the README. Done 2026-10-27.
