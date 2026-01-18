# utils.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DIGITS_RE = re.compile(r"\D+")


def sanitize_digits(value: str) -> str:
    """Remove anything that is not a digit."""
    if value is None:
        return ""
    return DIGITS_RE.sub("", str(value))


def is_digits_only(value: str) -> bool:
    return bool(value) and value.isdigit()


def parse_decimal_optional(value: str) -> Optional[Decimal]:
    """
    Parse decimal from string. Accepts comma or dot. Returns None if empty/blank.
    Raises ValueError if non-empty but invalid.
    """
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None

    # Accept "1.23" or "1,23"
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"Invalid decimal: {value}") from e


def now_filename(prefix: str = "invoice", ext: str = "json") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}.{ext}"


def save_json(payload: Dict[str, Any], folder: str = "data") -> Path:
    Path(folder).mkdir(parents=True, exist_ok=True)
    path = Path(folder) / now_filename()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def validate_required(value: str) -> Tuple[bool, str]:
    if not str(value or "").strip():
        return False, "Este campo es obligatorio."
    return True, ""


def validate_items(items: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    if not items:
        return ["Debes agregar al menos 1 item."]

    for i, it in enumerate(items, start=1):
        desc = str(it.get("descripcion", "")).strip()
        if not desc:
            errors.append(f"Item {i}: 'Descripción' es obligatoria.")

        qty = it.get("cantidad", None)
        try:
            qty_val = float(qty)
            if qty_val <= 0:
                errors.append(f"Item {i}: 'Cantidad' debe ser > 0.")
        except Exception:
            errors.append(f"Item {i}: 'Cantidad' debe ser numérica.")

        pu = it.get("precio_unitario", None)
        try:
            pu_val = float(pu)
            if pu_val <= 0:
                errors.append(f"Item {i}: 'Precio Unitario' debe ser > 0.")
        except Exception:
            errors.append(f"Item {i}: 'Precio Unitario' debe ser numérico.")

        # descuento optional
        desc_str = str(it.get("descuento_bonificacion", "")).strip()
        if desc_str != "":
            try:
                _ = parse_decimal_optional(desc_str)
            except ValueError:
                errors.append(f"Item {i}: 'Descuento/Bonificación' no es un número válido.")

        um = str(it.get("unidad_medida", "")).strip()
        if not um:
            errors.append(f"Item {i}: 'Unidad de medida' es obligatoria.")

    return errors


def build_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza y arma el payload final a enviar.
    """
    emisor = state["emisor"].copy()
    receptor = state["receptor"].copy()
    fact = state["facturacion"].copy()
    items = [it.copy() for it in state["items"]]

    # sanitize CUIT/DNI
    emisor["cuit"] = sanitize_digits(emisor.get("cuit", ""))
    receptor["cuit_dni"] = sanitize_digits(receptor.get("cuit_dni", ""))

    # normalize discounts: keep as string if empty, else Decimal -> str
    for it in items:
        d = str(it.get("descuento_bonificacion", "")).strip()
        if d == "":
            it["descuento_bonificacion"] = None
        else:
            it["descuento_bonificacion"] = str(parse_decimal_optional(d))

    payload = {
        "emisor": emisor,
        "receptor": receptor,
        "datos_facturacion": fact,
        "items": items,
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "streamlit_ui",
        }
    }
    return payload
