# pytrove 🛠️

[![PyPI version](https://img.shields.io/pypi/v/pytrove)](https://pypi.org/project/pytrove/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytrove)](https://pypi.org/project/pytrove/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An Arabic translation is kept in [`README.ar.md`](README.ar.md); this English text is the reference when the two differ.

**pytrove** is a modern Python utilities library providing async-ready helpers for backend systems, databases, cryptography, and Telegram automation.

> **Upgrading?** Every breaking change and how to migrate is in [CHANGELOG.md](CHANGELOG.md).

---

## ✨ Features

* ⚡ **Async-first design** built for modern `asyncio` applications
* 🗄️ **MongoDB utilities** for cleaner and safer database operations
* 🔐 **Cryptography helpers** (AES-GCM, secure key derivation)
* 🤖 **Telegram utilities** using Kurigram integration
* 📧 **IMAP email utilities** for fetching and parsing emails
* 🌍 **Country & phone utilities** for region and number handling
* 🧰 **General utilities** for parsing, validation, and data handling
* 🧩 **Fully typed codebase** with strict type hints support

---

## 📦 Installation

Starting from `v0.2.0`, the library uses **optional dependencies** — install only what you need.

### Minimal install (no optional dependencies)

```bash
pip install pytrove
```

### Install specific features

Each feature has its own extra; `full` installs all of them. The list of extras and the packages each one installs is defined in [`[project.optional-dependencies]` in `pyproject.toml`](pyproject.toml), which is the single source for it.

```bash
# Single feature
pip install "pytrove[crypto]"

# Multiple features
pip install "pytrove[crypto, mongo, phone]"

# Everything
pip install "pytrove[full]"
```

> **Note:** If you try to use a feature without its required packages installed, you'll get a clear `ImportError` with the exact install command needed.

### Install the latest version from GitHub

To install directly from the `main` branch (ahead of the latest PyPI release):

```bash
pip install git+https://github.com/eeeob/pytrove.git --force-reinstall
```
---
### 🔹 Without Deps
```bash
pip install git+https://github.com/eeeob/pytrove.git --force-reinstall --no-deps
```
---

## 🚀 Quick Start

### 🔐 Encryption example

```bash
pip install "pytrove[crypto]"
```

```python
from pytrove import encrypt, decrypt

key = "my-secure-key"

encrypted = encrypt("secret data", key)
print(encrypted)

decrypted = decrypt(encrypted, key)
print(decrypted)
```

### 🗄️ MongoDB example

```bash
pip install "pytrove[mongo]"
```

```python
from pytrove import MongoIndex

index = MongoIndex.from_dict({"key": {"field": 1}})
```

### 🤖 Telegram example

```bash
pip install "pytrove[tg]"
```

```python
from pytrove import format_tg_username, mention_tg_user

username = format_tg_username("@myuser")
mention = mention_tg_user(123456789, "John")
```

---

## 🧪 Development Setup

The only prerequisite is [`uv`](https://docs.astral.sh/uv/); it provisions the interpreter and the environment from `uv.lock`.

```bash
git clone https://github.com/eeeob/pytrove.git
cd pytrove
make sync        # the locked environment with every extra
make test        # the suite; also: make lint, make typecheck, make test-doctest
```

`CONTRIBUTING.md` describes the workflow and every recipe; CI runs the same recipes on Python 3.10 through 3.14, with and without the optional extras.

---

## 📄 License

This project is licensed under the **MIT License**.
See the [LICENSE](LICENSE) file for details.

---

## 📬 Contact

* Email: [aldheeb01@gmail.com](mailto:aldheeb01@gmail.com)
* GitHub: https://github.com/eeeob/pytrove
