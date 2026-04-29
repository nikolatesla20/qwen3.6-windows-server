# Releasing a new launcher zip

End-to-end automated.

## One-time setup (REQUIRED while `devnen/vllm-windows` is private)

The release workflow downloads the patched wheel from the
`devnen/vllm-windows` release assets. The default `GITHUB_TOKEN` cannot
read another private repo, so create a fine-grained PAT:

1. Go to <https://github.com/settings/personal-access-tokens/new>.
2. Token name: `qwen36-windows-server-wheel-read`. Expiration: pick something reasonable.
3. Resource owner: `devnen`.
4. Repository access: *Only select repositories* → pick `devnen/vllm-windows`.
5. Repository permissions → **Contents: Read-only**. (Nothing else.)
6. Generate, copy the `github_pat_…` value.
7. In `devnen/qwen3.6-windows-server` → *Settings → Secrets and variables → Actions → New repository secret*:
   - Name: `WHEEL_RELEASE_TOKEN`
   - Value: the PAT.

Once `devnen/vllm-windows` is made public, this PAT is no longer
needed — the workflow falls back to `${{ secrets.GITHUB_TOKEN }}`
automatically.

## Release flow

### Option A — tag and push (recommended)

```powershell
git tag v0.1.1
git push origin v0.1.1
```

The `release.yml` workflow:

1. Resolves the latest `.whl` asset from `devnen/vllm-windows` (or uses
   `WHEEL_RELEASE_TOKEN` to read it from the private repo).
2. Downloads the wheel.
3. Runs `windows_tools/build_launcher_zip.py --wheel vllm.whl`.
4. Computes `SHA256SUMS.txt`.
5. Creates a GitHub Release on the tag with the zip + sums attached
   and notes from `dist/RELEASE_NOTES.md`.

### Option B — Actions UI

Go to *Actions → Release portable launcher → Run workflow*. Required:
`release_tag`. Optional: `wheel_url` if you want to pin a specific
patched wheel rather than picking up "latest".

## Coordinating with vllm-windows

Whenever you cut a new patched wheel on `devnen/vllm-windows` (e.g.
`v0.19.0-devnen.2`), bump this repo's tag too (`v0.1.2`) so the new
wheel ends up bundled in the launcher zip. Without a new tag here, the
release workflow won't fire.

## Skipping CI

If you need to build the zip locally (e.g. with a wheel from a private
build):

```powershell
python windows_tools\build_launcher_zip.py --wheel <path-to-wheel.whl>
gh release create v0.1.X --notes-file dist\RELEASE_NOTES.md `
    dist\qwen3.6-windows-server-portable-x64.zip dist\SHA256SUMS.txt
```

Regenerate `dist\SHA256SUMS.txt` first.
