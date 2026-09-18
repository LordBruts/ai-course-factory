#!/usr/bin/env sh
# Re-fetch the vendored upstreams that video-production/ builds on.
#
# They are gitignored: two full clones, their own history, and test fixtures
# past GitHub's 100 MB limit. The pins below are what this project was built
# and tested against -- HyperFrames in particular changes behaviour between
# releases, and several workarounds in rendering/ are version-specific.
set -eu

VENDOR="$(cd "$(dirname "$0")/.." && pwd)/video-production/vendor"
mkdir -p "$VENDOR"

clone_at() {
  url="$1"; dir="$2"; sha="$3"
  if [ -d "$VENDOR/$dir/.git" ]; then
    echo "$dir: already present, leaving it alone"
    return
  fi
  git clone "$url" "$VENDOR/$dir"
  git -C "$VENDOR/$dir" checkout "$sha"
}

clone_at https://github.com/heygen-com/hyperframes.git  hyperframes 71b274bbfdfce9080d8a25e4ad096bfcfab6ef4c  # v0.8.42
clone_at https://github.com/browser-use/video-use.git   video-use   9575612f066aa517354790a645fd90f9f95a743b

echo "done"
