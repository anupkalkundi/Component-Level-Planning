import pandas as pd
import streamlit as st


# ================= SAFE EXECUTE =================
def safe_execute(conn, cur, query, params=None):
    try:
        cur.execute(query, params or ())
    except Exception as e:
        conn.rollback()
        raise e


# ================= HELPERS =================
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


def read_uploaded_file(uploaded_file):
    if uploaded_file.name.endswith(".csv"):
        return pd.read_csv(uploaded_file)

    return pd.read_excel(uploaded_file)


def show_expected_columns(title, columns):
    with st.expander(f"Expected columns for {title}"):
        st.code(", ".join(columns))


# ================= INSERT FUNCTIONS =================
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
    """, (project_name, unit_type, project_name, unit_type))


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
        INSERT INTO products (product_cat, product_code)
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


def insert_formula_variable(conn, cur, variable_name, description):
    safe_execute(conn, cur, """
        INSERT INTO formula_variables (variable_name, description)
        VALUES (%s, %s)
        ON CONFLICT (variable_name)
        DO UPDATE SET description = EXCLUDED.description
    """, (
        variable_name,
        description
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


# ================= UPLOAD PROCESSORS =================
def upload_projects(conn, cur, df):
    required = ["project_name"]

    if not all(col in df.columns for col in required):
        st.error("Missing columns. Required: project_name")
        return

    count = 0

    for _, row in df.iterrows():
        project_name = clean_text(row["project_name"])

        if not project_name:
            continue

        insert_project(conn, cur, project_name)
        count += 1

    conn.commit()
    st.success(f"Projects uploaded: {count}")


def upload_unit_types(conn, cur, df):
    required = ["project_name", "unit_type"]

    if not all(col in df.columns for col in required):
        st.error("Missing columns. Required: project_name, unit_type")
        return

    count = 0

    for _, row in df.iterrows():
        project_name = clean_text(row["project_name"])
        unit_type = clean_text(row["unit_type"])

        if not project_name or not unit_type:
            continue

        insert_project(conn, cur, project_name)
        insert_unit_type(conn, cur, project_name, unit_type)
        count += 1

    conn.commit()
    st.success(f"Unit types uploaded: {count}")


def upload_houses(conn, cur, df):
    required = ["project_name", "unit_type", "house_number"]

    if not all(col in df.columns for col in required):
        st.error("Missing columns. Required: project_name, unit_type, house_number")
        return

    count = 0

    for _, row in df.iterrows():
        project_name = clean_text(row["project_name"])
        unit_type = clean_text(row["unit_type"])
        house_number = clean_text(row["house_number"])

        if not project_name or not unit_type or not house_number:
            continue

        insert_project(conn, cur, project_name)
        insert_unit_type(conn, cur, project_name, unit_type)
        insert_house(conn, cur, project_name, unit_type, house_number)
        count += 1

    conn.commit()
    st.success(f"Houses uploaded: {count}")


def upload_products(conn, cur, df):
    required = ["product_cat", "product_code"]

    if not all(col in df.columns for col in required):
        st.error("Missing columns. Required: product_cat, product_code")
        return

    count = 0

    for _, row in df.iterrows():
        product_cat = clean_text(row["product_cat"])
        product_code = clean_text(row["product_code"])

        if not product_cat or not product_code:
            continue

        insert_product(conn, cur, product_cat, product_code)
        count += 1

    conn.commit()
    st.success(f"Products uploaded: {count}")


def upload_component_rules(conn, cur, df):
    required = [
        "product_cat",
        "product_code",
        "component",
        "attribute",
        "type",
        "formula_used",
        "quantity"
    ]

    missing = [col for col in required if col not in df.columns]

    if missing:
        st.error(f"Missing columns: {', '.join(missing)}")
        return

    count = 0

    for _, row in df.iterrows():
        product_cat = clean_text(row["product_cat"])
        product_code = clean_text(row["product_code"])
        component = clean_text(row["component"])
        attribute = clean_text(row["attribute"])
        rule_type = clean_text(row["type"])
        formula_used = clean_text(row["formula_used"])
        quantity = clean_int(row["quantity"])

        if not product_cat or not product_code or not component or not attribute or not rule_type:
            continue

        insert_product(conn, cur, product_cat, product_code)

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

        count += 1

    conn.commit()
    st.success(f"Component rules uploaded: {count}")


def upload_formula_variables(conn, cur, df):
    required = ["variable_name", "description"]

    if not all(col in df.columns for col in required):
        st.error("Missing columns. Required: variable_name, description")
        return

    count = 0

    for _, row in df.iterrows():
        variable_name = clean_text(row["variable_name"])
        description = clean_text(row["description"])

        if not variable_name:
            continue

        insert_formula_variable(conn, cur, variable_name, description)
        count += 1

    conn.commit()
    st.success(f"Formula variables uploaded: {count}")


def upload_component_inputs(conn, cur, df):
    required = ["component", "input_name", "input_type"]

    if not all(col in df.columns for col in required):
        st.error("Missing columns. Required: component, input_name, input_type")
        return

    count = 0

    for _, row in df.iterrows():
        component = clean_text(row["component"])
        input_name = clean_text(row["input_name"])
        input_type = clean_text(row["input_type"])

        if not component or not input_name or not input_type:
            continue

        insert_component_input(conn, cur, component, input_name, input_type)
        count += 1

    conn.commit()
    st.success(f"Component inputs uploaded: {count}")


# ================= MAIN PAGE =================
def show_upload(conn, cur):
    st.title("Upload Master Data")

    st.markdown("""
    Upload data in this order:

    1. Projects  
    2. Unit Types  
    3. Houses  
    4. Products  
    5. Component Rules  
    6. Formula Variables  
    7. Component Inputs
    """)

    upload_type = st.selectbox(
        "Select Upload Type",
        [
            "Projects",
            "Unit Types",
            "Houses",
            "Products",
            "Component Rules",
            "Formula Variables",
            "Component Inputs"
        ]
    )

    expected_columns = {
        "Projects": ["project_name"],
        "Unit Types": ["project_name", "unit_type"],
        "Houses": ["project_name", "unit_type", "house_number"],
        "Products": ["product_cat", "product_code"],
        "Component Rules": [
            "product_cat",
            "product_code",
            "component",
            "attribute",
            "type",
            "formula_used",
            "quantity"
        ],
        "Formula Variables": ["variable_name", "description"],
        "Component Inputs": ["component", "input_name", "input_type"]
    }

    show_expected_columns(upload_type, expected_columns[upload_type])

    uploaded_file = st.file_uploader(
        "Upload Excel or CSV",
        type=["xlsx", "xls", "csv"]
    )

    if uploaded_file is None:
        return

    try:
        df = read_uploaded_file(uploaded_file)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    df.columns = [str(col).strip() for col in df.columns]

    st.subheader("Preview")
    st.dataframe(df.head(50), use_container_width=True)

    if st.button("Upload to Database", type="primary"):
        try:
            if upload_type == "Projects":
                upload_projects(conn, cur, df)

            elif upload_type == "Unit Types":
                upload_unit_types(conn, cur, df)

            elif upload_type == "Houses":
                upload_houses(conn, cur, df)

            elif upload_type == "Products":
                upload_products(conn, cur, df)

            elif upload_type == "Component Rules":
                upload_component_rules(conn, cur, df)

            elif upload_type == "Formula Variables":
                upload_formula_variables(conn, cur, df)

            elif upload_type == "Component Inputs":
                upload_component_inputs(conn, cur, df)

        except Exception as e:
            conn.rollback()
            st.error(f"Upload failed: {e}")
