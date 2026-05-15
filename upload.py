import re
import pandas as pd
import streamlit as st


# ================= SAFE EXECUTE =================
def safe_execute(conn, cur, query, params=None):
    try:
        cur.execute(query, params or ())
    except Exception as e:
        conn.rollback()
        raise e


# ================= CLEAN HELPERS =================
def clean_text(value):
    if pd.isna(value):
        return None

    value = str(value).strip()
    return value if value else None


def clean_int(value):
    if pd.isna(value) or value == "":
        return None

    try:
        return int(float(value))
    except Exception:
        return None


def normalize_columns(df):
    df.columns = [
        str(col).strip().lower()
        .replace(" ", "_")
        .replace("-", "_")
        for col in df.columns
    ]
    return df


def normalize_rule_type(value):
    value = clean_text(value)

    if not value:
        return None

    value = value.lower().strip()

    if value in ["fomula", "formula", "formulas"]:
        return "formula"

    if value in ["manual", "input", "user_input"]:
        return "manual"

    if value in ["fixed", "constant", "qty"]:
        return "fixed"

    return value


def split_product_codes(value):
    value = clean_text(value)

    if not value:
        return []

    return [code.strip() for code in value.split(",") if code.strip()]


def extract_formula_variables(formula):
    formula = clean_text(formula)

    if not formula:
        return []

    ignore_words = {"abs", "max", "min", "round"}

    variables = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", formula)

    return sorted(set(v for v in variables if v not in ignore_words))


# ================= DATABASE INSERTS =================
def insert_project(conn, cur, project_name):
    safe_execute(conn, cur, """
        INSERT INTO projects (project_name)
        VALUES (%s)
        ON CONFLICT (project_name) DO NOTHING
    """, (project_name,))


def insert_unit_type(conn, cur, project_name, unit_type):
    safe_execute(conn, cur, """
        INSERT INTO unit_types (project_name, unit_type)
        SELECT %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM unit_types
            WHERE project_name = %s
            AND unit_type = %s
        )
    """, (
        project_name,
        unit_type,
        project_name,
        unit_type
    ))


def insert_house(conn, cur, project_name, unit_type, house_number):
    safe_execute(conn, cur, """
        INSERT INTO houses (project_name, unit_type, house_number)
        SELECT %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM houses
            WHERE project_name = %s
            AND unit_type = %s
            AND house_number = %s
        )
    """, (
        project_name,
        unit_type,
        house_number,
        project_name,
        unit_type,
        house_number
    ))


def insert_product(conn, cur, product_cat, product_code):
    safe_execute(conn, cur, """
        INSERT INTO products
        (
            product_cat,
            product_code
        )
        SELECT %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM products
            WHERE product_cat = %s
            AND product_code = %s
        )
    """, (
        product_cat,
        product_code,
        product_cat,
        product_code
    ))


def insert_component_rule(
    conn,
    cur,
    product_cat,
    product_code,
    component,
    attribute,
    rule_type,
    formula_used,
    quantity
):
    safe_execute(conn, cur, """
        INSERT INTO product_component_rules
        (
            product_cat,
            product_code,
            component,
            attribute,
            type,
            formula_used,
            quantity
        )
        SELECT %s, %s, %s, %s, %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM product_component_rules
            WHERE product_cat = %s
            AND product_code = %s
            AND component = %s
            AND attribute = %s
            AND type = %s
            AND COALESCE(formula_used, '') = COALESCE(%s, '')
            AND COALESCE(quantity, -1) = COALESCE(%s, -1)
        )
    """, (
        product_cat,
        product_code,
        component,
        attribute,
        rule_type,
        formula_used,
        quantity,
        product_cat,
        product_code,
        component,
        attribute,
        rule_type,
        formula_used,
        quantity
    ))


def insert_formula_variable(conn, cur, variable_name):
    safe_execute(conn, cur, """
        INSERT INTO formula_variables
        (
            variable_name,
            description
        )
        VALUES (%s, %s)
        ON CONFLICT (variable_name) DO NOTHING
    """, (
        variable_name,
        "Auto-created from uploaded formula rule"
    ))


def insert_component_input(conn, cur, component, input_name, input_type):
    safe_execute(conn, cur, """
        INSERT INTO component_inputs
        (
            component,
            input_name,
            input_type
        )
        SELECT %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM component_inputs
            WHERE component = %s
            AND input_name = %s
            AND input_type = %s
        )
    """, (
        component,
        input_name,
        input_type,
        component,
        input_name,
        input_type
    ))


# ================= READ COMPONENT ARCHITECTURE =================
def read_component_architecture(uploaded_file):
    raw_df = pd.read_excel(uploaded_file, sheet_name=0, header=None)

    header_row_index = None

    for index, row in raw_df.iterrows():
        row_values = [
            str(value).strip().lower()
            for value in row.tolist()
            if not pd.isna(value)
        ]

        if "product_cat" in row_values and "product_code" in row_values:
            header_row_index = index
            break

    if header_row_index is None:
        raise Exception("Could not find header row with Product_Cat and Product_Code")

    df = pd.read_excel(uploaded_file, sheet_name=0, header=header_row_index)
    df = normalize_columns(df)

    rename_map = {
        "product_cat": "product_cat",
        "product_code": "product_code",
        "components": "component",
        "component": "component",
        "attribute": "attribute",
        "type": "type",
        "formula_used": "formula_used",
        "formula": "formula_used",
        "quanity": "quantity",
        "quantity": "quantity"
    }

    df = df.rename(columns=rename_map)

    required_columns = [
        "product_cat",
        "product_code",
        "component",
        "attribute",
        "type",
        "formula_used",
        "quantity"
    ]

    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        raise Exception(f"Missing columns: {', '.join(missing)}")

    df = df[required_columns]

    df = df.dropna(
        subset=[
            "product_cat",
            "product_code",
            "component",
            "attribute",
            "type"
        ],
        how="any"
    )

    df["type"] = df["type"].apply(normalize_rule_type)

    return df


# ================= READ PROJECT MASTER =================
def read_project_master(uploaded_file):
    df = pd.read_excel(uploaded_file, sheet_name=0)
    df = normalize_columns(df)

    rename_map = {
        "project_name": "project_name",
        "unit_name": "unit_type",
        "unit_type": "unit_type",
        "house_no": "house_number",
        "house_number": "house_number",
        "product_category": "product_cat",
        "product_cat": "product_cat",
        "product_code": "product_code",
        "orientation": "orientation",
        "quantity": "quantity"
    }

    df = df.rename(columns=rename_map)

    required_columns = [
        "project_name",
        "unit_type",
        "house_number",
        "product_cat",
        "product_code",
        "orientation",
        "quantity"
    ]

    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        raise Exception(f"Missing columns: {', '.join(missing)}")

    df = df[required_columns]

    df = df.dropna(
        subset=[
            "project_name",
            "unit_type",
            "house_number"
        ],
        how="any"
    )

    return df


# ================= UPLOAD COMPONENT ARCHITECTURE =================
def upload_component_architecture(conn, cur, df):
    total_products = set()
    total_rules = 0
    total_variables = set()
    total_inputs = set()

    for _, row in df.iterrows():
        product_cat = clean_text(row["product_cat"])
        product_codes = split_product_codes(row["product_code"])
        component = clean_text(row["component"])
        attribute = clean_text(row["attribute"])
        rule_type = normalize_rule_type(row["type"])
        formula_used = clean_text(row["formula_used"])
        quantity = clean_int(row["quantity"])

        if not product_cat or not product_codes or not component or not attribute or not rule_type:
            continue

        for product_code in product_codes:
            insert_product(
                conn,
                cur,
                product_cat,
                product_code
            )

            total_products.add((product_cat, product_code))

            insert_component_rule(
                conn,
                cur,
                product_cat,
                product_code,
                component,
                attribute,
                rule_type,
                formula_used,
                quantity
            )

            total_rules += 1

        if formula_used:
            for variable_name in extract_formula_variables(formula_used):
                insert_formula_variable(conn, cur, variable_name)
                total_variables.add(variable_name)

        insert_component_input(
            conn,
            cur,
            component,
            attribute,
            rule_type
        )

        total_inputs.add((component, attribute, rule_type))

    conn.commit()

    return {
        "Products": len(total_products),
        "Component Rules": total_rules,
        "Formula Variables": len(total_variables),
        "Component Inputs": len(total_inputs)
    }


# ================= UPLOAD PROJECT MASTER =================
def upload_project_master(conn, cur, df):
    total_projects = set()
    total_units = set()
    total_houses = set()
    total_products = set()

    for _, row in df.iterrows():
        project_name = clean_text(row["project_name"])
        unit_type = clean_text(row["unit_type"])
        house_number = clean_text(row["house_number"])
        product_cat = clean_text(row["product_cat"])
        product_code = clean_text(row["product_code"])

        if not project_name or not unit_type or not house_number:
            continue

        insert_project(conn, cur, project_name)
        insert_unit_type(conn, cur, project_name, unit_type)
        insert_house(conn, cur, project_name, unit_type, house_number)

        total_projects.add(project_name)
        total_units.add((project_name, unit_type))
        total_houses.add((project_name, unit_type, house_number))

        if product_cat and product_code:
            insert_product(conn, cur, product_cat, product_code)
            total_products.add((product_cat, product_code))

    conn.commit()

    return {
        "Projects": len(total_projects),
        "Unit Types": len(total_units),
        "Houses": len(total_houses),
        "Products": len(total_products)
    }


# ================= MAIN UPLOAD PAGE =================
def show_upload(conn, cur):
    st.title("Master Database Upload")

    st.markdown("""
    This page builds the master database required by the component calculation engine.

    **Master database contains:**

    - Products
    - Components
    - Formula rules
    - Quantity rules
    - Product mapping
    - Project / Unit / House mapping
    """)

    upload_type = st.selectbox(
        "Select Master Upload",
        [
            "Component Architecture",
            "Project Master"
        ]
    )

    if upload_type == "Component Architecture":
        st.info(
            "Upload component architecture Excel. "
            "This saves products, components, formula rules, quantity rules, "
            "formula variables, and component inputs."
        )

        with st.expander("Expected Component Architecture Columns", expanded=True):
            st.code(
                "Product_Cat | Product_Code | Components | Attribute | Type | Formula_Used | Quanity"
            )

    else:
        st.info(
            "Upload project master Excel. "
            "This saves project, unit type, house number, product category, and product code mapping."
        )

        with st.expander("Expected Project Master Columns", expanded=True):
            st.code(
                "project_name | unit_name | house_no | product_category | product_code | orientation | quantity"
            )

    uploaded_file = st.file_uploader(
        "Upload Excel File",
        type=["xlsx", "xls"]
    )

    if uploaded_file is None:
        return

    try:
        if upload_type == "Component Architecture":
            df = read_component_architecture(uploaded_file)
        else:
            df = read_project_master(uploaded_file)

    except Exception as e:
        st.error(f"Excel read failed: {e}")
        return

    st.subheader("Preview")
    st.dataframe(df.head(100), use_container_width=True, hide_index=True)

    if st.button("Upload to Master Database", type="primary"):
        try:
            if upload_type == "Component Architecture":
                result = upload_component_architecture(conn, cur, df)
            else:
                result = upload_project_master(conn, cur, df)

            st.success("Master database updated successfully.")

            cols = st.columns(len(result))

            for index, (label, value) in enumerate(result.items()):
                cols[index].metric(label, value)

        except Exception as e:
            conn.rollback()
            st.error(f"Upload failed: {e}")
