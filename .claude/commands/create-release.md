# Create Release

Help me create a new release of treeloom.

## Steps

1. Ask me for the version number (should follow semver: major.minor.patch)
2. Ask me for a brief description of what changed in this release
3. Update the changelog section in README.md with the new version entry (newest first)
4. Run the release script: `./scripts/release.sh <version> "<description>"`

## Notes

- The release script handles updating version.py, pyproject.toml, committing, tagging, and pushing
- GitHub Actions will automatically create a GitHub Release and publish to PyPI
- Make sure all tests pass before releasing: `pytest`
- Make sure linting passes: `ruff check src tests`
