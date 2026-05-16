import streamlit as st
import pandas as pd
import re
from decimal import Decimal
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
    if not formula:
        return []

    formula = normalize_formula(formula)

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
        str(formula)
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


def generated_variable_name(component, attribute=None):
    parts = [str(component or "").strip()]

    if attribute:
        parts.append(str(attribute or "").strip())

    return (
        "_".join(parts)
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


def resolve_fixed_value(formula, quantity):
    formula_value = clean_number(formula)

    if formula_value is not None:
        return Decimal(str(round(formula_value, 2)))

    quantity_value = clean_number(quantity)

    if quantity_value is not None:
        return Decimal(str(round(quantity_value, 2)))

    return None


def resolve_base_quantity(component, quantity, previous_component_qty):
    component_name = str(component or "").strip().lower()

    if component_name == "flush shutter":
        return 1

    if quantity not in [None, ""]:
        return int(float(quantity))

    return int(previous_component_qty.get(component_name, 1))


def component_priority(component):
    name = str(component or "").strip()

    priority_map = {
        "Frame Vertical": 0.0,
        "Frame Horizontal": 0.0,
        "Door Frame Vertical": 0.0,
        "Door Frame Horizontal": 0.0,

        "Door Frame Vertical Beading 1": 0.0,
        "Door Frame Vertical Beading": 0.0,
        "Door Frame Horizontal Beading": 0.0,
        "Door Frame Horizontal Beading 1": 0.0,
        "Door Frame Horizontal Beading 2": 0.0,

        "Architrave Vertical": 0.0,
        "Architrave Horizontal": 0.0,
        "Architrave Vertical Front": 0.0,
        "Architrave Horizontal Front": 0.0,

        "Flush Shutter": 0.0,
        "Louver": 0.0,
    }

    return priority_map.get(name, 999)


def ensure_generated_components_table(conn, cur):
    safe_execute(conn, cur, """
        CREATE TABLE IF NOT EXISTS generated_components (
            id SERIAL PRIMARY KEY,
            project_name TEXT,
            unit_type TEXT,
            house_number TEXT,
            product_cat TEXT,
            product_code TEXT,
            orientation TEXT,
            component TEXT,
            attributes_json JSONB,
            quantity INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()


def show_component_calculator(conn, cur):

    st.title("Component Calculator")

    ensure_generated_components_table(conn, cur)

    projects = get_distinct_values(
        conn,
        cur,
        "projects",
        "project_name"
    )

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

    product_options = [
        f"{p[0]} | {p[1]}"
        for p in products
    ]

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

    rules = sorted(
        rules,
        key=lambda x: (
            component_priority(x[0]),
            str(x[0]).strip(),
            str(x[1]).strip()
        )
    )

    st.markdown("---")
    st.subheader("User Based Data")

    required_variables = set()

    for rule in rules:
        for variable in extract_formula_variables(rule[3]):
            required_variables.add(variable)

    for variable in DEFAULT_VALUES:
        required_variables.add(variable)

    generated_variables = set()

    for rule in rules:
        component = rule[0]
        attribute = rule[1]

        generated_variables.add(
            generated_variable_name(component, attribute)
        )

        generated_variables.add(
            generated_variable_name(component)
        )

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

        preview_rows = []
        tracking_rows = []
        errors_found = False

        product_qty_multiplier = int(
            float(variables.get("lh_quantity", 0))
            + float(variables.get("rh_quantity", 0))
        )

        if product_qty_multiplier <= 0:
            st.warning("Please enter LH Quantity or RH Quantity.")
            return

        for house_number in selected_houses:

            house_variables = variables.copy()
            previous_component_qty = {}
            component_tracking_map = {}

            for rule in rules:

                component = str(rule[0]).strip()
                attribute = str(rule[1]).strip()
                rule_type = str(rule[2] or "").strip().lower()
                formula = rule[3]
                raw_quantity = rule[4]

                base_quantity = resolve_base_quantity(
                    component,
                    raw_quantity,
                    previous_component_qty
                )

                total_quantity = int(base_quantity * product_qty_multiplier)

                previous_component_qty[
                    component.lower()
                ] = base_quantity

                component_key = generated_variable_name(component)
                attribute_key = generated_variable_name(component, attribute)

                value = None

                if rule_type in ["formula", "fomula"]:

                    try:
                        value = evaluate_formula(
                            formula,
                            house_variables
                        )

                        house_variables[attribute_key] = float(value)

                        if attribute.lower() in ["length", "width", "height"]:
                            house_variables[f"{component_key}_{attribute.lower()}"] = float(value)

                        house_variables[component_key] = float(value)

                    except Exception as e:
                        errors_found = True
                        st.error(
                            f"{house_number} - {component} / {attribute}: {e}"
                        )

                elif rule_type == "fixed":

                    value = resolve_fixed_value(
                        formula,
                        raw_quantity
                    )

                    if value is not None:
                        house_variables[attribute_key] = float(value)
                        house_variables[component_key] = float(value)

                else:
                    value = resolve_fixed_value(
                        formula,
                        raw_quantity
                    )

                    if value is not None:
                        house_variables[attribute_key] = float(value)
                        house_variables[component_key] = float(value)

                preview_rows.append({
                    "House Number": house_number,
                    "Product": product_code,
                    "Component": component,
                    "Attribute": attribute,
                    "Type": "formula" if rule_type == "fomula" else rule_type,
                    "Formula": normalize_formula(formula),
                    "Value": value,
                    "Base Quantity": base_quantity,
                    "Total Quantity": total_quantity,
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
                    "value": float(value) if value is not None else None,
                    "base_quantity": base_quantity,
                }

            tracking_rows.extend(component_tracking_map.values())

        st.session_state["generated_component_preview"] = preview_rows
        st.session_state["generated_component_tracking_rows"] = tracking_rows

    if "generated_component_preview" in st.session_state:

        st.subheader("Generated Components")

        df_preview = pd.DataFrame(
            st.session_state["generated_component_preview"]
        )

        st.dataframe(
            df_preview,
            use_container_width=True,
            hide_index=True
        )

        if df_preview["Value"].isna().any():
            st.warning("Some components did not calculate. Fix formulas before confirming.")
        else:
            st.success("All component formulas calculated successfully")

        st.markdown("---")

        if st.button("Confirm Components and Send to Tracking", type="primary"):

            tracking_rows = st.session_state.get(
                "generated_component_tracking_rows",
                []
            )

            if not tracking_rows:
                st.warning("No generated components to save.")
                return

            try:
                insert_rows = []

                for row in tracking_rows:
                    insert_rows.append((
                        row["project_name"],
                        row["unit_type"],
                        row["house_number"],
                        row["product_cat"],
                        row["product_code"],
                        row["orientation"],
                        row["component"],
                        row["attributes"],
                        row["quantity"],
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
                        orientation,
                        component,
                        attributes_json,
                        quantity
                    )
                    VALUES %s
                    """,
                    insert_rows
                )

                conn.commit()

                st.success(
                    f"{len(insert_rows)} component(s) sent to tracking successfully"
                )

            except Exception as e:
                conn.rollback()
                st.error(f"Failed to send components to tracking: {e}")
