import os
import psycopg2
import streamlit as st


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="OperaFlow Component App",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =========================================================
# SESSION DEFAULTS
# =========================================================
defaults = {
    "logged_in": False,
    "role": None,
    "page": "Component Calculator"
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =========================================================
# LOGIN PAGE
# =========================================================
def login():

    st.title("OperaFlow")
    st.subheader("Component Fabrication & Tracking System")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Sign In"):

        users = {
            "admin": {
                "password": "admin@123",
                "role": "admin"
            },
            "production": {
                "password": "123",
                "role": "production"
            }
        }

        if username in users:

            if users[username]["password"] == password:

                st.session_state.logged_in = True
                st.session_state.role = users[username]["role"]

                st.rerun()

        st.error("Invalid credentials")


# =========================================================
# LOGIN CHECK
# =========================================================
if not st.session_state.logged_in:
    login()
    st.stop()


# =========================================================
# DATABASE CONNECTION
# =========================================================
def create_connection():

    return psycopg2.connect(
        host=st.secrets["DB_HOST"],
        port=st.secrets["DB_PORT"],
        database=st.secrets["DB_NAME"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"]
    )


conn = create_connection()
cur = conn.cursor()


# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:

    st.title("OperaFlow")

    st.markdown(
        f"Logged in as: {st.session_state.role.upper()}"
    )

    st.markdown("---")

    pages = [
        "Component Calculator",
        "Tracking",
        "Upload Data"
    ]

    selected_page = st.radio(
        "Navigation",
        pages
    )

    st.session_state.page = selected_page

    st.markdown("---")

    if st.button("Logout"):

        st.session_state.logged_in = False
        st.session_state.role = None

        st.rerun()


# =========================================================
# PAGE ROUTER
# =========================================================
try:

    if selected_page == "Component Calculator":

        from component_calculator import show_component_calculator

        show_component_calculator(conn, cur)

    elif selected_page == "Tracking":

        from tracking import show_tracking

        show_tracking(conn, cur)

    elif selected_page == "Upload Data":

        from upload import show_upload

        show_upload(conn, cur)

except Exception as e:

    conn.rollback()

    st.error(f"Error: {e}")

finally:

    cur.close()
    conn.close()
```

---

# 2. component_calculator.py

This file handles ONLY:

* formula engine
* dynamic inputs
* recursive calculation
* generated components
* save generated components
* variable dependency resolution

---

# COMPLETE component_calculator.py

```python
import streamlit as st
import pandas as pd
import re
import ast
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

    "opening_length": "opening_height",
    "height_opening": "opening_height",

    "opening_w": "opening_width",

    "clr": "clearance",

    "extra_width": "allowance",
    "extra_length": "allowance"
}


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
# EXTRACT VARIABLES
# =========================================================
def extract_formula_variables(formula):

    if not formula:
        return []

    ignore_words = {
        "abs",
        "min",
        "max",
        "round"
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

    formula = str(formula or "").strip()

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

        return Decimal(str(result))

    except Exception as e:

        raise FormulaError(str(e))


# =========================================================
# MAIN PAGE
# =========================================================
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
        project_name = st.selectbox(
            "Project",
            projects
        )

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
        ORDER BY component, attribute
    """, (product_cat, product_code))

    rules = cur.fetchall()

    st.markdown("---")
    st.subheader("Formula Inputs")

    required_variables = set()

    for rule in rules:

        formula = rule[3]

        vars_found = extract_formula_variables(formula)

        for v in vars_found:
            required_variables.add(v)

    variables = {}

    cols = st.columns(4)

    for idx, variable in enumerate(sorted(required_variables)):

        with cols[idx % 4]:

            variables[variable] = st.number_input(
                variable,
                value=0.0,
                step=1.0
            )

    st.markdown("---")

    if st.button("Generate Components"):

        preview_rows = []

        for rule in rules:

            component = rule[0]
            attribute = rule[1]
            rule_type = str(rule[2]).lower()
            formula = rule[3]
            quantity = rule[4]

            value = None

            if rule_type == "formula":

                try:
                    value = evaluate_formula(
                        formula,
                        variables
                    )

                except Exception as e:

                    st.error(
                        f"{component} / {attribute}: {e}"
                    )

            elif rule_type == "fixed":

                value = quantity

            preview_rows.append({
                "Component": component,
                "Attribute": attribute,
                "Value": value
            })

        st.dataframe(
            pd.DataFrame(preview_rows),
            use_container_width=True,
            hide_index=True
        )

This is the correct architecture.
