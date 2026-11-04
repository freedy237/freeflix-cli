# Security policy

FreeFlix is a terminal client that talks to third-party streaming sites and
plays the resulting streams locally. It does not host or distribute content.

## Supported versions

Only the latest released version receives security fixes. Run
`freeflix --version` and `uv tool upgrade freeflix-cli` (or the installer of
your channel) before reporting.

## Reporting a vulnerability

Open a private report through GitHub Security Advisories
(<https://github.com/freedy237/freeflix-cli/security/advisories/new>) rather
than a public issue. Include the version, OS, steps to reproduce, and the
impact. Please do not include live cookies or tokens in the report.

## Security model

| Surface | Protection |
|---|---|
| Local HLS/MP4 proxy | Binds `127.0.0.1` only, random port, and requires a per-process capability token (`?k=…`) on every media/subtitle endpoint. Other local processes cannot use it as a relay. |
| SSRF | Target hostnames are rejected when they resolve to loopback, private, link-local or reserved addresses (IPv4, IPv6, obfuscated literals). Subtitle serving is jailed to the temp dir and the downloads dir. |
| Credentials | The AniList token and settings live in `progress.json` (mode `0600`, atomic write). Resume metadata strips `Cookie`, `Authorization`, `Proxy-Authorization`, `X-Api-Key` and `X-Auth-Token`, and is written `0600`. Signed CDN URLs are masked (`?…`) in the UI and logs. |
| DNS fallback | DoH uses the system certificate store (verification enabled). DoH is only a fallback; a failing resolver cannot silently downgrade TLS. |
| Windows notifications | Toast XML is written to a temporary file and loaded by path — scraped titles are never interpolated into a PowerShell command. |
| PATH setup | Windows updates the user `Path` through `winreg` (`REG_EXPAND_SZ`), preserving `%USERPROFILE%`-style entries; no `setx` truncation. |
| Updates | `update_checker` only upgrades through the detected installer (uv/pipx/pip) and never overwrites a source checkout. |
| Downloads | Staged in `.temp/`, verified (duration/size) before an atomic move; incomplete files are never published. |

## Known limitations

- The project scrapes third-party sites; a compromised site can serve a
  malicious media file. Playback relies on mpv/VLC/ffmpeg hardening.
- Some hosts require passing their gate cookies to the CDN. Those cookies stay
  in memory, are never written to `progress.json`, and are stripped from the
  resume metadata.
- The optional Cloudflare solver (FlareSolverr) runs in a container managed by
  the user; its security is the container runtime's.
- Installer scripts download `uv` from GitHub. Checksums for the application
  artifacts are published on each release (`SHA256SUMS`); verify them if you
  install a standalone binary manually.

## Dependency hygiene

`rich` is bounded (`>=14.2,<15`) because the alt-screen handoff uses one
private attribute; `curl-cffi`, `lxml`, `pycryptodome` and the rest are pinned
by `uv.lock` for reproducible builds. CI runs on Linux, Windows and macOS with
Python 3.9–3.13.
