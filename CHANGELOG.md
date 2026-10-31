# Changelog

Every notable change to `pytrove` is recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html): a release with a breaking change raises the major version.

Each breaking change says what changed, who it affects and how to migrate. Releases before 1.1.2 are not recorded here; see the [GitHub releases](https://github.com/eeeob/pytrove/releases).

## [Unreleased]

The next release breaks compatibility with 1.1.2 in many places. Read the sections for the tools you use before upgrading.

### Added

- `device_tools`: `random_device` (with keyword-only `os=` and `to_dict=`), `random_family`, `get_device_catalog`, `is_known_device` and the `DeviceCatalog` class. Each platform's devices come from bundled catalogs, weighted by real-world share.
- `pytrove.constants`, a sixth entry point that holds every public constant.
- `cancel_task`, `juxt` and `yield_control`, plus the `DeviceInfo` and `Jitter` models in `pytrove.models`.

### Breaking changes

#### Imports and names

- **Old module paths are removed.** `pytrove.misc_tools`, `pytrove.classes` (with `pytrove.classes.misc_classes` and `pytrove.classes.archiver`), `pytrove.models.misc_models` and `pytrove.__meta__` no longer exist, and importing them raises `ImportError`. The private flat modules (`pytrove._devices`, `pytrove._optional`, ...) are gone too. `from pytrove import ...` and the other entry points still give every name that remains.
  ```python
  # 1.1.2
  from pytrove.misc_tools import unwrap, patch_cls, generate_secret
  from pytrove.classes import PeriodicArchiver, MongoIndex, UTC3LogFormatter, KeyDefaultDict
  from pytrove.classes.misc_classes import classproperty, WeakRegistry
  from pytrove.models.misc_models import DeferredCall, DelayedCallback, JsonContainer
  from pytrove.__meta__ import __version__
  # now
  from pytrove import unwrap, patch_cls, generate_secret
  from pytrove import PeriodicArchiver, MongoIndex, UTC3LogFormatter, KeyDefaultDict
  from pytrove import classproperty, WeakRegistry
  from pytrove.models import DeferredCall, DelayedCallback, JsonContainer
  from pytrove import __version__
  ```

- **Constants moved to `pytrove.constants`.** `IMAP_DOMAIN_TO_PROVIDER` is no longer exported from `pytrove.enums`. The patterns and character sets that sat in the tool modules now live only in `pytrove.constants`, some under new names.
  ```python
  # 1.1.2
  from pytrove.enums import IMAP_DOMAIN_TO_PROVIDER
  from pytrove.validate_tools import EMAIL_PATTERN, TG_BOT_COMMAND_PATTERN, TG_CHANNEL_MSG_LINK_PATTERN
  from pytrove.tg_tools import CHAT_LINK_PATTERN, INVITE_LINK_PATTERN
  from pytrove.num_tools import CALC_ALLOWED_CHARS
  # now
  from pytrove.constants import (
      IMAP_DOMAIN_TO_PROVIDER,
      EMAIL_PATTERN,
      TG_BOT_COMMAND_PATTERN,
      TG_CHANNEL_MESSAGE_LINK_PATTERN,  # was TG_CHANNEL_MSG_LINK_PATTERN
      TG_CHAT_LINK_PATTERN,             # was CHAT_LINK_PATTERN
      TG_INVITE_LINK_PATTERN,           # was INVITE_LINK_PATTERN
      CALC_EXPRESSION_CHARS,            # was CALC_ALLOWED_CHARS
  )
  ```

- **Alias names are removed; each function keeps one name.** `backup_folder` → `compress_folder`, `remove_file` → `remove_files`, `remove_folder` → `remove_folders`, `remove_path` → `remove_paths`, `load_json` → `read_json`, `save_json` → `write_json`. `rand_tg_device` and `split_tg_message` are gone too; see `device_tools` and `text_tools` below.
  ```python
  # 1.1.2
  from pytrove import load_json, save_json, remove_file, backup_folder
  # now
  from pytrove import read_json, write_json, remove_files, compress_folder
  ```

- **Boolean `with_*` keywords are renamed after what they do.** The old keywords are not accepted; positional calls keep working.
  - `stamp_to_date`, `date_utc`, `date_utc_3`: `with_tzinfo` → `keep_tzinfo`
  - `get_rotating_log_files`: `with_base` → `include_base`
  - `clean_spaces`: `with_lines` → `include_newlines`
  - `is_tg_otp_code`: `with_str` → `allow_str`
  - `format_tg_username`: `with_invite_link` → `allow_invite_link`, `with_at` → `prefix_at`
  - `BaseDataClass.to_raw_dict`, `to_dict`, `from_raw_dict`, `from_dict`: `without_none_values` → `exclude_none`
  ```python
  # 1.1.2
  date_utc(with_tzinfo=True)
  format_tg_username(chat, with_invite_link=True, with_at=False)
  model.to_dict(without_none_values=True)
  # now
  date_utc(keep_tzinfo=True)
  format_tg_username(chat, allow_invite_link=True, prefix_at=False)
  model.to_dict(exclude_none=True)
  ```

#### Extras and dependencies

- **The `jsonref` and `fastjson` extras are merged into one `json` extra, which installs only `jsonref`.** `pytrove[jsonref]` and `pytrove[fastjson]` now install nothing. `orjson` is no longer installed or used (see `files_tools`).
  ```bash
  # 1.1.2
  pip install "pytrove[jsonref,fastjson]"
  # now
  pip install "pytrove[json]"
  ```

- **Optional features enforce their extra's version floor.** A feature used with a dependency older than its extra's floor now raises `ImportError` when called, naming the version it found. In 1.1.2 any installed version passed. Fix it with `pip install -U "pytrove[<extra>]"`.

- **Dependency floors are raised, and `packaging` is a new required dependency:**

  | dependency | 1.1.2 | now |
  |---|---|---|
  | `typing_extensions` (Python < 3.13, required) | `>=4.0` | `>=4.4` |
  | `packaging` (required) | not a dependency | `>=22.0` |
  | `cryptography` (`crypto`) | `>=48.0.1` | `>=50.0.0` |
  | `kurigram` (`tg`) | `>=2.1.35` | `>=2.2.24` |
  | `typeguard` (`typecheck`) | `>=4.3` | `>=4.6` |
  | `pymongo` (`mongo`) | `>=4.6.3` | `>=4.19.0`, Python 3.11+ only |

  Upgrade with `pip install -U "pytrove[full]"`, or the extras you use.

- **On Python 3.10 the `mongo` extra installs nothing.** `pymongo` 4.19.0, the first release without a known vulnerability, needs Python 3.11, so on 3.10 `MongoIndex` raises the missing-extra `ImportError`. Use Python 3.11 or newer for the Mongo helpers.

- **The `dev` extra is removed.** It no longer installs test or build tooling; contributors use `make sync`.

#### archive_tools

- **`compress_folder(delete_source=True)` keeps an archive written inside `src`.** Everything else in `src` is removed. In 1.1.2 the new archive was deleted with the tree.
- **`PeriodicArchiver` rejects a `delete_source` job that shares its `root` with another job**, raising `ValidationError` when the archiver is created; its cleanup used to delete the other job's archive. Give each `delete_source=True` job its own `root`. Sibling archives are now excluded only at their exact path in `root`, not at any depth. `PeriodicArchiver.stop()` now waits for a running `compress_folder` and removes its archive.
- **Include/exclude rules written as `./x`, `x/` or `./*.log` are anchored at `src`.** In 1.1.2 they matched at any depth. `/*.log` is anchored with or without `pathspec`; without it, 1.1.2 never matched it.
  ```python
  # 1.1.2: matched every "cache" dir and every *.log at any depth
  compress_folder(src, dest, exclude=["./cache", "./*.log"])
  # now
  compress_folder(src, dest, exclude=["cache", "*.log"])
  ```
- **Arguments are validated up front.** An unknown `format` (such as `'rar'`), an out-of-range `level` (-1 to 9 for zip and gzip), a malformed `ArchiveLimits` or a misspelled policy raises `ValidationError` before anything is written. `ValidationError` subclasses `ValueError`, so `except ValueError` still catches it. In 1.1.2 a misspelled policy silently fell back to skip.
- **`extract_archive` is stricter:**
  - `a.txt` followed by `./a.txt` counts as a duplicate and follows the `duplicates` policy.
  - On Windows, names containing `:` and device names (`CON`, `COM1`, ...) are refused and logged.
  - A symlink whose target climbs back after descending (`m/..`, `x/m/../f`) is refused and logged; write link targets without `..` detours.
  - A file member replaces an existing symlink or hardlink at its path instead of writing through it.
  - With `atomic`, a directory merged over an existing file is logged and skipped instead of raising `OSError` mid-merge.
  - A link refused by policy no longer counts against `max_files` or the breadth ceilings.

#### async_tools

- **`AioThreadWorker` and `SyncAwaitableRunner` are removed**, with no replacement class.
  ```python
  # 1.1.2
  from pytrove import SyncAwaitableRunner
  with SyncAwaitableRunner() as runner:
      result = runner.run(coro())

  # now: a one-off call
  from pytrove import run_awaitable_sync
  result = run_awaitable_sync(coro())   # or asyncio.run(coro())

  # now: one loop reused across calls (replaces both classes)
  import asyncio, threading
  loop = asyncio.new_event_loop()
  thread = threading.Thread(target=loop.run_forever, daemon=True)
  thread.start()
  result = asyncio.run_coroutine_threadsafe(coro(), loop).result()  # from sync code
  result = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro(), loop))  # from another loop
  loop.call_soon_threadsafe(loop.stop)
  thread.join()
  loop.close()
  ```
- **`safe_await` treats only a raised exception as a failure.** An awaitable that *returns* an exception object now gives a plain result: it is not logged, and with `return_exc=False` it is not raised. Raise the exception instead.
- **`run_awaitable_sync` closes a coroutine it refuses.** When it raises `RuntimeError` (closed or idle `loop`, or a loop already running in the calling thread), the coroutine is closed first; create a new one to retry.

#### callable_tools

- **`middleware` rejects an async hook on a sync function.** In 1.1.2 an async `before`/`after`/`on_error` on a sync `func` was never awaited; it now raises `TypeError`. Make the hooks sync, or make `func` async.
- **`middleware` validates its keywords up front.** An unknown keyword or a non-callable hook raises `TypeError` from `middleware(...)` itself. Pass only `before`, `after` and `on_error`, each a callable or `None`.
- **Objects with an async `__call__` count as async.** `middleware`, `raise_if` and `return_constant` return a coroutine-function wrapper for them, so the result must be awaited.
  ```python
  # 1.1.2
  result = middleware(async_callable_obj, after=hook)(x)
  # now
  result = await middleware(async_callable_obj, after=hook)(x)
  ```
- **`return_constant` awaits an async function.** In 1.1.2 `return_constant(async_func)` created the coroutine and never ran it. It now returns an async wrapper.
  ```python
  # 1.1.2 (async_func never actually ran)
  value = return_constant(async_func, value=True)()
  # now
  value = await return_constant(async_func, value=True)()
  ```
- **`raise_if` needs a condition, and `None` in `values` now matches.** `raise_if(exc)` with no `bool_value`, `values` or `always=True` was a silent no-op and now raises `ValueError`. A `None` in `values` now matches a `None` result. A shared exception instance has its `__traceback__` and `__context__` cleared on every raise; pass a class or factory if several threads may raise it at once.
  ```python
  # 1.1.2: never raised
  @raise_if(ValueError("bad"))
  def f(): ...
  # now
  @raise_if(ValueError("bad"), always=True)
  def f(): ...
  ```
- **`safe_call` and `asafe_call` reject `SystemExit` and `KeyboardInterrupt` in `include_exc`.** Both always propagate, so naming either one, or a subclass, now raises `TypeError` before the call.
  ```python
  # 1.1.2
  safe_call(func, include_exc=(ValueError, KeyboardInterrupt))
  # now
  safe_call(func, include_exc=ValueError)
  ```

#### country_tools and phone_tools

- `get_cinfo` and `get_cfullname` accept a calling code as a string (`"966"`, `"+966"`); 1.1.2 raised `KeyError`.
- `get_clanguage_code` ranks national official languages above regional ones: `get_clanguage_code("gh")` returns `"en"`, not `"ak"`. `get_cname_native` and `get_clanguage_name` follow the same ranking.
- `resolve_rc` no longer raises; it returns `None` when nothing matches. An `int` phone number resolves to its region, and a `bool` returns `None` instead of `"us"`.
- `rc_from_cc` and `rc_from_phone` raise `ValidationError` for non-geographic codes and numbers (`800`, `+800...`) instead of returning `"001"`. `cc_from_phone` and `rc_from_phone` validate an already-parsed `PhoneNumber` and raise `ValidationError` when it is invalid.

#### crypto_tools

- **`d_decrypt` raises `TypeError` for data that is not bytes-like**, where 1.1.2 raised `ValidationError`. `ValidationError` from `decrypt`/`d_decrypt` now means only a wrong password or altered data. `decrypt` now accepts `bytearray` and `memoryview`. Existing ciphertexts still decrypt.

#### data_tools and iter_tools

- **`value_to_enum` changed:**
  - Mode `'k'` converts only mapping keys, nested mappings included, and no longer converts leaves: `value_to_enum(['red'], C, 'k')` returns `['red']` (was `[C.RED]`). Use `'v'` for leaves.
  - An invalid `map_resolve_type` raises `ValidationError` (was `AttributeError`).
  - When a value matches members of several enum classes, the class passed last wins.
- **`get_nested_dict_key` checks every level.** A level with more than one key, or none, raises `TypeError` (1.1.2 took the first key or raised `StopIteration`), and so does a leaf other than `True` or `1`: `{'a': {'b': 2}}` gave `'a.b'` in 1.1.2. Keys are joined as strings, so `{1: True}` gives `'1'` (was `1`).
- `pad_list` with a negative `length` raises `ValueError`. `iter_flat_cont` is fully lazy, so an error from a source iterator is raised when that item is consumed.
- **`collections.UserString` is treated as one value, like `str`.** `to_list(UserString("ab"))` returns `[UserString("ab")]`, not `['a', 'b']`; `flat_cont`, `snapshot` and `map_deep` handle it the same way.
- `snapshot` keeps a `deque`'s `maxlen`. `map_deep` returns the original container with a warning when rebuilding it overflows, instead of raising `OverflowError`.

#### date_tools

- **`date_utc_3(keep_tzinfo=True)` returns a datetime in a real `UTC+3` zone.** In 1.1.2 `with_tzinfo=True` returned the time shifted by 3 hours but still labelled UTC, so comparing it with other aware datetimes was off by 3 hours.
- **`date_to_stamp(..., as_int=True)` floors instead of truncating toward zero.** Only negative fractional timestamps change: `'1969-12-31 23:59:59.5'` gives `-1` (was `0`). For the old result use `int(date_to_stamp(date, format=fmt, as_int=False))`.

#### device_tools

- **`rand_tg_device` is now `random_device`.** The arguments are unchanged (`platform_device`, then `to_tuple`, still positional). With no platform, the platform is weighted by its share of real clients, and Telegram Web devices can be drawn. Desktop draws only Windows and Linux devices.
  ```python
  # 1.1.2
  from pytrove import rand_tg_device
  model, version = rand_tg_device(PlatformDevice.ANDROID, to_tuple=True)
  # now
  from pytrove import random_device
  from pytrove.enums import PlatformDevice
  model, version = random_device(PlatformDevice.ANDROID, to_tuple=True)
  ```
- **`DeviceInfo` fields are renamed after Telegram's.** `.model` is `.device_model` and `.version` is `.system_version`. The class is a frozen dataclass, `DeviceInfo.from_dict()` is gone, and `to_dict()` keeps the `device_model`/`system_version` keys. Import it from `pytrove.models`.
  ```python
  # 1.1.2
  device = rand_tg_device()
  client_kwargs = {"device_model": device.model, "system_version": device.version}
  restored = DeviceInfo.from_dict(saved)
  # now
  from pytrove import random_device
  from pytrove.models import DeviceInfo
  device = random_device()
  client_kwargs = device.to_dict()
  restored = DeviceInfo(**saved)  # saved = an earlier device.to_dict()
  ```
- **The undocumented device classes are removed:** `SystemInfo`, `AndroidDevice`, `iOSDeivce`, `WindowsDevice`, `LinuxDevice` and `macOSDevice`, with `RandomDevice(unique_id)`, `GetDevices`, `GetDevicesBySdk`, `FindDevice`, `ResolveDevice` and `Load/SaveDeviceConfig`. Each platform now has a `DeviceCatalog`. A draw can no longer be seeded with an id: store the drawn device with its account and check it with `is_known_device`.
  ```python
  # 1.1.2
  from pytrove._devices import AndroidDevice
  device = AndroidDevice.RandomDevice(user_id)
  AndroidDevice.FindDevice(model, version)
  AndroidDevice.GetDevices()
  # now
  from pytrove import get_device_catalog, is_known_device
  from pytrove.enums import PlatformDevice
  from pytrove.models import DeviceInfo
  catalog = get_device_catalog(PlatformDevice.ANDROID)
  device = catalog.random_device()  # store device.to_dict() with the account
  catalog.find_device(model, version)
  catalog.devices()
  is_known_device(DeviceInfo(**stored), PlatformDevice.ANDROID)
  ```

#### email_tools

- **`fetch_emails_from` yields nothing when no email matches**, where 1.1.2 raised `ValidationError`. A `limit` of 0 or less reads no email (1.1.2 read every match with `limit=0`). A `sender` containing a line break raises `ValidationError`. Each message is read whole, so multipart emails decode properly.
  ```python
  # 1.1.2
  try:
      texts = [t async for t in fetch_emails_from(email, password, provider)]
  except ValidationError:
      texts = []
  # now
  texts = [t async for t in fetch_emails_from(email, password, provider)]
  ```

#### files_tools

- **`write_json` always uses the standard `json` module.** With the `fastjson` extra, 1.1.2 wrote compact orjson output, wrote `NaN` as `null` and serialised `Enum`/`UUID` natively. Output is now plain `json.dumps` (`{"a": 1}`, `NaN`), and `Enum`/`UUID` go to `default`, raising `TypeError` without one. Files are UTF-8 with LF line endings on every platform. `read_json` returns the same values.
  ```python
  # now: compact output, and handle Enum/UUID yourself
  write_json(path, data, separators=(",", ":"),
             default=lambda o: o.value if isinstance(o, Enum) else str(o))
  ```
- **`truncate_file` spilling changed.** With `spill=True` or a directory, 1.1.2 wrote parts of exactly `size` bytes with no limit on their number; it now writes at most 10 parts of `max(size, ceil(dropped / 10))` bytes. `spill=''` now means the current directory; to discard the removed bytes pass `spill=False`.
- **`read_pickle` refuses more globals below `PickleSafety.STRICT`.** At `MODULES` and `BLOCKLIST`, a global reached through another module (`pathlib` + `os.getcwd`) is refused; at `MODULES` a name must be defined in the allowed module, not just imported by it. At `STRICT`, `collections.namedtuple` is no longer allowed.
  ```python
  from pytrove import read_pickle
  from pytrove.enums import PickleSafety
  read_pickle(path, safe=PickleSafety.MODULES, allow_modules=["mypkg.models"])  # the defining module
  read_pickle(path, allow_classes=[MyClass])
  ```
- On POSIX, `remove_folders` unlinks a dangling symlink passed to it instead of reporting it missing.

#### logging_tools

- **`attach_logger_handlers` and `set_loggers` return a list for any container.** A one-item list or tuple returns a list of one; 1.1.2 returned the bare object. A single `LogHandlerOptions`/`LoggerOptions` still returns the bare object.
  ```python
  # 1.1.2
  handler = attach_logger_handlers([options])
  # now
  handler = attach_logger_handlers(options)  # or attach_logger_handlers([options])[0]
  ```
- `get_rotating_log_files` yields the backup paths as the handler's `namer` renames them.

#### models

- **`BaseDataClass` private fields and `copy()` changed:**
  - A model with both `a` and `_a` raises `TypeError` on first use; 1.1.2 silently dropped `_a` in `to_dict`. Rename one of them.
  - A private field's public name drops exactly one underscore: `__x__` is exposed as `_x__` (was `x__`).
  - `to_dict` reads the private field itself, even when a property has its public name.
  - `copy()` is `copy.deepcopy`: nested dataclasses keep their types and `__post_init__` does not run again.
- **`from_dict(..., values_to_enums=True)` converts only where a field's annotation names the enum.** In 1.1.2 a `str` field holding `'ok'` could become `Status.OK`. Give the field an enum type, or convert the value yourself.
- **`DelayedCallback.cancel()` before `start()` prevents the callback.** Create a fresh `DelayedCallback` to run it again.
- **Template models (`CompiledTemplate`, `CompiledButton`) changed:**
  - `CompiledButton.compile` converts only `meta["style"]` to `ButtonStyle`, not any value equal to a style name.
  - `compile_from_file` on a missing path raises `FileNotFoundError`; 1.1.2 returned `{}`.
  - `format()` drops only top-level `None` keyword arguments, not `None` inside nested values.
  - `format_message`/`format_rich_message`/`format_keyboard` apply `default_keys` and `key_time` themselves.
  - `row_width` below 1, an empty or non-str `each`, and a falsy `each` on a plain line or button raise `ValueError` at compile time. In 1.1.2 `row_width=0` meant 2; omit it for the default.
  - A button `type` of `"text"` raises `ValueError`. `meta` keys repeating the label or `type` are dropped with a `UserWarning`.

#### mongo_tools

- `MongoIndex.from_dict` keeps the document's `name` and leaves the input dict unchanged; 1.1.2 dropped the name and emptied the dict. Index equality ignores option order, and comparing a `MongoIndex` with another type returns `False` instead of raising `NotImplementedError`.

#### num_tools

- **`jitter` has a new signature and distribution.** 1.1.2's `jitter(base, minus=2, plus=2)` drew uniformly from `[max(0, base - minus), base + plus]`. It is now `jitter(value, decrease, increase, bias=0.5, previous=None, min_distance=0.0, *, rng=None)`: `decrease` and `increase` are required fractions of `value`, and the draw is triangular.
  ```python
  # 1.1.2
  jitter(base)              # ±2
  jitter(base, minus, plus)
  # now (triangular)
  jitter(base, 2 / base, 2 / base)
  jitter(base, minus / base, plus / base)
  # or, for the old uniform draw
  random.uniform(max(0, base - minus), base + plus)
  ```
- **`apply_discount` raises `ValidationError` for a negative discount**, which 1.1.2 applied as a surcharge. `calc(..., as_int=True)` returns the input text for an infinite or NaN result instead of raising.

#### object_tools

- **`unwrap`: `with_prop` is renamed `unwrap_properties` and is keyword-only.** `unwrap(obj, False)` now raises `TypeError`. `unwrap` and `patch_into` also peel a `functools.cached_property` down to its function; pass `unwrap_properties=False` to keep the property.
  ```python
  # 1.1.2
  unwrap(obj, False)
  # now
  unwrap(obj, unwrap_properties=False)
  ```
- **`RestrictedProxy` and `WeakRestrictedProxy` close their escape routes:**
  - `allowed=[]` allows nothing; in 1.1.2 it allowed everything. Omit both lists for no restriction.
  - Passing both lists, even when one is empty, raises `ValueError`.
  - `del proxy.<refused>` raises `AttributeError`, and `proxy.__dict__`/`vars(proxy)` is refused whenever a list is given, unless the allow-list names `__dict__`.
- **`unwrap_cls`, `patch_into`/`patch_cls` with `preserve_old`, and `FrozenClassAttrs` read class members raw**, without running descriptors: wrapped classmethods and staticmethods keep their kind, and `old<name>` stores the original member, not a bound value.

#### text_tools

- **`y_or_n`, `en_or_dis` and `op_or_cl` are removed.** Use the expression each one wrapped.
  ```python
  "✅" if v else "❌"                 # y_or_n(v)
  "مفعل ✅" if v else "معطل ❌"       # en_or_dis(v)
  "مفتوح ✅" if v else "مغلق ❌"      # op_or_cl(v)
  ```
- **`split_tg_message` is removed; use `chunk_text`.** Its `length` keyword is `max_length`. A line longer than the limit is cut at its last space instead of mid-word.
  ```python
  # 1.1.2
  from pytrove import split_tg_message
  split_tg_message(text, length=4096)
  # now
  from pytrove import chunk_text
  chunk_text(text, max_length=4096)
  ```
- **`chunk_text` strips the text, returns `[]` for blank text, and skips the whitespace left at each cut.** 1.1.2 returned `['']` for blank text, and `chunk_text('para one\n\npara two', 8)` now gives `['para one', 'para two']` (was `['para', 'one', 'para two']`).
- **`to_str` returns bytes-like values unchanged** instead of their repr (`"b'ab'"`), so `clean_spaces(b'...')` raises `TypeError`. Decode first: `clean_spaces(data.decode())`.
- `to_snake_case('my_Var')` gives `'my_var'` (was `'my__var'`). `to_pascal_case` capitalises only the first character of each word: `'user_2fa'` gives `'User2fa'` (was `'User2Fa'`).
- `format_exc_tree` hides a context suppressed with `raise ... from None`, aligns multi-line messages, and lists the members of an `ExceptionGroup`.

#### tg_tools

- **Telegram link hosts are narrowed** to `t.me`, `telegram.me`, `telegram.dog` and `telegram.org` in `format_tg_link`, `format_tg_username`, `parse_tg_target` and `is_tg_channel_message_link`. `t.org/...` and `t.dog/...` are no longer read as Telegram links.
- **`format_tg_username`** returns `default` for text that is not a bare name (another site's URL, a `t.me/c/<id>` link) instead of `"@<text>"`. `t.me/s/<name>` gives `@<name>` instead of `@s`. Links are recognised in any letter case.
- **`parse_tg_target` keeps the sign of a numeric string**: `"-100123..."` returns `-100123...`, where 1.1.2 dropped the minus. Invite links are returned as given, not lowercased, and `t.me/c/<id>/...` gives the chat id.
  ```python
  # 1.1.2
  chat_id = -parse_tg_target(text)
  # now
  chat_id = parse_tg_target(text)
  ```
- `format_tg_link`: a basic-group id (`-N`) links to `tg://openmessage?chat_id=N`; an id Pyrogram cannot place, or a message without a link, returns `default` (1.1.2 returned `None` for the latter); `t.me/c/<id>/...` keeps that form.
- `fetch_tg_email_code` matches exactly `code_length` digits and raises `ValidationError` when `code_length` is below 1 or no known IMAP provider serves the address.
- `tg_account_created_at` returns different estimates: the bundled points now never decrease as the id grows.

#### validate_tools

- **`is_accessible_received_email` returns `True` only when the IMAP server accepts the login.** 1.1.2 returned `True` for any reachable server, even with a wrong password.
- **`validate_type` no longer consumes iterators or generators.** It checks the kind only, so the items are not checked; materialise them first (`validate_type(list(gen), list[int])`).
- **Importing `pytrove` no longer changes `typeguard` for the whole process.** pytrove's rules (an enum accepts a member's value, `Container[X]` checks each item) apply only inside `validate_type`; call it instead of `typeguard.check_type` where you relied on them.
- **Public patterns end in `\Z`**, so a trailing newline no longer matches. `is_tg_bot_command` accepts only ASCII letters, digits and `_`, plus an optional `@botname`: `"/start@mybot"` is now `True`, `"/start\n"` is `False`.
- **The Telegram checks are stricter.** `is_tg_otp_code` takes an `int` from 10000 to 99999 or exactly five ASCII digits; `is_tg_bot_token` needs an ASCII-digit id and a non-empty secret; `is_tg_user_id(True)` and `is_tg_channel_id(True)` are `False`.
- **`validation(cond, SomeExceptionClass)` raises that class**, where 1.1.2 raised `ValidationError`.
- **Typing only:** the content validators (`is_email`, `is_rc`, `is_tg_*`, ...) are typed `TypeGuard[...]` instead of `TypeIs[...]`, and `is_phone_number` and `is_tg_bot_command` return plain `bool`. A `False` result no longer narrows; add an `isinstance` check where you relied on it.

#### typings

- The `Template*` TypedDicts report their `NotRequired` keys correctly in `__required_keys__` and `__optional_keys__`; 1.1.2 listed every key as required.

[Unreleased]: https://github.com/eeeob/pytrove/compare/v1.1.2...HEAD
