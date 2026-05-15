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


def normalize_rule_type(value):
    value = clean_text(value)

    if not value:
        return None

    value = value.lower().strip()

    if value in ["fomula", "formula", "formulas"]:
        return "formula"

    if value in ["manual", "input"]:
        return "manual"

    if value in ["fixed", "constant"]:
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


# ================= DB INSERTS =================
def insert_product(conn, cur, product_cat, product_code):
    safe_execute(conn, cur, """
        INSERT INTO products
        (
            product_cat,
            product_code
        )
        SELECT %s, %s
        WHERE NOT EXISTS (
            SELECT 1
            FROM products
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
            SELECT 1
            FROM product_component_rules
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
        "Auto-created from uploaded component formula"
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
            SELECT 1
            FROM component_inputs
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


# ================= READ EXCEL =================
def read_component_architecture(uploaded_file):
    raw_df = pd.read_excel(uploaded_file, sheet_name=0, header=None)

    header_row_index = None

    for index, row in raw_df.iterrows():
        row_values = [str(v).strip().lower() for v in row.tolist() if not pd.isna(v)]

        if "product_cat" in row_values and "product_code" in row_values:
            header_row_index = index
            break

    if header_row_index is None:
        raise Exception("Could not find header row with Product_Cat and Product_Code")

    df = pd.read_excel(uploaded_file, sheet_name=0, header=header_row_index)

    df.columns = [
        str(col).strip().lower()
        .replace(" ", "_")
        .replace("-", "_")
        for col in df.columns
    ]

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

    return df


# ================= UPLOAD PAGE =================
def show_upload(conn, cur):
    st.title("Upload Component Architecture")

    st.markdown("""
    Upload your component-level Excel file.

    Correct flow:

    1. Read Product Category  
    2. Split Product Codes  
    3. Save Products  
    4. Save Component Rules  
    5. Auto-create Formula Variables  
    6. Auto-create Component Inputs  
    """)

    st.info(
        "This upload is for your Excel format: "
        "Product_Cat, Product_Code, Components, Attribute, Type, Formula_Used, Quanity"
    )

    uploaded_file = st.file_uploader(
        "Upload Component Architecture Excel",
        type=["xlsx", "xls"]
    )

    if uploaded_file is None:
        return

    try:
        df = read_component_architecture(uploaded_file)
    except Exception as e:
        st.error(f"Excel read failed: {e}")
        return

    preview_df = df.copy()
    preview_df["type"] = preview_df["type"].apply(normalize_rule_type)

    st.subheader("Preview From Excel")
    st.dataframe(preview_df, use_container_width=True, hide_index=True)

    total_rules = 0
    total_products = set()
    total_variables = set()
    total_inputs = set()

    if st.button("Upload Component Rules", type="primary"):
        try:
            for _, row in preview_df.iterrows():
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

            st.success("Upload completed successfully.")

            col1, col2, col3, col4 = st.columns(4)

            col1.metric("Products", len(total_products))
            col2.metric("Component Rules", total_rules)
            col3.metric("Formula Variables", len(total_variables))
            col4.metric("Component Inputs", len(total_inputs))

        except Exception as e:
            conn.rollback()
            st.error(f"Upload failed: {e}")
