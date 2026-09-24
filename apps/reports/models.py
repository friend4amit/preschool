"""This app owns no models, and that is the point of it.

A dashboard and a set of exports are reads across `people`, `attendance`, `activities`
and `website`. Giving them a table would mean caching a number that is already a query,
and the first stale tile is the last time anyone trusts the screen.

The file exists rather than being absent because `.importlinter`'s layers contract
names `models` as the bottom layer of every container, and a missing module is a hard
error there — `lint-imports` says "Missing layer in container 'apps.reports'" and goes
red. Deleting this file to tidy up breaks CI, which is why this paragraph is longer
than the file it explains.

(`python -m importlinter.cli lint` exits 0 without running anything. The command is
`lint-imports`, as the README and CI have it. Worth knowing before trusting a green.)
"""
