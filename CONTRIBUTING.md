# Contributing to treeloom

Thanks for your interest in contributing!

## Getting started

1. Fork the repository
2. Clone your fork locally
3. Create a branch for your change: `git checkout -b my-change`
4. Make your changes, with tests where applicable
5. Run the test suite and any linting the project uses
6. Open a pull request against `main`

## Commit messages

Use the [conventional commits](https://www.conventionalcommits.org/) format:

- `feat: add new feature`
- `fix: correct the X bug`
- `docs: update contributor guide`
- `refactor: simplify Y module`
- `test: add coverage for Z`
- `chore: update dependencies`

The commit body should explain the *why* behind the change, not just the *what*. A reader in six months should be able to understand the motivation without pulling up a design doc.

## Pull requests

- Keep PRs focused. One feature or fix per PR is ideal; split large changes into reviewable pieces.
- Include tests for new behavior.
- Update docs when you change user-facing behavior.
- Link related issues in the PR description (`Closes #123`, `Relates to #456`).
- Make sure CI is green before requesting review.

## Code style

Follow the conventions already in the codebase. If the project uses a formatter or linter, run it before pushing.

## Reporting bugs

Open an issue with:
- A clear description of what went wrong
- Steps to reproduce
- What you expected vs. what happened
- Version / commit hash

## Security issues

Do NOT open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md) for the private reporting process.

## Questions

Open an issue with the `question` label, or reach out via the contact in [SECURITY.md](SECURITY.md) for anything sensitive.

## Code of conduct

Be kind, be direct, and assume good intent. Technical disagreements are welcome; personal attacks are not.
