import streamlit as st
import pandas as pd
import re
from decimal import Decimal


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
    "opening_length": 2100.0,
    "opening_width": 1200.0,

    "vertical_clearance": 10.0,
    "horizontal_clearance": 10.0,
    "architrave_extra_length": 50.0,
    "architrave_extra_width": 100.0,
    "frame_horizontal_thickness": 50.0,
    "frame_vertical_thickness": 50.0,

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

    # Some Excel rows are like: Grilll_shutter_vertical=shutter_length
    # We only need the right side as the formula expression.
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

    ignore_words = {"abs", "min", "max", "round", "float", "int", "Decimal"}

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

    for k, v in variables.items():
        if v not in [None, ""]:
            clean_vars[normalize_variable(k)] = float(v)

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


def resolve_quantity(component, quantity, previous_component_qty):
    component_name = str(component or "").strip().lower()

    # In your Excel, Flush Shutter quantity is merged.
    # Length row has 1, width row becomes blank. Every door has 1 flush shutter.
    if component_name == "flush shutter":
        return 1

    if quantity not in [None, ""]:
        return quantity

    return previous_component_qty.get(component_name, 1)


def show_component_calculator(conn, cur):

    st.title("Component Calculator")

    projects = get_distinct_values(
        conn,
        cur,
        "projects",
        "project_name"
    )

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

    priority_map = {
        "Frame Vertical": 1,
        "Frame Horizontal": 2,
        "Door Frame Vertical": 3,
        "Door Frame Horizontal": 4,
        "Door Frame Vertical Beading": 5,
        "Door Frame Horizontal Beading": 6,
        "Architrave Vertical": 7,
        "Architrave Horizontal": 8,
        "Architrave Vertical Front": 9,
        "Architrave Horizontal Front": 10,
        "Flush Shutter": 11,
        "Louver": 12,
    }

    rules = sorted(
        rules,
        key=lambda x: (
            priority_map.get(str(x[0]).strip(), 99),
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

        # Some formulas refer only to component name, for example:
        # door_frame_vertical - shutter_thickness
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
        errors_found = False
        previous_component_qty = {}

        for house_number in selected_houses:

            # Each house should calculate independently.
            house_variables = variables.copy()

            for rule in rules:

                component = str(rule[0]).strip()
                attribute = str(rule[1]).strip()
                rule_type = str(rule[2] or "").strip().lower()
                formula = rule[3]
                quantity = resolve_quantity(
                    component,
                    rule[4],
                    previous_component_qty
                )

                component_key = generated_variable_name(component)
                attribute_key = generated_variable_name(component, attribute)

                previous_component_qty[
                    component.lower()
                ] = quantity

                value = None

                if rule_type in ["formula", "fomula"]:

                    try:
                        value = evaluate_formula(
                            formula,
                            house_variables
                        )

                        house_variables[attribute_key] = float(value)

                        # Store component-level value also.
                        # This helps formulas like door_frame_vertical - shutter_thickness.
                        house_variables[component_key] = float(value)

                    except Exception as e:
                        errors_found = True
                        st.error(f"{house_number} - {component} / {attribute}: {e}")

                elif rule_type == "fixed":

                    value = quantity

                    house_variables[attribute_key] = float(value)
                    house_variables[component_key] = float(value)

                preview_rows.append({
                    "House Number": house_number,
                    "Product": product_code,
                    "Component": component,
                    "Attribute": attribute,
                    "Type": rule_type,
                    "Formula": normalize_formula(formula),
                    "Value": value,
                    "Quantity": quantity,
                })

        st.subheader("Generated Components")

        df_preview = pd.DataFrame(preview_rows)

        st.dataframe(
            df_preview,
            use_container_width=True,
            hide_index=True
        )

        if not errors_found:
            st.success("All component formulas calculated successfully")
