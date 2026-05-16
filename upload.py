def show_upload(conn, cur):
    import re
    import time
    import pandas as pd
    import streamlit as st
    from psycopg2.extras import execute_values

    if st.session_state.get("role") != "admin":
        st.error("Access denied")
        st.stop()

    st.title("Upload Master Data")

    # =========================================================
    # HELPERS
    # =========================================================

    def clean_text(value):
        if pd.isna(value):
            return ""

        value = str(value).strip()
        return value

    def clean_int(value):
        if pd.isna(value) or value == "":
            return None

        try:
            return int(float(value))
        except Exception:
            return None

    def normalize_columns(df):
        df.columns = (
            df.columns
            .astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "_", regex=False)
            .str.replace("-", "_", regex=False)
        )
        return df

    def normalize_rule_type(value):
        value = clean_text(value).lower()

        if value in ["fomula", "formula", "formulas"]:
            return "formula"

        if value in ["fixed", "constant", "qty"]:
            return "fixed"

        if value in ["manual", "input", "user_input"]:
            return "manual"

        return value

    def split_product_codes(value):
        value = clean_text(value)

        if not value:
            return []

        # Excel has comma separated product codes.
        return [
            code.strip()
            for code in value.split(",")
            if code.strip()
        ]

    def extract_formula_variables(formula):
        formula = clean_text(formula)

        if not formula:
            return []

        # If formula is written like x=y, keep only right side.
        if "=" in formula:
            left, right = formula.split("=", 1)
            if re.fullmatch(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*", left):
                formula = right.strip()

        ignore_words = {
            "abs",
            "max",
            "min",
            "round",
            "float",
            "int",
            "decimal",
            "Decimal"
        }

        variables = re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*\b",
            formula
        )

        return sorted({
            v.strip()
            for v in variables
            if v.strip() not in ignore_words
        })

    def read_component_architecture(file):
        raw_df = pd.read_excel(
            file,
            sheet_name=0,
            header=None,
            engine="openpyxl"
        )

        header_row_index = None

        for index, row in raw_df.iterrows():
            row_values = [
                str(value).strip().lower()
                for value in row.tolist()
                if not pd.isna(value)
            ]

            if (
                "product_cat" in row_values
                and "product_code" in row_values
            ):
                header_row_index = index
                break

        if header_row_index is None:
            raise Exception(
                "Could not find header row with Product_Cat and Product_Code"
            )

        df = pd.read_excel(
            file,
            sheet_name=0,
            header=header_row_index,
            engine="openpyxl"
        )

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

        required_cols = [
            "product_cat",
            "product_code",
            "component",
            "attribute",
            "type",
            "formula_used",
            "quantity"
        ]

        for col in required_cols:
            if col not in df.columns:
                st.error(f"Missing column: {col}")
                st.stop()

        df = df[required_cols]

        df = df.dropna(
            subset=[
                "product_cat",
                "product_code",
                "component",
                "attribute",
                "type"
            ]
        )

        df["product_cat"] = df["product_cat"].apply(clean_text)
        df["product_code"] = df["product_code"].apply(clean_text)
        df["component"] = df["component"].apply(clean_text)
        df["attribute"] = df["attribute"].apply(clean_text)
        df["type"] = df["type"].apply(normalize_rule_type)
        df["formula_used"] = df["formula_used"].apply(clean_text)
        df["quantity"] = df["quantity"].apply(clean_int)

        # Expand comma-separated product codes into separate rows.
        expanded_rows = []

        for _, row in df.iterrows():
            product_codes = split_product_codes(row["product_code"])

            for product_code in product_codes:
                expanded_rows.append({
                    "product_cat": row["product_cat"],
                    "product_code": product_code,
                    "component": row["component"],
                    "attribute": row["attribute"],
                    "type": row["type"],
                    "formula_used": row["formula_used"],
                    "quantity": row["quantity"],
                })

        df = pd.DataFrame(expanded_rows)

        if df.empty:
            raise Exception("No valid component rules found in Excel")

        # Remove exact duplicate rules before DB insert.
        df = df.drop_duplicates(
            subset=[
                "product_cat",
                "product_code",
                "component",
                "attribute",
                "type",
                "formula_used",
                "quantity"
            ]
        )

        return df

    def read_project_master(file):
        df = pd.read_excel(
            file,
            sheet_name=0,
            engine="openpyxl"
        )

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

        required_cols = [
            "project_name",
            "unit_type",
            "house_number",
            "product_cat",
            "product_code",
            "orientation",
            "quantity"
        ]

        for col in required_cols:
            if col not in df.columns:
                st.error(f"Missing column: {col}")
                st.stop()

        df = df[required_cols]

        df = df.dropna(
            subset=[
                "project_name",
                "unit_type",
                "house_number"
            ]
        )

        df["project_name"] = df["project_name"].apply(clean_text)
        df["unit_type"] = df["unit_type"].apply(clean_text)
        df["house_number"] = df["house_number"].apply(clean_text)
        df["product_cat"] = df["product_cat"].apply(clean_text)
        df["product_code"] = df["product_code"].apply(clean_text)
        df["orientation"] = df["orientation"].apply(clean_text)
        df["quantity"] = (
            pd.to_numeric(df["quantity"], errors="coerce")
            .fillna(1)
            .astype(int)
        )

        df = df.drop_duplicates()

        return df

    # =========================================================
    # DB UPLOAD: COMPONENT ARCHITECTURE
    # =========================================================

    def upload_component_architecture(df):
        start_time = time.time()

        status = st.empty()
        progress = st.progress(0)

        status.info("Uploading component architecture...")

        # ================= PRODUCTS =================

        product_rows = (
            df[["product_cat", "product_code"]]
            .drop_duplicates()
            .values
            .tolist()
        )

        execute_values(cur, """
            INSERT INTO products
            (
                product_cat,
                product_code
            )
            VALUES %s
            ON CONFLICT DO NOTHING
        """, product_rows)

        conn.commit()
        progress.progress(20)

        # ================= COMPONENT RULES =================

        rule_rows = (
            df[
                [
                    "product_cat",
                    "product_code",
                    "component",
                    "attribute",
                    "type",
                    "formula_used",
                    "quantity"
                ]
            ]
            .drop_duplicates()
            .values
            .tolist()
        )

        execute_values(cur, """
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
            VALUES %s
            ON CONFLICT DO NOTHING
        """, rule_rows)

        conn.commit()
        progress.progress(55)

        # ================= FORMULA VARIABLES =================

        variable_set = set()

        for formula in df["formula_used"].dropna():
            for variable in extract_formula_variables(formula):
                variable_set.add(variable)

        variable_rows = [
            (
                variable,
                "Auto-created from uploaded formula rule"
            )
            for variable in sorted(variable_set)
        ]

        if variable_rows:
            execute_values(cur, """
                INSERT INTO formula_variables
                (
                    variable_name,
                    description
                )
                VALUES %s
                ON CONFLICT (variable_name) DO NOTHING
            """, variable_rows)

            conn.commit()

        progress.progress(75)

        # ================= COMPONENT INPUTS =================

        input_rows = (
            df[
                [
                    "component",
                    "attribute",
                    "type"
                ]
            ]
            .drop_duplicates()
            .values
            .tolist()
        )

        execute_values(cur, """
            INSERT INTO component_inputs
            (
                component,
                input_name,
                input_type
            )
            VALUES %s
            ON CONFLICT DO NOTHING
        """, input_rows)

        conn.commit()
        progress.progress(100)

        total_time = round(time.time() - start_time, 2)
        status.empty()

        return {
            "Products": len(product_rows),
            "Component Rules": len(rule_rows),
            "Formula Variables": len(variable_rows),
            "Component Inputs": len(input_rows),
            "Time": total_time
        }

    # =========================================================
    # DB UPLOAD: PROJECT MASTER
    # =========================================================

    def upload_project_master(df):
        start_time = time.time()

        status = st.empty()
        progress = st.progress(0)

        status.info("Uploading project master...")

        # ================= PROJECTS =================

        project_rows = [
            (p,)
            for p in sorted(set(df["project_name"]))
            if p
        ]

        execute_values(cur, """
            INSERT INTO projects
            (
                project_name
            )
            VALUES %s
            ON CONFLICT (project_name) DO NOTHING
        """, project_rows)

        conn.commit()
        progress.progress(20)

        # ================= UNIT TYPES =================

        unit_rows = (
            df[
                [
                    "project_name",
                    "unit_type"
                ]
            ]
            .drop_duplicates()
            .values
            .tolist()
        )

        execute_values(cur, """
            INSERT INTO unit_types
            (
                project_name,
                unit_type
            )
            VALUES %s
            ON CONFLICT DO NOTHING
        """, unit_rows)

        conn.commit()
        progress.progress(45)

        # ================= HOUSES =================

        house_rows = (
            df[
                [
                    "project_name",
                    "unit_type",
                    "house_number"
                ]
            ]
            .drop_duplicates()
            .values
            .tolist()
        )

        execute_values(cur, """
            INSERT INTO houses
            (
                project_name,
                unit_type,
                house_number
            )
            VALUES %s
            ON CONFLICT DO NOTHING
        """, house_rows)

        conn.commit()
        progress.progress(70)

        # ================= PRODUCTS =================

        product_rows = (
            df[
                [
                    "product_cat",
                    "product_code"
                ]
            ]
            .drop_duplicates()
        )

        product_rows = product_rows[
            (product_rows["product_cat"] != "")
            & (product_rows["product_code"] != "")
        ]

        product_rows = product_rows.values.tolist()

        if product_rows:
            execute_values(cur, """
                INSERT INTO products
                (
                    product_cat,
                    product_code
                )
                VALUES %s
                ON CONFLICT DO NOTHING
            """, product_rows)

            conn.commit()

        progress.progress(100)

        total_time = round(time.time() - start_time, 2)
        status.empty()

        return {
            "Projects": len(project_rows),
            "Unit Types": len(unit_rows),
            "Houses": len(house_rows),
            "Products": len(product_rows),
            "Time": total_time
        }

    # =========================================================
    # PAGE UI
    # =========================================================

    upload_type = st.selectbox(
        "Select Upload Type",
        [
            "Component Architecture",
            "Project Master"
        ]
    )

    if upload_type == "Component Architecture":
        st.info(
            "Upload product component formulas and quantity rules."
        )

        with st.expander("Expected Columns", expanded=True):
            st.code(
                "Product_Cat | Product_Code | Components | Attribute | Type | Formula_Used | Quanity"
            )

    else:
        st.info(
            "Upload project, unit, house, and product mapping."
        )

        with st.expander("Expected Columns", expanded=True):
            st.code(
                "project_name | unit_name | house_no | product_category | product_code | orientation | quantity"
            )

    file = st.file_uploader(
        "Upload Excel",
        type=["xlsx", "xls"]
    )

    if not file:
        return

    try:
        if upload_type == "Component Architecture":
            df = read_component_architecture(file)
        else:
            df = read_project_master(file)

    except Exception as e:
        st.error(f"Excel read failed: {e}")
        st.stop()

    st.subheader("Preview")
    st.dataframe(
        df.head(100),
        use_container_width=True,
        hide_index=True
    )

    st.info(f"Rows ready to upload: {len(df)}")

    upload_btn = st.button(
        "Upload to Master Database",
        type="primary"
    )

    if upload_btn:
        try:
            if upload_type == "Component Architecture":
                result = upload_component_architecture(df)
            else:
                result = upload_project_master(df)

            st.success("Upload completed successfully")

            metric_cols = st.columns(len(result))

            for index, (label, value) in enumerate(result.items()):
                metric_cols[index].metric(label, value)

        except Exception as e:
            conn.rollback()
            st.error(f"Upload failed: {e}")
