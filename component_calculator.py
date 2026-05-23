import streamlit as st
import pandas as pd
import re
from decimal import Decimal
from psycopg2.extras import execute_values, Json


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
}


DEFAULT_VALUES = {
    "opening_length": 0.0,
    "opening_width": 0.0,
    "vertical_clearance": 0.0,
    "horizontal_clearance": 0.0,
    "architrave_extra_length": 0.0,
    "architrave_extra_width": 0.0,
    "frame_horizontal_thickness": 0.0,
    "frame_vertical_thickness": 0.0,
    "lh_quantity": 0.0,
    "rh_quantity": 0.0,
    "shutter_thickness": 0.0,
    "allowance": 0.0,
    "groove": 0.0,
    "cut": 0.0,
    "offset": 0.0,
}


def normalize_variable(var_name):
    var_name = str(var_name).strip()
    return VARIABLE_ALIASES.get(var_name, var_name)


def normalize_formula(formula):
    formula = str(formula or "").strip()

    if "=" in formula:
        left, right = formula.split("=", 1)
        if re.fullmatch(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*", left):
            formula = right.strip()

    for old_var, new_var in VARIABLE_ALIASES.items():
        formula = re.sub(rf"\b{old_var}\b", new_var, formula)

    return formula


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


def extract_formula_variables(formula):
    formula = normalize_formula(formula)

    if not formula:
        return []

    ignore_words = {
        "abs",
        "min",
        "max",
        "round",
        "float",
        "int",
        "Decimal"
    }

    variables = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        formula
    )

    return sorted({
        normalize_variable(v)
        for v in variables
        if v not in ignore_words
    })


def evaluate_formula(formula, variables):
    formula = normalize_formula(formula)

    if not formula:
        raise FormulaError("Formula empty")

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
        result = eval(
            formula,
            {"__builtins__": {}},
            clean_vars
        )
        return Decimal(str(round(result, 2)))

    except NameError as e:
        raise FormulaError(f"Missing variable: {e}")

    except Exception as e:
        raise FormulaError(str(e))


def slug(value):
    return (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def clean_number(value):
    if value in [None, ""]:
        return None

    try:
        return float(value)
    except Exception:
        return None


def fixed_value(formula, quantity):
    formula_num = clean_number(formula)

    if formula_num is not None:
        return Decimal(str(round(formula_num, 2)))

    quantity_num = clean_number(quantity)

    if quantity_num is not None:
        return Decimal(str(round(quantity_num, 2)))

    return None


def base_quantity(component, quantity, previous_qty):
    component_key = slug(component)

    if component_key == "flush_shutter":
        return 1

    if quantity not in [None, ""]:
        return int(float(quantity))

    return int(previous_qty.get(component_key, 1))


def manual_dimension_key(component, attribute):
    return f"manual_{slug(component)}_{slug(attribute)}"


def is_architrave_component(component):
    return slug(component) in ["architrave_vertical", "architrave_horizontal"]


def apply_fixed_architrave_value(component, attribute, value):
    if is_architrave_component(component):
        attribute_key = slug(attribute)

        if attribute_key == "width":
            return Decimal("40")

        if attribute_key == "thickness":
            return Decimal("12")

    return value


def needs_manual_dimension(rule):
    component, attribute, rule_type, formula, _ = rule
    attribute_key = slug(attribute)
    rule_type = str(rule_type or "").strip().lower()
    formula = normalize_formula(formula)

    return (
        attribute_key in ["width", "thickness"]
        and rule_type not in ["formula", "fomula"]
        and formula == ""
    )


def store_calculated_value(variables, component, attribute, value):
    if value is None:
        return

    component_key = slug(component)
    attribute_key = slug(attribute)
    numeric_value = float(value)

    keys = {
        component_key,
        f"{component_key}_{attribute_key}",
    }

    if attribute_key in ["length", "width", "height", "thickness"]:
        keys.add(f"{component_key}_{attribute_key}")

    for key in keys:
        variables[key] = numeric_value


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
            orientation TEXT,
            qty INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
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

    product_options = [f"{p[0]} | {p[1]}" for p in products]

    with col4:
        selected_product = st.selectbox("Product", product_options)

    product_cat, product_code = selected_product.split(" | ", 1)

    safe_execute(conn, cur, """
        SELECT
            component,
            attribute,
            type,
            formula_used,
            quantity
        FROM product_component_rules
        WHERE product_cat = %s
        AND product_code = %s
    """, (product_cat, product_code))

    rules = cur.fetchall()

    if not rules:
        st.warning("No component rules found for selected product.")
        return

    st.markdown("---")
    st.subheader("User Based Data")

    required_variables = set()

    for rule in rules:
        for variable in extract_formula_variables(rule[3]):
            required_variables.add(variable)

    for variable in DEFAULT_VALUES:
        required_variables.add(variable)

    generated_variables = set()

    for component, attribute, _, _, _ in rules:
        component_key = slug(component)
        attribute_key = slug(attribute)
        generated_variables.add(component_key)
        generated_variables.add(f"{component_key}_{attribute_key}")

    required_variables = required_variables - generated_variables

    variables = {}

    st.markdown("#### Opening Size")
    open_col1, open_col2 = st.columns(2)

    with open_col1:
        variables["opening_length"] = st.number_input(
            "Opening Length",
            value=float(DEFAULT_VALUES["opening_length"]),
            step=1.0,
            format="%.2f"
        )

    with open_col2:
        variables["opening_width"] = st.number_input(
            "Opening Width",
            value=float(DEFAULT_VALUES["opening_width"]),
            step=1.0,
            format="%.2f"
        )

    st.markdown("#### Component Inputs")

    input_fields = [
        ("vertical_clearance", "Vertical Clearance"),
        ("horizontal_clearance", "Horizontal Clearance"),
        ("architrave_extra_length", "Architrave Extra Length"),
        ("architrave_extra_width", "Architrave Extra Width"),
        ("frame_horizontal_thickness", "Frame Horizontal Thickness"),
        ("frame_vertical_thickness", "Frame Vertical Thickness"),
        ("shutter_thickness", "Shutter Thickness"),
        ("lh_quantity", "LH Quantity"),
        ("rh_quantity", "RH Quantity"),
    ]

    input_cols = st.columns(4)

    for idx, (key, label) in enumerate(input_fields):
        with input_cols[idx % 4]:
            variables[key] = st.number_input(
                label,
                value=float(DEFAULT_VALUES.get(key, 0.0)),
                step=1.0,
                format="%.2f"
            )

    manual_rules = [
        rule
        for rule in rules
        if needs_manual_dimension(rule)
    ]

    if manual_rules:
        st.markdown("#### Manual Component Dimensions")
        manual_cols = st.columns(4)

        for idx, rule in enumerate(manual_rules):
            component, attribute, _, _, _ = rule
            key = manual_dimension_key(component, attribute)

            with manual_cols[idx % 4]:
                variables[key] = st.number_input(
                    f"{component} {attribute}".title(),
                    value=0.0,
                    step=1.0,
                    format="%.2f"
                )

    extra_variables = sorted(
        required_variables - {
            "opening_length",
            "opening_width",
            "vertical_clearance",
            "horizontal_clearance",
            "architrave_extra_length",
            "architrave_extra_width",
            "frame_horizontal_thickness",
            "frame_vertical_thickness",
            "shutter_thickness",
            "lh_quantity",
            "rh_quantity",
        }
    )

    if extra_variables:
        st.markdown("#### Other Required Inputs")
        extra_cols = st.columns(4)

        for idx, variable in enumerate(extra_variables):
            with extra_cols[idx % 4]:
                variables[variable] = st.number_input(
                    variable.replace("_", " ").title(),
                    value=float(DEFAULT_VALUES.get(variable, 0.0)),
                    step=1.0,
                    format="%.2f"
                )

    st.markdown("---")

    if st.button("Generate Components"):

        if not selected_houses:
            st.warning("Please select at least one house number.")
            return

        lh_quantity = int(float(variables.get("lh_quantity", 0)))
        rh_quantity = int(float(variables.get("rh_quantity", 0)))
        product_qty_multiplier = lh_quantity + rh_quantity

        if product_qty_multiplier <= 0:
            st.warning("Please enter LH Quantity or RH Quantity.")
            return

        preview_rows = []
        tracking_rows = []
        errors_found = False

        for house_number in selected_houses:

            house_variables = variables.copy()
            pending_rules = list(rules)
            calculated_rules = []
            previous_qty = {}
            component_tracking_map = {}

            while pending_rules:
                progressed = False
                next_pending = []

                for rule in pending_rules:
                    component = str(rule[0]).strip()
                    attribute = str(rule[1]).strip()
                    rule_type = str(rule[2] or "").strip().lower()
                    formula = rule[3]
                    quantity = rule[4]

                    component_qty = base_quantity(
                        component,
                        quantity,
                        previous_qty
                    )

                    total_quantity = int(
                        component_qty * product_qty_multiplier
                    )

                    try:
                        if rule_type in ["formula", "fomula"]:
                            value = evaluate_formula(formula, house_variables)

                        elif needs_manual_dimension(rule):
                            value = Decimal(str(round(
                                float(variables.get(
                                    manual_dimension_key(component, attribute),
                                    0.0
                                )),
                                2
                            )))

                        else:
                            value = fixed_value(formula, quantity)

                        if value is None:
                            value = Decimal("0")

                        value = apply_fixed_architrave_value(
                            component,
                            attribute,
                            value
                        )

                        store_calculated_value(
                            house_variables,
                            component,
                            attribute,
                            value
                        )

                        previous_qty[slug(component)] = component_qty

                        calculated_rules.append({
                            "House Number": house_number,
                            "Product": product_code,
                            "Component": component,
                            "Attribute": attribute,
                            "Type": "formula" if rule_type == "fomula" else rule_type,
                            "Formula": normalize_formula(formula),
                            "Value": value,
                            "Base Quantity": component_qty,
                            "Total Quantity": total_quantity,
                            "LH Quantity": lh_quantity,
                            "RH Quantity": rh_quantity,
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
                                "attributes": {}
                            }

                        component_tracking_map[tracking_key]["attributes"][attribute] = {
                            "type": "formula" if rule_type == "fomula" else rule_type,
                            "formula": normalize_formula(formula),
                            "value": float(value),
                            "base_quantity": component_qty,
                        }

                        progressed = True

                    except FormulaError as e:
                        if "Missing variable" in str(e):
                            next_pending.append(rule)
                        else:
                            errors_found = True
                            st.error(f"{house_number} - {component} / {attribute}: {e}")

                    except Exception as e:
                        errors_found = True
                        st.error(f"{house_number} - {component} / {attribute}: {e}")

                if not progressed:
                    for rule in next_pending:
                        component = str(rule[0]).strip()
                        attribute = str(rule[1]).strip()
                        formula = rule[3]
                        quantity = rule[4]
                        rule_type = str(rule[2] or "").strip().lower()

                        component_qty = base_quantity(
                            component,
                            quantity,
                            previous_qty
                        )

                        preview_rows.append({
                            "House Number": house_number,
                            "Product": product_code,
                            "Component": component,
                            "Attribute": attribute,
                            "Type": "formula" if rule_type == "fomula" else rule_type,
                            "Formula": normalize_formula(formula),
                            "Value": None,
                            "Base Quantity": component_qty,
                            "Total Quantity": int(component_qty * product_qty_multiplier),
                            "LH Quantity": lh_quantity,
                            "RH Quantity": rh_quantity,
                        })

                        missing = ", ".join(extract_formula_variables(formula))

                        st.error(
                            f"{house_number} - {component} / {attribute}: Missing dependency. Required: {missing}"
                        )

                    errors_found = True
                    break

                pending_rules = next_pending

            preview_rows.extend(calculated_rules)
            tracking_rows.extend(component_tracking_map.values())

        st.session_state["generated_component_preview"] = preview_rows
        st.session_state["generated_component_tracking_rows"] = tracking_rows
        st.session_state["generated_component_errors"] = errors_found
        st.session_state["generated_lh_quantity"] = lh_quantity
        st.session_state["generated_rh_quantity"] = rh_quantity
        st.session_state["generated_shutter_thickness"] = variables.get(
            "shutter_thickness",
            ""
        )

    if "generated_component_preview" in st.session_state:

        st.subheader("Generated Components")

        generated_lh = st.session_state.get("generated_lh_quantity", 0)
        generated_rh = st.session_state.get("generated_rh_quantity", 0)

        st.info(
            f"LH Quantity: {generated_lh} | RH Quantity: {generated_rh}"
        )

        df_preview_raw = pd.DataFrame(
            st.session_state["generated_component_preview"]
        )

        display_rows = []

        group_cols = [
            "House Number",
            "Product",
            "Component",
            "Total Quantity",
        ]

        for _, group_df in df_preview_raw.groupby(
            group_cols,
            dropna=False,
            sort=False
        ):
            first_row = group_df.iloc[0].to_dict()
            values = {}

            for _, row in group_df.iterrows():
                attr = str(row["Attribute"]).strip().lower()
                values[attr] = row["Value"]

            component_name = str(
                first_row["Component"]
            ).strip().lower()

            thickness_value = values.get(
                "thickness",
                values.get("height", "")
            )

            width_value = values.get("width", "")

            if slug(component_name) in ["architrave_vertical", "architrave_horizontal"]:
                width_value = Decimal("40")
                thickness_value = Decimal("12")

            if component_name == "flush shutter":
                thickness_value = st.session_state.get(
                    "generated_shutter_thickness",
                    ""
                )

            display_rows.append({
                "House Number": first_row["House Number"],
                "Product": first_row["Product"],
                "Component": first_row["Component"],
                "Length": values.get("length", ""),
                "Width": width_value,
                "Thickness": thickness_value,
                "Total Quantity": first_row["Total Quantity"],
            })

        df_preview = pd.DataFrame(display_rows)

        st.dataframe(
            df_preview,
            use_container_width=True,
            hide_index=True
        )

        errors_found = st.session_state.get(
            "generated_component_errors",
            False
        )

        if errors_found or df_preview_raw["Value"].isna().any():
            st.warning("Some components did not calculate. Fix formulas before confirming.")
        else:
            st.success("All component formulas calculated successfully")

        st.markdown("---")

        if st.button("Confirm Components and Send to Tracking", type="primary"):

            if errors_found or df_preview_raw["Value"].isna().any():
                st.warning("Please fix formula errors before sending to tracking.")
                return

            tracking_rows = st.session_state.get(
                "generated_component_tracking_rows",
                []
            )

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

                    if is_architrave_component(row["component"]):
                        width_value = 40
                        thickness_value = 12

                    if str(row["component"]).strip().lower() == "flush shutter":
                        thickness_value = st.session_state.get(
                            "generated_shutter_thickness",
                            None
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

                st.success(
                    f"{len(generated_insert_rows)} component(s) sent to tracking successfully"
                )

            except Exception as e:
                conn.rollback()
                st.error(f"Failed to send components to tracking: {e}")
