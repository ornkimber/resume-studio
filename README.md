# Resume Studio

A local resume editor that turns structured YAML or TOML into styled Word documents.
The desktop app uses Tauri, React, and TypeScript, with a Python/python-docx engine
for document generation. Export the resulting DOCX to PDF in Word when ready.

All included resume data is fictional. The English sample uses **John Doe** and
the Chinese sample uses **陈大文**. Employers, schools, achievements, and locations
are invented, and contact links use `example.com`.

## Features

- YAML and TOML editing for resume content and styles, with explicit conversion.
- Live document preview and actionable generation errors.
- Saved versions, source comparisons, document comparisons, and restore.
- English and Chinese typography using the reference Python renderer.
- Local draft storage, source import/export, workspace backups, and DOCX export.

The preview is approximate; review final pagination in Word. PDF export is a
separate step, and the app does not upload resumes to a server.

## Start the desktop app

Windows development requires Python 3.11+, Node.js 24 LTS, npm, Rust with the MSVC
toolchain, Microsoft C++ Build Tools, and WebView2. The pinned Rust toolchain is
selected by `resume-studio/rust-toolchain.toml`.

```powershell
cd resume-studio
python -m pip install -r python/requirements.txt
npm ci
npm run desktop
```

For browser development, run `npm run dev` instead and open
`http://127.0.0.1:1420`. The development server starts the same Python engine.
See [the application README](resume-studio/README.md) for storage, recovery,
architecture, and detailed build instructions.

## Build a Windows installer

From `resume-studio/`:

```powershell
python -m pip install -r python/requirements-build.txt
npm ci
npm run desktop:build
```

The installer is created in `src-tauri/target/release/bundle/nsis/`. It includes
Python and the document libraries. The installer is currently unsigned.

## Repository layout

- `resume-studio/`: desktop application, Python adapter, tests, and fictional fixtures.
- `generate_resume.py`: original YAML-to-DOCX CLI and reference rendering implementation.
- `resume_en.yaml`, `resume_zh.yaml`: fictional samples matching the app fixtures.
- `style_config.yaml`, `style-guide.md`: reference formatting configuration and notes.
- `resume_builder_ui.py`, `build_exe.ps1`: optional legacy Tkinter UI and build script.
- `export_pdf_word.ps1`: optional DOCX-to-PDF helper using an installed Microsoft Word.
- `scripts/`: public-sample checks and release-version validation.
- `.github/`: CI, draft release automation, and dependency update configuration.

The legacy CLI remains available from the repository root:

```powershell
python -m pip install -r resume-studio/python/requirements.txt
python generate_resume.py --input resume_en.yaml --config style_config.yaml --lang en --output resume_en.docx
python generate_resume.py --input resume_zh.yaml --config style_config.yaml --lang zh --output resume_zh.docx
.\export_pdf_word.ps1 -Both
```

The legacy CLI accepts YAML. The app and `resume-studio/python/engine.py` accept
both YAML and TOML. Supported resume sections are `summary`, `skills`,
`experience`, `education`, and `bullets`. Edit fonts, spacing, margins, date
alignment, and language overrides in the style configuration.

## CI and releases

[GitHub Actions](.github/workflows/ci.yml) runs on pushes, pull requests, and manual
dispatch. It checks fictional fixtures and tracked files, runs TypeScript, Python,
browser, and Rust tests, builds the Windows installer, and exercises the packaged
Python engine in both languages. Successful runs expose a Windows installer and
SHA-256 checksums as an artifact. Actions are pinned to commit hashes; Dependabot
proposes action and dependency updates.

To prepare a release, update the version in `resume-studio/package.json`,
`resume-studio/src-tauri/Cargo.toml`, and `resume-studio/src-tauri/tauri.conf.json`,
then refresh the npm and Cargo lockfiles. Commit the version change and push a
matching tag such as `v0.1.0`. After all checks pass, the workflow creates a
**draft GitHub release** containing the installer and checksums. Review it in
GitHub and publish when ready. Reruns can update draft assets but cannot overwrite
an already published release.

The workflow uses the repository's built-in `GITHUB_TOKEN`; no personal token or
signing secret is required. GitHub Actions must be enabled on the destination
repository. Hosted CI and release jobs run only after the repository is pushed.
The action setup follows the official [checkout](https://github.com/actions/checkout),
[Node.js](https://github.com/actions/setup-node), and
[Python](https://github.com/actions/setup-python) action documentation.

## Keep personal data local

Keep real resume sources and exports outside this repository or in the ignored
`private/` directory. Do not replace the committed fictional fixtures with a real
resume. Workspaces, backup files, generated documents, binaries, dependency folders,
and build/test caches are ignored. App data is stored outside the checkout; browser
development data lives in the ignored `resume-studio/.test-data/` directory.

Before committing, run `python scripts/check_public_tree.py` and review
`git diff --cached`. The checker catches known artifact paths and changes to the
fictional sample identities; it is not a general detector for personal information
or credentials. Git retains committed content even after a file is deleted, so
review staged content before the first public push.
