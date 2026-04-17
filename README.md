![Firefox Browser](./docs/readme/readme-banner.svg)

[Firefox](https://firefox.com/) is a fast, reliable and private web browser from the non-profit [Mozilla organization](https://mozilla.org/).

### Contributing

To learn how to contribute to Firefox read the [Firefox Contributors' Quick Reference document](https://firefox-source-docs.mozilla.org/contributing/contribution_quickref.html).

We use [bugzilla.mozilla.org](https://bugzilla.mozilla.org/) as our issue tracker, please file bugs there.

### Resources

* [Firefox Source Docs](https://firefox-source-docs.mozilla.org/) is our primary documentation repository
* Nightly development builds can be downloaded from [Firefox Nightly page](https://www.mozilla.org/firefox/channel/desktop/#nightly)

### Interactive Build Script

Use top-level `build.py` to select build settings once and reuse them later.

```bash
./build.py
```

First run prompts for:
- platform (`linux-x86_64`, `linux-aarch64`, `macos`, `windows-x86_64`, `android-arm64`, `android-x86_64`)
- release type (`dev`, `nightly`, `beta`, `release`)
- build mode (`full`, `artifact`)
- debug/optimize/jobs/run-after-build flags

Selections are saved to `.build-last-config.json`.

Useful commands:

```bash
# Reuse saved selection
./build.py --last

# Show saved selection
./build.py --show-last

# Remove saved selection
./build.py --reset-last

# CI/script usage (no prompts)
./build.py --non-interactive \
  --platform macos \
  --release-type dev \
  --build-mode full \
  --debug \
  --no-optimize \
  --jobs auto \
  --no-run-after-build
```

Preview generated command without running build:

```bash
./build.py --last --print-command
```

If you have a question about developing Firefox, and can't find the solution
on [Firefox Source Docs](https://firefox-source-docs.mozilla.org/), you can try asking your question on Matrix at
chat.mozilla.org in the [Introduction channel](https://chat.mozilla.org/#/room/#introduction:mozilla.org).
