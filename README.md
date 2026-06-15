# kodi-addons

Personal Kodi addon repository. Source for a small, single-purpose service addon and its
distribution-wrapper repository addon. Built for serving via Cloudflare Pages.

## Build

```
ALFRED_REPO_URL=https://<your-pages-subdomain>.pages.dev python3 build_repo.py
```

Produces `dist-pages/` in Kodi addon-repository format. Deploy that directory as the
Cloudflare Pages output.

## Layout

- `plugin.service.alfredbridge/` — the service addon (polls a private API for commands)
- `repository.alfredbridge/` — the Kodi-side repository wrapper that points Kodi at this repo's hosting URL
- `build_repo.py` — packages both into the Kodi-format directory tree, generates `addons.xml` + `addons.xml.md5`
- `dist-pages/` — build output (committed so CF Pages can serve directly with no build step)
