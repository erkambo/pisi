# PISI and Google: verification

Goal: friends click **Connect** in Settings → Google Calendar and see a normal
Google sign-in for "PISI", with nothing to paste and no warnings.

What PISI asks for: one permission,
`https://www.googleapis.com/auth/calendar.app.created` ("Make secondary
Google calendars, and see, create, change, and delete events on them"). In
the Google Cloud console this is a **non-sensitive** scope (checked October
2026), so Google's Verification Center says data-access verification isn't
required: no scope review and no demo video. The only check left is
**brand verification**, so the sign-in screen shows PISI's name.

Pages (in `site/`, published on the website repo `erkambo/erkamboyacioglu.com`
in a `pisi/` folder):

| Page | URL |
|---|---|
| Homepage | `https://erkamboyacioglu.com/pisi/` |
| Privacy policy | `https://erkamboyacioglu.com/pisi/privacy/` |

Everything below uses one Google account (boyaciogluerkam@gmail.com).

## 1. Domain ownership (Search Console): done

`erkamboyacioglu.com` is a verified **Domain** property in
<https://search.google.com/search-console>. The TXT record lives in
Namecheap → Domain List → Manage → Advanced DNS (host `@`). Leave it there.

## 2. Cloud project: done

Project **PISI** in <https://console.cloud.google.com/>, with the
**Google Calendar API** enabled.

## 3. Google Auth Platform

- **Branding:** app name `PISI`, support email, home page and privacy policy
  (above), authorized domain `erkamboyacioglu.com`. No logo yet (a logo can be
  added later; it's checked with the brand).
- **Audience:** External, **In production**. (Leaving it in "Testing" makes
  connections expire after 7 days.)
- **Data access:** `.../auth/calendar.app.created`, listed under
  non-sensitive scopes.
- **Clients:** a **Desktop app** client, `PISI desktop`. Keep its JSON file
  somewhere safe, outside the repo.
- **Verification Center:** submit **branding** for verification (a few
  business days). Data access shows "verification is not required".

## 4. Give the client to PISI

Release builds bake it in from two repository secrets (it is never committed;
`scripts/stage_google_client.py` writes it at build time):

```bash
gh secret set PISI_GOOGLE_CLIENT_ID --repo erkambo/pisi      # paste the ID
gh secret set PISI_GOOGLE_CLIENT_SECRET --repo erkambo/pisi  # paste the secret
```

To use it from source, paste the same ID and secret into PISI's
**Settings → Google Calendar**.

## If PISI ever needs more

Adding any other calendar permission (for example reading your other
calendars) can make it sensitive, which needs Google's sensitive-scope review:
a scope justification and an unlisted YouTube demo video of the sign-in and of
PISI using the permission. Prefer the narrowest scope that does the job.
