# app.py
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

# Listado de opciones de Tipo de Factura según AFIP
TIPO_FACTURA_OPTIONS = ["Factura A", "Factura B", "Factura C"]

# Listado de opciones de Condición frente al IVA según AFIP
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

# Listado de opciones de Condición de Venta según AFIP
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

# Listado de opciones de Servicio/Producto según AFIP
SERVICIO_PRODUCTO_OPTIONS = ["Producto", "Servicio", "Producto/Servicio"]

# Listado de Unidades de Medida según AFIP
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
    """
    Convierte recursivamente objetos no serializables (date/datetime) a string.
    """
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
        # asegurar llaves (migración)
        today = date.today()
        st.session_state["facturacion"].setdefault("fecha_inicio", today)
        st.session_state["facturacion"].setdefault("fecha_fin", today)
        st.session_state["facturacion"].setdefault("fecha_vencimiento", today)

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
        # migración: asegurar uid en items ya existentes
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
    st.title("Bienvenido Gabi a tu prtal de Facturación automatizada !  by Optimizar-ia ")
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
    st.markdown("### Tipo de Factura")
    st.session_state["facturacion"]["tipo_factura"] = st.selectbox(
        "Tipo de Factura *",
        options=["(Seleccionar)"] + TIPO_FACTURA_OPTIONS,
        index=0
        if not st.session_state["facturacion"]["tipo_factura"]
        else (TIPO_FACTURA_OPTIONS.index(st.session_state["facturacion"]["tipo_factura"]) + 1),
        key="tipo_factura",
    )
    if st.session_state["facturacion"]["tipo_factura"] == "(Seleccionar)":
        st.session_state["facturacion"]["tipo_factura"] = None


def render_emisor():
    st.markdown("### Emisor")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state["emisor"]["razon_social"] = st.text_input(
            "Nombre/razón social *", value=st.session_state["emisor"]["razon_social"], key="em_rs"
        )
    with col2:
        st.session_state["emisor"]["cuit"] = st.text_input(
            "CUIT * (Solo colocar números sin guiones)",
            value=st.session_state["emisor"]["cuit"],
            help="Solo números, sin guiones.",
            on_change=set_digits_field,
            args=("emisor.cuit",),
            key="em_cuit",
        )
        if st.session_state["emisor"]["cuit"] and not is_digits_only(st.session_state["emisor"]["cuit"]):
            st.warning("El CUIT solo puede contener números. Se limpiaron caracteres inválidos.")

    st.session_state["emisor"]["domicilio"] = st.text_input(
        "Domicilio (Opcional)", value=st.session_state["emisor"]["domicilio"], key="em_dom"
    )

    st.session_state["emisor"]["condicion_iva"] = st.selectbox(
        "Condición frente al IVA *",
        options=["(Seleccionar)"] + IVA_OPTIONS,
        index=0
        if not st.session_state["emisor"]["condicion_iva"]
        else (IVA_OPTIONS.index(st.session_state["emisor"]["condicion_iva"]) + 1),
        key="em_iva",
    )
    if st.session_state["emisor"]["condicion_iva"] == "(Seleccionar)":
        st.session_state["emisor"]["condicion_iva"] = None

    st.divider()
    st.info(
        "En caso de requerir Delegación de servicios  tildar esta casilla (por única vez) "
        "y deberá ingresar por única vez la Clave Fiscal del Emisor."
    )
    st.session_state["emisor"]["requiere_delegacion"] = st.checkbox(
        "Requiere Delegación de servicios (por única vez)",
        value=bool(st.session_state["emisor"].get("requiere_delegacion", False)),
        key="em_req_del",
    )

    if st.session_state["emisor"]["requiere_delegacion"]:
        st.session_state["emisor"]["clave_fiscal"] = st.text_input(
            "Clave Fiscal del Emisor *",
            value=st.session_state["emisor"].get("clave_fiscal", ""),
            type="password",
            key="em_clave",
        )
    else:
        st.session_state["emisor"]["clave_fiscal"] = ""


def render_receptor():
    st.markdown("### Receptor")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state["receptor"]["razon_social"] = st.text_input(
            "Nombre/razón social *",
            value=st.session_state["receptor"]["razon_social"],
            key="rec_rs",
        )
    with col2:
        st.session_state["receptor"]["cuit_dni"] = st.text_input(
            "CUIT/DNI * (Solo colocar números sin guiones)",
            value=st.session_state["receptor"]["cuit_dni"],
            help="Solo números, sin guiones.",
            on_change=set_digits_field,
            args=("receptor.cuit_dni",),
            key="rec_cuit",
        )
        if st.session_state["receptor"]["cuit_dni"] and not is_digits_only(st.session_state["receptor"]["cuit_dni"]):
            st.warning("El CUIT/DNI solo puede contener números. Se limpiaron caracteres inválidos.")

    st.session_state["receptor"]["domicilio"] = st.text_input(
        "Domicilio (Opcional)", value=st.session_state["receptor"]["domicilio"], key="rec_dom"
    )

    st.session_state["receptor"]["condicion_iva"] = st.selectbox(
        "Condición frente al IVA *",
        options=["(Seleccionar)"] + IVA_OPTIONS,
        index=0
        if not st.session_state["receptor"]["condicion_iva"]
        else (IVA_OPTIONS.index(st.session_state["receptor"]["condicion_iva"]) + 1),
        key="rec_iva",
    )
    if st.session_state["receptor"]["condicion_iva"] == "(Seleccionar)":
        st.session_state["receptor"]["condicion_iva"] = None

    st.session_state["receptor"]["condicion_venta"] = st.selectbox(
        "Condición de venta *",
        options=["(Seleccionar)"] + COND_VENTA_OPTIONS,
        index=0
        if not st.session_state["receptor"]["condicion_venta"]
        else (COND_VENTA_OPTIONS.index(st.session_state["receptor"]["condicion_venta"]) + 1),
        key="rec_cv",
    )
    if st.session_state["receptor"]["condicion_venta"] == "(Seleccionar)":
        st.session_state["receptor"]["condicion_venta"] = None


def render_facturacion():
    st.markdown("### Datos de Facturación")
    st.session_state["facturacion"]["servicio_producto"] = st.selectbox(
        "Servicio/Producto *",
        options=["(Seleccionar)"] + SERVICIO_PRODUCTO_OPTIONS,
        index=0
        if not st.session_state["facturacion"]["servicio_producto"]
        else (SERVICIO_PRODUCTO_OPTIONS.index(st.session_state["facturacion"]["servicio_producto"]) + 1),
        key="sp",
    )
    if st.session_state["facturacion"]["servicio_producto"] == "(Seleccionar)":
        st.session_state["facturacion"]["servicio_producto"] = None

    st.markdown("#### Fechas")
    f1, f2, f3 = st.columns(3)
    with f1:
        st.session_state["facturacion"]["fecha_inicio"] = st.date_input(
            "Fecha de inicio *",
            value=st.session_state["facturacion"]["fecha_inicio"],
            format="DD/MM/YYYY",
            key="fecha_inicio",
        )
    with f2:
        st.session_state["facturacion"]["fecha_fin"] = st.date_input(
            "Fecha de fin *",
            value=st.session_state["facturacion"]["fecha_fin"],
            format="DD/MM/YYYY",
            key="fecha_fin",
        )
    with f3:
        st.session_state["facturacion"]["fecha_vencimiento"] = st.date_input(
            "Fecha de vencimiento *",
            value=st.session_state["facturacion"]["fecha_vencimiento"],
            format="DD/MM/YYYY",
            key="fecha_vencimiento",
        )


def render_items():
    st.markdown("### Items a facturar")

    items_list = st.session_state["items"]
    tipo_factura = st.session_state["facturacion"]["tipo_factura"]
    con_iva = is_factura_con_iva(tipo_factura)

    if con_iva:
        st.caption("Factura A/B: podés ingresar **Precio Unitario con IVA** o **Precio sin IVA** (se aplica IVA 21%).")
    else:
        st.caption("Factura C: el precio se toma como final (sin desglose de IVA).")

    # Render por item (con keys basadas en uid para que no se pierda estado)
    for it in list(items_list):
        uid = it["uid"]

        with st.container(border=True):
            st.markdown("**Item**")

            c1, c2, c3 = st.columns([1, 2, 1])
            with c1:
                it["codigo"] = st.text_input("Código (Opcional)", value=it.get("codigo", ""), key=f"{uid}_cod")
            with c2:
                it["descripcion"] = st.text_input("Descripción *", value=it.get("descripcion", ""), key=f"{uid}_desc")
            with c3:
                it["cantidad"] = st.number_input(
                    "Cantidad *",
                    min_value=0.0,
                    value=float(it.get("cantidad", 1.0) or 1.0),
                    step=1.0,
                    key=f"{uid}_qty",
                )

            c4, c5, c6 = st.columns([2, 1, 1])
            with c4:
                it["unidad_medida"] = st.selectbox(
                    "Unidad de medida *",
                    options=UNIDADES_MEDIDA,
                    index=UNIDADES_MEDIDA.index(it.get("unidad_medida", "Unidad"))
                    if it.get("unidad_medida", "Unidad") in UNIDADES_MEDIDA
                    else 0,
                    key=f"{uid}_um",
                )

            if con_iva:
                with c5:
                    modo_label = st.selectbox(
                        "Modo de precio *",
                        options=["Precio unitario final (con IVA)", "Precio unitario sin IVA"],
                        index=0 if it.get("precio_modo", "con_iva") == "con_iva" else 1,
                        key=f"{uid}_modo",
                    )
                    it["precio_modo"] = "con_iva" if modo_label.startswith("Precio unitario final") else "sin_iva"
                with c6:
                    it["precio_unitario"] = st.number_input(
                        "Precio Unitario *",
                        min_value=0.0,
                        value=float(it.get("precio_unitario", 0.0) or 0.0),
                        step=1.0,
                        key=f"{uid}_pu",
                    )
            else:
                with c5:
                    it["precio_modo"] = "con_iva"
                    it["precio_unitario"] = st.number_input(
                        "Precio Unitario *",
                        min_value=0.0,
                        value=float(it.get("precio_unitario", 0.0) or 0.0),
                        step=1.0,
                        key=f"{uid}_pu",
                    )
                with c6:
                    st.write("")

            it["descuento_bonificacion"] = st.text_input(
                "Descuento/Bonificación (Opcional)",
                value=str(it.get("descuento_bonificacion", "") or ""),
                help="Podés usar coma o punto (ej: 10,5). Se interpreta como MONTO (no porcentaje).",
                key=f"{uid}_descbon",
            )

            # Subtotal del item calculado con los valores ya leídos
            am, err = compute_item_amounts(it, tipo_factura)
            if err or not am:
                st.warning("Subtotal: no disponible (revisá cantidad/precio/descuento)")
            else:
                if con_iva:
                    st.caption(
                        f"Subtotal Neto: {fmt_money(float(am.get('subtotal_net', 0.0)))}  |  "
                        f"IVA 21%: {fmt_money(float(am.get('subtotal_iva', 0.0)))}  |  "
                        f"Subtotal Total: {fmt_money(float(am.get('subtotal_gross', 0.0)))}"
                    )
                else:
                    st.caption(f"Subtotal: {fmt_money(float(am.get('subtotal_gross', 0.0)))}")

            col_del, _ = st.columns([1, 5])
            with col_del:
                if len(items_list) > 1 and st.button("Eliminar item", key=f"{uid}_del"):
                    st.session_state["items"] = [x for x in st.session_state["items"] if x["uid"] != uid]
                    st.rerun()

    if st.button("Agregar item"):
        st.session_state["items"] = st.session_state["items"] + [_new_item()]
        st.rerun()

    # Totales (recalculados con el estado ya actualizado)
    items_list = st.session_state["items"]
    per_item_amounts, totals, calc_errors = compute_totals(items_list, tipo_factura)

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Cantidad de items", len(items_list))
    if con_iva:
        with c2:
            st.metric("TOTAL Neto", fmt_money(float(totals["total_net"])))
        with c3:
            st.metric("TOTAL (con IVA 21%)", fmt_money(float(totals["total_gross"])))
        st.caption(f"IVA 21% total: {fmt_money(float(totals['total_iva']))}")
    else:
        with c2:
            st.metric("TOTAL", fmt_money(float(totals["total_gross"])))
        with c3:
            st.write("")

    if calc_errors:
        with st.expander("Ver advertencias de cálculo"):
            for e in calc_errors:
                st.write(f"- {e}")


# -----------------------------
# VALIDATION + PAYLOAD
# -----------------------------
def validate_all() -> list[str]:
    errors: list[str] = []

    if not st.session_state["facturacion"]["tipo_factura"]:
        errors.append("Tipo de Factura: es obligatorio seleccionar una opción.")

    if not st.session_state["facturacion"]["fecha_inicio"]:
        errors.append("Fecha de inicio: es obligatoria.")
    if not st.session_state["facturacion"]["fecha_fin"]:
        errors.append("Fecha de fin: es obligatoria.")
    if not st.session_state["facturacion"]["fecha_vencimiento"]:
        errors.append("Fecha de vencimiento: es obligatoria.")

    ok, msg = validate_required(st.session_state["emisor"]["razon_social"])
    if not ok:
        errors.append("Emisor - Nombre/razón social: " + msg)

    if not is_digits_only(st.session_state["emisor"]["cuit"]):
        errors.append("Emisor - CUIT: Debe contener solo números y no puede estar vacío.")

    if not st.session_state["emisor"]["condicion_iva"]:
        errors.append("Emisor - Condición frente al IVA: es obligatoria.")

    if st.session_state["emisor"].get("requiere_delegacion", False):
        clave = str(st.session_state["emisor"].get("clave_fiscal", "") or "").strip()
        if not clave:
            errors.append("Emisor - Clave Fiscal: es obligatoria si se requiere Delegación de servicios.")

    ok, msg = validate_required(st.session_state["receptor"]["razon_social"])
    if not ok:
        errors.append("Receptor - Nombre/razón social: " + msg)

    if not is_digits_only(st.session_state["receptor"]["cuit_dni"]):
        errors.append("Receptor - CUIT/DNI: Debe contener solo números y no puede estar vacío.")

    if not st.session_state["receptor"]["condicion_iva"]:
        errors.append("Receptor - Condición frente al IVA: es obligatoria.")

    if not st.session_state["receptor"]["condicion_venta"]:
        errors.append("Receptor - Condición de venta: es obligatoria.")

    if not st.session_state["facturacion"]["servicio_producto"]:
        errors.append("Datos de Facturación - Servicio/Producto: es obligatorio.")

    # Validación base de items (tu utils.py)
    errors.extend(validate_items(st.session_state["items"]))

    # Validar descuentos numéricos (coma/punto)
    for i, it in enumerate(st.session_state["items"], start=1):
        d_raw = str(it.get("descuento_bonificacion", "") or "").strip()
        if d_raw != "":
            try:
                _ = parse_decimal_optional(d_raw)
            except ValueError:
                errors.append(f"Item {i}: 'Descuento/Bonificación' no es un número válido.")

    return errors


def build_payload_from_session() -> dict:
    # Copia “sanitizada” de facturacion con fechas como string
    fact = dict(st.session_state["facturacion"])
    fact["fecha_inicio"] = _date_to_str(fact["fecha_inicio"])
    fact["fecha_fin"] = _date_to_str(fact["fecha_fin"])
    fact["fecha_vencimiento"] = _date_to_str(fact["fecha_vencimiento"])

    payload = build_payload(
        {
            "emisor": st.session_state["emisor"],
            "receptor": st.session_state["receptor"],
            "facturacion": fact,
            "items": st.session_state["items"],
        }
    )

    tipo_factura = st.session_state["facturacion"]["tipo_factura"]
    per_item_amounts, totals, _ = compute_totals(st.session_state["items"], tipo_factura)

    payload["totales"] = {
        "moneda": "ARS",
        "tipo_factura": tipo_factura,
        "total_neto": totals["total_net"],
        "total_iva_21": totals["total_iva"],
        "total": totals["total_gross"],
        "items_calculados": per_item_amounts,
        "nota": "Factura A/B: total = neto + IVA 21%. Factura C: sin desglose de IVA.",
    }

    # Por las dudas: convertir cualquier date/datetime que haya quedado
    payload = make_json_safe(payload)
    return payload


# -----------------------------
# PAGES
# -----------------------------
def page_edit():
    header()

    render_tipo_factura()
    st.divider()

    render_emisor()
    st.divider()

    render_receptor()
    st.divider()

    render_facturacion()
    st.divider()

    render_items()

    st.divider()
    if st.button("Finalizar"):
        errs = validate_all()
        if errs:
            st.error("Hay errores en el formulario:")
            for e in errs:
                st.write(f"- {e}")
            return

        payload = build_payload_from_session()
        st.session_state["last_payload"] = payload
        st.session_state["step"] = "review"
        st.rerun()


def page_review():
    st.title("Revisar Factura a generar:")
    st.write("Visualizá todos los datos añadidos antes de confirmar.")
    st.divider()

    payload = st.session_state["last_payload"]
    if not payload:
        st.warning("No hay datos para revisar. Volviendo a edición.")
        st.session_state["step"] = "edit"
        st.rerun()

    tipo_factura = (payload.get("datos_facturacion", {}) or {}).get("tipo_factura", None)
    con_iva = is_factura_con_iva(tipo_factura)

    st.markdown("#### Resumen de items")
    rows = []
    items = payload.get("items", [])
    calc_items = (payload.get("totales", {}) or {}).get("items_calculados", [])

    for i, it in enumerate(items, start=1):
        am = calc_items[i - 1] if i - 1 < len(calc_items) else {}
        row = {
            "N°": i,
            "Código": it.get("codigo", ""),
            "Descripción": it.get("descripcion", ""),
            "Cantidad": it.get("cantidad", ""),
            "Unidad": it.get("unidad_medida", ""),
            "Modo Precio": ("Con IVA" if it.get("precio_modo") == "con_iva" else "Sin IVA") if con_iva else "-",
            "Precio Ingresado": it.get("precio_unitario", ""),
            "Descuento": it.get("descuento_bonificacion", ""),
        }
        if con_iva:
            row.update(
                {
                    "Unit Neto": am.get("unit_net", None),
                    "Unit IVA": am.get("unit_iva", None),
                    "Unit Total": am.get("unit_gross", None),
                    "Sub Neto": am.get("subtotal_net", None),
                    "Sub IVA": am.get("subtotal_iva", None),
                    "Sub Total": am.get("subtotal_gross", None),
                }
            )
        else:
            row.update({"Subtotal": am.get("subtotal_gross", None)})
        rows.append(row)

    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.divider()
    tot = payload.get("totales", {}) or {}
    st.markdown("#### Totales")
    st.write(f"Tipo de factura: **{tot.get('tipo_factura', '-') }**")
    if con_iva:
        st.metric("TOTAL Neto", fmt_money(float(tot.get("total_neto", 0.0) or 0.0)))
        st.metric("IVA 21%", fmt_money(float(tot.get("total_iva_21", 0.0) or 0.0)))
        st.metric("TOTAL", fmt_money(float(tot.get("total", 0.0) or 0.0)))
    else:
        st.metric("TOTAL", fmt_money(float(tot.get("total", 0.0) or 0.0)))

    st.divider()
    st.markdown("#### Resumen completo (JSON)")
    st.json(payload)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Editar"):
            st.session_state["step"] = "edit"
            st.rerun()
    with col2:
        if st.button("Confirmar Datos a Facturar"):
            st.session_state["step"] = "confirmed"
            st.rerun()


def send_to_webhook(payload: dict) -> dict:
    payload = make_json_safe(payload)  # seguridad extra
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=300)
        content_type = (r.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            body = r.json()
        else:
            body = {"raw_text": r.text}
        return {"ok": r.ok, "status_code": r.status_code, "response": body}
    except requests.RequestException as e:
        return {"ok": False, "status_code": None, "response": {"error": str(e)}}


def page_confirmed():
    st.title("Confirmación")
    st.write("Si todo está correcto, enviá los datos al workflow de n8n.")
    st.divider()

    payload = st.session_state["last_payload"]
    if not payload:
        st.warning("No hay datos confirmados. Volviendo a edición.")
        st.session_state["step"] = "edit"
        st.rerun()

    tot = payload.get("totales", {}) or {}
    tipo_factura = tot.get("tipo_factura", None)
    con_iva = is_factura_con_iva(tipo_factura)

    st.markdown("#### Items (Resumen)")
    calc_items = tot.get("items_calculados", []) or []
    st.dataframe(
        [
            {
                "Código": it.get("codigo", ""),
                "Descripción": it.get("descripcion", ""),
                "Cantidad": it.get("cantidad", ""),
                "Unidad": it.get("unidad_medida", ""),
                "Modo Precio": ("Con IVA" if it.get("precio_modo") == "con_iva" else "Sin IVA") if con_iva else "-",
                "Precio Ingresado": it.get("precio_unitario", ""),
                "Descuento": it.get("descuento_bonificacion", ""),
                "Subtotal": (calc_items[i].get("subtotal_gross") if i < len(calc_items) else None),
            }
            for i, it in enumerate(payload.get("items", []))
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.markdown("#### Totales")
    st.write(f"Tipo de factura: **{tipo_factura or '-'}**")
    if con_iva:
        st.metric("TOTAL Neto", fmt_money(float(tot.get("total_neto", 0.0) or 0.0)))
        st.metric("IVA 21%", fmt_money(float(tot.get("total_iva_21", 0.0) or 0.0)))
        st.metric("TOTAL", fmt_money(float(tot.get("total", 0.0) or 0.0)))
    else:
        st.metric("TOTAL", fmt_money(float(tot.get("total", 0.0) or 0.0)))

    st.divider()
    st.markdown("#### Datos confirmados (JSON)")
    st.json(payload)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Volver a Editar"):
            st.session_state["step"] = "edit"
            st.rerun()

    with col2:
        if st.button("Enviar Datos"):
            safe_payload = make_json_safe(payload)
            path = save_json(safe_payload, folder="data")  # <- ahora no rompe con date
            st.session_state["last_saved_path"] = str(path)

            result = send_to_webhook(safe_payload)
            st.session_state["last_webhook_result"] = result
            st.rerun()

    if st.session_state["last_saved_path"]:
        st.success(f"JSON guardado en: {st.session_state['last_saved_path']}")

    if st.session_state["last_webhook_result"]:
        res = st.session_state["last_webhook_result"]
        if res["ok"]:
            st.success("Respuesta del workflow (éxito):")
        else:
            st.error("Respuesta del workflow (error):")
        st.write(f"Status code: {res['status_code']}")
        st.json(res["response"])


# -----------------------------
# MAIN
# -----------------------------
def main():
    st.set_page_config(page_title="Facturación Automatizada", layout="wide")
    init_state()

    step = st.session_state["step"]
    if step == "edit":
        page_edit()
    elif step == "review":
        page_review()
    elif step == "confirmed":
        page_confirmed()
    else:
        st.session_state["step"] = "edit"
        st.rerun()


if __name__ == "__main__":
    main()
