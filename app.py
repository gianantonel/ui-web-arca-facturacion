from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4
import requests
import streamlit as st

from utils import (
    build_payload,
    sanitize_digits,
    is_digits_only,
    validate_required,
    validate_items,
    save_json,
    parse_decimal_optional,  # acepta coma o punto
)

WEBHOOK_URL = "https://n8n.optimizar-ia.com/webhook/06cf93de-06f0-42ac-b859-9424155fa9b7"
IVA_RATE = 0.21

TIPO_FACTURA_OPTIONS = ["Factura A", "Factura B", "Factura C"]

IVA_OPTIONS = [
    "IVA Responsable Inscripto",
    "IVA Sujeto Exento",
    "Consumidor Final",
    "Responsable Monotributo",
    "Sujeto No Categorizado",
    "Proveedor del Exterior",
    "Cliente del Exterior",
    "IVA Liberado – Ley N° 19.640",
    "Monotributista Social",
    "IVA No Alcanzado",
    "Monotributo Trabajador Independiente Promovido",
]

COND_VENTA_OPTIONS = [
    "Contado",
    "Cuenta Corriente",
    "Tarjeta de Débito",
    "Tarjeta de Crédito",
    "Cheque",
    "Ticket / Tiquet",
    "Otros medios de pago electrónico",
    "Transferencia Bancaria",
    "Otra",
]

SERVICIO_PRODUCTO_OPTIONS = ["Producto", "Servicio", "Producto/Servicio"]

UNIDADES_MEDIDA = [
    "Sin descripción",
    "Kilogramo",
    "Metros",
    "Metro cuadrado",
    "Metro cubico",
    "Litros",
    "1000 kilowatt hora",
    "Unidad",
    "Par",
    "Docena",
    "Quilate",
    "Millar",
    "Mega-u. int. act. antib",
    "Unidad int. act. inmung",
    "Gramo",
    "Milimetro",
    "Milimetro cubico",
    "Kilometro",
    "Hectolitro",
    "Mega u. int. act. inmung.",
    "Centímetro",
    "Kilogramo activo",
    "Gramo activo",
    "Gramo base",
    "Uiacthor",
    "Juego o paquete mazo de naipes",
    "Muiacthor",
    "Centimetro cubico",
    "Uiactant",
    "Tonelada",
    "Decametro cubico",
    "Hectometro cubico",
    "Kilometro cubico",
    "Microgramo",
    "Nanogramo",
    "Picogramo",
    "Muiactant",
    "Uiactig",
    "Miligramo",
    "Mililitro",
    "Curie",
    "Milicurie",
    "Microcurie",
    "U. inter. act. hor.",
    "Mega u. inter. act. hor.",
    "Kilogramo base",
    "Gruesa",
    "Muiactig",
    "Kg. bruto",
    "Pack",
    "Horma",
    "Otras unidades",
]


# -----------------------------
# JSON SAFE
# -----------------------------
def _date_to_str(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def make_json_safe(obj):
    """Convierte recursivamente objetos no serializables (date/datetime) a string."""
    if isinstance(obj, (date, datetime)):
        return _date_to_str(obj.date() if isinstance(obj, datetime) else obj)
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [make_json_safe(v) for v in obj]
    return obj


# -----------------------------
# STATE
# -----------------------------
def _new_item() -> dict:
    return {
        "uid": str(uuid4()),
        "codigo": "",
        "descripcion": "",
        "cantidad": 1.0,
        "unidad_medida": "Unidad",
        "precio_modo": "con_iva",  # "con_iva" | "sin_iva"
        "precio_unitario": 0.0,
        "descuento_bonificacion": "",
    }


def init_state():
    if "step" not in st.session_state:
        st.session_state["step"] = "edit"  # edit | review | confirmed

    if "facturacion" not in st.session_state:
        today = date.today()
        st.session_state["facturacion"] = {
            "tipo_factura": None,
            "servicio_producto": None,
            "fecha_inicio": today,
            "fecha_fin": today,
            "fecha_vencimiento": today,
        }
    else:
        today = date.today()
        st.session_state["facturacion"].setdefault("fecha_inicio", today)
        st.session_state["facturacion"].setdefault("fecha_fin", today)
        st.session_state["facturacion"].setdefault("fecha_vencimiento", today)
        st.session_state["facturacion"].setdefault("tipo_factura", None)
        st.session_state["facturacion"].setdefault("servicio_producto", None)

    if "emisor" not in st.session_state:
        st.session_state["emisor"] = {
            "razon_social": "",
            "cuit": "",
            "domicilio": "",
            "condicion_iva": None,
            "requiere_delegacion": False,
            "clave_fiscal": "",
        }

    if "receptor" not in st.session_state:
        st.session_state["receptor"] = {
            "razon_social": "",
            "cuit_dni": "",
            "domicilio": "",
            "condicion_iva": None,
            "condicion_venta": None,
        }

    if "items" not in st.session_state:
        st.session_state["items"] = [_new_item()]
    else:
        fixed = []
        for it in st.session_state["items"]:
            if not isinstance(it, dict):
                continue
            if not it.get("uid"):
                it["uid"] = str(uuid4())
            it.setdefault("precio_modo", "con_iva")
            it.setdefault("precio_unitario", 0.0)
            it.setdefault("cantidad", 1.0)
            it.setdefault("unidad_medida", "Unidad")
            it.setdefault("descuento_bonificacion", "")
            it.setdefault("codigo", "")
            it.setdefault("descripcion", "")
            fixed.append(it)
        if not fixed:
            fixed = [_new_item()]
        st.session_state["items"] = fixed

    st.session_state.setdefault("last_payload", None)
    st.session_state.setdefault("last_saved_path", None)
    st.session_state.setdefault("last_webhook_result", None)


# -----------------------------
# UI HELPERS
# -----------------------------
def fmt_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def header():
    st.title("Bienvenido Gabi a tu portal de Facturación automatizada !  by Optimizar-ia ")
    st.subheader("Ingresa los datos de la factura que deseas realizar:")
    st.divider()


def set_digits_field(key_path: str):
    obj_name, field = key_path.split(".")
    obj = st.session_state[obj_name]
    obj[field] = sanitize_digits(obj.get(field, ""))
    st.session_state[obj_name] = obj


def is_factura_con_iva(tipo_factura: str | None) -> bool:
    return tipo_factura in ("Factura A", "Factura B")


# -----------------------------
# CALC
# -----------------------------
def _parse_discount_to_float(d_raw: str) -> float:
    s = str(d_raw or "").strip()
    if s == "":
        return 0.0
    return float(parse_decimal_optional(s))


def compute_item_amounts(item: dict, tipo_factura: str | None) -> tuple[dict, str | None]:
    """
    Factura A/B:
      - si precio_modo=con_iva => precio_unitario es final (con IVA).
      - si precio_modo=sin_iva => precio_unitario es neto, se suma IVA 21%.
    Descuento: MONTO (no %) y se resta del subtotal_total.
    """
    try:
        qty = float(item.get("cantidad", 0) or 0.0)
        price_input = float(item.get("precio_unitario", 0) or 0.0)
        discount = _parse_discount_to_float(item.get("descuento_bonificacion", ""))

        if qty < 0:
            return {}, "Cantidad inválida."
        if price_input < 0:
            return {}, "Precio inválido."

        if is_factura_con_iva(tipo_factura):
            modo = item.get("precio_modo", "con_iva")
            if modo == "sin_iva":
                unit_net = price_input
                unit_gross = unit_net * (1.0 + IVA_RATE)
            else:
                unit_gross = price_input
                unit_net = unit_gross / (1.0 + IVA_RATE)

            unit_iva = unit_gross - unit_net

            subtotal_gross = qty * unit_gross - discount
            subtotal_net = subtotal_gross / (1.0 + IVA_RATE)
            subtotal_iva = subtotal_gross - subtotal_net

            return {
                "unit_net": unit_net,
                "unit_iva": unit_iva,
                "unit_gross": unit_gross,
                "subtotal_net": subtotal_net,
                "subtotal_iva": subtotal_iva,
                "subtotal_gross": subtotal_gross,
            }, None

        # Factura C: sin desglose
        unit_gross = price_input
        subtotal_gross = qty * unit_gross - discount
        return {
            "unit_net": unit_gross,
            "unit_iva": 0.0,
            "unit_gross": unit_gross,
            "subtotal_net": subtotal_gross,
            "subtotal_iva": 0.0,
            "subtotal_gross": subtotal_gross,
        }, None

    except Exception:
        return {}, "No se pudo calcular (revisá cantidad / precio / descuento)."


def compute_totals(items_list: list[dict], tipo_factura: str | None) -> tuple[list[dict], dict, list[str]]:
    per_item_amounts: list[dict] = []
    calc_errors: list[str] = []
    total_net = 0.0
    total_iva = 0.0
    total_gross = 0.0

    for i, it in enumerate(items_list, start=1):
        amounts, err = compute_item_amounts(it, tipo_factura)
        per_item_amounts.append(amounts)
        if err:
            calc_errors.append(f"Item {i}: {err}")
            continue

        total_net += float(amounts.get("subtotal_net", 0.0) or 0.0)
        total_iva += float(amounts.get("subtotal_iva", 0.0) or 0.0)
        total_gross += float(amounts.get("subtotal_gross", 0.0) or 0.0)

    totals = {"total_net": total_net, "total_iva": total_iva, "total_gross": total_gross}
    return per_item_amounts, totals, calc_errors


# -----------------------------
# SECTIONS
# -----------------------------
def render_tipo_factura():
    st.subheader("1) Tipo de factura y fechas")

    fac = st.session_state["facturacion"]

    c1, c2 = st.columns(2)
    with c1:
        fac["tipo_factura"] = st.selectbox(
            "Tipo de factura",
            options=[None] + TIPO_FACTURA_OPTIONS,
            index=0 if fac.get("tipo_factura") is None else ([None] + TIPO_FACTURA_OPTIONS).index(fac["tipo_factura"]),
        )
    with c2:
        fac["servicio_producto"] = st.selectbox(
            "Producto / Servicio",
            options=[None] + SERVICIO_PRODUCTO_OPTIONS,
            index=0
            if fac.get("servicio_producto") is None
            else ([None] + SERVICIO_PRODUCTO_OPTIONS).index(fac["servicio_producto"]),
        )

    c3, c4, c5 = st.columns(3)
    with c3:
        fac["fecha_inicio"] = st.date_input("Fecha inicio", value=fac.get("fecha_inicio", date.today()))
    with c4:
        fac["fecha_fin"] = st.date_input("Fecha fin", value=fac.get("fecha_fin", date.today()))
    with c5:
        fac["fecha_vencimiento"] = st.date_input("Fecha vencimiento", value=fac.get("fecha_vencimiento", date.today()))

    st.session_state["facturacion"] = fac
    st.divider()


def render_emisor():
    st.subheader("2) Datos del emisor")

    em = st.session_state["emisor"]

    em["razon_social"] = st.text_input("Razón social (Emisor)", value=em.get("razon_social", ""))
    em["cuit"] = st.text_input("CUIT (solo números)", value=em.get("cuit", ""), on_change=set_digits_field, args=("emisor.cuit",))
    em["domicilio"] = st.text_input("Domicilio (Emisor)", value=em.get("domicilio", ""))

    em["condicion_iva"] = st.selectbox(
        "Condición frente al IVA (Emisor)",
        options=[None] + IVA_OPTIONS,
        index=0 if em.get("condicion_iva") is None else ([None] + IVA_OPTIONS).index(em["condicion_iva"]),
    )

    em["requiere_delegacion"] = st.checkbox(
        "Requiere delegación / clave fiscal",
        value=bool(em.get("requiere_delegacion", False)),
    )

    if em["requiere_delegacion"]:
        em["clave_fiscal"] = st.text_input("Clave fiscal (si aplica)", value=em.get("clave_fiscal", ""), type="password")

    st.session_state["emisor"] = em
    st.divider()


def render_receptor():
    st.subheader("3) Datos del receptor")

    re = st.session_state["receptor"]

    re["razon_social"] = st.text_input("Razón social (Receptor)", value=re.get("razon_social", ""))
    re["cuit_dni"] = st.text_input(
        "CUIT / DNI (solo números)",
        value=re.get("cuit_dni", ""),
        on_change=set_digits_field,
        args=("receptor.cuit_dni",),
    )
    re["domicilio"] = st.text_input("Domicilio (Receptor)", value=re.get("domicilio", ""))

    c1, c2 = st.columns(2)
    with c1:
        re["condicion_iva"] = st.selectbox(
            "Condición frente al IVA (Receptor)",
            options=[None] + IVA_OPTIONS,
            index=0 if re.get("condicion_iva") is None else ([None] + IVA_OPTIONS).index(re["condicion_iva"]),
        )
    with c2:
        re["condicion_venta"] = st.selectbox(
            "Condición de venta",
            options=[None] + COND_VENTA_OPTIONS,
            index=0
            if re.get("condicion_venta") is None
            else ([None] + COND_VENTA_OPTIONS).index(re["condicion_venta"]),
        )

    st.session_state["receptor"] = re
    st.divider()


def render_items():
    st.subheader("4) Ítems de la factura")

    tipo_factura = st.session_state["facturacion"].get("tipo_factura")
    items = st.session_state["items"]

    # Botones arriba
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("➕ Agregar ítem"):
            items.append(_new_item())
            st.session_state["items"] = items
            st.rerun()
    with c2:
        st.caption("El descuento/bonificación es un MONTO (no porcentaje). En Factura A/B podés elegir precio con o sin IVA.")

    # Render de cada ítem
    for idx, it in enumerate(items):
        with st.container(border=True):
            st.markdown(f"**Ítem {idx+1}**")

            a, b = st.columns([2, 1])
            with a:
                it["descripcion"] = st.text_input(
                    "Descripción",
                    value=it.get("descripcion", ""),
                    key=f"desc_{it['uid']}",
                )
                it["codigo"] = st.text_input(
                    "Código (opcional)",
                    value=it.get("codigo", ""),
                    key=f"cod_{it['uid']}",
                )

            with b:
                it["unidad_medida"] = st.selectbox(
                    "Unidad de medida",
                    options=UNIDADES_MEDIDA,
                    index=UNIDADES_MEDIDA.index(it.get("unidad_medida", "Unidad"))
                    if it.get("unidad_medida", "Unidad") in UNIDADES_MEDIDA
                    else UNIDADES_MEDIDA.index("Unidad"),
                    key=f"um_{it['uid']}",
                )
                it["cantidad"] = st.number_input(
                    "Cantidad",
                    min_value=0.0,
                    value=float(it.get("cantidad", 1.0) or 1.0),
                    step=1.0,
                    key=f"qty_{it['uid']}",
                )

            c3, c4, c5 = st.columns([1.2, 1.2, 1.0])
            with c3:
                if is_factura_con_iva(tipo_factura):
                    it["precio_modo"] = st.radio(
                        "Precio ingresado",
                        options=["con_iva", "sin_iva"],
                        format_func=lambda x: "Con IVA" if x == "con_iva" else "Sin IVA",
                        horizontal=True,
                        index=0 if it.get("precio_modo", "con_iva") == "con_iva" else 1,
                        key=f"pm_{it['uid']}",
                    )
                else:
                    it["precio_modo"] = "con_iva"
                    st.text_input("Precio ingresado", value="(Factura C) Total", disabled=True, key=f"pmc_{it['uid']}")

            with c4:
                it["precio_unitario"] = st.number_input(
                    "Precio unitario",
                    min_value=0.0,
                    value=float(it.get("precio_unitario", 0.0) or 0.0),
                    step=100.0,
                    key=f"pu_{it['uid']}",
                )
            with c5:
                it["descuento_bonificacion"] = st.text_input(
                    "Desc./Bonif. (monto)",
                    value=str(it.get("descuento_bonificacion", "")),
                    key=f"disc_{it['uid']}",
                    help="Ej: 1500 o 1500,50",
                )

            # Cálculo y vista rápida
            amounts, err = compute_item_amounts(it, tipo_factura)
            if err:
                st.warning(err)
            else:
                if is_factura_con_iva(tipo_factura):
                    st.caption(
                        f"Neto unit.: ${fmt_money(amounts['unit_net'])} | IVA unit.: ${fmt_money(amounts['unit_iva'])} | Total unit.: ${fmt_money(amounts['unit_gross'])}"
                    )
                    st.caption(
                        f"Subtotal neto: ${fmt_money(amounts['subtotal_net'])} | IVA: ${fmt_money(amounts['subtotal_iva'])} | Total: ${fmt_money(amounts['subtotal_gross'])}"
                    )
                else:
                    st.caption(f"Subtotal: ${fmt_money(amounts['subtotal_gross'])}")

            # Botón borrar
            if len(items) > 1:
                if st.button("🗑️ Eliminar este ítem", key=f"del_{it['uid']}"):
                    st.session_state["items"] = [x for x in items if x.get("uid") != it.get("uid")]
                    st.rerun()

        # Persistir
        items[idx] = it

    st.session_state["items"] = items

    # Totales
    per_item, totals, calc_errors = compute_totals(items, tipo_factura)
    if calc_errors:
        for e in calc_errors:
            st.warning(e)

    st.divider()
    st.subheader("Totales")
    if is_factura_con_iva(tipo_factura):
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Neto", f"$ {fmt_money(totals['total_net'])}")
        c2.metric("Total IVA", f"$ {fmt_money(totals['total_iva'])}")
        c3.metric("Total", f"$ {fmt_money(totals['total_gross'])}")
    else:
        st.metric("Total", f"$ {fmt_money(totals['total_gross'])}")

    st.divider()


def validate_all() -> list[str]:
    """Devuelve lista de errores (strings)."""
    errors: list[str] = []

    fac = st.session_state["facturacion"]
    em = st.session_state["emisor"]
    re = st.session_state["receptor"]
    items = st.session_state["items"]

    # Validaciones básicas
    # (usamos utilidades si están disponibles)
    try:
        errors += validate_required(fac, ["tipo_factura", "servicio_producto"])
    except Exception:
        # fallback suave
        if not fac.get("tipo_factura"):
            errors.append("Falta Tipo de factura.")
        if not fac.get("servicio_producto"):
            errors.append("Falta Producto/Servicio.")

    # Emisor
    if not em.get("razon_social", "").strip():
        errors.append("Falta Razón social del emisor.")
    if not is_digits_only(str(em.get("cuit", ""))):
        errors.append("CUIT del emisor inválido (solo números).")
    if not em.get("condicion_iva"):
        errors.append("Falta Condición IVA del emisor.")

    # Receptor
    if not re.get("razon_social", "").strip():
        errors.append("Falta Razón social del receptor.")
    if not is_digits_only(str(re.get("cuit_dni", ""))):
        errors.append("CUIT/DNI del receptor inválido (solo números).")
    if not re.get("condicion_iva"):
        errors.append("Falta Condición IVA del receptor.")
    if not re.get("condicion_venta"):
        errors.append("Falta Condición de venta del receptor.")

    # Items
    try:
        errors += validate_items(items)
    except Exception:
        # fallback
        if not items:
            errors.append("Debe haber al menos 1 ítem.")
        for i, it in enumerate(items, start=1):
            if not str(it.get("descripcion", "")).strip():
                errors.append(f"Ítem {i}: falta descripción.")
            try:
                float(it.get("cantidad", 0) or 0)
                float(it.get("precio_unitario", 0) or 0)
            except Exception:
                errors.append(f"Ítem {i}: cantidad/precio inválidos.")

    # Cálculos
    _, _, calc_errors = compute_totals(items, fac.get("tipo_factura"))
    errors += calc_errors

    return errors


def build_and_store_payload() -> dict:
    """Construye payload con utils.build_payload y lo guarda en session_state['last_payload']."""
    fac = make_json_safe(st.session_state["facturacion"])
    em = make_json_safe(st.session_state["emisor"])
    re = make_json_safe(st.session_state["receptor"])
    items = make_json_safe(st.session_state["items"])

    payload = build_payload(
        facturacion=fac,
        emisor=em,
        receptor=re,
        items=items,
    )

    st.session_state["last_payload"] = payload
    return payload


def render_review():
    st.subheader("Revisión")

    errs = validate_all()
    if errs:
        st.error("Hay errores para corregir antes de enviar:")
        for e in errs:
            st.write(f"- {e}")
        st.info("Volvé atrás, corregí y luego revisá nuevamente.")
        return

    payload = build_and_store_payload()

    st.success("Todo OK. Este es el JSON que se enviará:")
    st.json(payload)

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("⬅️ Volver a editar"):
            st.session_state["step"] = "edit"
            st.rerun()
    with c2:
        if st.button("💾 Guardar JSON"):
            try:
                saved_path = save_json(payload)
                st.session_state["last_saved_path"] = saved_path
                st.success(f"Guardado en: {saved_path}")
            except Exception as e:
                st.error(f"No se pudo guardar JSON: {e}")

    with c3:
        if st.button("🚀 Enviar al webhook", type="primary"):
            try:
                resp = requests.post(WEBHOOK_URL, json=payload, timeout=45)
                st.session_state["last_webhook_result"] = {
                    "status_code": resp.status_code,
                    "text": resp.text[:3000],
                }
                if 200 <= resp.status_code < 300:
                    st.success("Enviado correctamente.")
                    st.session_state["step"] = "confirmed"
                    st.rerun()
                else:
                    st.error(f"El webhook respondió con status {resp.status_code}")
                    st.code(resp.text)
            except Exception as e:
                st.error(f"Error enviando al webhook: {e}")


def render_confirmed():
    st.subheader("✅ Confirmado")

    st.success("La operación fue enviada. Si querés, podés iniciar una nueva factura.")
    if st.session_state.get("last_saved_path"):
        st.caption(f"Último JSON guardado: {st.session_state['last_saved_path']}")

    last = st.session_state.get("last_webhook_result")
    if last:
        st.caption("Respuesta del webhook:")
        st.write(f"Status: {last.get('status_code')}")
        st.code(last.get("text", ""))

    if st.button("🧾 Nueva factura"):
        # reset suave, conservando estructura
        for k in ["facturacion", "emisor", "receptor", "items", "last_payload", "last_saved_path", "last_webhook_result"]:
            if k in st.session_state:
                del st.session_state[k]
        st.session_state["step"] = "edit"
        st.rerun()


def main():
    st.set_page_config(page_title="Facturación ARCA", layout="wide")
    init_state()
    header()

    step = st.session_state.get("step", "edit")

    if step == "edit":
        render_tipo_factura()
        render_emisor()
        render_receptor()
        render_items()

        errs = validate_all()
        if errs:
            st.warning(f"Hay {len(errs)} cosas a corregir antes de revisar.")
        if st.button("✅ Revisar antes de enviar", type="primary"):
            st.session_state["step"] = "review"
            st.rerun()

    elif step == "review":
        render_review()

    elif step == "confirmed":
        render_confirmed()

    else:
        st.session_state["step"] = "edit"
        st.rerun()


if __name__ == "__main__":
    main()
