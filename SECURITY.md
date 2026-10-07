# Security policy

## Reporting a problem

Please don't open a public issue. Report it privately instead:

- **Preferred:** [Report a vulnerability](https://github.com/erkambo/pisi/security/advisories/new)
  (GitHub's private reporting), or
- email [boyaciogluerkam@gmail.com](mailto:boyaciogluerkam@gmail.com) with
  "PISI security" in the subject.

Say what you found, how to reproduce it, and what someone could do with it.
You'll hear back within a week. Once it's fixed and released, you'll be
credited in the release notes if you'd like.

## Supported versions

Only the latest release gets fixes. New releases appear on the
[releases page](https://github.com/erkambo/pisi/releases) (watch the repo for
"Releases only" to hear about them); installing one over the old one keeps
your cat.

## What PISI handles, and how

Useful context for judging what matters:

- **No servers.** PISI has no account and no server of its own. It talks to
  Google only if you connect Google Calendar, to your calendar provider if you
  add an iCal address, and to nothing else (apart from one connection check
  when you run `--doctor`).
- **Your data folder** (settings, your cat, Google tokens, a private calendar
  address) is readable only by your user account.
- **The browser extension** sends PISI the shape of the page and yes/no
  signals, never page text or addresses, through the browser's native
  messaging to a socket only your user account can reach.
- **Google sign-in** uses PKCE and a loopback redirect on 127.0.0.1; PISI's
  permission only covers the one calendar it creates.
- **Releases** are built by GitHub Actions from tagged code, with
  `SHA256SUMS.txt` and build provenance you can check with
  `gh attestation verify <file> --repo erkambo/pisi`.

The full privacy policy is at <https://erkamboyacioglu.com/pisi/privacy/>.
