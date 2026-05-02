# Releasing a new launcher zip

End-to-end automated.

## One-time setup

None required. `devnen/vllm-windows` is public, so the release workflow
downloads the patched wheel using the default `${{ secrets.GITHUB_TOKEN }}`.
No PAT, no `WHEEL_RELEASE_TOKEN` secret needed.

> Historical note: while `devnen/vllm-windows` was private, this repo
> required a fine-grained `WHEEL_RELEASE_TOKEN` PAT with `Contents: Read`
> on the wheel repo. The workflow still honors that secret if it's set,
> but it's no longer necessary.

## Release flow

### Option A, tag and push (recommended)

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

### Option B, Actions UI

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
