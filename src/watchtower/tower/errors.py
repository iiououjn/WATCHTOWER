from __future__ import annotations


class NeedsOwner(Exception):
    pass


class SpecRejected(Exception):
    pass


class AppRejected(SpecRejected):  # same outcome for the runner: the job fails
    pass
