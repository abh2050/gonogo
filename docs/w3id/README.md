# Registering the w3id.org namespace

The ontology's namespace is `https://w3id.org/gonogo/ontology#`. It becomes a working link when the public
[perma-id/w3id.org](https://github.com/perma-id/w3id.org) repository contains an `ids/gonogo/` folder with the
files in [ids/gonogo/](ids/gonogo/). The service redirects and hosts nothing, so the redirect targets are the
project's Vercel site, where the generated documentation and the Turtle files are served.

What I did already:

- Wrote the redirect rules to the w3id.org guidelines: 303 for content-negotiated ontology IRIs, 302 for the rest,
  the most specific rule first, and an unconditional default last.
- Ran the repository's own checker on the folder. Result: "No problems found".
- Ran the rules on a local Apache that mirrors the live service, and checked 17 redirect cases. They are in
  `tests/integration/test_w3id.py`.
- Deployed the documentation and Turtle files to https://gonogo-livid.vercel.app/ontology/, with the correct
  `text/turtle` content type.

## What you do

1. Sign in to GitHub as `abh2050`, open https://github.com/perma-id/w3id.org, and choose **Fork**.
2. In your fork, choose **Add file → Create new file**. Type the whole path `ids/gonogo/.htaccess` into the
   filename box, because GitHub's editor accepts a leading dot only when the path has a folder in front of it.
   Paste the contents of [ids/gonogo/.htaccess](ids/gonogo/.htaccess), and commit to a new branch named
   `add-gonogo`.
3. Create a second file named `ids/gonogo/README.md` with the contents of [ids/gonogo/README.md](ids/gonogo/README.md).
4. Check the contact block at the top of the `.htaccess` file. It lists your name and GitHub username. Add an email
   address there if you want maintainers to be able to reach you by email. It is optional, and it becomes public.
5. Open a pull request from `add-gonogo` to the `master` branch of `perma-id/w3id.org`. Use the title
   `Add gonogo identifier`. In the description, say that it is an open ontology for patent license clearance, link
   https://github.com/abh2050/gonogo, and say that you maintain it.
6. Watch the pull request. An automated check comments on the changed lines if anything needs fixing, and a
   volunteer reviews it. Reviews usually take days.

Change nothing outside `ids/gonogo/`.

## After the merge

Tell me, or run these yourself. They should print what the comments show.

```bash
# A browser gets the documentation
curl -sIL https://w3id.org/gonogo/ontology | grep -iE "^(HTTP|location)"      # 303, then 200

# An RDF client gets Turtle
curl -sL -H "Accept: text/turtle" https://w3id.org/gonogo/ontology | head -5   # @prefix lines

# The same 17 cases as the local test
W3ID_BASE=https://w3id.org uv run pytest -m w3id
```

## Run the local test yourself

```bash
git clone --depth 1 https://github.com/perma-id/w3id.org /tmp/w3id && cp -r docs/w3id/ids/gonogo /tmp/w3id/ids/
(cd /tmp/w3id/tools/server && docker compose up -d --build)
uv run pytest -m w3id
```

## If the Vercel address changes

Every target in the `.htaccess` file uses `https://gonogo-livid.vercel.app`. If you move the site to a custom
domain, change that one string and open a second pull request.
