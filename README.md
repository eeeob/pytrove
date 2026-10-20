# pytrove 🛠️

[![PyPI version](https://img.shields.io/pypi/v/pytrove)](https://pypi.org/project/pytrove/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytrove)](https://pypi.org/project/pytrove/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**pytrove** is a modern Python utilities library providing async-ready helpers for backend systems, databases, cryptography, and Telegram automation.

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

```bash
git clone https://github.com/eeeob/pytrove.git
cd pytrove
pip install -e ".[full,dev]"
```

### Running tests

```bash
pytest
```

Tests run in CI across every Python version listed in the classifiers above (3.10 through 3.14), both with the minimal (no-extras) install and with `[full,dev]`.

---

## 📄 License

This project is licensed under the **MIT License**.
See the [LICENSE](LICENSE) file for details.

---

## 📬 Contact

* Email: [aldheeb01@gmail.com](mailto:aldheeb01@gmail.com)
* GitHub: https://github.com/eeeob/pytrove
