"""A port of desktop-app/lib_base's own device-model rules.

Imports nothing from the package on purpose: `tests/tools/tg/test_devices_data.py`
loads this file by path to check the stored models against it.
"""

from __future__ import annotations

from typing import ClassVar, Iterable

# ========================== lib_base model rules ==========================

class LibBase:
    """Port of `base::Platform` from desktop-app/lib_base.

    Telegram Desktop does not report a device name: it reads the firmware and
    then rejects, trims or replaces what it finds. Reproducing those rules is
    the only way to know what a given machine actually puts on the wire, so
    this mirrors base_platform_info.cpp function for function. Keep it in step
    with that file.
    """

    #: IsDeviceModelOk's limit, and the longer one SimplifyGoodDeviceModel allows.
    MAX_MODEL: ClassVar[int] = 15
    MAX_GOOD_MODEL: ClassVar[int] = 32

    #: Words ProductNameToDeviceModel strips out of an HP product name.
    HP_FILLER: ClassVar[frozenset[str]] = frozenset(
        {"notebook", "desktop", "mobile", "workstation", "pc"})

    @staticmethod
    def clean_and_simplify(value: str) -> str:
        """base::CleanAndSimplify: every control character becomes a space,
        then QString::simplified() trims and collapses whitespace runs."""

        return " ".join(
            "".join(" " if ch < " " else ch for ch in value).split())

    @classmethod
    def simplify_device_model(cls, value: str) -> str:
        """SimplifyDeviceModel: drop underscores, collapse whitespace."""

        return cls.clean_and_simplify(value.replace("_", ""))

    @classmethod
    def is_device_model_ok(cls, model: str) -> bool:
        return bool(model) and len(model) <= cls.MAX_MODEL

    @classmethod
    def simplify_good_device_model(cls, model: str, remove: Iterable[str]) -> str:
        """SimplifyGoodDeviceModel: drop filler words, then take whole words
        while they still fit in MAX_GOOD_MODEL -- never a mid-word cut."""

        remove = set(remove)
        result = ""
        for word in model.split(" "):
            if word.lower() in remove:
                continue
            if not result:
                result = word
            elif len(result) + len(word) + 1 > cls.MAX_GOOD_MODEL:
                return result
            else:
                result += " " + word
        return result

    @classmethod
    def product_name_to_device_model(cls, product: str) -> str:
        """ProductNameToDeviceModel: HP names get the long treatment because
        HP puts its own name in the product string; everything else is taken
        verbatim or not at all."""

        if product.startswith("HP "):
            return cls.simplify_good_device_model(product, cls.HP_FILLER)
        return product if cls.is_device_model_ok(product) else ""

    @classmethod
    def device_model_from_dmi(cls, product: str, family: str, board: str) -> str:
        """DeviceModelPretty for Windows and Linux, which share one order:
        product name, then family + board, then board, then family.

        Returns "" when the firmware offers nothing the client would report;
        the caller decides whether that becomes the "Desktop" fallback.
        """

        product, family, board = (cls.simplify_device_model(v)
                                  for v in (product, family, board))

        model = cls.product_name_to_device_model(product)
        if model:
            return model

        family_board = cls.simplify_device_model(family + " " + board)
        for candidate in (family_board, board, family):
            if cls.is_device_model_ok(candidate):
                return candidate
        return ""
