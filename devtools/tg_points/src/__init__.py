"""Regenerate `pytrove/data/tg_points.json`: known Telegram account creation points.

Each point is `[user id, "YYYY-MM-DD"]`, a real account and the day it was
registered. `tg_account_created_at` interpolates between them. Telegram
publishes nothing of the kind, so every point is somebody's observation, and
this tool only gathers the ones that are published.

Modules, in reading order:

    cache    the only module that touches the network
    points   the sources, the merge, and the file it writes
    cli      the argument parsing

Sources (declared in `sources/sources.toml`):

    WizardLoop/CreationDate  data/tg_points.json, the 212 points the library
                             first shipped with; frozen since 2026-01-25
    LyoSU/LyAdminBot         tools/account-age-calibrate/sources.json, whose
                             `observations` grow by hand every month or two
"""
