"""Screens for activities and photos.

Empty on purpose. This commit is the data layer — models, selectors, services and the
consent gate — matching how Phase 3 landed (`b1035ac`, then the screens). The teacher
quick-entry, tagging and publish screens, and the parent feed, arrive next.

The module exists rather than being absent because `.importlinter`'s layers contract
names `views` as a layer of every container, and a missing layer module fails the
check for the whole app — which would be a green build on an unchecked app, and that
is worse than no contract at all.
"""
