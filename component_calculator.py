import streamlit as st
import pandas as pd
import re
from decimal import Decimal
from html import escape
from psycopg2.extras import execute_values


class FormulaError(Exception):
    pass


VARIABLE_ALIASES = {
    "opening_height": "opening_length",
    "opening_l": "opening_length",
    "opening_w": "opening_width",
    "height_opening": "opening_length",
    "width_opening": "opening_width",
    "clearance": "vertical_clearance",
    "clr": "vertical_clearance",
    "v_clearance": "vertical_clearance",
    "h_clearance": "horizontal_clearance",
    "extra_l": "architrave_extra_length",
    "extra_length": "architrave_extra_length",
    "extra_w": "architrave_extra_width",
    "extra_width": "architrave_extra_width",
    "frame_h_thk": "frame_horizontal_thickness",
    "frame_v_thk": "frame_vertical_thickness",
    "frame_horizontal_thicknes": "frame_horizontal_thickness",
    "glass_shutter_width_top1": "glass_shutter_width_top_1",
    "glass_shutter_width_top2": "glass_shutter_width_top_2",
    "glass_shutter_width_bottom1": "glass_shutter_width_bottom_1",
    "glass_shutter_width_bottom2": "glass_shutter_width_bottom_2",
    "mesh_shutter_width_top1": "mesh_shutter_width_top_1",
    "mesh_shutter_width_top2": "mesh_shutter_width_top_2",
    "mesh_shutter_width_bottom1": "mesh_shutter_width_bottom_1",
    "mesh_shutter_width_bottom2": "mesh_shutter_width_bottom_2",
    "glass_shutter_width_topf1": "glass_shutter_width_top_f1",
    "glass_shutter_width_topf2": "glass_shutter_width_top_f2",
    "glass_shutter_width_bottomf1": "glass_shutter_width_bottom_f1",
    "glass_shutter_width_bottomf2": "glass_shutter_width_bottom_f2",
}


DEFAULT_VALUES = {
    "opening_length": 0,
    "opening_width": 0.0,
    "opening_height_1": 0.0,
    "opening_height_2": 0.0,
    "opening_length_1": 0.0,
    "opening_length_2": 0.0,
    "vertical_clearance": 10.0,
    "horizontal_clearance": 20.0,
    "architrave_extra_length": 50.0,
    "architrave_extra_width": 100.0,
    "frame_horizontal_thickness": 0.0,
    "frame_vertical_thickness": 0.0,
    "shutter_thickness": 38.0,
    "lh_quantity": 0.0,
    "rh_quantity": 0.0,
    "quantity": 0.0,
    "mesh_yes": 0.0,
}


COMPONENT_INPUT_KEYS = {
    "vertical_clearance",
    "horizontal_clearance",
    "architrave_extra_length",
    "architrave_extra_width",
    "frame_horizontal_thickness",
    "frame_vertical_thickness",
    "shutter_thickness",
    "lh_quantity",
    "rh_quantity",
    "quantity",
}


FIXED_COMPONENT_DIMENSIONS = {
    "architrave_vertical": {"width": Decimal("40"), "thickness": Decimal("12")},
    "architrave_horizontal": {"width": Decimal("40"), "thickness": Decimal("12")},
    "architrave_vertical_front": {"width": Decimal("40"), "thickness": Decimal("12")},
    "architrave_horizontal_front": {"width": Decimal("40"), "thickness": Decimal("12")},
    "door_frame_vertical_beading": {"width": Decimal("27"), "thickness": Decimal("11")},
    "door_frame_horizontal_beading": {"width": Decimal("27"), "thickness": Decimal("11")},
    "door_frame_vertical_beading_1": {"width": Decimal("15"), "thickness": Decimal("7")},
    "door_frame_horizontal_beading_1": {"width": Decimal("15"), "thickness": Decimal("7")},
    "door_frame_horizontal_beading_2": {"width": Decimal("20"), "thickness": Decimal("8")},
    "louver": {"width": Decimal("41.5"), "thickness": Decimal("7.5")},
}


def slug(value):
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def label_from_key(key):
    if key == "mesh_yes":
        return "Mesh"
    return str(key).replace("_", " ").title()


def split_product_codes(product_code):
    return [code.strip() for code in str(product_code or "").split(",") if code.strip()]


def is_door_product(product_cat, product_code):
    text = slug(f"{product_cat} {product_code}")
    return "door" in text or "doowindow" in text or "door_window" in text


def is_fw_product(product_cat, product_code):
    text = slug(f"{product_cat} {product_code}")
    return "fw" in text or "french_window" in text


def is_fw3_product(product_cat, product_code):
    return "fw3" in slug(f"{product_cat} {product_code}")


def normalize_variable(var_name):
    var_name = slug(var_name)
    return VARIABLE_ALIASES.get(var_name, var_name)


def clean_number(value):
    if value in [None, ""]:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    try:
        return float(value)
    except Exception:
        return None


def clean_int(value):
    number = clean_number(value)

    if number is None:
        return 0

    return int(float(number))


def decimal_or_none(value):
    number = clean_number(value)

    if number is None:
        return None

    return Decimal(str(round(number, 2)))


def safe_execute(conn, cur, query, params=None):
    try:
        cur.execute(query, params or ())
    except Exception as e:
        conn.rollback()
        raise e


def get_distinct_values(conn, cur, table, column, where_sql="", params=None):
    query = f"""
        SELECT DISTINCT {column}
        FROM {table}
        {where_sql}
        ORDER BY {column}
    """
    safe_execute(conn, cur, query, params)
    return [r[0] for r in cur.fetchall() if r[0] is not None]


def get_table_columns(conn, cur, table):
    safe_execute(conn, cur, """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
    """, (table,))
    return {row[0] for row in cur.fetchall()}


def first_existing_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def rule_value(rule, key, default=None):
    return rule.get(key, default)


def load_product_rules(conn, cur, product_cat, selected_product_code):
    columns = get_table_columns(conn, cur, "product_component_rules")

    product_code_col = first_existing_column(columns, ["product_code", "productcode"])
    product_cat_col = first_existing_column(columns, ["product_cat", "productcat"])
    component_col = first_existing_column(columns, ["component", "components"])
    attribute_col = first_existing_column(columns, ["attribute"])
    type_col = first_existing_column(columns, ["type"])
    formula_col = first_existing_column(columns, ["formula_used", "formula"])
    quantity_col = first_existing_column(columns, ["quantity", "quanity"])
    width_col = first_existing_column(columns, ["width", "fixed_width", "component_width"])
    thickness_col = first_existing_column(columns, ["thickness", "fixed_thickness", "component_thickness"])

    if not all([product_code_col, product_cat_col, component_col, attribute_col, type_col, formula_col, quantity_col]):
        raise Exception("Missing required columns in product_component_rules table.")

    select_cols = [
        f"{product_code_col} AS product_code",
        f"{component_col} AS component",
        f"{attribute_col} AS attribute",
        f"{type_col} AS type",
        f"{formula_col} AS formula_used",
        f"{quantity_col} AS quantity",
    ]

    if width_col:
        select_cols.append(f"{width_col} AS fixed_width")
    else:
        select_cols.append("NULL AS fixed_width")

    if thickness_col:
        select_cols.append(f"{thickness_col} AS fixed_thickness")
    else:
        select_cols.append("NULL AS fixed_thickness")

    query = f"""
        SELECT {", ".join(select_cols)}
        FROM product_component_rules
        WHERE {product_cat_col} = %s
    """

    safe_execute(conn, cur, query, (product_cat,))

    col_names = [desc[0] for desc in cur.description]
    rows = [dict(zip(col_names, row)) for row in cur.fetchall()]

    rules = []
    last_product_code = None

    for row in rows:
        db_product_code = row.get("product_code")

        if db_product_code not in [None, ""]:
            last_product_code = db_product_code
        else:
            db_product_code = last_product_code

        row["product_code"] = db_product_code

        if selected_product_code in split_product_codes(db_product_code):
            rules.append({
                "product_code": row.get("product_code"),
                "component": row.get("component"),
                "attribute": row.get("attribute"),
                "rule_type": row.get("type"),
                "formula": row.get("formula_used"),
                "quantity": row.get("quantity"),
                "fixed_width": row.get("fixed_width"),
                "fixed_thickness": row.get("fixed_thickness"),
            })

    return rules


def build_product_options(products):
    options = []

    for product_cat, product_code in products:
        for single_code in split_product_codes(product_code):
            options.append(f"{product_cat} | {single_code}")

    return sorted(set(options))


def formula_known_keys(rules, variables=None):
    variables = variables or {}
    keys = set(DEFAULT_VALUES.keys())
    keys.update(variables.keys())

    for rule in rules:
        component = rule_value(rule, "component")
        attribute = rule_value(rule, "attribute")

        component_key = slug(component)
        attribute_key = slug(attribute)

        keys.add(component_key)
        keys.add(f"{component_key}_{attribute_key}")

        normalized_component_key = normalize_variable(component_key)
        if normalized_component_key != component_key:
            keys.add(normalized_component_key)
            keys.add(f"{normalized_component_key}_{attribute_key}")

    return sorted(keys, key=len, reverse=True)


def split_joined_formula_token(token, known_keys):
    token = normalize_variable(token)

    if token in known_keys:
        return None

    parts = []
    remaining = token

    while remaining:
        match = None

        for key in known_keys:
            if remaining == key:
                match = key
                break

            if remaining.startswith(key + "_"):
                match = key
                break

        if not match:
            return None

        parts.append(match)

        if remaining == match:
            remaining = ""
        else:
            remaining = remaining[len(match) + 1:]

    if len(parts) <= 1:
        return None

    return parts


def operator_between(left, right):
    right_key = str(right).lower()

    if "extra" in right_key:
        return "+"

    return "-"


def joined_parts_to_formula(parts):
    expression = parts[0]

    for part in parts[1:]:
        expression += f" {operator_between(expression, part)} {part}"

    return expression


def repair_joined_formula_tokens(formula, rules, variables=None):
    variables = variables or {}
    known_keys = formula_known_keys(rules, variables)

    def replace_token(match):
        token = match.group(0)
        normalized_token = normalize_variable(token)

        if normalized_token in known_keys:
            return normalized_token

        parts = split_joined_formula_token(normalized_token, known_keys)

        if not parts:
            return token

        return "(" + joined_parts_to_formula(parts) + ")"

    return re.sub(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        replace_token,
        formula
    )


def normalize_formula_for_eval(formula, rules, variables=None):
    formula = str(formula or "").strip()

    if not formula:
        return ""

    if "=" in formula:
        left, right = formula.split("=", 1)
        if re.fullmatch(r"\s*[A-Za-z_][A-Za-z0-9_ ]*\s*", left):
            formula = right.strip()

    for old_var, new_var in VARIABLE_ALIASES.items():
        formula = re.sub(
            rf"\b{old_var}\b",
            new_var,
            formula,
            flags=re.IGNORECASE
        )

    known_keys = formula_known_keys(rules, variables)

    for key in known_keys:
        if "_width_" in key:
            formula = re.sub(
                rf"\b{re.escape(key.replace('_width_', '-width_'))}\b",
                key,
                formula,
                flags=re.IGNORECASE
            )

        if "_length_" in key:
            formula = re.sub(
                rf"\b{re.escape(key.replace('_length_', '-length_'))}\b",
                key,
                formula,
                flags=re.IGNORECASE
            )

    formula = repair_joined_formula_tokens(formula, rules, variables)

    return formula


def extract_formula_variables(formula, rules=None, variables=None):
    formula = normalize_formula_for_eval(formula, rules or [], variables or {})

    if not formula:
        return []

    ignore_words = {"abs", "min", "max", "round", "float", "int", "Decimal"}

    found = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", formula)

    return sorted({
        normalize_variable(v)
        for v in found
        if v not in ignore_words
    })


def evaluate_formula(formula, variables, rules):
    formula = normalize_formula_for_eval(formula, rules, variables)

    if not formula:
        raise FormulaError("Formula empty")

    if re.search(r"[A-Za-z_][A-Za-z0-9_]*\s+[A-Za-z_][A-Za-z0-9_]*", formula):
        raise FormulaError(f"Invalid formula syntax: {formula}")

    clean_vars = {}

    for key, value in variables.items():
        if value not in [None, ""]:
            clean_vars[normalize_variable(key)] = float(value)

    clean_vars.update({
        "abs": abs,
        "min": min,
        "max": max,
        "round": round,
    })

    try:
        result = eval(formula, {"__builtins__": {}}, clean_vars)
        return Decimal(str(round(result, 2)))

    except NameError as e:
        try:
            missing_var = str(e).split("'")[1]
        except Exception:
            missing_var = str(e)
        raise FormulaError(f"Missing dependency variable: {missing_var}")

    except Exception as e:
        raise FormulaError(str(e))


def fixed_value(formula, quantity):
    formula_num = clean_number(formula)

    if formula_num is not None:
        return Decimal(str(round(formula_num, 2)))

    quantity_num = clean_number(quantity)

    if quantity_num is not None:
        return Decimal(str(round(quantity_num, 2)))

    return None


def conditional_quantity(quantity, variables):
    text = str(quantity or "").strip().lower()

    if not text:
        return None

    number = clean_number(quantity)

    if number is not None:
        return int(number)

    if "mesh yes" in text or "mesh no" in text:
        yes_match = re.search(r"mesh\s*yes\s*[:\-]?\s*([0-9.]+)", text)
        no_match = re.search(r"mesh\s*no\s*[:\-]?\s*([0-9.]+)", text)

        yes_qty = int(float(yes_match.group(1))) if yes_match else 0
        no_qty = int(float(no_match.group(1))) if no_match else 0

        return yes_qty if int(variables.get("mesh_yes", 0)) == 1 else no_qty

    first_number = re.search(r"([0-9.]+)", text)

    if first_number:
        return int(float(first_number.group(1)))

    return None


def base_quantity(component, quantity, previous_qty, variables=None):
    variables = variables or {}
    component_key = slug(component)

    if component_key == "flush_shutter":
        return 1

    if component_key == "architrave_vertical":
        return 4

    quantity_num = conditional_quantity(quantity, variables)

    if quantity_num is not None:
        return quantity_num

    return int(previous_qty.get(component_key, 1))


def manual_dimension_key(component, attribute):
    return f"manual_{slug(component)}_{slug(attribute)}"


def fixed_dimension_value(component, attribute):
    return FIXED_COMPONENT_DIMENSIONS.get(slug(component), {}).get(slug(attribute))


def uploaded_dimension_value(rules, component, attribute):
    component_key = slug(component)
    attribute_key = slug(attribute)

    for rule in rules:
        if slug(rule_value(rule, "component")) != component_key:
            continue

        if attribute_key == "width":
            value = decimal_or_none(rule_value(rule, "fixed_width"))
            if value is not None:
                return value

        if attribute_key == "thickness":
            value = decimal_or_none(rule_value(rule, "fixed_thickness"))
            if value is not None:
                return value

    return None


def existing_component_input_key(component, attribute):
    component_key = slug(component)
    attribute_key = slug(attribute)

    if component_key == "flush_shutter" and attribute_key == "thickness":
        return "shutter_thickness"

    key = f"{component_key}_{attribute_key}"
    return key if key in COMPONENT_INPUT_KEYS else None


def has_fixed_or_uploaded_dimension(rules, component, attribute):
    return (
        fixed_dimension_value(component, attribute) is not None
        or uploaded_dimension_value(rules, component, attribute) is not None
    )


def needs_manual_dimension(rule, rules):
    component = rule_value(rule, "component")
    attribute = rule_value(rule, "attribute")
    rule_type = str(rule_value(rule, "rule_type") or "").strip().lower()
    formula = str(rule_value(rule, "formula") or "").strip()
    attribute_key = slug(attribute)

    if existing_component_input_key(component, attribute):
        return False

    return (
        attribute_key in ["width", "thickness"]
        and not has_fixed_or_uploaded_dimension(rules, component, attribute)
        and rule_type not in ["formula", "fomula"]
        and formula == ""
    )


def selected_component_manual_dimensions(rules):
    component_attributes = {}

    for rule in rules:
        component = rule_value(rule, "component")
        attribute = rule_value(rule, "attribute")
        component_key = slug(component)
        attribute_key = slug(attribute)

        if component_key not in component_attributes:
            component_attributes[component_key] = {
                "component": component,
                "attributes": set(),
            }

        component_attributes[component_key]["attributes"].add(attribute_key)

    manual_dimensions = []

    for component_data in component_attributes.values():
        component = component_data["component"]
        attributes = component_data["attributes"]

        for attribute in ["width", "thickness"]:
            if has_fixed_or_uploaded_dimension(rules, component, attribute):
                continue

            if existing_component_input_key(component, attribute):
                continue

            if attribute not in attributes:
                manual_dimensions.append((component, attribute))

    for rule in rules:
        if needs_manual_dimension(rule, rules):
            item = (rule_value(rule, "component"), rule_value(rule, "attribute"))

            if item not in manual_dimensions:
                manual_dimensions.append(item)

    return manual_dimensions


def calculated_variable_keys(rules):
    keys = set()

    for rule in rules:
        component_key = slug(rule_value(rule, "component"))
        attribute_key = slug(rule_value(rule, "attribute"))

        keys.add(component_key)
        keys.add(f"{component_key}_{attribute_key}")

    return keys


def product_input_keys(product_cat, product_code, rules):
    if is_door_product(product_cat, product_code):
        return [
            "opening_length",
            "opening_width",
            "vertical_clearance",
            "horizontal_clearance",
            "architrave_extra_length",
            "architrave_extra_width",
            "frame_horizontal_thickness",
            "frame_vertical_thickness",
            "shutter_thickness",
        ]

    if is_fw3_product(product_cat, product_code):
        return [
            "opening_height_1",
            "opening_height_2",
            "opening_length_1",
            "opening_length_2",
            "mesh_yes",
        ]

    formula_vars = set()

    for rule in rules:
        rule_type = str(rule_value(rule, "rule_type") or "").strip().lower()
        formula = rule_value(rule, "formula")

        if rule_type in ["formula", "fomula"]:
            formula_vars.update(extract_formula_variables(formula, rules))

    formula_vars -= calculated_variable_keys(rules)
    formula_vars.discard("quantity")
    formula_vars.discard("lh_quantity")
    formula_vars.discard("rh_quantity")

    if is_fw_product(product_cat, product_code):
        formula_vars.add("mesh_yes")

    return sorted(formula_vars)


def get_dimension_value(component, attribute, variables, rules):
    fixed = fixed_dimension_value(component, attribute)

    if fixed is not None:
        return fixed

    uploaded = uploaded_dimension_value(rules, component, attribute)

    if uploaded is not None:
        return uploaded

    input_key = existing_component_input_key(component, attribute)

    if input_key:
        return Decimal(str(round(float(variables.get(input_key, 0.0)), 2)))

    manual_key = manual_dimension_key(component, attribute)

    if manual_key in variables:
        return Decimal(str(round(float(variables.get(manual_key, 0.0)), 2)))

    return None


def apply_fixed_or_uploaded_component_value(component, attribute, value, rules):
    fixed = fixed_dimension_value(component, attribute)

    if fixed is not None:
        return fixed

    uploaded = uploaded_dimension_value(rules, component, attribute)

    if uploaded is not None and slug(attribute) in ["width", "thickness"]:
        return uploaded

    return value


def store_calculated_value(variables, component, attribute, value):
    if value is None:
        return

    component_key = normalize_variable(slug(component))
    attribute_key = normalize_variable(slug(attribute))
    numeric_value = float(value)

    full_key = f"{component_key}_{attribute_key}"
    variables[full_key] = numeric_value

    if attribute_key == "length":
        variables[component_key] = numeric_value
    elif component_key not in variables:
        variables[component_key] = numeric_value


def calculate_cft(length, width, thickness, quantity, round_value=True):
    length_num = clean_number(length)
    width_num = clean_number(width)
    thickness_num = clean_number(thickness)
    quantity_num = clean_number(quantity)

    if length_num is None or quantity_num is None:
        return Decimal("0.00")

    if width_num is None or thickness_num is None:
        return Decimal("0.00")

    cft = length_num * width_num * thickness_num / 1000000000 * 35.315 * quantity_num

    if round_value:
        return Decimal(str(round(cft, 2)))

    return Decimal(str(cft))


def clean_display_number(value):
    if value in [None, ""]:
        return ""

    try:
        number = float(value)

        if number.is_integer():
            return int(number)

        return round(number, 2)

    except Exception:
        return value


def render_summary_header(project_name, product_code, generated_lh, generated_rh):
    cells = [
        "Project", project_name,
        "Product", product_code,
        "Total LH Quantity", generated_lh,
        "Total RH Quantity", generated_rh,
    ]

    html_cells = "".join(
        f"<td style='border:1px solid #d9d9d9;padding:8px 12px;font-weight:600;'>{escape(str(cell))}</td>"
        for cell in cells
    )

    st.markdown(
        f"""
        <table style="border-collapse:collapse;width:100%;margin-bottom:16px;">
            <tr>{html_cells}</tr>
        </table>
        """,
        unsafe_allow_html=True
    )


def ensure_generated_components_table(conn, cur):
    safe_execute(conn, cur, """
        CREATE TABLE IF NOT EXISTS generated_components (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            project_name TEXT NOT NULL,
            unit_type TEXT NOT NULL,
            house_number TEXT NOT NULL,
            product_cat TEXT NOT NULL,
            product_code TEXT NOT NULL,
            component TEXT NOT NULL,
            attribute TEXT NOT NULL,
            calculated_value TEXT,
            width NUMERIC,
            thickness NUMERIC,
            cft NUMERIC,
            orientation TEXT,
            qty INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    safe_execute(conn, cur, """
        ALTER TABLE generated_components
        ADD COLUMN IF NOT EXISTS cft NUMERIC
    """)

    safe_execute(conn, cur, """
        CREATE TABLE IF NOT EXISTS tracking (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            project_name TEXT NOT NULL,
            house_number TEXT NOT NULL,
            component TEXT NOT NULL,
            required_qty INTEGER,
            completed_qty INTEGER DEFAULT 0,
            pending_qty INTEGER,
            status TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()


def reset_generated_state_if_product_changed(state_key):
    previous_key = st.session_state.get("generated_component_product_state_key")

    if previous_key and previous_key != state_key:
        for key in [
            "generated_component_preview",
            "generated_component_tracking_rows",
            "generated_component_errors",
            "generated_lh_quantity",
            "generated_rh_quantity",
            "generated_total_quantity",
            "generated_shutter_thickness",
        ]:
            st.session_state.pop(key, None)

    st.session_state["generated_component_product_state_key"] = state_key


def show_component_calculator(conn, cur):
    st.title("Component Calculator")

    ensure_generated_components_table(conn, cur)

    projects = get_distinct_values(conn, cur, "projects", "project_name")

    if not projects:
        st.warning("No projects found. Upload project master first.")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        project_name = st.selectbox("Project", projects)

    unit_types = get_distinct_values(
        conn,
        cur,
        "unit_types",
        "unit_type",
        "WHERE project_name = %s",
        (project_name,)
    )

    if not unit_types:
        st.warning("No unit types found for selected project.")
        return

    with col2:
        unit_type = st.selectbox("Unit Type", unit_types)

    houses = get_distinct_values(
        conn,
        cur,
        "houses",
        "house_number",
        "WHERE project_name = %s AND unit_type = %s",
        (project_name, unit_type)
    )

    with col3:
        selected_houses = st.multiselect(
            "House Number",
            houses,
            default=houses[:1]
        )

    safe_execute(conn, cur, """
        SELECT DISTINCT product_cat, product_code
        FROM products
        ORDER BY product_cat, product_code
    """)

    products = cur.fetchall()

    if not products:
        st.warning("No products found. Upload component architecture first.")
        return

    product_options = build_product_options(products)

    with col4:
        selected_product = st.selectbox("Product", product_options)

    product_cat, product_code = selected_product.split(" | ", 1)
    uses_orientation = is_door_product(product_cat, product_code)

    state_key = f"{project_name}_{unit_type}_{product_cat}_{product_code}"
    reset_generated_state_if_product_changed(state_key)

    rules = load_product_rules(conn, cur, product_cat, product_code)

    if not rules:
        st.warning("No component rules found for selected product.")
        return

    st.markdown("---")

    if uses_orientation:
        st.subheader("House Wise LH / RH Quantity")

        house_qty_df = pd.DataFrame({
            "House Number": selected_houses,
            "LH Quantity": [0 for _ in selected_houses],
            "RH Quantity": [0 for _ in selected_houses],
        })

        edited_house_qty_df = st.data_editor(
            house_qty_df,
            use_container_width=True,
            hide_index=True,
            key=f"house_wise_lh_rh_qty_{state_key}",
            disabled=["House Number"]
        )

        house_qty_map = {
            str(row["House Number"]): {
                "lh_quantity": clean_int(row["LH Quantity"]),
                "rh_quantity": clean_int(row["RH Quantity"]),
                "quantity": clean_int(row["LH Quantity"]) + clean_int(row["RH Quantity"]),
            }
            for _, row in edited_house_qty_df.iterrows()
        }

        total_lh_quantity = sum(item["lh_quantity"] for item in house_qty_map.values())
        total_rh_quantity = sum(item["rh_quantity"] for item in house_qty_map.values())
        total_product_quantity = total_lh_quantity + total_rh_quantity

        st.info(
            f"Total LH Quantity: {total_lh_quantity} | Total RH Quantity: {total_rh_quantity} | Total Quantity: {total_product_quantity}"
        )

    else:
        st.subheader("House Wise Quantity")

        house_qty_df = pd.DataFrame({
            "House Number": selected_houses,
            "Quantity": [0 for _ in selected_houses],
        })

        edited_house_qty_df = st.data_editor(
            house_qty_df,
            use_container_width=True,
            hide_index=True,
            key=f"house_wise_qty_{state_key}",
            disabled=["House Number"]
        )

        house_qty_map = {
            str(row["House Number"]): {
                "lh_quantity": 0,
                "rh_quantity": 0,
                "quantity": clean_int(row["Quantity"]),
            }
            for _, row in edited_house_qty_df.iterrows()
        }

        total_lh_quantity = 0
        total_rh_quantity = 0
        total_product_quantity = sum(item["quantity"] for item in house_qty_map.values())

        st.info(f"Total Quantity: {total_product_quantity}")

    st.markdown("---")
    st.subheader("User Based Data")

    variables = {}
    input_keys = product_input_keys(product_cat, product_code, rules)

    if input_keys:
        input_cols = st.columns(4)

        for idx, key in enumerate(input_keys):
            with input_cols[idx % 4]:
                if key == "mesh_yes":
                    mesh_choice = st.selectbox(
                        "Mesh",
                        ["No", "Yes"],
                        key=f"input_{state_key}_{key}"
                    )
                    variables[key] = 1 if mesh_choice == "Yes" else 0
                else:
                    variables[key] = st.number_input(
                        label_from_key(key),
                        value=float(DEFAULT_VALUES.get(key, 0.0)),
                        step=1.0,
                        format="%.2f",
                        key=f"input_{state_key}_{key}"
                    )
    else:
        st.info("No user based inputs required for this product.")

    manual_dimensions = selected_component_manual_dimensions(rules)

    if manual_dimensions:
        st.markdown("#### Manual Component Dimensions")
        manual_cols = st.columns(4)

        for idx, (component, attribute) in enumerate(manual_dimensions):
            key = manual_dimension_key(component, attribute)

            with manual_cols[idx % 4]:
                variables[key] = st.number_input(
                    f"{component} {attribute}".title(),
                    value=0.0,
                    step=1.0,
                    format="%.2f",
                    key=f"manual_input_{state_key}_{slug(component)}_{slug(attribute)}_{idx}"
                )

    st.markdown("---")

    if st.button("Generate Components", key=f"generate_components_{state_key}"):

        if not selected_houses:
            st.warning("Please select at least one house number.")
            return

        preview_rows = []
        tracking_rows = []
        errors_found = False

        for house_number in selected_houses:
            house_qty = house_qty_map.get(str(house_number), {})
            lh_quantity = int(float(house_qty.get("lh_quantity", 0)))
            rh_quantity = int(float(house_qty.get("rh_quantity", 0)))
            product_qty_multiplier = int(float(house_qty.get("quantity", 0)))

            if product_qty_multiplier <= 0:
                st.warning(f"Please enter quantity for house {house_number}.")
                errors_found = True
                continue

            house_variables = variables.copy()
            house_variables["lh_quantity"] = lh_quantity
            house_variables["rh_quantity"] = rh_quantity
            house_variables["quantity"] = product_qty_multiplier

            pending_rules = list(rules)
            calculated_rules = []
            previous_qty = {}
            component_tracking_map = {}
            loop_count = 0

            while pending_rules:
                loop_count += 1

                if loop_count > 20:
                    st.error("Infinite dependency loop detected")
                    errors_found = True
                    break

                progressed = False
                next_pending = []
                dependency_errors = []

                for rule in pending_rules:
                    component = str(rule_value(rule, "component")).strip()
                    attribute = str(rule_value(rule, "attribute")).strip()
                    rule_type = str(rule_value(rule, "rule_type") or "").strip().lower()
                    formula = rule_value(rule, "formula")
                    quantity = rule_value(rule, "quantity")

                    component_qty = base_quantity(component, quantity, previous_qty, house_variables)
                    total_quantity = int(component_qty * product_qty_multiplier)

                    try:
                        if rule_type in ["formula", "fomula"]:
                            value = evaluate_formula(formula, house_variables, rules)

                        elif needs_manual_dimension(rule, rules):
                            value = get_dimension_value(component, attribute, variables, rules)

                        else:
                            value = fixed_value(formula, quantity)

                        if value is None:
                            value = Decimal("0")

                        value = apply_fixed_or_uploaded_component_value(
                            component,
                            attribute,
                            value,
                            rules
                        )

                        store_calculated_value(
                            house_variables,
                            component,
                            attribute,
                            value
                        )

                        previous_qty[slug(component)] = component_qty
                        normalized_formula = normalize_formula_for_eval(formula, rules, house_variables)

                        calculated_rules.append({
                            "House Number": house_number,
                            "Product": product_code,
                            "Component": component,
                            "Attribute": attribute,
                            "Type": "formula" if rule_type == "fomula" else rule_type,
                            "Formula": normalized_formula,
                            "Value": value,
                            "Base Quantity": component_qty,
                            "Total Quantity": total_quantity,
                            "LH Quantity": lh_quantity,
                            "RH Quantity": rh_quantity,
                            "Quantity": product_qty_multiplier,
                        })

                        tracking_key = (
                            house_number,
                            product_cat,
                            product_code,
                            component
                        )

                        if tracking_key not in component_tracking_map:
                            component_tracking_map[tracking_key] = {
                                "project_name": project_name,
                                "unit_type": unit_type,
                                "house_number": house_number,
                                "product_cat": product_cat,
                                "product_code": product_code,
                                "orientation": "",
                                "component": component,
                                "quantity": total_quantity,
                                "lh_quantity": lh_quantity,
                                "rh_quantity": rh_quantity,
                                "product_quantity": product_qty_multiplier,
                                "attributes": {}
                            }

                        component_tracking_map[tracking_key]["attributes"][attribute] = {
                            "type": "formula" if rule_type == "fomula" else rule_type,
                            "formula": normalized_formula,
                            "value": float(value),
                            "base_quantity": component_qty,
                        }

                        progressed = True

                    except FormulaError as e:
                        if "Missing dependency variable" in str(e):
                            next_pending.append(rule)
                            dependency_errors.append((rule, str(e)))
                        else:
                            errors_found = True
                            st.error(f"{house_number} - {component} / {attribute}: {e}")

                    except Exception as e:
                        errors_found = True
                        st.error(f"{house_number} - {component} / {attribute}: {e}")

                if not progressed:
                    for rule, error_message in dependency_errors:
                        component = str(rule_value(rule, "component")).strip()
                        attribute = str(rule_value(rule, "attribute")).strip()
                        formula = rule_value(rule, "formula")
                        quantity = rule_value(rule, "quantity")
                        rule_type = str(rule_value(rule, "rule_type") or "").strip().lower()
                        component_qty = base_quantity(component, quantity, previous_qty, house_variables)

                        preview_rows.append({
                            "House Number": house_number,
                            "Product": product_code,
                            "Component": component,
                            "Attribute": attribute,
                            "Type": "formula" if rule_type == "fomula" else rule_type,
                            "Formula": normalize_formula_for_eval(formula, rules, house_variables),
                            "Value": None,
                            "Base Quantity": component_qty,
                            "Total Quantity": int(component_qty * product_qty_multiplier),
                            "LH Quantity": lh_quantity,
                            "RH Quantity": rh_quantity,
                            "Quantity": product_qty_multiplier,
                        })

                        st.error(
                            f"{house_number} - {component} / {attribute}: {error_message}"
                        )

                    errors_found = True
                    break

                pending_rules = next_pending

            for row in component_tracking_map.values():
                for attribute in ["width", "thickness"]:
                    if attribute in row["attributes"]:
                        continue

                    value = get_dimension_value(
                        row["component"],
                        attribute,
                        variables,
                        rules
                    )

                    if value is None:
                        continue

                    fallback_qty = base_quantity(
                        row["component"],
                        None,
                        previous_qty,
                        house_variables
                    )

                    row["attributes"][attribute] = {
                        "type": "dimension",
                        "formula": "",
                        "value": float(value),
                        "base_quantity": fallback_qty,
                    }

                    calculated_rules.append({
                        "House Number": house_number,
                        "Product": product_code,
                        "Component": row["component"],
                        "Attribute": attribute,
                        "Type": "dimension",
                        "Formula": "",
                        "Value": value,
                        "Base Quantity": fallback_qty,
                        "Total Quantity": row["quantity"],
                        "LH Quantity": lh_quantity,
                        "RH Quantity": rh_quantity,
                        "Quantity": product_qty_multiplier,
                    })

            preview_rows.extend(calculated_rules)
            tracking_rows.extend(component_tracking_map.values())

        st.session_state["generated_component_preview"] = preview_rows
        st.session_state["generated_component_tracking_rows"] = tracking_rows
        st.session_state["generated_component_errors"] = errors_found
        st.session_state["generated_lh_quantity"] = total_lh_quantity
        st.session_state["generated_rh_quantity"] = total_rh_quantity
        st.session_state["generated_total_quantity"] = total_product_quantity
        st.session_state["generated_shutter_thickness"] = variables.get("shutter_thickness", "")

    if "generated_component_preview" in st.session_state:
        st.subheader("Generated Components")

        generated_lh = st.session_state.get("generated_lh_quantity", 0)
        generated_rh = st.session_state.get("generated_rh_quantity", 0)
        generated_total = st.session_state.get("generated_total_quantity", 0)

        if uses_orientation:
            st.info(
                f"Total LH Quantity: {generated_lh} | Total RH Quantity: {generated_rh} | Total Quantity: {generated_total}"
            )
        else:
            st.info(f"Total Quantity: {generated_total}")

        df_preview_raw = pd.DataFrame(st.session_state["generated_component_preview"])
        house_rows = []

        group_cols = [
            "Product",
            "Component",
        ]

        for _, group_df in df_preview_raw.groupby(group_cols, dropna=False, sort=False):
            first_row = group_df.iloc[0].to_dict()
            values = {}

            for _, row in group_df.iterrows():
                values[str(row["Attribute"]).strip().lower()] = row["Value"]

            length_value = clean_display_number(values.get("length", ""))
            width_value = clean_display_number(values.get("width", ""))
            thickness_value = clean_display_number(values.get("thickness", values.get("height", "")))

            component_name = str(first_row["Component"]).strip().lower()

            if component_name == "flush shutter":
                cft_value = Decimal("0")
            else:
                cft_value = calculate_cft(
                    length_value,
                    width_value,
                    thickness_value,
                    first_row["Total Quantity"],
                    round_value=True
                )

            row_data = {
                "Component": first_row["Component"],
                "Length": length_value,
                "Width": width_value,
                "Thickness": thickness_value,
                "Total Quantity": first_row["Total Quantity"],
                "CFT": cft_value,
                "LH & RH Details": "",
            }

            house_rows.append(row_data)

        total_cft = sum(
            clean_number(row.get("CFT")) or 0
            for row in house_rows
            if str(row.get("Component", "")).strip().lower() != "flush shutter"
        )

        total_row = {
            "Component": "CFT Total",
            "Length": "",
            "Width": "",
            "Thickness": "",
            "Total Quantity": "",
            "CFT": Decimal(str(round(total_cft, 2))),
            "LH & RH Details": "",
        }

        house_rows.append(total_row)

        lh_rh_summary = []

        if uses_orientation:
            unique_houses = df_preview_raw[
                ["House Number", "LH Quantity", "RH Quantity"]
            ].drop_duplicates()

            for _, row in unique_houses.iterrows():
                house_no = row["House Number"]
                lh_qty = clean_int(row["LH Quantity"])
                rh_qty = clean_int(row["RH Quantity"])

                summary_parts = []

                if lh_qty > 0:
                    summary_parts.append(f"{lh_qty}L")

                if rh_qty > 0:
                    summary_parts.append(f"{rh_qty}R")

                if summary_parts:
                    lh_rh_summary.append(
                        f"{house_no}: {', '.join(summary_parts)}"
                    )

        df_preview = pd.DataFrame(house_rows)

        if uses_orientation:
            lh_rh_chunks = []
            chunk_size = 2

            for i in range(0, len(lh_rh_summary), chunk_size):
                lh_rh_chunks.append(
                    " | ".join(lh_rh_summary[i:i + chunk_size])
                )

            df_preview["LH & RH Details"] = ""

            for idx, chunk in enumerate(lh_rh_chunks):
                if idx < len(df_preview):
                    df_preview.loc[idx, "LH & RH Details"] = chunk

            render_summary_header(
                project_name,
                product_code,
                generated_lh,
                generated_rh
            )

        else:
            render_summary_header(
                project_name,
                product_code,
                0,
                0
            )

        st.dataframe(
            df_preview,
            hide_index=True,
            use_container_width=True
        )

        errors_found = st.session_state.get("generated_component_errors", False)

        if errors_found or df_preview_raw["Value"].isna().any():
            st.warning("Some components did not calculate. Fix formulas before confirming.")
        else:
            st.success("All component formulas calculated successfully")

        st.markdown("---")

        if st.button(
            "Confirm Components and Send to Tracking",
            type="primary",
            key=f"confirm_components_{state_key}"
        ):
            if errors_found or df_preview_raw["Value"].isna().any():
                st.warning("Please fix formula errors before sending to tracking.")
                return

            tracking_rows = st.session_state.get("generated_component_tracking_rows", [])

            if not tracking_rows:
                st.warning("No generated components to save.")
                return

            try:
                generated_insert_rows = []
                tracking_insert_rows = []

                for row in tracking_rows:
                    attrs = row["attributes"]

                    length_value = ""
                    width_value = None
                    thickness_value = None

                    if "length" in attrs:
                        length_value = str(attrs["length"]["value"])

                    if "width" in attrs:
                        width_value = attrs["width"]["value"]

                    if "thickness" in attrs:
                        thickness_value = attrs["thickness"]["value"]

                    cft_value = calculate_cft(
                        length_value,
                        width_value,
                        thickness_value,
                        row["quantity"],
                        round_value=True
                    )

                    generated_insert_rows.append((
                        row["project_name"],
                        row["unit_type"],
                        row["house_number"],
                        row["product_cat"],
                        row["product_code"],
                        row["component"],
                        "combined",
                        length_value,
                        width_value,
                        thickness_value,
                        cft_value,
                        row["orientation"],
                        row["quantity"],
                    ))

                    tracking_insert_rows.append((
                        row["project_name"],
                        row["house_number"],
                        row["component"],
                        row["quantity"],
                        0,
                        row["quantity"],
                        "Pending",
                    ))

                execute_values(
                    cur,
                    """
                    INSERT INTO generated_components
                    (
                        project_name,
                        unit_type,
                        house_number,
                        product_cat,
                        product_code,
                        component,
                        attribute,
                        calculated_value,
                        width,
                        thickness,
                        cft,
                        orientation,
                        qty
                    )
                    VALUES %s
                    """,
                    generated_insert_rows
                )

                execute_values(
                    cur,
                    """
                    INSERT INTO tracking
                    (
                        project_name,
                        house_number,
                        component,
                        required_qty,
                        completed_qty,
                        pending_qty,
                        status
                    )
                    VALUES %s
                    """,
                    tracking_insert_rows
                )

                conn.commit()
                st.success(f"{len(generated_insert_rows)} component(s) sent to tracking successfully")

            except Exception as e:
                conn.rollback()
                st.error(f"Failed to send components to tracking: {e}")
