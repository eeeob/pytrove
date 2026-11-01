# pytrove 🛠️

[![PyPI version](https://img.shields.io/pypi/v/pytrove)](https://pypi.org/project/pytrove/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytrove)](https://pypi.org/project/pytrove/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

هذا الملف ترجمة عربية لـ [`README.md`](README.md). عند أي اختلاف بينهما يكون النص الإنجليزي هو المرجع.

**pytrove** مكتبة أدوات حديثة للغة Python. تقدّم أدوات جاهزة للعمل مع `async` في الأنظمة الخلفية، وقواعد البيانات، والتشفير، وأتمتة Telegram.

> **تحدّث المكتبة؟** كل تغيير كاسر وطريقة الانتقال منه موجودة في [CHANGELOG.md](CHANGELOG.md).

---

## ✨ المزايا

* ⚡ **تصميم يبدأ من `async`**، مبني لتطبيقات `asyncio` الحديثة
* 🗄️ **أدوات MongoDB** لعمليات قاعدة بيانات أنظف وأكثر أمانًا
* 🔐 **أدوات تشفير** (AES-GCM، واشتقاق مفاتيح آمن)
* 🤖 **أدوات Telegram** مبنية على Kurigram
* 📧 **أدوات بريد IMAP** لجلب الرسائل وتحليلها
* 🌍 **أدوات الدول والهواتف** للتعامل مع المناطق والأرقام
* 🧰 **أدوات عامة** للتحليل والتحقق ومعالجة البيانات
* 🧩 **كود مكتوب الأنواع بالكامل**، مع دعم صارم للـ type hints

---

## 📦 التثبيت

منذ `v0.2.0` تستخدم المكتبة **اعتماديات اختيارية**: ثبّت ما تحتاجه فقط.

### التثبيت الأدنى (بلا اعتماديات اختيارية)

```bash
pip install pytrove
```

### تثبيت ميزات محددة

لكل ميزة extra خاص بها، و`full` يثبّتها كلها. قائمة الـ extras والحزم التي يثبّتها كل واحد معرّفة في [`[project.optional-dependencies]` داخل `pyproject.toml`](pyproject.toml)، وهو مصدرها الوحيد.

```bash
# ميزة واحدة
pip install "pytrove[crypto]"

# عدة ميزات
pip install "pytrove[crypto, mongo, phone]"

# كل شيء
pip install "pytrove[full]"
```

> **ملاحظة:** إن استخدمت ميزة دون تثبيت حزمها، تحصل على `ImportError` واضح فيه أمر التثبيت المطلوب بالضبط.

### تثبيت أحدث نسخة من GitHub

للتثبيت مباشرة من فرع `main`، وهو يسبق آخر إصدار على PyPI:

```bash
pip install git+https://github.com/eeeob/pytrove.git --force-reinstall
```
---
### 🔹 بلا اعتماديات
```bash
pip install git+https://github.com/eeeob/pytrove.git --force-reinstall --no-deps
```
---

## 🚀 البدء السريع

### 🔐 مثال التشفير

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

### 🗄️ مثال MongoDB

```bash
pip install "pytrove[mongo]"
```

```python
from pytrove import MongoIndex

index = MongoIndex.from_dict({"key": {"field": 1}})
```

### 🤖 مثال Telegram

```bash
pip install "pytrove[tg]"
```

```python
from pytrove import format_tg_username, mention_tg_user

username = format_tg_username("@myuser")
mention = mention_tg_user(123456789, "John")
```

---

## 🧪 إعداد بيئة التطوير

المتطلب الوحيد هو [`uv`](https://docs.astral.sh/uv/): يجهّز المفسّر والبيئة من `uv.lock`.

```bash
git clone https://github.com/eeeob/pytrove.git
cd pytrove
make sync        # the locked environment with every extra
make test        # the suite; also: make lint, make typecheck, make test-doctest
```

[`CONTRIBUTING.ar.md`](CONTRIBUTING.ar.md) يشرح سير العمل وكل أمر. ويشغّل CI الأوامر نفسها على Python من 3.10 حتى 3.14، مع الـ extras الاختيارية وبدونها.

---

## 📄 الترخيص

المشروع مرخّص بـ **رخصة MIT**.
التفاصيل في ملف [LICENSE](LICENSE).

---

## 📬 التواصل

* البريد: [aldheeb01@gmail.com](mailto:aldheeb01@gmail.com)
* GitHub: https://github.com/eeeob/pytrove
