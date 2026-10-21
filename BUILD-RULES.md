# Build rules – read before changing any code

This GitHub repository is the master copy. Every session and every person works from it.

1. `git pull` before you start. Never build from an old copy left anywhere else.
2. Read CHANGELOG.md: every entry is behaviour that must still work after your change.
3. Bump `VERSION` in station_review/server.py to the next number up. Never reuse a version number.
4. Every bug fix gets a regression test in tests/test_regressions.py that fails on the old code, plus a
   comment at the fix point naming the bug and the version.
5. Release only through `python build.py`, which runs every test and refuses to build if any fail.
6. Add a CHANGELOG.md line, commit, tag the release `v<version>` and push. If the push is rejected because
   someone else pushed first, pull, merge, re-run the tests, then push.
7. Nothing in the repository may name a site, station, customer, person or address from a real job –
   not in code, tests, documents, templates or examples. Test data is invented (tests/fixtures.py).
   `test_no_site_references_anywhere` checks this. Site names belong only in the data folder.
