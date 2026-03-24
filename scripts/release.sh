#!/usr/bin/env bash
#
# release.sh - Automated release script for treeloom
#
# Usage: ./scripts/release.sh <version> "<description>"
#
# Example: ./scripts/release.sh 0.1.0 "Initial release"
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }
print_info() { echo -e "${YELLOW}ℹ${NC} $1"; }

if [ $# -ne 2 ]; then
    print_error "Usage: $0 <version> <commit-message>"
    echo "Example: $0 0.1.0 \"Initial release\""
    exit 1
fi

VERSION=$1
COMMIT_MSG=$2

if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    print_error "Invalid version format: $VERSION"
    echo "Version must be in format: x.y.z (e.g., 0.1.0)"
    exit 1
fi

print_info "Preparing release v$VERSION"
echo

if [ ! -f "pyproject.toml" ] || [ ! -f "src/treeloom/version.py" ]; then
    print_error "Must run from project root directory"
    exit 1
fi

if ! git diff --quiet --exit-code -- ':!src/treeloom/version.py' ':!pyproject.toml' ':!README.md'; then
    print_error "You have uncommitted changes. Please commit or stash them first."
    git status --short
    exit 1
fi

print_info "Updating src/treeloom/version.py to $VERSION"
sed -i.bak "s/^__version__ = .*/__version__ = \"$VERSION\"/" src/treeloom/version.py
rm -f src/treeloom/version.py.bak
print_success "Updated version.py"

print_info "Updating pyproject.toml to $VERSION"
sed -i.bak "s/^version = .*/version = \"$VERSION\"/" pyproject.toml
rm -f pyproject.toml.bak
print_success "Updated pyproject.toml"

print_info "Verifying version updates..."
VERSION_PY=$(grep -E '^__version__' src/treeloom/version.py | cut -d'"' -f2)
VERSION_TOML=$(grep -E '^version' pyproject.toml | head -1 | cut -d'"' -f2)

if [ "$VERSION_PY" != "$VERSION" ] || [ "$VERSION_TOML" != "$VERSION" ]; then
    print_error "Version verification failed!"
    echo "  version.py: $VERSION_PY"
    echo "  pyproject.toml: $VERSION_TOML"
    echo "  expected: $VERSION"
    exit 1
fi
print_success "Version verification passed"

echo
print_info "Changes to be committed:"
git diff src/treeloom/version.py pyproject.toml README.md
echo

print_info "Committing changes..."
git add src/treeloom/version.py pyproject.toml README.md
git commit -m "$COMMIT_MSG"
print_success "Changes committed"

print_info "Pushing to main..."
git push origin main
print_success "Pushed to main"

print_info "Creating tag v$VERSION..."
git tag "v$VERSION"
print_success "Tag created"

print_info "Pushing tag v$VERSION..."
git push origin "v$VERSION"
print_success "Tag pushed"

echo
print_success "Release v$VERSION initiated!"
echo
echo "GitHub Actions will now:"
echo "  1. Create GitHub Release"
echo "  2. Build distribution packages"
echo "  3. Publish to PyPI"
echo
echo "Monitor progress at: https://github.com/rdwj/treeloom/actions"
echo "View release at: https://github.com/rdwj/treeloom/releases/tag/v$VERSION"
