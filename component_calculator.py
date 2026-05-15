import streamlit as st
import pandas as pd
import re
from decimal import Decimal
from psycopg2.extras import Json


# =========================================================
# FORMULA ERROR
# =========================================================
class FormulaError(Exception):
    pass


# =========================================================
# VARIABLE ALIASES
# =========================================================
VARIABLE_ALIASES = {

    # HEIGHT / LENGTH
    "opening_length": "opening_height",
    "height_opening": "opening_height",

    # WIDTH
    "opening_w": "opening_width",
    "width_opening": "opening_width",

    # CLEARANCE
    "clr": "clearance",

    # EXTRA VALUES
    "extra_w": "extra_width",
    "extra_l": "extra_length",

    # FRAME SHORTCUTS
    "frame_h_thk": "frame_horizontal_thickness",
    "frame_v_thk": "frame_vertical_thickness",

    # COMMON SHORTCUTS
    "allow": "allowance"
}


# =========================================================
# DEFAULT VARIABLES
# =========================================================
DEFAULT_VARIABLES = [

    "opening_height",
    "opening_width",

    "clearance",

    "extra_width",
    "extra_length",

    "allowance",

    "frame_horizontal_thickness",
    "frame_vertical_thickness",

    "groove",
    "cut",
    "offset"
]


# =========================================================
# NORMALIZE VARIABLE
# =========================================================
def normalize_variable(var_name):

    var_name = str(var_name).strip()

    return VARIABLE_ALIASES.get(
        var_name,
        var_name
    )


# =========================================================
# NORMALIZE FORMULA
# =========================================================
def normalize_formula(formula):

    formula = str(formula or "").strip()

    for old_var, new_var in VARIABLE_ALIASES.items():

        formula = re.sub(
            rf"\b{old_var}\b",
            new_var,
            formula
        )

    return formula


# =========================================================
# SAFE EXECUTE
# =========================================================
def safe_execute(conn, cur, query, params=None):

    try:

        cur.execute(query, params or ())

    except Exception as e:

        conn.rollback()

        raise e


# =========================================================
# GET DISTINCT VALUES
# =========================================================
def get_distinct_values(
    conn,
    cur,
    table,
    column,
    where_sql="",
    params=None
):

    query = f"""
        SELECT DISTINCT {column}
        FROM {table}
        {where_sql}
        ORDER BY {column}
    """

    safe_execute(conn, cur, query, params)

    rows = cur.fetchall()

    return [r[0] for r in rows if r[0] is not None]


# =========================================================
# EXTRACT VARIABLES FROM FORMULA
# =========================================================
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

    cleaned = []

    for variable in variables:

        if variable not in ignore_words:

            cleaned.append(
                normalize_variable(variable)
            )

    return sorted(list(set(cleaned)))


# =========================================================
# SAFE FORMULA EVALUATION
# =========================================================
def evaluate_formula(formula, variables):

    formula = normalize_formula(formula)

    if not formula:
        raise FormulaError("Formula empty")

    allowed_functions = {
        "abs": abs,
        "min": min,
        "max": max,
        "round": round
    }

    clean_vars = {}

    for k, v in variables.items():

        if v not in [None, ""]:

            clean_vars[k] = float(v)

    clean_vars.update(allowed_functions)

    try:

        result = eval(
            formula,
            {"__builtins__": {}},
            clean_vars
        )

        return Decimal(str(round(result, 2)))

    except NameError as e:

        missing_var = str(e)

        raise FormulaError(f"Missing variable: {missing_var}")

    except Exception as e:

        raise FormulaError(str(e))


# =========================================================
# MAIN PAGE
# =========================================================
def show_component_calculator(conn, cur):

    st.title("Component Calculator")


    # =====================================================
    # PROJECTS
    # =====================================================
    projects = get_distinct_values(
        conn,
        cur,
        "projects",
        "project_name"
    )

    col1, col2, col3, col4 = st.columns(4)


    # =====================================================
    # PROJECT
    # =====================================================
    with col1:

        project_name = st.selectbox(
            "Project",
            projects
        )


    # =====================================================
    # UNIT TYPES
    # =====================================================
    unit_types = get_distinct_values(
        conn,
        cur,
        "unit_types",
        "unit_type",
        "WHERE project_name = %s",
        (project_name,)
    )

    with col2:

        unit_type = st.selectbox(
            "Unit Type",
            unit_types
        )


    # =====================================================
    # HOUSES
    # =====================================================
    houses = get_distinct_values(
        conn,
        cur,
        "houses",
        "house_number",
        "WHERE project_name = %s AND unit_type = %s",
        (project_name, unit_type)
    )

    with col3:

        house_number = st.selectbox(
            "House Number",
            houses
        )


    # =====================================================
    # PRODUCTS
    # =====================================================
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

        selected_product = st.selectbox(
            "Product",
            product_options
        )


    # =====================================================
    # SPLIT PRODUCT
    # =====================================================
    product_cat, product_code = selected_product.split(" | ", 1)


    # =====================================================
    # FETCH RULES
    # =====================================================
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
        ORDER BY component, attribute
    """, (product_cat, product_code))

    rules = cur.fetchall()


    # =====================================================
    # FORMULA INPUTS
    # =====================================================
    st.markdown("---")
    st.subheader("Formula Inputs")

    required_variables = set()


    # =====================================================
    # EXTRACT VARIABLES FROM FORMULAS
    # =====================================================
    for rule in rules:

        formula = rule[3]

        vars_found = extract_formula_variables(formula)

        for v in vars_found:
            required_variables.add(v)


    # =====================================================
    # ADD DEFAULT VARIABLES
    # =====================================================
    for v in DEFAULT_VARIABLES:
        required_variables.add(v)


    # =====================================================
    # DEFAULT VALUES
    # =====================================================
    default_values = {
        "opening_height": 1200.0,
        "opening_width": 2100.0,
        "clearance": 20.0,
        "extra_width": 60.0,
        "extra_length": 60.0,
        "allowance": 11.0,
        "frame_horizontal_thickness": 50.0,
        "frame_vertical_thickness": 50.0,
        "groove": 8.0,
        "cut": 7.0,
        "offset": 22.0
    }


    # =====================================================
    # INPUT UI
    # =====================================================
    variables = {}

    cols = st.columns(4)

    for idx, variable in enumerate(sorted(required_variables)):

        with cols[idx % 4]:

            variables[variable] = st.number_input(
                variable,
                value=float(default_values.get(variable, 0.0)),
                step=1.0,
                format="%.2f"
            )


    st.markdown("---")


    # =====================================================
    # GENERATE BUTTON
    # =====================================================
    if st.button("Generate Components"):

        preview_rows = []

        errors_found = False


        # =================================================
        # LOOP RULES
        # =================================================
        for rule in rules:

            component = rule[0]
            attribute = rule[1]
            rule_type = str(rule[2]).lower()
            formula = rule[3]
            quantity = rule[4]

            value = None


            # =============================================
            # FORMULA TYPE
            # =============================================
            if rule_type == "formula":

                try:

                    value = evaluate_formula(
                        formula,
                        variables
                    )

                except Exception as e:

                    errors_found = True

                    st.error(
                        f"{component} / {attribute}: {e}"
                    )


            # =============================================
            # FIXED TYPE
            # =============================================
            elif rule_type == "fixed":

                value = quantity


            # =============================================
            # APPEND ROW
            # =============================================
            preview_rows.append({
                "Component": component,
                "Attribute": attribute,
                "Formula": formula,
                "Value": value
            })


        # =================================================
        # DISPLAY TABLE
        # =================================================
        st.subheader("Generated Components")

        df_preview = pd.DataFrame(preview_rows)

        st.dataframe(
            df_preview,
            use_container_width=True,
            hide_index=True
        )


        # =================================================
        # SUCCESS MESSAGE
        # =================================================
        if not errors_found:

            st.success("All component formulas calculated successfully")
