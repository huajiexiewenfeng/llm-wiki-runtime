# Third-Party Notices

These browser assets are checked in and run fully offline. `npm ci && npm test && npm run build` is a maintainer-only update command; Python installation, builds, and graph export never invoke npm. Bundle integrity is recorded in `ASSET_CHECKSUMS.json`.

| Package | Version | Source | License | Role |
| --- | --- | --- | --- | --- |
| `sigma` | `3.0.3` | https://github.com/jacomyal/sigma.js | MIT | Runtime bundle |
| `graphology` | `0.26.0` | https://github.com/graphology/graphology | MIT | Runtime bundle |
| `graphology-utils` | `2.5.2` | https://github.com/graphology/graphology | MIT | Runtime bundle |
| `events` | `3.3.0` | https://github.com/browserify/events | MIT | Runtime bundle |
| `esbuild` | `0.28.1` | https://github.com/evanw/esbuild | MIT | Maintainer build only |
| `playwright` | `1.61.1` | https://github.com/microsoft/playwright | Apache-2.0 | Maintainer browser test only |
| `playwright-core` | `1.61.1` | https://github.com/microsoft/playwright | Apache-2.0 | Maintainer browser test only |

## Runtime MIT Notices

Sigma: Copyright (C) 2013-2025, Alexis Jacomy, Guillaume Plique, Benoit Simard.

Graphology: Copyright (c) 2016-2021 Guillaume Plique (Yomguithereal).

Graphology Utils: Copyright (c) 2017-2021 Guillaume Plique (Yomguithereal).

Events: Copyright Joyent, Inc. and other Node contributors.

The following MIT text is copied from the locked runtime packages:

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Apache License 2.0

Playwright and Playwright Core are licensed under the Apache License, Version 2.0. A copy of the complete license is available in the locked package at `web/node_modules/playwright/LICENSE` when maintainers refresh these assets.
