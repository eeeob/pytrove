"""Regenerate `pytrove/data/tg_points.json` and `tg_blocks.json`: how old a Telegram account is.

Each point is `[user id, "YYYY-MM-DD"]`, a real account and the day it was
registered; below the first randomized block, `tg_account_created_at`
interpolates between them. Each block is `[low id, high id, "YYYY-MM-DD"]`, a
range Telegram hands out at random and the day it opened; an id inside one
dates only to its window. Telegram publishes nothing of the kind, so all of it
comes from somebody's observations, and this tool only gathers the published ones.

Modules, in reading order:

    cache    the only module that touches the network
    points   the points: their sources, the merge, and the file it writes
    blocks   the blocks: their bounds, their openings, ssleg's cross-check
    cli      the argument parsing, and `build`, which writes both or neither

Sources (declared in `sources/sources.toml`):

    WizardLoop/CreationDate  data/tg_points.json, the 212 points the library
                             first shipped with; frozen since 2026-01-25
    LyoSU/LyAdminBot         tools/account-age-calibrate/sources.json: its
                             `observations` become points, and with its
                             `constraints` they date its `randomizedBlocks`;
                             refreshed by hand every month or two
    anton/tg_account_age     tg_account_age.py on git.ssleg.tech, whose
                             `uid_dict` pools only cross-check the openings
"""
