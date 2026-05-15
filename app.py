import ast
import os
from decimal import Decimal

import psycopg2
import streamlit as st
from psycopg2.extras import Json


st.set_page_config(
    page_title="OperaFlow Component App",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ================= SAFE EXECUTE =================
def safe_execute(conn, cur, query, params=None):
    try:
        cur.execute(query, params or ())
    except Exception as e:
        conn.rollback()
        raise e


# ================= SESSION =================
defaults = {
    "logged_in": False,
    "role": None,
    "page": "Component Calculator"
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ================= LOGIN =================
def login():
    st.markdown("""
        <style>
        .stApp {
            background: #f5f2eb;
            font-family: 'Segoe UI', sans-serif;
        }

        .block-container {
            padding-top: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }

        .login-title {
            font-size: 42px;
            font-weight: 700;
            color: #333;
            line-height: 1.2;
        }

        .highlight {
            color: #f57c00;
        }

        .login-subtitle {
            color: #666;
            font-size: 18px;
            margin-top: 10px;
        }

        .login-box {
            max-width: 460px;
            margin: 110px auto 0 auto;
            padding: 10px;
        }

        .heading {
            font-size: 28px;
            font-weight: 700;
        }

        .subtext {
            color: #666;
            margin-bottom: 25px;
        }

        .stTextInput>div>div>input {
            border-radius: 10px;
            height: 45px;
        }

        .stButton>button {
            background-color: #f57c00;
            color: white;
            height: 45px;
            border-radius: 10px;
            width: 150px;
            font-weight: 600;
            border: none;
        }

        section[data-testid="stSidebar"] {
            background: #ffffff;
        }
        </style>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("<div style='margin-top:120px;margin-left:100px;'>", unsafe_allow_html=True)

        if os.path.exists("logo.png"):
            st.image("logo.png", width=220)

        st.markdown("""
            <div class="login-title">
                Total Environment <span class="highlight">Machine Craft</span>
            </div>
            <div class="login-subtitle">
                Component Fabrication & Tracking System
            </div>
        """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="login-box">', unsafe_allow_html=True)

        st.markdown('<div class="heading">Sign in to your account</div>', unsafe_allow_html=True)
        st.markdown('<div class="subtext">Authorized access only</div>', unsafe_allow_html=True)

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Sign In"):
            users = {
                "production": {"password": "123", "role": "production"},
                "preassembly": {"password": "123", "role": "preassembly"},
                "polishing": {"password": "123", "role": "polishing"},
                "final": {"password": "123", "role": "final"},
                "dispatch": {"password": "123", "role": "dispatch"},
                "admin": {"password": "admin@123", "role": "admin"}
            }

            if username in users and users[username]["password"] == password:
                st.session_state.logged_in = True
                st.session_state.role = users[username]["role"]
                st.success("Login successful")
                st.rerun()
            else:
                st.error("Invalid credentials")

        st.markdown("</div>", unsafe_allow_html=True)


# ================= LOGIN CHECK =================
if not st.session_state.logged_in:
    login()
    st.stop()


# ================= DB CONNECTION =================
def create_connection():
    try:
        return psycopg2.connect(
            host=st.secrets["DB_HOST"],
            port=st.secrets["DB_PORT"],
            database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"],
            password=st.secrets["DB_PASSWORD"]
        )
    except Exception as e:
        st.error(f"DB connection failed: {e}")
        return None


conn = create_connection()

if conn is None:
    st.stop()

cur = conn.cursor()


# ================= FORMULA ENGINE =================
class FormulaError(Exception):
    pass


def evaluate_formula(formula, variables):
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Call,
    )

    allowed_functions = {
        "abs": abs,
        "max": max,
        "min": min,
        "round": round,
    }

    formula = str(formula or "").strip()

    if not formula:
        raise FormulaError("Formula is empty")

    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        raise FormulaError(f"Invalid formula: {formula}")

    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise FormulaError(f"Unsupported expression: {formula}")

        if isinstance(node, ast.Name):
            if node.id not in variables and node.id not in allowed_functions:
                raise FormulaError(f"Missing variable: {node.id}")

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaError("Invalid formula function")

            if node.func.id not in allowed_functions:
                raise FormulaError("Only abs, max, min, round allowed")

    clean_vars = {}

    for key, value in variables.items():
        if value not in [None, ""]:
            clean_vars[key] = float(value)

    clean_vars.update(allowed_functions)

    try:
        result = eval(
            compile(tree, "<formula>", "eval"),
            {"__builtins__": {}},
            clean_vars
        )
        return Decimal(str(result))
    except Exception as e:
        raise FormulaError(str(e))


def get_distinct_values(table, column, where_sql="", params=None):
    query = f"""
        SELECT DISTINCT {column}
        FROM {table}
        {where_sql}
        ORDER BY {column}
    """
    safe_execute(conn, cur, query, params)
    rows = cur.fetchall()
    return [r[0] for r in rows if r[0] is not None]


def get_product_rules(product_cat, product_code):
    safe_execute(conn, cur, """
        SELECT id, component, attribute, type, formula_used, quantity
        FROM product_component_rules
        WHERE product_cat = %s
        AND product_code = %s
        ORDER BY component, attribute, id
    """, (product_cat, product_code))

    return cur.fetchall()


def save_calculation_log(project_name, house_number, product_code, formula, input_values, output_value):
    safe_execute(conn, cur, """
        INSERT INTO calculation_logs
        (
            project_name,
            house_number,
            product_code,
            formula,
            input_values,
            output_value
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        project_name,
        house_number,
        product_code,
        formula,
        Json(input_values),
        str(output_value)
    ))


def save_generated_components(rows, project_name, unit_type, house_number, product_cat, product_code):
    safe_execute(conn, cur, """
        DELETE FROM generated_components
        WHERE project_name = %s
        AND unit_type = %s
        AND house_number = %s
        AND product_cat = %s
        AND product_code = %s
    """, (
        project_name,
        unit_type,
        house_number,
        product_cat,
        product_code
    ))

    for row in rows:
        safe_execute(conn, cur, """
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            row["project_name"],
            row["unit_type"],
            row["house_number"],
            row["product_cat"],
            row["product_code"],
            row["component"],
            row["attribute"],
            row["calculated_value"],
            row["width"],
            row["thickness"],
            row["orientation"],
            row["qty"]
        ))

    update_tracking_from_generated(rows, project_name, house_number)

    conn.commit()


def update_tracking_from_generated(rows, project_name, house_number):
    component_qty = {}

    for row in rows:
        if row["qty"] is not None:
            component = row["component"]
            component_qty[component] = component_qty.get(component, 0) + int(row["qty"])

    for component, required_qty in component_qty.items():
        safe_execute(conn, cur, """
            SELECT id, completed_qty
            FROM tracking
            WHERE project_name = %s
            AND house_number = %s
            AND component = %s
            ORDER BY id DESC
            LIMIT 1
        """, (
            project_name,
            house_number,
            component
        ))

        existing = cur.fetchone()

        if existing:
            tracking_id = existing[0]
            completed_qty = existing[1] or 0
        else:
            tracking_id = None
            completed_qty = 0

        pending_qty = max(required_qty - completed_qty, 0)

        if pending_qty == 0:
            status = "Completed"
        elif completed_qty > 0:
            status = "In Progress"
        else:
            status = "Pending"

        if tracking_id:
            safe_execute(conn, cur, """
                UPDATE tracking
                SET required_qty = %s,
                    completed_qty = %s,
                    pending_qty = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (
                required_qty,
                completed_qty,
                pending_qty,
                status,
                tracking_id
            ))
        else:
            safe_execute(conn, cur, """
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
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                project_name,
                house_number,
                component,
                required_qty,
                completed_qty,
                pending_qty,
                status
            ))


# ================= SIDEBAR =================
with st.sidebar:
    st.markdown("## OperaFlow")
    st.markdown(f"**Logged in as:** `{st.session_state.role.upper()}`")
    st.markdown("---")

    if st.session_state.role == "admin":
        pages = [
            "Component Calculator",
            "Tracking",
            "Upload Data"
        ]
    else:
        pages = [
            "Tracking"
        ]

    page = st.radio("Navigation", pages)
    st.session_state.page = page

    st.markdown("---")

    if st.button("Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.role = None
        st.session_state.page = "Component Calculator"
        st.rerun()


page = st.session_state.page


# ================= ACCESS CHECK =================
if st.session_state.role != "admin" and page in ["Component Calculator", "Upload Data"]:
    st.error("Access denied")
    st.stop()


# ================= COMPONENT CALCULATOR PAGE =================
def show_component_calculator():
    st.title("Component Calculator")

    st.markdown("""
        This page follows the flow:

        Project -> Unit -> House -> Product -> Inputs -> Rule Engine -> Generated Components -> Tracking
    """)

    projects = get_distinct_values("projects", "project_name")

    if not projects:
        st.warning("No projects found. Upload or create master data first.")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        project_name = st.selectbox("Project", projects)

    unit_types = get_distinct_values(
        "unit_types",
        "unit_type",
        "WHERE project_name = %s",
        (project_name,)
    )

    with col2:
        unit_type = st.selectbox("Unit Type", unit_types) if unit_types else None

    if not unit_type:
        st.warning("No unit types found for this project.")
        return

    houses = get_distinct_values(
        "houses",
        "house_number",
        "WHERE project_name = %s AND unit_type = %s",
        (project_name, unit_type)
    )

    with col3:
        house_number = st.selectbox("House Number", houses) if houses else None

    if not house_number:
        st.warning("No houses found for this project and unit type.")
        return

    safe_execute(conn, cur, """
        SELECT DISTINCT product_cat, product_code
        FROM products
        ORDER BY product_cat, product_code
    """)

    products = cur.fetchall()

    if not products:
        st.warning("No products found.")
        return

    product_options = [f"{p[0]} | {p[1]}" for p in products]

    with col4:
        selected_product = st.selectbox("Product", product_options)

    product_cat, product_code = selected_product.split(" | ", 1)

    rules = get_product_rules(product_cat, product_code)

    if not rules:
        st.warning("No component rules found for this product.")
        return

    st.markdown("---")
    st.subheader("Formula Inputs")

    default_variables = [
        "opening_width",
        "opening_height",
        "clearance",
        "groove",
        "allowance",
        "LH",
        "RH",
        "total_shutters"
    ]

    variables = {}

    input_cols = st.columns(4)

    for index, variable in enumerate(default_variables):
        with input_cols[index % 4]:
            variables[variable] = st.number_input(
                variable,
                value=0.0,
                step=1.0
            )

    st.markdown("---")
    st.subheader("Generated Component Preview")

    preview_rows = []
    generated_rows = []
    errors = []

    for rule in rules:
        rule_id = rule[0]
        component = rule[1]
        attribute = rule[2]
        rule_type = str(rule[3] or "").lower()
        formula_used = rule[4]
        quantity = rule[5]

        value = None

        if rule_type == "formula":
            try:
                value = evaluate_formula(formula_used, variables)

                save_calculation_log(
                    project_name,
                    house_number,
                    product_code,
                    formula_used,
                    variables,
                    value
                )

            except FormulaError as e:
                errors.append(f"{component} / {attribute}: {e}")

        elif rule_type == "fixed":
            if quantity is not None:
                value = quantity
            else:
                value = formula_used

        elif rule_type == "manual":
            key = f"manual_{rule_id}"

            if str(attribute).lower() in ["width", "thickness", "qty"]:
                value = st.number_input(
                    f"{component} - {attribute}",
                    value=0.0,
                    step=1.0,
                    key=key
                )
            else:
                value = st.text_input(
                    f"{component} - {attribute}",
                    key=key
                )

        attribute_lower = str(attribute).lower()

        width = None
        thickness = None
        orientation = None
        qty = None

        if attribute_lower == "width" and value not in [None, ""]:
            width = float(value)

        if attribute_lower == "thickness" and value not in [None, ""]:
            thickness = float(value)

        if attribute_lower == "orientation" and value not in [None, ""]:
            orientation = str(value)

        if attribute_lower == "qty" and value not in [None, ""]:
            qty = int(float(value))

        generated_row = {
            "project_name": project_name,
            "unit_type": unit_type,
            "house_number": house_number,
            "product_cat": product_cat,
            "product_code": product_code,
            "component": component,
            "attribute": attribute,
            "calculated_value": str(value) if value is not None else None,
            "width": width,
            "thickness": thickness,
            "orientation": orientation,
            "qty": qty
        }

        generated_rows.append(generated_row)

        preview_rows.append({
            "Component": component,
            "Attribute": attribute,
            "Type": rule_type,
            "Formula": formula_used,
            "Value": str(value) if value is not None else ""
        })

    if errors:
        for error in errors:
            st.error(error)

    st.dataframe(preview_rows, use_container_width=True, hide_index=True)

    if st.button("Save Generated Components", type="primary", disabled=bool(errors)):
        save_generated_components(
            generated_rows,
            project_name,
            unit_type,
            house_number,
            product_cat,
            product_code
        )

        st.success("Generated components saved and tracking updated.")


# ================= PAGE ROUTER =================
try:
    if page == "Component Calculator":
        show_component_calculator()

    elif page == "Tracking":
        from tracking import show_tracking
        show_tracking(conn, cur)

    elif page == "Upload Data":
        from upload import show_upload
        show_upload(conn, cur)

except Exception as e:
    try:
        conn.rollback()
    except Exception:
        pass

    st.error(f"Error occurred: {e}")

finally:
    try:
        cur.close()
        conn.close()
    except Exception:
        pass
